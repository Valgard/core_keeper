"""The structure layer against the real handbook corpus, not fixtures.

This is the acceptance test of the symbol-anchoring work. It runs over every
citation rather than a sample on purpose: the median search space moved by a
factor of three between two prototypes that each looked plausible on a handful
of citations, so an aggregate taken from part of the corpus measures whichever
bug happens to dominate.

**What each test here can and cannot catch.** Two earlier drafts of this
paragraph were wrong, in the same way each time: they claimed a reach for a test
without measuring it. What follows is measured.

The round trip is an identity whenever `describe` and `locate` agree on the
element. `describe` computes an offset from the element it found; `locate`
re-finds it by name and inverts the arithmetic. So a wrong *extent* passes it
unharmed. What it catches is every way the *name* fails -- an anchor matching
several declarations, a form nothing can spell, a token that will not parse back
-- which is how it found seven `UpdateJob` declarations sharing one name.

The tier census does **not** cover extents either, which was the second wrong
claim. A decoy member nested inside every real member of every cited assembly
leaves it reading exactly 660/56/5/1, with the round trip, the token round trip
and the range test all green: the decoy is the innermost element, so the tier
stays "member" and the arithmetic stays consistent. What the census does catch
is an extent that changes which tier a line falls in -- a member whose `end`
runs past its own body, for instance.

Extents are covered by the two property tests at the end of this file --
members disjoint, members inside their type -- and by the four calibration
fixtures, whose expected values were read out of the decompile by hand rather
than taken from this code. The properties are the load-bearing half: five
hand-checked points against 157,134 elements is a sample, and disjointness is
a property.

It needs the decompile checkout and skips loudly without one. A skip here means
the suite proved nothing about the handbook, which is different from passing.
"""

from pathlib import Path

import pytest
from check_citation_drift import CITATION
from check_citation_drift import DEFAULT_DECOMPILE
from check_citation_drift import source_for
from citation_notation import parse
from citation_notation import render
from citation_notation import tier
from decompile_structure import describe
from decompile_structure import locate
from decompile_structure import structure_of

# Four citations resolved by hand against the decompile, as the fixtures that
# catch a regression in name construction.
#
# The fourth is the interesting one. An earlier draft of this suite expected
# type `MaterialInfoData`, which is what a regex prototype reported: it read
# the nearest preceding declaration, and `public struct MaterialInfoData(
# ObjectID, ...)` is a primary-constructor struct that looks like a method
# head. The enclosing type is `PugDatabase`, the method head sits at 326,272,
# and 326,339 is its relative line 68.
CALIBRATION = [
    (380762, "SaveManager", "SetCharacterId"),
    (338981, "SimpleCraftingUIContainer", "MAX_RECIPES_PER_UI"),
    (370859, "SmallTitleUIBackground", "UpdateTextAndBackground"),
    (326339, "PugDatabase", "GetRandomLoot"),
]

# The anchor-tier census the design spec states, measured over the same corpus.
TIERS = {"member": 660, "type": 56, "absolute": 5, "unchecked": 1}


@pytest.fixture(scope="module")
def decompile():
    """The decompile checkout, or a loud skip."""
    path = Path(str(DEFAULT_DECOMPILE)).expanduser()
    if not path.is_dir():
        pytest.skip(f"no decompile tree at {path} — this suite checks the real corpus")
    return path


@pytest.fixture(scope="module")
def corpus():
    """Every unique `(assembly, first line)` the handbook cites.

    Unique by assembly and line, which is the base the spec's figures use. The
    occurrence count is higher and the two must not be mixed.
    """
    root = Path(__file__).resolve().parents[2] / "docs" / "ck"
    cited = set()
    for chapter in sorted(root.glob("*.md")):
        for match in CITATION.finditer(chapter.read_text()):
            assembly, _, tail = match.group(0).strip("`").rpartition(":")
            first = tail.split("-")[0]
            if first.isdigit():
                cited.add((assembly, int(first)))
    return sorted(cited)


@pytest.fixture(scope="module")
def structures(decompile, corpus):
    """One Structure per cited assembly, parsed once and shared.

    Resolved and parsed per assembly rather than per citation: `structure_of`
    is cached, but decoding a 62,000-element entry 506 times for one assembly
    is the same linear-scan mistake one layer out.
    """
    index = {}
    for assembly, _ in corpus:
        if assembly not in index:
            path = source_for(assembly, decompile)
            index[assembly] = structure_of(path) if path else None
    return index


@pytest.mark.parametrize(("line", "type_name", "member"), CALIBRATION)
def test_calibration_against_known_citations(structures, line, type_name, member):
    """Each hand-resolved citation gets the type and member it really sits in."""
    citation = describe(structures["Pug.Other"], line, "Pug.Other")
    assert citation.type_name == type_name
    assert citation.member.split("(")[0] == member


def test_the_documented_relative_line_is_reproduced(structures):
    """`Pug.Other:370859` is line 29 of its member, as the design spec states."""
    assert describe(structures["Pug.Other"], 370859, "Pug.Other").first == 29


def test_every_citation_round_trips(corpus, structures):
    """locate(describe(line)) == line, for all of them.

    What this licenses is the migration of an already-verified chapter without
    re-reading it: the new citation provably resolves to the line the old number
    pointed at, so the verdict weighed against that line still stands. That is
    a statement about the arithmetic and the name, not about the extent -- see
    the module docstring for what it cannot see.
    """
    broken = []
    for assembly, line in corpus:
        structure = structures[assembly]
        if structure is None:
            continue  # the unchecked tier; the census test counts these
        citation = describe(structure, line, assembly)
        if citation is None or locate(structure, citation) != line:
            spelled = render(citation) if citation else None
            broken.append(f"{assembly}:{line} -> {spelled}")
    assert broken == [], f"{len(broken)} citation(s) do not round trip: {broken[:10]}"


def test_the_tier_census_matches_the_spec(corpus, structures):
    """The anchor tiers come out 660 / 56 / 5 / 1 over the 722 unique citations.

    A census that drifts is the signal that element extents moved — a grammar
    upgrade, or a decompile regenerated from different DLLs — and it is worth a
    hard failure rather than a warning, because the citations keep resolving
    either way and nothing else would say so.
    """
    counts = dict.fromkeys(TIERS, 0)
    for assembly, line in corpus:
        structure = structures[assembly]
        if structure is None:
            counts["unchecked"] += 1
            continue
        counts[tier(describe(structure, line, assembly))] += 1
    assert counts == TIERS


def test_the_corpus_is_the_size_the_spec_says(corpus):
    """722 unique citations — the denominator every other figure here rests on."""
    assert len(corpus) == 722


@pytest.fixture(scope="module")
def range_citations():
    """Every unique range citation the handbook carries, as (assembly, first, last)."""
    root = Path(__file__).resolve().parents[2] / "docs" / "ck"
    spans = set()
    for chapter in sorted(root.glob("*.md")):
        for match in CITATION.finditer(chapter.read_text()):
            citation = parse(match.group(0).strip("`"))
            if citation is not None and citation.first != citation.last:
                spans.add((citation.assembly, citation.first, citation.last))
    return sorted(spans)


def test_every_citation_survives_being_written_and_read_back(corpus, structures):
    """Describe -> render -> parse returns the same citation, for all of them.

    The round trip above never leaves the objects, so it cannot see a citation
    that is correct in memory and unspellable on the page. One real parameter
    type, `global::Discord.Discord`, carries the character the grammar splits
    fields on, and a form built from it rendered a token `parse` refused.
    """
    broken = []
    for assembly, line in corpus:
        structure = structures[assembly]
        if structure is None:
            continue
        citation = describe(structure, line, assembly)
        if parse(render(citation)) != citation:
            broken.append(render(citation))
    assert broken == [], f"{len(broken)} citation(s) do not survive a round trip: {broken[:5]}"


def test_every_range_citation_keeps_its_span(range_citations, structures):
    """A range resolves to its first line and still spans as many lines.

    127 of the handbook's citations are ranges and five of them cross out of
    their first line's member, so this is the test that the widening to the
    enclosing type actually holds on real data rather than on the fixture.
    """
    assert len(range_citations) == 127
    broken = []
    for assembly, first, last in range_citations:
        structure = structures[assembly]
        if structure is None:
            continue
        citation = describe(structure, first, assembly, last=last)
        if locate(structure, citation) != first or citation.last - citation.first != last - first:
            broken.append(f"{assembly}:{first}-{last} -> {render(citation)}")
    assert broken == [], f"{len(broken)} range(s) do not round trip: {broken[:5]}"


def test_member_extents_are_disjoint_across_the_corpus(structures):
    """`_enclosing` bisects over member starts, which is only valid if they are.

    The property both other instruments are blind to, measured rather than
    argued: a decoy member nested inside every real member of every cited
    assembly leaves the tier census at exactly 660/56/5/1 and the round trip at
    zero failures. `describe` picks the decoy because it is the innermost
    element, `locate` inverts the same arithmetic, and the citation ends up
    naming a member that does not exist with nothing saying so.

    Disjointness sees it, because a nested decoy overlaps its parent -- and so
    does an extent that reaches into its neighbour, which the census catches but
    this catches earlier and by name. It is also the assumption `_enclosing`
    has been making all along, so checking it costs nothing that was not
    already owed.
    """
    overlaps = []
    for assembly, structure in sorted(structures.items()):
        if structure is None:
            continue
        furthest = None
        for element in structure.members:
            if furthest is not None and element.start <= furthest.end:
                overlaps.append(
                    f"{assembly}: {furthest.type_name}:{furthest.member}"
                    f" ({furthest.start}-{furthest.end}) overlaps"
                    f" {element.type_name}:{element.member}"
                    f" ({element.start}-{element.end})"
                )
            if furthest is None or element.end > furthest.end:
                furthest = element
    assert overlaps == [], f"{len(overlaps)} overlapping member extent(s): {overlaps[:3]}"


def test_every_member_lies_inside_the_type_it_names(structures):
    """A member's extent inside its type's, for every member that has a type.

    The members with `type_name=None` are the namespace-level declarations, and
    `describe` already refuses to claim those -- they are the legitimate
    exception, not a violation.
    """
    escaped = []
    for assembly, structure in sorted(structures.items()):
        if structure is None:
            continue
        extents = {}
        for element in structure.types:
            extents.setdefault(element.type_name, []).append(element)
        for element in structure.members:
            if element.type_name is None:
                continue
            holders = extents.get(element.type_name, ())
            if not any(t.start <= element.start and element.end <= t.end for t in holders):
                escaped.append(f"{assembly}: {element.type_name}:{element.member}")
    assert escaped == [], f"{len(escaped)} member(s) outside their type: {escaped[:3]}"
