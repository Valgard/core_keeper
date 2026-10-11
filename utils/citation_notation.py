"""The grammar of a handbook citation: what it names and where it points.

A citation separates the two, following salesbuddy's ADR 0042: the anchor says
what is meant, the location says where it stands. Five forms, and no others:

    Assembly:Class:member:7       the 7th line of the element, 1-based
    Assembly:Class:member:7-12    a range inside the element
    Assembly:Class:member         the element as a whole
    Assembly:Class                the type as a whole
    Assembly:7                    the escape hatch

`Assembly:Class:7` is the third tier: a line inside a type but inside no member
of it. `DedicatedServer/` may precede the assembly, for the server build.

**This module deliberately imports no parser.** The syntactic half of
`check_citation_style.py` -- is the assembly present, is the form well-formed --
runs in every mod repository, where neither a decompile nor `tree-sitter` is
installed. Anything that needs to know what a *real* element is called belongs
in `decompile_structure`, which this module knows nothing about.

The fields are read by position, never by scanning for punctuation. A member
specification carries `(`, `)`, `<`, `>`, `,`, `.` and the ellipsis `…`, so any
rule phrased over those characters eventually meets a parameter list that
contradicts it -- `Bar(Dictionary<int, string>, …)` is one citation, not two.
What the grammar relies on instead is that `:` appears in none of them.
"""

import re
from dataclasses import dataclass

# A location field: one line, or a range. Anchored, so nothing else matches.
_LOCATION = re.compile(r"^(\d+)(?:-(\d+))?$")

# Finding a citation in prose is a narrower question than parsing one, and
# `FINDER` is deliberately stricter than the grammar: it requires a location.
#
# Measured over `docs/ck/`, where 193 backticked tokens carry a colon without
# being citations -- YAML keys (`skipSafetyChecks: true`), exception messages,
# C# named arguments (`recursive: true`). Rejecting a space after the colon
# removes all but two, and those two are the instructive ones:
# `Mod:WorkbenchChestExtra`, a CoreLib workbench id, and
# `PugMod.Loader:LoadScripts (..., RoslynCSharp.ScriptDomain, ...)`, which is
# the handbook writing a signature after an assembly name -- the exact shape of
# a member-tier citation. No rule over the text can tell those from a real
# citation, because there is no difference to see.
#
# Requiring the last field to be a location removes both and loses nothing: all
# 796 citations in the handbook are still found, and `describe` never writes a
# citation without one. So `Assembly:Class` and `Assembly:Class:member` stay in
# the grammar, parseable and renderable, but are not discovered in prose.
_ASSEMBLY = r"(?:DedicatedServer/)?[A-Za-z][A-Za-z0-9_.]*"
_NAME_FIELD = r"[A-Za-z0-9_][A-Za-z0-9_.()<>,… \t-]*"
FINDER = re.compile(rf"`({_ASSEMBLY}(?::{_NAME_FIELD})*:\d+(?:-\d+)?)`")


@dataclass(frozen=True)
class Citation:
    """One citation, parsed. `assembly` is always present; the rest may not be.

    `first` and `last` are both None for a whole-element citation and equal for
    a single line, so a reader never has to ask which of the two shapes it holds.

    **The constructor refuses a state the grammar cannot express**, because
    every one of them used to lie rather than fail. Measured: `first=None,
    last=5` made `locate` return the element's first line and `render` drop the
    end without a word; a reversed range made `locate` return a line unrelated
    to the citation; a member with no enclosing type rendered `A:Bar:1`, which
    parses back as the *type* tier. Two of those three were silent, so a
    documented convention was not enough -- `parse` and `describe` never built
    one, and the next plan's checker will construct citations by hand.

    Validation costs 3.5 ms over the 62,797 elements of the largest assembly,
    0.08 % of the parse it follows, so there is nothing to trade away here.
    """

    assembly: str
    type_name: str | None
    member: str | None
    first: int | None
    last: int | None

    def __post_init__(self):
        """Refuse what the five grammar forms cannot spell."""
        if not self.assembly:
            raise ValueError("a citation names an assembly or a file")
        if self.member is not None and self.type_name is None:
            raise ValueError(
                f"member {self.member!r} has no enclosing type; "
                "`Assembly:member:N` reads back as the type tier"
            )
        if (self.first is None) != (self.last is None):
            raise ValueError(
                f"a location needs both ends or neither, got {self.first}..{self.last}"
            )
        if self.first is not None and not 1 <= self.first <= self.last:
            raise ValueError(f"lines are 1-based and ordered, got {self.first}..{self.last}")


def _location(field):
    """(first, last) if the field is a location, else None. Does not validate."""
    match = _LOCATION.match(field)
    if not match:
        return None
    first = int(match.group(1))
    return (first, int(match.group(2)) if match.group(2) else first)


def parse(token):
    """A Citation, or None when the token is not one.

    None rather than an exception: the callers are checkers walking prose, where
    a thing that merely looks like a citation is the normal case, not an error.
    """
    assembly, *rest = token.split(":")
    if not assembly or not rest:
        return None

    first = last = None
    if (location := _location(rest[-1])) is not None:
        first, last = location
        if first < 1 or last < first:
            return None  # line 0 and a reversed range name nothing
        rest = rest[:-1]

    if len(rest) > 2 or any(not name for name in rest):
        return None
    if not rest and first is None:
        return None  # an assembly alone is not a citation

    type_name = rest[0] if rest else None
    member = rest[1] if len(rest) > 1 else None
    return Citation(assembly, type_name, member, first, last)


def render(c):
    """The token a Citation was parsed from -- the inverse of `parse`."""
    parts = [c.assembly]
    if c.type_name is not None:
        parts.append(c.type_name)
    if c.member is not None:
        parts.append(c.member)
    if c.first is not None:
        parts.append(str(c.first) if c.first == c.last else f"{c.first}-{c.last}")
    return ":".join(parts)


def tier(c):
    """Which anchor the citation carries: "member", "type" or "absolute".

    The anchor, not the location -- `Assembly:Class` and `Assembly:Class:7` are
    both the type tier. What the tier decides is what the citation survives: a
    member anchor only cares about edits inside that member, a type anchor about
    edits anywhere in the type, and an absolute line about every line above it.
    """
    if c.member is not None:
        return "member"
    if c.type_name is not None:
        return "type"
    return "absolute"


def find(text):
    """Every citation in `text`, as (token as written, Citation), in order.

    The token comes back without its backticks, so a caller can report it or
    substitute it. A candidate `FINDER` matches but `parse` refuses is dropped
    rather than returned: this function answers with citations. Reporting a
    malformed one is the style checker's job and needs the raw text, which is
    why `FINDER` is exported beside this.
    """
    found = []
    for match in FINDER.finditer(text):
        token = match.group(1)
        if (citation := parse(token)) is not None:
            found.append((token, citation))
    return found
