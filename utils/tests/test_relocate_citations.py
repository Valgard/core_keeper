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
    def test_single_line_found_once(self):
        assert find_sequence(["a", "b", "c"], ["b"]) == [2]

    def test_multi_line_sequence_must_be_consecutive(self):
        haystack = ["a", "b", "c", "b", "x", "c"]
        assert find_sequence(haystack, ["b", "c"]) == [2]

    def test_reports_every_occurrence(self):
        assert find_sequence(["x", "y", "x", "y"], ["x", "y"]) == [1, 3]

    def test_absent_sequence_is_empty(self):
        assert find_sequence(["a", "b"], ["c"]) == []

    def test_empty_needle_matches_nothing(self):
        # A citation past the end of file records no lines. Returning every
        # position for it would relocate it to line 1 with full confidence.
        assert find_sequence(["a", "b"], []) == []

    def test_sequence_running_past_the_end_does_not_match(self):
        assert find_sequence(["a", "b"], ["b", "c"]) == []


class TestRelocate:
    def _source(self, tmp_path, lines):
        p = tmp_path / "X.decompiled.cs"
        p.write_text("\n".join(lines))
        return p

    def test_unchanged_when_text_is_still_at_the_old_line(self, tmp_path):
        src = self._source(tmp_path, ["a", "b", "c"])
        assert relocate(["b"], 2, src) == (2, "unchanged", "")

    def test_moved_reports_the_new_line(self, tmp_path):
        src = self._source(tmp_path, ["new", "a", "b", "c"])
        line, verdict, _ = relocate(["b"], 2, src)
        assert (line, verdict) == (3, "moved")

    def test_gone_when_the_text_is_absent(self, tmp_path):
        src = self._source(tmp_path, ["a", "c"])
        line, verdict, _ = relocate(["b"], 2, src)
        assert line is None and verdict == "gone"

    def test_ambiguous_picks_nearest_and_says_so(self, tmp_path):
        src = self._source(tmp_path, ["b", "x", "x", "x", "b", "x", "x", "b"])
        line, verdict, detail = relocate(["b"], 7, src)
        assert (line, verdict) == (8, "ambiguous")
        assert "3 matches" in detail

    def test_an_equidistant_tie_resolves_to_the_earlier_line(self, tmp_path):
        # Documented rather than meaningful: a tie has no right answer, and the
        # suggestion only ever reaches a human, because "ambiguous" is never
        # applied automatically. Pinned so the choice cannot drift silently.
        src = self._source(tmp_path, ["b", "x", "b"])
        line, verdict, _ = relocate(["b"], 2, src)
        assert (line, verdict) == (1, "ambiguous")

    def test_indentation_is_ignored(self, tmp_path):
        # A nesting level added around unchanged code moves every line inside
        # it without altering what any of them says.
        src = self._source(tmp_path, ["if (x) {", "    b", "}"])
        line, verdict, _ = relocate(["b"], 1, src)
        assert (line, verdict) == (2, "moved")


class TestRewriteChapter:
    def _chapter(self, tmp_path, text):
        p = tmp_path / "c.md"
        p.write_text(text)
        return p

    def test_rewrites_a_single_line_citation(self, tmp_path):
        p = self._chapter(tmp_path, "see `Pug.Other:100` for this")
        assert rewrite_chapter(p, {"Pug.Other:100": 250}) == 1
        assert p.read_text() == "see `Pug.Other:250` for this"

    def test_a_range_keeps_its_span(self, tmp_path):
        p = self._chapter(tmp_path, "`Pug.Other:100-104`")
        rewrite_chapter(p, {"Pug.Other:100-104": 200})
        assert p.read_text() == "`Pug.Other:200-204`"

    def test_dedicated_server_prefix_survives(self, tmp_path):
        p = self._chapter(tmp_path, "`DedicatedServer/Pug.Other:10`")
        rewrite_chapter(p, {"DedicatedServer/Pug.Other:10": 20})
        assert p.read_text() == "`DedicatedServer/Pug.Other:20`"

    def test_citations_absent_from_the_mapping_are_untouched(self, tmp_path):
        p = self._chapter(tmp_path, "`Pug.Other:100` and `Pug.Base:5`")
        assert rewrite_chapter(p, {"Pug.Other:100": 200}) == 1
        assert p.read_text() == "`Pug.Other:200` and `Pug.Base:5`"

    def test_every_occurrence_of_one_key_is_rewritten(self, tmp_path):
        p = self._chapter(tmp_path, "`Pug.Other:7` … later `Pug.Other:7`")
        assert rewrite_chapter(p, {"Pug.Other:7": 9}) == 2
        assert p.read_text() == "`Pug.Other:9` … later `Pug.Other:9`"

    def test_no_mapping_leaves_the_file_alone(self, tmp_path):
        p = self._chapter(tmp_path, "`Pug.Other:100`")
        assert rewrite_chapter(p, {}) == 0
        assert p.read_text() == "`Pug.Other:100`"

    def test_a_relocation_does_not_cascade_into_another_citation(self, tmp_path):
        # Rewriting A onto B's old number must not then rewrite it again as B.
        p = self._chapter(tmp_path, "`Pug.Other:10` and `Pug.Other:20`")
        rewrite_chapter(p, {"Pug.Other:10": 20, "Pug.Other:20": 30})
        assert p.read_text() == "`Pug.Other:20` and `Pug.Other:30`"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
