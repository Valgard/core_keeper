"""Tests for relocate_citations.

The two pieces worth testing are the ones that can be wrong quietly: finding a
recorded line sequence in a changed file, and rewriting a citation without
disturbing the span it covers or anything around it.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from relocate_citations import find_sequence
from relocate_citations import relocate
from relocate_citations import rewrite_chapter


class TestFindSequence:
    """Coverage for find_sequence() -- locating a recorded run of lines in a file."""

    def test_single_line_found_once(self):
        """A single-line needle present exactly once is found at its correct position."""
        assert find_sequence(["a", "b", "c"], ["b"]) == [2]

    def test_multi_line_sequence_must_be_consecutive(self):
        """A multi-line needle matches only where its lines are consecutive."""
        haystack = ["a", "b", "c", "b", "x", "c"]
        assert find_sequence(haystack, ["b", "c"]) == [2]

    def test_reports_every_occurrence(self):
        """Every occurrence of the needle is reported, not only the first."""
        assert find_sequence(["x", "y", "x", "y"], ["x", "y"]) == [1, 3]

    def test_absent_sequence_is_empty(self):
        """A needle that appears nowhere returns no matches, not a sentinel value."""
        assert find_sequence(["a", "b"], ["c"]) == []

    def test_empty_needle_matches_nothing(self):
        """An empty needle matches nothing, rather than every position.

        The empty needle is what a citation past the end of a file records;
        matching it everywhere would relocate such a citation to line 1 with
        unearned confidence.
        """
        assert find_sequence(["a", "b"], []) == []

    def test_sequence_running_past_the_end_does_not_match(self):
        """A needle whose tail runs past the file end is not accepted as a partial match."""
        assert find_sequence(["a", "b"], ["b", "c"]) == []


class TestRelocate:
    """Coverage for relocate() -- placing a citation's text at its current line, or why not."""

    def _source(self, tmp_path, lines):
        p = tmp_path / "X.decompiled.cs"
        p.write_text("\n".join(lines))
        return p

    def test_unchanged_when_text_is_still_at_the_old_line(self, tmp_path):
        """Text still at its recorded line is reported unchanged, not as a move in place."""
        src = self._source(tmp_path, ["a", "b", "c"])
        assert relocate(["b"], 2, src) == (2, "unchanged", "")

    def test_moved_reports_the_new_line(self, tmp_path):
        """Text at a different line than recorded is reported moved, giving the new line."""
        src = self._source(tmp_path, ["new", "a", "b", "c"])
        line, verdict, _ = relocate(["b"], 2, src)
        assert (line, verdict) == (3, "moved")

    def test_gone_when_the_text_is_absent(self, tmp_path):
        """Recorded text no longer present in the file is reported gone, not pinned to a line."""
        src = self._source(tmp_path, ["a", "c"])
        line, verdict, _ = relocate(["b"], 2, src)
        assert line is None and verdict == "gone"

    def test_ambiguous_picks_nearest_and_says_so(self, tmp_path):
        """Several equally plausible matches, with no anchors, resolve to the nearest one.

        The verdict's detail also names how many candidates it was chosen among.
        """
        src = self._source(tmp_path, ["b", "x", "x", "x", "b", "x", "x", "b"])
        line, verdict, detail = relocate(["b"], 7, src)
        assert (line, verdict) == (8, "ambiguous")
        assert "3 matches" in detail

    def test_an_equidistant_tie_resolves_to_the_earlier_line(self, tmp_path):
        """An equidistant tie between two candidates resolves to the earlier line.

        The choice is arbitrary -- a tie has no right answer -- but pinned here
        so it cannot silently drift, since the verdict is "ambiguous" either way
        and only a human ever acts on it.
        """
        src = self._source(tmp_path, ["b", "x", "b"])
        line, verdict, _ = relocate(["b"], 2, src)
        assert (line, verdict) == (1, "ambiguous")

    def test_indentation_is_ignored(self, tmp_path):
        """Indentation differences between the recorded text and the source are ignored.

        A nesting level added around otherwise unchanged code therefore counts
        as a move, not as the text being gone.
        """
        src = self._source(tmp_path, ["if (x) {", "    b", "}"])
        line, verdict, _ = relocate(["b"], 1, src)
        assert (line, verdict) == (2, "moved")


class TestRewriteChapter:
    """Coverage for rewrite_chapter() -- rewriting citations in a chapter per a mapping."""

    def _chapter(self, tmp_path, text):
        p = tmp_path / "c.md"
        p.write_text(text)
        return p

    def test_rewrites_a_single_line_citation(self, tmp_path):
        """A single-line citation in the mapping is rewritten; the count reflects one rewrite."""
        p = self._chapter(tmp_path, "see `Pug.Other:100` for this")
        assert rewrite_chapter(p, {"Pug.Other:100": 250}) == 1
        assert p.read_text() == "see `Pug.Other:250` for this"

    def test_a_range_keeps_its_span(self, tmp_path):
        """A range citation keeps its original span width when relocated.

        Only the start line comes from the mapping; the end line shifts by the
        same offset.
        """
        p = self._chapter(tmp_path, "`Pug.Other:100-104`")
        rewrite_chapter(p, {"Pug.Other:100-104": 200})
        assert p.read_text() == "`Pug.Other:200-204`"

    def test_dedicated_server_prefix_survives(self, tmp_path):
        """A citation's DedicatedServer/ assembly prefix survives the rewrite unchanged."""
        p = self._chapter(tmp_path, "`DedicatedServer/Pug.Other:10`")
        rewrite_chapter(p, {"DedicatedServer/Pug.Other:10": 20})
        assert p.read_text() == "`DedicatedServer/Pug.Other:20`"

    def test_citations_absent_from_the_mapping_are_untouched(self, tmp_path):
        """A citation absent from the mapping is left untouched, beside one that is rewritten."""
        p = self._chapter(tmp_path, "`Pug.Other:100` and `Pug.Base:5`")
        assert rewrite_chapter(p, {"Pug.Other:100": 200}) == 1
        assert p.read_text() == "`Pug.Other:200` and `Pug.Base:5`"

    def test_every_occurrence_of_one_key_is_rewritten(self, tmp_path):
        """Every occurrence of one citation is rewritten, not just the first; each is counted."""
        p = self._chapter(tmp_path, "`Pug.Other:7` … later `Pug.Other:7`")
        assert rewrite_chapter(p, {"Pug.Other:7": 9}) == 2
        assert p.read_text() == "`Pug.Other:9` … later `Pug.Other:9`"

    def test_no_mapping_leaves_the_file_alone(self, tmp_path):
        """An empty mapping leaves the file's content and citation completely untouched."""
        p = self._chapter(tmp_path, "`Pug.Other:100`")
        assert rewrite_chapter(p, {}) == 0
        assert p.read_text() == "`Pug.Other:100`"

    def test_a_relocation_does_not_cascade_into_another_citation(self, tmp_path):
        """Rewriting a citation onto a number that is itself a rewrite target does not cascade.

        A citation moved from 10 to 20 is not then swept up again by the rule
        that moves 20 to 30, in the same pass.
        """
        p = self._chapter(tmp_path, "`Pug.Other:10` and `Pug.Other:20`")
        rewrite_chapter(p, {"Pug.Other:10": 20, "Pug.Other:20": 30})
        assert p.read_text() == "`Pug.Other:20` and `Pug.Other:30`"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
