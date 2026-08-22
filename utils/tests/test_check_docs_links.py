"""Tests for check_docs_links.

The cases here are the mistakes that were actually made while writing the
handbook, not hypothetical ones: an anchor broken by rewording a heading, a
link whose text wraps across two lines, and a slug rule that collapsed runs of
spaces and so reported a correct anchor as broken.
"""

import check_docs_links as mod


def write(tmp_path, name, text):
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def git(repo, *args):
    """Run git with GIT_* stripped, for the same reason the script does.

    A hook runs with GIT_DIR and GIT_INDEX_FILE set, and those outrank `-C`,
    so without this the test repo's commands reach the real repository
    instead. The suite passed outside the hook and failed inside it.
    """
    import os
    import subprocess

    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    subprocess.run(["git", "-C", str(repo), *args], check=True, env=env)


def git_repo(tmp_path):
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "t@t")
    git(tmp_path, "config", "user.name", "t")
    return tmp_path


class TestAnchor:
    def test_lowercases_and_hyphenates(self):
        assert mod.anchor("The Editor locks the project") == (
            "the-editor-locks-the-project"
        )

    def test_every_space_becomes_a_hyphen_not_every_run(self):
        # An em-dash is stripped and leaves two spaces behind; GitHub emits two
        # hyphens. Collapsing them reported a correct anchor as broken.
        assert mod.anchor("Build — install") == "build--install"

    def test_strips_backticks_and_punctuation(self):
        assert mod.anchor("`CS0246` on CoreLib types") == "cs0246-on-corelib-types"

    def test_keeps_digits_and_existing_hyphens(self):
        assert mod.anchor("Unity 6000.0.59f2, exactly") == "unity-6000059f2-exactly"


class TestMaskFences:
    def test_blanks_fenced_content_but_keeps_line_count(self):
        text = "a\n```\nb\nc\n```\nd"
        masked, unclosed = mod.mask_fences(text)
        assert not unclosed
        assert masked.splitlines() == ["a", "", "", "", "", "d"]

    def test_reports_an_unclosed_fence(self):
        _, unclosed = mod.mask_fences("a\n```\nb")
        assert unclosed

    def test_tilde_fences_count_too(self):
        masked, _ = mod.mask_fences("~~~\n[x](nope.md)\n~~~")
        assert "nope.md" not in masked


class TestCheck:
    def test_accepts_a_resolving_link_and_anchor(self, tmp_path):
        write(tmp_path, "b.md", "# Target Heading\n")
        a = write(tmp_path, "a.md", "See [it](b.md#target-heading).\n")
        assert mod.check([a, tmp_path / "b.md"], tmp_path) == []

    def test_reports_a_missing_file(self, tmp_path):
        a = write(tmp_path, "a.md", "See [it](gone.md).\n")
        (problem,) = mod.check([a], tmp_path)
        assert "no such file" in problem and "gone.md" in problem

    def test_reports_a_missing_anchor(self, tmp_path):
        write(tmp_path, "b.md", "# Can cost a second\n")
        a = write(tmp_path, "a.md", "See [it](b.md#costs-a-second).\n")
        (problem,) = mod.check([a, tmp_path / "b.md"], tmp_path)
        assert "no such anchor" in problem

    def test_reports_a_missing_local_anchor(self, tmp_path):
        a = write(tmp_path, "a.md", "# Here\n\nSee [it](#elsewhere).\n")
        (problem,) = mod.check([a], tmp_path)
        assert "no such anchor" in problem

    def test_finds_a_link_whose_text_wraps_across_lines(self, tmp_path):
        a = write(tmp_path, "a.md", "See [the long\nlink text](gone.md).\n")
        (problem,) = mod.check([a], tmp_path)
        assert "no such file" in problem

    def test_ignores_links_inside_code_fences(self, tmp_path):
        a = write(tmp_path, "a.md", "```\n[x](gone.md)\n```\n")
        assert mod.check([a], tmp_path) == []

    def test_ignores_external_links(self, tmp_path):
        a = write(tmp_path, "a.md", "[x](https://example.invalid/nope)\n")
        assert mod.check([a], tmp_path) == []

    def test_reports_duplicate_heading_anchors(self, tmp_path):
        a = write(tmp_path, "a.md", "## Same one\n\ntext\n\n## Same one\n")
        (problem,) = mod.check([a], tmp_path)
        assert "duplicate heading anchor" in problem

    def test_reports_an_unclosed_fence(self, tmp_path):
        a = write(tmp_path, "a.md", "# H\n\n```\nstill open\n")
        (problem,) = mod.check([a], tmp_path)
        assert "unclosed code fence" in problem

    def test_headings_inside_a_fence_are_not_headings(self, tmp_path):
        write(tmp_path, "b.md", "```\n# Fenced\n```\n")
        a = write(tmp_path, "a.md", "[x](b.md#fenced)\n")
        (problem,) = mod.check([a, tmp_path / "b.md"], tmp_path)
        assert "no such anchor" in problem

    def test_line_number_survives_fence_masking(self, tmp_path):
        a = write(tmp_path, "a.md", "```\nx\ny\n```\n\n[x](gone.md)\n")
        (problem,) = mod.check([a], tmp_path)
        assert problem.startswith("a.md:6")

    def test_a_bad_anchor_is_caught_on_a_target_outside_the_checked_scope(
        self, tmp_path
    ):
        # a target that exists on disk but is not in `files` (a gitignored
        # file, say) used to skip the anchor check entirely, because it was
        # never in `known` — the scope rule governs which files are checked,
        # not which are resolvable as link targets
        write(tmp_path, "ignored.md", "# Real Heading\n")
        a = write(tmp_path, "a.md", "See [it](ignored.md#wrong-anchor).\n")
        (problem,) = mod.check([a], tmp_path)
        assert "no such anchor" in problem

    def test_a_good_anchor_on_a_target_outside_the_checked_scope_is_silent(
        self, tmp_path
    ):
        write(tmp_path, "ignored.md", "# Real Heading\n")
        a = write(tmp_path, "a.md", "See [it](ignored.md#real-heading).\n")
        assert mod.check([a], tmp_path) == []


class TestHandbookComplete:
    def _handbook(self, tmp_path, readme, index):
        docs = tmp_path / "docs" / "ck"
        files = [
            write(tmp_path, "docs/ck/README.md", readme),
            write(tmp_path, "docs/ck/index.md", index),
            write(tmp_path, "docs/ck/chapter.md", "# Chapter\n"),
        ]
        assert docs.exists()
        return files

    def test_silent_when_the_index_links_every_chapter(self, tmp_path):
        files = self._handbook(tmp_path, "no list here\n", "[c](chapter.md)\n")
        assert mod.check_handbook_complete(files, tmp_path) == []

    def test_a_link_carrying_an_anchor_still_counts(self, tmp_path):
        files = self._handbook(tmp_path, "no list here\n", "[c](chapter.md#section)\n")
        assert mod.check_handbook_complete(files, tmp_path) == []

    def test_reports_a_chapter_missing_from_the_index(self, tmp_path):
        files = self._handbook(tmp_path, "[c](chapter.md)\n", "nothing\n")
        (problem,) = mod.check_handbook_complete(files, tmp_path)
        assert "index.md" in problem and "chapter.md" in problem

    def test_a_bare_prose_mention_does_not_count_as_a_link(self, tmp_path):
        # naming the file is not the same as linking to it
        files = self._handbook(
            tmp_path, "no list here\n", "see chapter.md for detail\n"
        )
        (problem,) = mod.check_handbook_complete(files, tmp_path)
        assert "index.md" in problem and "chapter.md" in problem

    def test_a_mention_inside_a_code_fence_does_not_count_as_a_link(self, tmp_path):
        # a directory listing in a fenced block names the file without linking it
        files = self._handbook(tmp_path, "no list here\n", "```\nchapter.md\n```\n")
        (problem,) = mod.check_handbook_complete(files, tmp_path)
        assert "index.md" in problem and "chapter.md" in problem

    def test_the_readme_is_not_required_to_enumerate_chapters(self, tmp_path):
        # README.md describes the work; enumerating it there too would be the
        # duplicate list that splitting the two files was meant to avoid.
        files = self._handbook(tmp_path, "just prose\n", "[c](chapter.md)\n")
        assert mod.check_handbook_complete(files, tmp_path) == []

    def test_silent_in_a_repo_without_a_handbook(self, tmp_path):
        a = write(tmp_path, "a.md", "# Nothing to do\n")
        assert mod.check_handbook_complete([a], tmp_path) == []


class TestMarkdownFiles:
    """A tracked file missing from the working tree used to raise
    FileNotFoundError — which is the state of every deleted .md at the moment
    the commit hook runs."""

    def test_separates_present_from_missing(self, tmp_path):
        repo = git_repo(tmp_path)
        write(repo, "kept.md", "# Kept\n")
        write(repo, "gone.md", "# Gone\n")
        git(repo, "add", "kept.md", "gone.md")
        (repo / "gone.md").unlink()

        present, missing = mod.markdown_files(repo)
        assert [p.name for p in present] == ["kept.md"]
        assert [p.name for p in missing] == ["gone.md"]

    def test_includes_untracked_files(self, tmp_path):
        # A chapter written and not yet staged is the file most likely to carry
        # a broken link; skipping it reported OK on exactly the wrong run.
        repo = git_repo(tmp_path)
        write(repo, "untracked.md", "# Not staged yet\n")
        present, missing = mod.markdown_files(repo)
        assert [p.name for p in present] == ["untracked.md"]
        assert missing == []

    def test_ignores_files_git_is_told_to_ignore(self, tmp_path):
        repo = git_repo(tmp_path)
        write(repo, ".gitignore", "scratch/\n")
        write(repo, "scratch/notes.md", "# Ignored\n")
        present, missing = mod.markdown_files(repo)
        assert [p.name for p in present] == [] and missing == []


class TestMain:
    """main() and its exit code are what the pre-commit hook actually reads
    — a gate that finds a defect and exits 0 does not block anything."""

    def test_exits_zero_on_a_clean_repo(self, tmp_path, capsys):
        repo = git_repo(tmp_path)
        write(repo, "a.md", "# Fine\n\nSee [it](b.md).\n")
        write(repo, "b.md", "# Fine\n")
        assert mod.main(["prog", str(repo)]) == 0
        assert "OK" in capsys.readouterr().out

    def test_exits_nonzero_on_a_broken_link(self, tmp_path, capsys):
        repo = git_repo(tmp_path)
        write(repo, "a.md", "See [it](gone.md).\n")
        assert mod.main(["prog", str(repo)]) == 1
        assert "no such file" in capsys.readouterr().out
