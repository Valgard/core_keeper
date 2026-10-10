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

from dataclasses import dataclass
from pathlib import Path

import tree_sitter
import tree_sitter_c_sharp

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
    """
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
        types.append(_text(declared) if declared is not None else "?")
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
            inner = _text(name) if name is not None else type_name
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


def structure_of(path):
    """The Structure of the file at `path`, or None if nothing is known about it."""
    return _parse(Path(path))
