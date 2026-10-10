"""What a decompiled assembly declares, and where each declaration sits.

A handbook citation is anchored on an element -- a type, or a member of one --
plus a line counted from that element's first line. This module is the half that
knows what the elements are. `citation_notation` is the half that knows how a
citation is spelled, and it imports nothing from here, so the syntactic half of
the style check still runs in a mod repository with no decompile.

Two answers that must not merge:

    None                      nothing is known about this file
    Structure(elements=())    it was parsed and declares nothing

A `.prefab` is the first; an empty `.cs` is the second. Collapsing them would
turn "I could not look" into "there is nothing there", which is how an open
boundary becomes a silent verdict.

`params` carries the same distinction one level down: `None` for a declaration
with no parameter list at all -- a field, a property, a type -- and `()` for a
method that takes nothing.

**Why a real parser.** Two throwaway regex recognisers were written while
designing this and both failed silently, in opposite directions: one read
namespace-indented type declarations as members and produced decoy elements up
to 3,816 lines long, the other read `for` loops as declarations and lost 51
citations. The median search space between them differed by a factor of three,
so the aggregate figure was an artifact of whichever bug dominated. Only
calibration against known citations exposed it.
"""

import contextlib
import hashlib
import json
import os
import re
from bisect import bisect_right
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

import tree_sitter
import tree_sitter_c_sharp
from citation_notation import Citation
from citation_notation import tier

# Nodes that declare a type. A line inside one of these but inside no member of
# it is still anchorable -- that is the type tier, 56 citations today.
_TYPE_NODES = frozenset(
    {
        "class_declaration",
        "struct_declaration",
        "interface_declaration",
        "enum_declaration",
        "record_declaration",
        "record_struct_declaration",
    }
)

# Nodes that declare a member. The walk does not descend into these: a citation
# names the member, and a statement inside it is located by counting lines.
_MEMBER_NODES = frozenset(
    {
        "method_declaration",
        "constructor_declaration",
        "destructor_declaration",
        "property_declaration",
        "field_declaration",
        "indexer_declaration",
        "operator_declaration",
        "conversion_operator_declaration",
        "event_declaration",
        "event_field_declaration",
        "enum_member_declaration",
        "delegate_declaration",
    }
)

_LANGUAGE = tree_sitter.Language(tree_sitter_c_sharp.language())


@dataclass(frozen=True)
class Element:
    """One declaration and its extent. `start` and `end` are 1-based, inclusive.

    A type has `member=None` and `params=None`. A member carries the enclosing
    type's name in `type_name`, its own in `member`, and is spelled the way the
    decompile spells it -- including an `Interface<T>.` qualifier.
    """

    type_name: str | None
    member: str | None
    params: tuple[str, ...] | None
    start: int
    end: int


@dataclass(frozen=True)
class Structure:
    """Every element in one file, ordered by `start`, plus the spans that did not parse.

    Error ranges are reported rather than swallowed, because a caller can only
    say "I am not checking the location here" if it is told where not to.
    """

    elements: tuple[Element, ...]
    error_ranges: tuple[tuple[int, int], ...]

    # Indexes, built on first use and kept on the instance. `cached_property`
    # writes through `__dict__`, which `frozen=True` does not guard, and the
    # generated `__eq__` compares declared fields only -- so two Structures
    # still compare equal whether or not either has been indexed.
    #
    # They exist because the obvious alternative is the mistake this project
    # already made once: a linear scan per citation over ~62,000 elements is
    # 45 million comparisons for one assembly's citations, which is how an
    # earlier measurement in this design ran past its timeout.

    @cached_property
    def members(self):
        """Members only, in `start` order. Disjoint, so one line has at most one."""
        return tuple(e for e in self.elements if e.member is not None)

    @cached_property
    def _member_starts(self):
        return tuple(e.start for e in self.members)

    @cached_property
    def types(self):
        """Types only. These nest, so finding the innermost is a scan, not a bisect."""
        return tuple(e for e in self.elements if e.member is None)

    @cached_property
    def members_by_type(self):
        """Members grouped by enclosing type -- the scope uniqueness is judged in.

        Keyed by the *qualified* type name, so two systems' nested `UpdateJob`
        structs do not pool their members into one namespace.
        """
        index = {}
        for element in self.members:
            index.setdefault(element.type_name, []).append(element)
        return index

    @cached_property
    def types_by_form(self):
        """Every suffix of every qualified type name, to the elements it could mean.

        `EquipmentUpdateSystem.UpdateJob` is reachable as `UpdateJob` and as
        the full name; the first is shared with six other declarations and the
        second is not. Uniqueness is counted in *elements*, not names, because
        two declarations can share even a fully qualified name and a citation
        to either would then resolve to neither.
        """
        index = {}
        for element in self.types:
            for form in _type_forms(element.type_name):
                index.setdefault(form, []).append(element)
        return index


def _text(node):
    return node.text.decode("utf-8", errors="replace")


def _extent(node):
    return (node.start_point[0] + 1, node.end_point[0] + 1)


def _member_name(node):
    """The member's name as written, or None when no name can be derived.

    `name` covers most declarations. A field or an event field keeps its name on
    a variable declarator instead, and a declaration with several declarators
    (`int a, b;`) is named for the first -- they share one extent, so any choice
    is as good as another and only determinism matters.

    An `explicit_interface_specifier` is joined back on, because tree-sitter's
    `name` field returns the bare name for both `Serialize` and
    `IRpcCommandSerializer<Rpc>.Serialize`. A layer reading only that field
    merges two real members, and a citation to either is then measured against
    the other.

    Three kinds have no identifier at all in C#, and each is named the way the
    decompile writes it: an indexer is `this` and is told apart by its
    parameters, a binary operator is `operator ==`, a conversion is named for
    its target type as `operator Foo`. Measured over the cited assemblies they
    are 162 of 157,134 member nodes -- 0.1 %, but *all* of those three kinds,
    where every other kind is fully named. Leaving them unnamed anchored their
    lines on the enclosing type instead, which for a large type gives up most
    of the precision this module exists for.
    """
    if node.type == "indexer_declaration":
        return "this"
    if node.type == "operator_declaration":
        operator = node.child_by_field_name("operator")
        return f"operator {_text(operator)}" if operator is not None else None
    if node.type == "conversion_operator_declaration":
        target = node.child_by_field_name("type")
        return f"operator {_text(target)}" if target is not None else None

    name = node.child_by_field_name("name")
    if name is None:
        declarator = next(
            (
                d
                for d in node.named_children
                for d in ([d] if d.type == "variable_declarator" else d.named_children)
                if d.type == "variable_declarator"
            ),
            None,
        )
        if declarator is None:
            return None
        name = declarator.child_by_field_name("name")
        if name is None:
            return None

    qualifier = next(
        (c for c in node.named_children if c.type == "explicit_interface_specifier"),
        None,
    )
    return f"{_text(qualifier)}{_text(name)}" if qualifier else _text(name)


def _params(node):
    """The parameter types, names dropped, or None when there is no parameter list."""
    parameters = node.child_by_field_name("parameters")
    if parameters is None:
        return None
    types = []
    for parameter in parameters.named_children:
        if parameter.type != "parameter":
            continue
        declared = parameter.child_by_field_name("type")
        # `global::Discord.Discord` is three real declarations' parameter type,
        # and the citation grammar splits its fields on ":" -- so a form built
        # from it renders a token `parse` rejects. The qualifier resolves an
        # alias and means nothing a citation needs, so it goes.
        spelled = _text(declared) if declared is not None else "?"
        types.append(spelled.replace("global::", ""))
    return tuple(types)


def _collect(node, type_name, elements):
    """Append every element under `node`, carrying the enclosing type's name down."""
    for child in node.named_children:
        if child.type in _MEMBER_NODES:
            member = _member_name(child)
            if member is not None:
                start, end = _extent(child)
                elements.append(Element(type_name, member, _params(child), start, end))
            continue
        if child.type in _TYPE_NODES:
            name = child.child_by_field_name("name")
            if name is None:
                _collect(child, type_name, elements)
                continue
            # Nested types carry their enclosing type, dotted, because a simple
            # name is not an anchor: `UpdateJob` names seven declarations in
            # `Pug.Other` alone -- it is what DOTS calls the job struct nested
            # in a system. `describe` shortens this back to the briefest
            # unique suffix, so the 3,343 unqualified names stay unqualified.
            inner = f"{type_name}.{_text(name)}" if type_name else _text(name)
            start, end = _extent(child)
            elements.append(Element(inner, None, None, start, end))
            _collect(child, inner, elements)
            continue
        _collect(child, type_name, elements)


def _errors(root):
    """Extents of every ERROR and missing node, anywhere in the tree.

    A separate traversal, and only when the tree reports an error at all, so a
    well-formed file pays nothing for it. Separate because an error can sit
    inside a member body, which `_collect` deliberately does not enter.

    **An error range does not disqualify an anchor, and must not.** Measured on
    `Pug.Other` at 1.3.0.6: 4,570 ranges covering 14.68 % of the file, the
    widest of them 63,160 lines -- from a `namespace` keyword the grammar
    rejects straight to the end of the file -- and 61 of that assembly's 506
    cited lines sit inside one. The declarations inside those ranges parse
    correctly all the same: `PugMap` comes out spanning its real 590 lines and
    its fields one line each. So the ranges say where the *grammar* gave up on
    the enclosing syntax, not where the elements are untrustworthy. Refusing to
    anchor inside one would move 61 verifiable citations into the escape hatch,
    which has no location check at all -- strictly worse than an anchor that
    provably round-trips.

    What the ranges are for is letting a caller report honestly when it does
    decline, and giving the round-trip test a place to look first when an anchor
    does turn out wrong.
    """
    if not root.has_error:
        return ()
    found, stack = [], [root]
    while stack:
        node = stack.pop()
        if node.type == "ERROR" or node.is_missing:
            found.append(_extent(node))
            continue
        stack.extend(node.children)
    return tuple(sorted(found))


def _parse(path):
    """Parse one file into a Structure, or None when nothing can be known about it."""
    if path.suffix != ".cs":
        return None
    try:
        source = path.read_bytes()
    except OSError:
        return None

    root = tree_sitter.Parser(_LANGUAGE).parse(source).root_node
    elements = []
    _collect(root, None, elements)
    elements.sort(key=lambda e: (e.start, e.end))
    return Structure(tuple(elements), _errors(root))


DEFAULT_CACHE_DIR = Path.home() / ".cache" / "ck-decompile-structure"

# What this module's own output means, stamped into every entry. Bump it when a
# change alters the *content* of a Structure for a file that has not moved --
# a node type added to either list, a change to how a name is built, a new
# field on Element. The file's size and mtime cannot see such a change, and the
# shape check in `_decode` only catches it when the JSON layout changes too.
#
# Earned, not anticipated: qualifying nested type names (`UpdateJob` ->
# `EquipmentUpdateSystem.UpdateJob`) left the layout identical, so entries
# written before it were accepted afterwards and seven citations silently
# resolved to the escape hatch instead of their member.
CACHE_FORMAT = 3

# The decompile README's title carries the build it was taken from. Duplicated
# from `verify_status` rather than imported: that is a command-line tool, and a
# library reaching into one inverts the dependency for the sake of one regex.
_BUILD_HEADING = re.compile(r"^#\s.*`(\d+\.\d+\.\d+\.\d+-\w+)`", re.MULTILINE)


def _cache_dir(explicit):
    """Where entries live: the argument, else `CK_STRUCTURE_CACHE`, else the default."""
    if explicit is not None:
        return Path(explicit)
    override = os.environ.get("CK_STRUCTURE_CACHE")
    return Path(override) if override else DEFAULT_CACHE_DIR


def _build_identity(path):
    """The build this file was decompiled from, for diagnostics, or None.

    Found by looking for a README with a version heading in the file's own
    directory and the two above it -- an assembly sits at the decompile root, a
    dependency clone's source a level or two down.
    """
    for parent in [path.parent, *list(path.parents)[1:3]]:
        readme = parent / "README.md"
        if readme.is_file():
            match = _BUILD_HEADING.search(readme.read_text(errors="replace"))
            if match:
                return match[1]
    return None


def _entry_for(directory, path):
    digest = hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:32]
    return directory / f"{digest}.json"


def _encode(structure):
    # `is not None`, never truthiness: `()` is falsy and means "a method that
    # takes nothing", while None means "no parameter list at all". An `and`
    # here collapses the two, which is the distinction this module exists to
    # keep -- and it did collapse it, caught by the cache round trip.
    return {
        "elements": [
            [
                e.type_name,
                e.member,
                list(e.params) if e.params is not None else None,
                e.start,
                e.end,
            ]
            for e in structure.elements
        ],
        "error_ranges": [list(r) for r in structure.error_ranges],
    }


def _decode(data):
    """A Structure from a cache entry, or None if the entry is not one.

    None rather than an exception, because an entry written by an older version
    of this module is the expected case every time `Element` gains a field --
    and the right answer to it is to parse the file again, not to fail a gate.
    """
    try:
        elements = tuple(
            Element(
                type_name,
                member,
                tuple(params) if params is not None else None,
                start,
                end,
            )
            for type_name, member, params, start, end in data["elements"]
        )
        # Sorted here rather than trusted from the file. `_enclosing` bisects
        # over member starts, so their order is an invariant of `Structure` --
        # and nothing in a JSON array enforces it. Read back out of order the
        # bisect lands on the wrong element and the citation anchors somewhere
        # else, with the round trip still green because `describe` and `locate`
        # would agree on the same wrong element.
        elements = tuple(sorted(elements, key=lambda e: (e.start, e.end)))
        return Structure(elements, tuple(tuple(r) for r in data["error_ranges"]))
    except (KeyError, TypeError, ValueError):
        return None


def _read_entry(entry, stat):
    """The cached Structure for a file in this exact state, or None.

    The key is `(path, size, mtime_ns)`: the path picks the entry, the other two
    decide whether it still describes the file. The build identity is read back
    but never compared -- a decompile regenerated without a version change would
    otherwise keep serving a stale index, which is the one failure this cache
    must not have.
    """
    try:
        data = json.loads(entry.read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None  # valid JSON of the wrong kind; `.get` below would raise
    if data.get("format") != CACHE_FORMAT:
        return None
    if data.get("size") != stat.st_size or data.get("mtime_ns") != stat.st_mtime_ns:
        return None
    return _decode(data)


def _write_entry(entry, structure, stat, build):
    """Write one entry, atomically, so a concurrent reader never sees a half of it.

    The main checkout and a worktree share this directory and both run the
    gates. A reader must get either the previous entry or the whole new one, so
    the write lands on a private name first and is renamed into place.
    """
    entry.parent.mkdir(parents=True, exist_ok=True)
    payload = _encode(structure) | {
        "format": CACHE_FORMAT,
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "build": build,
    }
    temporary = entry.with_suffix(f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload))
    os.replace(temporary, entry)


def structure_of(path, *, cache_dir=None):
    """The Structure of the file at `path`, or None if nothing is known about it.

    Parsing the 25 cited assemblies costs 7.8 s, 5.6 s of it the two 16 MB
    copies of `Pug.Other`. A pre-commit gate cannot pay that per run, so the
    result is cached outside the repository -- it describes the decompile, not
    the repository, and `git clean -fdx` should not cost 7.8 s.
    """
    path = Path(path)
    try:
        stat = path.stat()
    except OSError:
        return None
    if path.suffix != ".cs":
        return None

    entry = _entry_for(_cache_dir(cache_dir), path)
    if (cached := _read_entry(entry, stat)) is not None:
        return cached

    structure = _parse(path)
    if structure is not None:
        # The cache is an optimisation. An unwritable or unreachable directory
        # costs this run its 4.4 s, not the commit: check_citation_style.py is
        # a pre-commit hook and its structural half resolves symbols through
        # here, so it must not fail for want of somewhere to put an index.
        with contextlib.suppress(OSError):
            _write_entry(entry, structure, stat, _build_identity(path))
    return structure


def _forms(element):
    """Every spelling of this member, shortest first.

    The bare name, then the parameter type list truncated to one type, two, and
    so on, with `…` standing for everything left out. A prefix that is the whole
    list carries no ellipsis, because nothing was omitted and saying otherwise
    would make a complete signature look truncated.

    There is no modifier tier and no separate interface tier. Modifiers are not
    in `Element` -- nothing in the corpus needs them to disambiguate -- and an
    explicit interface implementation already carries its qualifier *inside*
    `member`, so it is a different name rather than a longer form of the same
    one, and unique by the language rule that allows it at all.
    """
    yield element.member
    if element.params is None:
        return
    if any(":" in declared for declared in element.params):
        return  # unspellable in a grammar that splits on ":"; stay with the name
    if not element.params:
        yield f"{element.member}()"
        return
    for count in range(1, len(element.params) + 1):
        shown = ", ".join(element.params[:count])
        omitted = count < len(element.params)
        yield f"{element.member}({shown}, …)" if omitted else f"{element.member}({shown})"


def _type_forms(qualified):
    """Suffixes of a dotted type name, shortest first: `Inner`, `Outer.Inner`, ..."""
    parts = qualified.split(".")
    for count in range(1, len(parts) + 1):
        yield ".".join(parts[-count:])


def _shortest_unique_type(structure, qualified):
    """The briefest suffix of `qualified` that names one declaration, or None.

    The same rule the member names follow, for the same reason: an anchor that
    matches seven declarations is not an anchor. None when even the full name
    is shared, which leaves the citation nothing to be but absolute.
    """
    for form in _type_forms(qualified):
        if len(structure.types_by_form.get(form, ())) == 1:
            return form
    return None


def _shortest_unique(structure, element):
    """The shortest spelling of `element` that no sibling in its type shares.

    **This is the only place that decides what "shortest unique" means.** ADR
    0042 records what letting two implementations judge one claim cost: "both
    had to be taught to judge alike -- they did not, twice, before this was
    closed." Here the consequence would be worse, because a verification pass
    would write citations its own commit hook rejects, and the natural response
    to a red gate over freshly written citations is to weaken the gate. So
    `locate` re-derives candidates through this same function, and the style
    checker calls it rather than re-deciding.
    """
    siblings = structure.members_by_type.get(element.type_name, ())
    spellings = [frozenset(_forms(sibling)) for sibling in siblings]
    for form in _forms(element):
        if sum(form in spelling for spelling in spellings) == 1:
            return form
    return None


def _enclosing(structure, first, last):
    """The innermost element containing the whole span, or None if none does.

    Members are disjoint, so the last one starting at or before `first` is the
    only candidate -- a bisect. Types nest, so the innermost is the smallest
    extent that contains the span, and that is a scan. The scan only runs when
    no member matched, which is under a tenth of the corpus.

    It takes a span rather than a line because 127 of the handbook's citations
    are ranges, and a range must be anchored on something containing both ends.
    A span crossing out of its first line's member is anchored on the type that
    holds both -- anchoring on the member would describe a range reaching past
    the element it names, which `locate` then refuses, so the citation would
    resolve to nothing.
    """
    index = bisect_right(structure._member_starts, first) - 1
    if index >= 0 and structure.members[index].end >= last:
        return structure.members[index]

    innermost = None
    for candidate in structure.types:
        if (
            candidate.start <= first
            and last <= candidate.end
            and (
                innermost is None
                or candidate.end - candidate.start < innermost.end - innermost.start
            )
        ):
            innermost = candidate
    return innermost


def describe(structure, line, assembly, last=None):
    """The citation that anchors `line`, or the span `line`..`last`.

    A member if one contains the whole span, else the enclosing type, else an
    absolute line. The tier decides what the citation survives, so the
    innermost is always the right answer -- it is exposed to the least.

    An element with no enclosing type is passed over rather than claimed: a
    namespace-level delegate would have to be spelled `Assembly:member:N`,
    which the grammar reads back as the *type* tier, so claiming it would break
    the round trip in a way no reader could see.
    """
    last = line if last is None else last
    element = _enclosing(structure, line, last)
    if element is None or element.type_name is None:
        return Citation(assembly, None, None, line, last)

    named = _shortest_unique_type(structure, element.type_name)
    if named is None:
        return Citation(assembly, None, None, line, last)

    first, final = line - element.start + 1, last - element.start + 1
    if element.member is None:
        return Citation(assembly, named, None, first, final)

    form = _shortest_unique(structure, element)
    if form is None:
        return Citation(assembly, None, None, line, last)
    return Citation(assembly, named, form, first, final)


def locate(structure, citation):
    """The absolute line a citation resolves to, or None if it no longer does.

    None is the outcome that does not exist under absolute line numbers and is
    the reason for this change: a renamed or removed member stops resolving and
    says so, where a line number would have gone on pointing at whatever moved
    into its place.

    Permissive where `describe` is canonical: any valid spelling resolves, not
    only the shortest. The style checker reports a longer-than-necessary form
    rather than blocking on it, so such citations exist legitimately and must
    not fail to resolve for being verbose.
    """
    if tier(citation) == "absolute":
        return citation.first

    candidates = structure.types_by_form.get(citation.type_name, ())
    if citation.member is None:
        matches = list(candidates)
    else:
        # Gathered across every type the cited name could mean, so a member
        # that is unique on its own still resolves under a type name that is
        # not -- which is what makes `describe`'s shortening safe to undo.
        matches = [
            element
            for candidate in candidates
            for element in structure.members_by_type.get(candidate.type_name, ())
            if citation.member in frozenset(_forms(element))
        ]
    if len(matches) != 1:
        return None  # absent, or named ambiguously -- never guess which
    element = matches[0]

    if citation.first is None:
        return element.start
    first = element.start + citation.first - 1
    last = element.start + citation.last - 1
    if citation.first < 1 or last > element.end:
        return None  # the offset leaves the element; clamping would invent a line
    return first
