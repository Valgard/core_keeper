"""What `describe` writes, the gate that judges it must accept.

The design spec calls this the most important test and the easiest to omit.
Without it a verification pass could write citations that its own commit hook
rejects, and the natural response to a red gate over freshly written citations
is to weaken the gate.

It is deliberately **not** a cross-check between two judges. The structural
half of the style checker calls `describe`; it does not re-decide what the
shortest unique form is, because ADR 0042 records what letting two
implementations judge one claim cost -- "both had to be taught to judge alike;
they did not, twice". What this tests is the wiring between them: that the
value `describe` returns survives `render`, a chapter on disk, the finder, the
grammar, and the checker's own structural pass, all the way back out.

So it runs over the whole real corpus rather than a sample, and the citations
it checks are generated rather than written by hand -- the point is that no
human intervenes anywhere in that path.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from check_citation_drift import resolve_citation
from check_citation_drift import source_for
from check_citation_style import structural_problems
from check_citation_style import syntactic_problems
from citation_notation import parse
from citation_notation import render
from decompile_structure import describe
from decompile_structure import structure_of


@pytest.fixture(scope="module")
def generated(tmp_path_factory, decompile, corpus):
    """(chapter path, [(assembly, line, token)]) for the whole corpus, built once.

    Module-scoped and with the structures resolved per assembly rather than per
    citation. Built the obvious way -- `structure_of` inside the loop -- this
    decodes a 62,000-element cache entry once for each of the corpus's citations
    and then does it again for every test in the file, which is how the first
    version of this ran past a two-minute timeout.
    """
    structures = {}
    lines, written = [], []
    for assembly, line in corpus:
        if assembly not in structures:
            source = source_for(assembly, decompile)
            structures[assembly] = structure_of(source) if source is not None else None
        structure = structures[assembly]
        if structure is None:
            continue
        citation = describe(structure, line, assembly)
        if citation is None:
            continue
        token = render(citation)
        written.append((assembly, line, token))
        lines.append(f"the call `{token}` does it")

    chapter = tmp_path_factory.mktemp("generated") / "docs" / "ck" / "generated.md"
    chapter.parent.mkdir(parents=True, exist_ok=True)
    chapter.write_text("\n".join(lines) + "\n")
    return chapter, written


def test_the_style_checker_accepts_every_citation_describe_writes(generated, decompile):
    """End to end: describe -> render -> a chapter on disk -> the real checker."""
    chapter, written = generated
    assert written, "the corpus resolved to nothing — the fixtures or the decompile moved"

    assert syntactic_problems(chapter) == []
    assert structural_problems(chapter, decompile) == []


def test_every_generated_citation_parses_back_to_what_describe_returned(generated):
    """The grammar leg of the same path, isolated so a failure says which half broke.

    A citation can be correct in memory and unspellable on the page -- one real
    parameter type carries the character the grammar splits fields on -- so
    rendering and re-parsing is its own claim.
    """
    _, written = generated
    broken = [token for _, _, token in written if parse(token) is None]
    assert broken == [], f"{len(broken)} citation(s) do not parse back: {broken[:5]}"


def test_the_drift_checker_resolves_every_citation_describe_writes(generated, decompile):
    """The other consumer of the same output, and the one that gates commits.

    The style checker only has to accept the form; the drift checker has to
    resolve it back to the line it came from. A citation that passes the first
    and fails the second would be reported as a renamed member on every run.
    """
    _, written = generated
    structures = {}  # one decode per assembly; without it this took 95 s
    broken = [
        f"{token} (from {assembly}:{line})"
        for assembly, line, token in written
        if resolve_citation(parse(token), decompile, structures) is None
    ]
    assert broken == [], f"{len(broken)} citation(s) do not resolve: {broken[:5]}"
