"""The structure layer against the real handbook corpus, not fixtures.

This is the acceptance test of the symbol-anchoring work and the instrument
that would have caught both throwaway regex recognisers the day they were
written. It runs over every citation rather than a sample on purpose: the
median search space moved by a factor of three between two prototypes that
each looked plausible on a handful of citations, so an aggregate taken from
part of the corpus measures whichever bug happens to dominate.

It needs the decompile checkout and skips loudly without one. A skip here means
the suite proved nothing about the handbook, which is different from passing.
"""

from pathlib import Path

import pytest
from check_citation_drift import CITATION
from check_citation_drift import DEFAULT_DECOMPILE
from check_citation_drift import source_for
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

    The property that makes the migration safe to run mechanically on a
    verified chapter: the new citation provably resolves to the line the old
    number pointed at, so the verdict that was weighed against that line stands.
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
