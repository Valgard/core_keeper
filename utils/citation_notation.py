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


@dataclass(frozen=True)
class Citation:
    """One citation, parsed. `assembly` is always present; the rest may not be.

    `first` and `last` are both None for a whole-element citation and equal for
    a single line, so a reader never has to ask which of the two shapes it holds.
    """

    assembly: str
    type_name: str | None
    member: str | None
    first: int | None
    last: int | None


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
        if last < first:
            return None  # a reversed range names nothing
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
