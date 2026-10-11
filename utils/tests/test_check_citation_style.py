"""Tests for check_citation_style.

The gate's whole value is where it draws the line between a line reference and
a quantity, so that is what these test. A checker that also rejected `~143 MB`
would be turned off within a week, and then the short form comes back.
"""

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import check_citation_style as mod
from check_citation_style import BARE
from check_citation_style import TILDE_AFTER_ASSEMBLY
from check_citation_style import syntactic_problems


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


class TestSyntacticProblems:
    """Unverifiable citations in one file, with the line numbers to find them by."""

    def test_reports_line_numbers_and_text(self, tmp_path):
        """A problem's line number is where it occurs; its text is the exact matched citation."""
        p = tmp_path / "c.md"
        p.write_text("fine `Pug.Other:1`\nbroken `:419767`\n")
        found = syntactic_problems(p)
        assert len(found) == 1
        number, text, _why, _fix = found[0]
        assert number == 2
        assert text == "`:419767`"

    def test_a_clean_file_reports_nothing(self, tmp_path):
        """A file where every citation is already checkable reports no problems at all."""
        p = tmp_path / "c.md"
        p.write_text("all good `Pug.Other:1` and `DedicatedServer/Pug.Other:2-9`\n")
        assert syntactic_problems(p) == []

    def test_several_offenders_on_one_line_are_all_reported(self, tmp_path):
        """Multiple violations on one line are each reported, not collapsed into one problem."""
        p = tmp_path / "c.md"
        p.write_text("(`:1` client, `:2` server)\n")
        assert len(syntactic_problems(p)) == 2


class TestCodeFences:
    """Coverage for syntactic_problems()'s fenced-code-block exclusion."""

    def test_a_short_form_inside_a_fence_is_an_example_not_a_violation(self, tmp_path):
        """A short form shown as an example inside a fenced code block is not flagged.

        Using the notation to explain it is not the same as writing it for real.
        """
        p = tmp_path / "c.md"
        p.write_text("prose\n\n```text\n`:419767`\n`Pug.Other` ~355773\n```\n\nmore prose\n")
        assert syntactic_problems(p) == []

    def test_the_same_text_outside_a_fence_still_fails(self, tmp_path):
        """The same unverifiable text outside any fence is still caught.

        Confirms the fence exclusion is scoped to fenced content, not a
        blanket disabling of detection.
        """
        p = tmp_path / "c.md"
        p.write_text("prose `:419767` here\n")
        assert len(syntactic_problems(p)) == 1

    def test_a_tilde_fence_also_opens_a_block(self, tmp_path):
        """A `~~~`-delimited fence opens and closes a block exactly like a backtick fence."""
        p = tmp_path / "c.md"
        p.write_text("~~~\n`:1`\n~~~\n")
        assert syntactic_problems(p) == []

    def test_violations_after_a_closed_fence_are_caught(self, tmp_path):
        """A fence that has already closed no longer suppresses detection.

        A violation written afterward, in prose, is still caught.
        """
        p = tmp_path / "c.md"
        p.write_text("```\n`:1`\n```\nand then `:2` in prose\n")
        found = syntactic_problems(p)
        assert len(found) == 1 and found[0][1] == "`:2`"


# --- the two halves ----------------------------------------------------------

FAKE_SOURCE = """\
class Foo
{
    void Bar()
    {
        x();
    }

    void Baz()
    {
        y();
    }
}
"""


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def fake_decompile(tmp_path):
    """A decompile tree holding one assembly, `A`, with two members.

    Line 4 is inside `Bar`, and `Bar` is the type's only member -- so `Bar` is
    already the minimal form while `Bar()` is a longer one that still resolves.
    """
    tree = tmp_path / "decompile"
    tree.mkdir()
    (tree / "A.decompiled.cs").write_text(FAKE_SOURCE)
    return tree


def write(tmp_path, text, name="a.md"):
    """Write a markdown file at `tmp_path/name` and return its path."""
    path = tmp_path / name
    path.write_text(text)
    return path


def write_chapter(root, name, text):
    """Write a handbook chapter at `root/docs/ck/<name>`."""
    docs = root / "docs" / "ck"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / name).write_text(text)


def whys(problems):
    """Just the reasons, which is what these tests are about."""
    return [why for _, _, why, _ in problems]


def test_a_malformed_citation_token_is_a_syntactic_problem(tmp_path):
    """A reversed range is unparseable, so no checker can follow it."""
    path = write(tmp_path, "see `Pug.Other:Foo:Bar:12-7` here\n")
    assert whys(mod.syntactic_problems(path)) == ["citation token does not parse"]


def test_the_two_banned_short_forms_are_still_syntactic_problems(tmp_path):
    """The rule that existed before this change keeps working."""
    path = write(tmp_path, "see `:419767` and `Pug.Other` ~355773\n")
    assert len(mod.syntactic_problems(path)) == 2


def test_a_fenced_citation_is_not_reported_anywhere(tmp_path):
    """A README showing the notation is not using it."""
    path = write(tmp_path, "```\n`:419767`\n```\n", name="README.md")
    assert mod.syntactic_problems(path) == []


def test_a_bare_line_where_a_name_exists_is_a_structural_problem(tmp_path, fake_decompile):
    """The finding that drives the migration: this line is inside a named member."""
    path = write(tmp_path, "see `A:4` here\n")
    assert whys(mod.structural_problems(path, fake_decompile)) == [
        "line is inside Foo:Bar, which the citation could name"
    ]


def test_a_longer_than_necessary_member_form_is_a_structural_problem(tmp_path, fake_decompile):
    """`Bar()` resolves, but `Bar` is already unique and shorter."""
    path = write(tmp_path, "see `A:Foo:Bar():1` here\n")
    assert whys(mod.structural_problems(path, fake_decompile)) == [
        "longer than necessary; `A:Foo:Bar:1` says the same"
    ]


def test_a_citation_already_minimal_is_no_problem(tmp_path, fake_decompile):
    """The form `describe` would write is the form that passes."""
    path = write(tmp_path, "see `A:Foo:Bar:1` here\n")
    assert mod.structural_problems(path, fake_decompile) == []


def test_a_citation_that_does_not_resolve_is_a_structural_problem(tmp_path, fake_decompile):
    """The member was renamed or never existed, so the anchor names nothing."""
    path = write(tmp_path, "see `A:Foo:Gone:1` here\n")
    assert whys(mod.structural_problems(path, fake_decompile)) == ["does not resolve"]


def test_an_assembly_missing_from_the_checkout_is_skipped_with_its_reason(tmp_path, fake_decompile):
    """One unresolvable assembly does not fail the file, and says why it was skipped."""
    path = write(tmp_path, "see `Absent.Assembly:Foo:Bar:1` here\n")
    assert whys(mod.structural_problems(path, fake_decompile)) == [
        "not checked: nothing named Absent.Assembly in the decompile"
    ]


def test_a_file_that_is_found_but_not_csharp_says_that_instead(tmp_path, fake_decompile):
    """Two facts, not one: the file is missing, or it is there and has no elements.

    The only case that occurs in the real corpus is the second -- both prefab
    citations resolve to a file that exists -- so a message about a missing
    source was false every time it was printed, and its advice sent the reader
    looking for a file that is right there. The spec's None-versus-() rule,
    given up one level higher.
    """
    assets = fake_decompile / "Resources" / "Assets" / "GameObject"
    assets.mkdir(parents=True)
    (assets / "Thing.prefab").write_text("m_Name: Thing\n")
    path = write(tmp_path, "see `Thing.prefab:1` here\n")
    assert whys(mod.structural_problems(path, fake_decompile)) == [
        "not checked: Thing.prefab is not C#, so it has no elements to name"
    ]


def test_structural_findings_do_not_fail_the_run(tmp_path, fake_decompile, capsys):
    """The decision this work rests on: report, never block.

    The checker runs over the whole repository on any staged `.md`, so blocking
    would let one hotfix-added overload stop every documentation commit.
    """
    write_chapter(tmp_path, "a.md", "see `A:4` here\n")
    assert mod.main([str(tmp_path), "--decompile", str(fake_decompile)]) == 0
    assert "line is inside Foo:Bar" in capsys.readouterr().out


def test_syntactic_findings_do_fail_the_run(tmp_path):
    """A malformed citation is checkable by nobody, so it still blocks."""
    write_chapter(tmp_path, "a.md", "see `:419767` here\n")
    assert mod.main([str(tmp_path)]) == 1


def test_without_a_decompile_the_structural_half_says_so(tmp_path, capsys):
    """Skipped with its reason stated, never silently."""
    write_chapter(tmp_path, "a.md", "see `A:4` here\n")
    assert mod.main([str(tmp_path), "--decompile", str(tmp_path / "absent")]) == 0
    assert "structural checks skipped" in capsys.readouterr().out


def test_every_markdown_file_is_checked_not_only_docs_ck(tmp_path):
    """The reach decision: the syntactic half runs in the mod repositories."""
    (tmp_path / "README.md").write_text("see `:419767` here\n")
    assert mod.main([str(tmp_path)]) == 1


def test_a_range_is_judged_against_the_element_holding_the_whole_span(tmp_path, fake_decompile):
    """Describing only the first line names the wrong element and drops the range.

    Measured on the real corpus before this was fixed: 133 of 894 findings
    suggested a citation that threw the span away, and some named a different
    element entirely -- `ScriptableData:34-45` spans three field declarations
    and the checker advised `...:m_guid:1`, where describing the whole span
    gives `ScriptableData:DataBlockAddress:5-16`.
    """
    path = write(tmp_path, "see `A:4-9` here\n")
    whats = [why for _, _, why, _ in mod.structural_problems(path, fake_decompile)]
    assert whats == ["line is inside Foo, which the citation could name"]


def test_a_range_already_anchored_on_its_element_is_no_problem(tmp_path, fake_decompile):
    """A migrated range must not be reported for ever as longer than necessary."""
    path = write(tmp_path, "see `A:Foo:3-8` here\n")
    assert mod.structural_problems(path, fake_decompile) == []


def test_the_structural_half_is_skipped_when_the_parser_is_missing(monkeypatch, tmp_path):
    """Tied to tree-sitter being importable, not only to the decompile existing.

    With a decompile present and the parser absent the run used to die with an
    ImportError traceback and a non-zero exit -- a blocking structural half,
    which is exactly what the design forbids.
    """
    monkeypatch.setitem(sys.modules, "decompile_structure", None)
    ready, reason = mod.structural_available(tmp_path)
    assert not ready
    assert "tree-sitter" in reason


def test_a_frozen_path_stays_unchecked_when_a_subdirectory_is_the_root(tmp_path):
    """`UNCHECKED` is repo-relative, so it has to be matched against the repo.

    The same defect `CLAUDE.md` records for `check_docs_wrapping --fix docs/`:
    passing an intermediate directory made the exclusion miss, and here that
    turns a *blocking* gate red on files it is meant to leave alone.
    """
    _git(tmp_path, "init", "-q")
    spec = tmp_path / "docs" / "specs" / "a-design.md"
    spec.parent.mkdir(parents=True)
    spec.write_text("see `:419767` here\n")

    assert mod.markdown_files(tmp_path / "docs") == []
    assert mod.main([str(tmp_path / "docs")]) == 0


@pytest.mark.parametrize(
    "relative",
    [
        "docs/specs/a-design.md",
        ".claude/skills/ck-docs-review/scoring/planted-errors.md",
        ".claude/skills/ck-verify-chapter/SKILL.md",
    ],
)
def test_a_record_or_a_description_of_the_notation_is_not_checked(tmp_path, relative):
    """Widening the reach surfaced 67 references in files that are not defects.

    A spec is a record of a decision and quotes the banned forms to argue about
    them; a scoring fixture contains planted bad citations on purpose and is
    half of a calibration instrument; and `ck-verify-chapter/SKILL.md` carries
    `:419767` inside the sentence that explains why the form is refused. A
    chapter can fence such an example, running prose cannot.
    """
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("see `:419767` here\n")
    assert mod.markdown_files(tmp_path) == []
    assert mod.main([str(tmp_path)]) == 0


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
