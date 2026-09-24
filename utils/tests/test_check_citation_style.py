"""Tests for check_citation_style.

The gate's whole value is where it draws the line between a line reference and
a quantity, so that is what these test. A checker that also rejected `~143 MB`
would be turned off within a week, and then the short form comes back.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from check_citation_style import BARE
from check_citation_style import TILDE_AFTER_ASSEMBLY
from check_citation_style import problems_in


def flagged(text):
    """Whether `text` trips either of the two unverifiable-citation patterns below."""
    return bool(BARE.search(text) or TILDE_AFTER_ASSEMBLY.search(text))


class TestRejects:
    """Text forms the checker must flag as unverifiable line references."""

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
        """Every parametrized form -- missing assembly or one split off by a tilde -- is flagged."""
        assert flagged(text)


class TestAccepts:
    """Prose the checker must never flag: valid citations and quantities that only resemble one."""

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
        """Valid citations and quantities that merely look like one both pass without a flag."""
        assert not flagged(text)

    def test_an_assembly_named_without_a_number_is_fine(self):
        """An assembly name in backticks with no number nearby is not itself a violation."""
        assert not flagged("the whole `Pug.Other` family of assemblies")

    def test_a_plain_colon_in_prose_is_not_a_citation(self):
        """A colon directly followed by digits, but with no backticks at all, is not a citation.

        The old fixture ("the rule is this: every reference carries its
        assembly") had neither a digit nor a colon-then-number shape
        anywhere in it, so BARE's mandatory backticks were never exercised —
        the sentence could not have matched even with them dropped entirely.
        This one has both ingredients BARE looks for (a colon immediately
        followed by digits) with no backticks in sight, so it only stays
        unflagged while the backtick requirement is actually enforced.
        """
        assert not flagged("the id is this:419767, and that colon is not an assembly")


class TestProblemsIn:
    """Coverage for problems_in() -- unverifiable citations in one file, with line numbers."""

    def test_reports_line_numbers_and_text(self, tmp_path):
        """A problem's line number is where it occurs; its text is the exact matched citation."""
        p = tmp_path / "c.md"
        p.write_text("fine `Pug.Other:1`\nbroken `:419767`\n")
        found = problems_in(p)
        assert len(found) == 1
        number, text, _why, _fix = found[0]
        assert number == 2
        assert text == "`:419767`"

    def test_a_clean_file_reports_nothing(self, tmp_path):
        """A file where every citation is already checkable reports no problems at all."""
        p = tmp_path / "c.md"
        p.write_text("all good `Pug.Other:1` and `DedicatedServer/Pug.Other:2-9`\n")
        assert problems_in(p) == []

    def test_several_offenders_on_one_line_are_all_reported(self, tmp_path):
        """Multiple violations on one line are each reported, not collapsed into one problem."""
        p = tmp_path / "c.md"
        p.write_text("(`:1` client, `:2` server)\n")
        assert len(problems_in(p)) == 2


class TestCodeFences:
    """Coverage for problems_in()'s fenced-code-block exclusion."""

    def test_a_short_form_inside_a_fence_is_an_example_not_a_violation(self, tmp_path):
        """A short form shown as an example inside a fenced code block is not flagged.

        Using the notation to explain it is not the same as writing it for real.
        """
        p = tmp_path / "c.md"
        p.write_text("prose\n\n```text\n`:419767`\n`Pug.Other` ~355773\n```\n\nmore prose\n")
        assert problems_in(p) == []

    def test_the_same_text_outside_a_fence_still_fails(self, tmp_path):
        """The same unverifiable text outside any fence is still caught.

        Confirms the fence exclusion is scoped to fenced content, not a
        blanket disabling of detection.
        """
        p = tmp_path / "c.md"
        p.write_text("prose `:419767` here\n")
        assert len(problems_in(p)) == 1

    def test_a_tilde_fence_also_opens_a_block(self, tmp_path):
        """A `~~~`-delimited fence opens and closes a block exactly like a backtick fence."""
        p = tmp_path / "c.md"
        p.write_text("~~~\n`:1`\n~~~\n")
        assert problems_in(p) == []

    def test_violations_after_a_closed_fence_are_caught(self, tmp_path):
        """A fence that has already closed no longer suppresses detection.

        A violation written afterward, in prose, is still caught.
        """
        p = tmp_path / "c.md"
        p.write_text("```\n`:1`\n```\nand then `:2` in prose\n")
        found = problems_in(p)
        assert len(found) == 1 and found[0][1] == "`:2`"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
