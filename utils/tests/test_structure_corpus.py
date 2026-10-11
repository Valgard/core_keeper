"""The structure layer against the real handbook corpus, not fixtures.

This is the acceptance test of the symbol-anchoring work. It runs over every
citation rather than a sample on purpose: the median search space moved by a
factor of three between two prototypes that each looked plausible on a handful
of citations, so an aggregate taken from part of the corpus measures whichever
bug happens to dominate.

**What each test here catches, by mutation rather than by argument.** Three
earlier drafts of this paragraph each claimed a reach that a twenty-line
measurement then refuted, so this one states only what was measured. Each row
is a defect injected into the real corpus; the columns say which test went red.

| injected defect | round trip | tier bounds | properties |
|---|---|---|---|
| type names left unqualified | — | **absolute 12 > 10** | — |
| every member's `end` + 20 | — | **type 2 < 20** | **overlap** |
| decoy member nested in each real one | — | 727/57/5/1, in bounds | **overlap** |

The round trip caught none of the three, and that is not a gap to close but
what it is: `describe` falls back to a tier `locate` can always invert, so the
two are mutual inverses by construction. It did catch the seven `UpdateJob`
declarations while it was being built, before that fallback existed. What it
pins today is the inverse relationship itself -- change `_forms` on one side
only and it goes red -- which is worth a test and is not a check on the data.

So the data is covered by the census and the two property tests, and they are
complementary rather than redundant: the census sees a line change tier, which
a nested decoy never does; the properties see an extent overlap another, which
the census reads as a perfectly ordinary distribution. The four calibration
fixtures cover name construction at four points, read out of the decompile by
hand rather than taken from this code -- a sample, where the properties are
properties.

It needs the decompile checkout and skips loudly without one. A skip here means
the suite proved nothing about the handbook, which is different from passing.
"""

import pytest
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

# Bounds on the anchor-tier distribution, not the counts themselves. The counts
# are a measurement of one day's corpus -- the spec records 660/56/5/1 over 722
# citations -- and the handbook gains citations constantly: `main` added 68 in a
# single day while this branch was being built. A test pinned to the numbers
# goes red every time somebody documents something, which is the gate that
# teaches people to edit the expected value instead of looking at it.
#
# These bounds were chosen by measuring them against the defects the exact
# census caught, on the enlarged corpus: leaving nested type names unqualified
# pushes `absolute` to 12, and adding 20 lines to every member's extent
# collapses `type` to 2. Both still fail here.
MAX_ABSOLUTE = 10
MIN_TYPE = 20
MIN_MEMBER_SHARE = 0.85


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
    assert citation.member is not None
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


def _census(corpus, structures):
    """How many citations land in each anchor tier."""
    counts = dict.fromkeys(("member", "type", "absolute", "unchecked"), 0)
    for assembly, line in corpus:
        structure = structures[assembly]
        if structure is None:
            counts["unchecked"] += 1
            continue
        counts[tier(describe(structure, line, assembly))] += 1
    return counts


def test_the_anchor_tiers_stay_in_the_shape_the_design_assumes(corpus, structures):
    """Nearly every citation anchors on a member, a few on a type, almost none absolutely.

    The instrument that notices element extents moving -- a grammar upgrade, a
    decompile regenerated from different DLLs -- because the citations keep
    resolving either way and nothing else here would say so. Bounds rather than
    counts, for the reason given at MAX_ABSOLUTE.
    """
    counts = _census(corpus, structures)
    assert counts["absolute"] <= MAX_ABSOLUTE, counts
    assert counts["type"] >= MIN_TYPE, counts
    assert counts["member"] >= MIN_MEMBER_SHARE * len(corpus), counts


def test_every_citation_is_accounted_for_in_exactly_one_tier(corpus, structures):
    """The tiers partition the corpus, so no citation is counted twice or lost.

    What the pinned corpus size used to assert, as a property instead: it holds
    at any size, and it is the invariant the other figures here rest on.
    """
    assert sum(_census(corpus, structures).values()) == len(corpus)
    # A floor on the corpus itself, which the range fixture has and this did
    # not: every other assertion here is relative to `len(corpus)`, so a
    # fixture that silently collected nothing would satisfy all of them.
    assert len(corpus) >= 500, f"only {len(corpus)} citations — the fixture or docs/ck moved"


def test_the_corpus_leaves_no_citation_out_without_saying_so(unresolved):
    """Every citation in `docs/ck/` reached the corpus, or this test names the ones that did not.

    An anchored citation is resolved through `locate` to the line it points
    at, and one that no longer resolves cannot be. Dropping it is right --
    there is no line to measure, and the drift gate has the recorded text to
    say what changed -- but dropping it *silently* is the defect the fixture's
    own opening paragraph warns about: a corpus that "would quietly shrink as
    the migration progressed and every suite resting on it would test less
    without saying so".

    The floor below is not that guard. Measured: the corpus holds 790 unique
    lines, and the 566 spans reachable through a still-absolute citation leave
    561 of them — so losing every anchored citation passes a floor of 500, and
    the slack grows with each chapter migrated.

    **And it covers one of the two ways a citation can go missing, not both.**
    What `unresolved` holds is a citation `FINDER` discovered and `locate`
    could not place. One the pattern stops matching at all -- a grammar
    change, a character nobody anticipated in a member name -- is in neither
    set and this test says nothing about it.

    A second, rougher census was tried for that and does not work: a pattern
    loose enough to catch what the grammar might reject finds 950 tokens
    against `find`'s 893, and the 57 it adds are YAML keys and exception
    messages. Asserting a gap would pin two corpus figures, which is the thing
    this file does not do. What does detect that case is
    `check_citation_drift`: a citation the pattern stops matching leaves its
    snapshot record cited by nothing, which `compare` reports and exits 1 on.
    It **fails** rather than *blocks* -- that checker is in no pre-commit hook,
    so it catches this whenever somebody runs it, which the verification
    procedure requires and no machine enforces. Saying "blocks" here would be
    the third instance on this branch alone of claiming a gate that is not
    wired.
    """
    assert unresolved == (), f"{len(unresolved)} citation(s) left out: {unresolved[:5]}"


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
    # A floor, not the count. 07167d0 removed the pinned corpus figures from
    # this suite because `main` gained 68 citations in a day and every one of
    # them went red; re-pinning 127 here would have brought that back the first
    # time anyone wrote a range. What the test needs is that there are enough
    # of them to be worth checking.
    assert len(range_citations) >= 100
    broken = []
    for assembly, first, last in range_citations:
        structure = structures[assembly]
        if structure is None:
            continue
        citation = describe(structure, first, assembly, last=last)
        if (
            citation.first is None
            or citation.last is None
            or locate(structure, citation) != first
            or citation.last - citation.first != last - first
        ):
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
