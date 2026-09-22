"""Tests for check_citation_style.

The gate's whole value is where it draws the line between a line reference and
a quantity, so that is what these test. A checker that also rejected `~143 MB`
would be turned off within a week, and then the short form comes back.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from check_citation_style import BARE, TILDE_AFTER_ASSEMBLY, problems_in  # noqa: E402


def flagged(text):
    return bool(BARE.search(text) or TILDE_AFTER_ASSEMBLY.search(text))


class TestRejects:
    @pytest.mark.parametrize(
        "text",
        [
            "see (`:419767`) for this",
            "(`:263245` client, `:263187` server)",
            "a span at (`:124944-124946`) covers it",
            "`UIMouse.UpdateMouseUIInput()` (`Pug.Other` ~355773) casts a ray",
            "(`Pug.Other`, decompiled ~338577) calls Browser.Open()",
            "with the status enum at `modio.UnityPlugin`, decompiled ~29014.",
            "`PugText.Start()` (`Pug.Other` ~`:351419`) is:",
        ],
    )
    def test_unverifiable_forms(self, text):
        assert flagged(text)


class TestAccepts:
    @pytest.mark.parametrize(
        "text",
        [
            "see (`Pug.Other:419767`) for this",
            "(`Pug.Other:263245` client, `DedicatedServer/Pug.Other:263187` server)",
            "the range `Pug.Other:124944-124946` covers it",
            # Quantities, not line references. Rejecting these would make the
            # gate wrong far more often than right.
            "Measured on a ~1300-entity scan",
            "~143 MB plus a ~227 MB `.resS` stream",
            "sits ~135 lines into the same struct",
            "| ~180 scene and structure names |",
            "`Pug.Other` is ~16 MB / ~441k lines",
            "roughly ~40 s per export",
        ],
    )
    def test_acceptable_prose(self, text):
        assert not flagged(text)

    def test_an_assembly_named_without_a_number_is_fine(self):
        assert not flagged("the whole `Pug.Other` family of assemblies")

    def test_a_plain_colon_in_prose_is_not_a_citation(self):
        assert not flagged("the rule is this: every reference carries its assembly")


class TestProblemsIn:
    def test_reports_line_numbers_and_text(self, tmp_path):
        p = tmp_path / "c.md"
        p.write_text("fine `Pug.Other:1`\nbroken `:419767`\n")
        found = problems_in(p)
        assert len(found) == 1
        number, text, _why, _fix = found[0]
        assert number == 2
        assert text == "`:419767`"

    def test_a_clean_file_reports_nothing(self, tmp_path):
        p = tmp_path / "c.md"
        p.write_text("all good `Pug.Other:1` and `DedicatedServer/Pug.Other:2-9`\n")
        assert problems_in(p) == []

    def test_several_offenders_on_one_line_are_all_reported(self, tmp_path):
        p = tmp_path / "c.md"
        p.write_text("(`:1` client, `:2` server)\n")
        assert len(problems_in(p)) == 2


class TestCodeFences:
    def test_a_short_form_inside_a_fence_is_an_example_not_a_violation(self, tmp_path):
        p = tmp_path / "c.md"
        p.write_text(
            "prose\n\n```text\n`:419767`\n`Pug.Other` ~355773\n```\n\nmore prose\n"
        )
        assert problems_in(p) == []

    def test_the_same_text_outside_a_fence_still_fails(self, tmp_path):
        p = tmp_path / "c.md"
        p.write_text("prose `:419767` here\n")
        assert len(problems_in(p)) == 1

    def test_a_tilde_fence_also_opens_a_block(self, tmp_path):
        p = tmp_path / "c.md"
        p.write_text("~~~\n`:1`\n~~~\n")
        assert problems_in(p) == []

    def test_violations_after_a_closed_fence_are_caught(self, tmp_path):
        p = tmp_path / "c.md"
        p.write_text("```\n`:1`\n```\nand then `:2` in prose\n")
        found = problems_in(p)
        assert len(found) == 1 and found[0][1] == "`:2`"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
