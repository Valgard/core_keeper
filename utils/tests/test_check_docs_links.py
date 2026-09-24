"""Tests for check_docs_links.

The cases here are the mistakes that were actually made while writing the
handbook, not hypothetical ones: an anchor broken by rewording a heading, a
link whose text wraps across two lines, and a slug rule that collapsed runs of
spaces and so reported a correct anchor as broken.
"""

import check_docs_links as mod


def write(tmp_path, name, text):
    """Write `text` to `tmp_path/name`, creating parent directories as needed.

    Returns the path, so callers can hand it straight to check().
    """
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
    """Initialise `tmp_path` as a git repository with a throwaway identity.

    For markdown_files() tests, which need `git ls-files` to have something
    real to run against.
    """
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "t@t")
    git(tmp_path, "config", "user.name", "t")
    return tmp_path


class TestAnchor:
    """anchor() turns a heading into the same slug GitHub's own renderer produces for it."""

    def test_lowercases_and_hyphenates(self):
        """Baseline: lowercase every character and hyphenate the spaces between words."""
        assert mod.anchor("The Editor locks the project") == ("the-editor-locks-the-project")

    def test_every_space_becomes_a_hyphen_not_every_run(self):
        """Each space becomes its own hyphen — runs of spaces are not collapsed to one.

        An em-dash is stripped and leaves two spaces behind; GitHub emits two
        hyphens for that. Collapsing them would report a correct anchor as
        broken.
        """
        assert mod.anchor("Build — install") == "build--install"

    def test_strips_backticks_and_punctuation(self):
        """Backticks and punctuation are stripped before slugifying.

        A heading containing an inline-code span still gets the plain-text
        anchor GitHub would generate.
        """
        assert mod.anchor("`CS0246` on CoreLib types") == "cs0246-on-corelib-types"

    def test_keeps_digits_and_existing_hyphens(self):
        """Digits and hyphens already in the heading survive unchanged.

        Only spaces are turned into new hyphens.
        """
        assert mod.anchor("Unity 6000.0.59f2, exactly") == "unity-6000059f2-exactly"


class TestMaskFences:
    """mask_fences() blanks fenced blocks so links and headings inside them are never checked."""

    def test_blanks_fenced_content_but_keeps_line_count(self):
        """Content between a fence pair is blanked line-by-line, not removed.

        The line count coming out must match what went in, so later line
        numbers a caller reports stay accurate.
        """
        text = "a\n```\nb\nc\n```\nd"
        masked, unclosed = mod.mask_fences(text)
        assert not unclosed
        assert masked.splitlines() == ["a", "", "", "", "", "d"]

    def test_reports_an_unclosed_fence(self):
        """An unterminated fence toggles `inside` and never toggles back.

        mask_fences reports that as unclosed rather than silently treating
        the rest of the file as fenced.
        """
        _, unclosed = mod.mask_fences("a\n```\nb")
        assert unclosed

    def test_tilde_fences_count_too(self):
        """`~~~` fences are recognised the same as ``` ones.

        A link inside a tilde-fenced block must also be masked out.
        """
        masked, _ = mod.mask_fences("~~~\n[x](nope.md)\n~~~")
        assert "nope.md" not in masked


class TestCheck:
    """check() tests: the end-to-end link, anchor and fence checks over a small file tree."""

    def test_accepts_a_resolving_link_and_anchor(self, tmp_path):
        """Baseline: a link whose file and anchor both resolve reports nothing."""
        write(tmp_path, "b.md", "# Target Heading\n")
        a = write(tmp_path, "a.md", "See [it](b.md#target-heading).\n")
        assert mod.check([a, tmp_path / "b.md"], tmp_path) == []

    def test_reports_a_missing_file(self, tmp_path):
        """A link to a file that does not exist is reported with the target path."""
        a = write(tmp_path, "a.md", "See [it](gone.md).\n")
        (problem,) = mod.check([a], tmp_path)
        assert "no such file" in problem and "gone.md" in problem

    def test_reports_a_missing_anchor(self, tmp_path):
        """A link whose file exists but whose `#fragment` matches no heading is reported."""
        write(tmp_path, "b.md", "# Can cost a second\n")
        a = write(tmp_path, "a.md", "See [it](b.md#costs-a-second).\n")
        (problem,) = mod.check([a, tmp_path / "b.md"], tmp_path)
        assert "no such anchor" in problem

    def test_reports_a_missing_local_anchor(self, tmp_path):
        """A same-file `#fragment` link is checked against that file's own headings too.

        Not only a cross-file link.
        """
        a = write(tmp_path, "a.md", "# Here\n\nSee [it](#elsewhere).\n")
        (problem,) = mod.check([a], tmp_path)
        assert "no such anchor" in problem

    def test_finds_a_link_whose_text_wraps_across_lines(self, tmp_path):
        """A link whose bracketed text wraps onto a second line is still found.

        A line-by-line matcher would silently skip it, since the closing
        `]` sits on the following line — valid Markdown that LINK's
        newline-spanning character class exists to catch.
        """
        a = write(tmp_path, "a.md", "See [the long\nlink text](gone.md).\n")
        (problem,) = mod.check([a], tmp_path)
        assert "no such file" in problem

    def test_ignores_links_inside_code_fences(self, tmp_path):
        """A link written inside a fenced code block is not checked at all.

        mask_fences blanks it out before the link regex ever sees it.
        """
        a = write(tmp_path, "a.md", "```\n[x](gone.md)\n```\n")
        assert mod.check([a], tmp_path) == []

    def test_ignores_external_links(self, tmp_path):
        """http(s)/mailto targets are skipped outright.

        Only a relative link gets resolved against the filesystem.
        """
        a = write(tmp_path, "a.md", "[x](https://example.invalid/nope)\n")
        assert mod.check([a], tmp_path) == []

    def test_reports_duplicate_heading_anchors(self, tmp_path):
        """Two headings in one file that slugify to the same anchor are reported.

        A later link naming that anchor could otherwise land on either one.
        """
        a = write(tmp_path, "a.md", "## Same one\n\ntext\n\n## Same one\n")
        (problem,) = mod.check([a], tmp_path)
        assert "duplicate heading anchor" in problem

    def test_a_changelog_may_repeat_its_category_headings(self, tmp_path):
        """CHANGELOG.md is exempt from the duplicate-anchor rule.

        Keep a Changelog repeats "### Added" once per release, which is the
        format rather than a defect, and it is what every mod repo's
        changelog does.
        """
        a = write(
            tmp_path,
            "CHANGELOG.md",
            "## [1.1.0]\n\n### Added\n\nx\n\n## [1.0.0]\n\n### Added\n\ny\n",
        )
        assert mod.check([a], tmp_path) == []

    def test_a_changelog_still_has_its_own_links_checked(self, tmp_path):
        """Only the duplicate-heading rule steps aside for CHANGELOG.md.

        Its own links are still resolved like any other file's.
        """
        a = write(tmp_path, "CHANGELOG.md", "## [1.0.0]\n\n[x](gone.md)\n")
        (problem,) = mod.check([a], tmp_path)
        assert "gone.md" in problem

    def test_an_anchor_into_a_changelog_still_resolves(self, tmp_path):
        """A link into a changelog's repeated `#added` still resolves.

        Anchors are collected despite the duplicate exemption, and the link
        lands on the first heading — the same place a browser would send it.
        """
        write(tmp_path, "CHANGELOG.md", "## [1.1.0]\n\n### Added\n")
        a = write(tmp_path, "a.md", "[x](CHANGELOG.md#added)\n")
        assert mod.check([a, tmp_path / "CHANGELOG.md"], tmp_path) == []

    def test_reports_an_unclosed_fence(self, tmp_path):
        """check() surfaces mask_fences()'s unclosed-fence signal as a reported problem.

        Worded "unclosed code fence".
        """
        a = write(tmp_path, "a.md", "# H\n\n```\nstill open\n")
        (problem,) = mod.check([a], tmp_path)
        assert "unclosed code fence" in problem

    def test_headings_inside_a_fence_are_not_headings(self, tmp_path):
        """A `#` line inside a fenced block is not collected as a heading.

        A link's anchor naming it is reported as unresolved rather than
        matching the fenced text.
        """
        write(tmp_path, "b.md", "```\n# Fenced\n```\n")
        a = write(tmp_path, "a.md", "[x](b.md#fenced)\n")
        (problem,) = mod.check([a, tmp_path / "b.md"], tmp_path)
        assert "no such anchor" in problem

    def test_line_number_survives_fence_masking(self, tmp_path):
        """The line number reported for a problem after a fence still counts the fence's lines.

        mask_fences keeps the line count when it blanks a fence, so numbers
        stay true past it.
        """
        a = write(tmp_path, "a.md", "```\nx\ny\n```\n\n[x](gone.md)\n")
        (problem,) = mod.check([a], tmp_path)
        assert problem.startswith("a.md:6")

    def test_a_bad_anchor_is_caught_on_a_target_outside_the_checked_scope(self, tmp_path):
        """The case check() used to get wrong.

        A target outside the checked `files` scope (gitignored, say) still
        exists on disk, so its anchors are parsed on demand rather than
        skipped — the scope rule governs which files are checked, not which
        are resolvable as link targets.
        """
        write(tmp_path, "ignored.md", "# Real Heading\n")
        a = write(tmp_path, "a.md", "See [it](ignored.md#wrong-anchor).\n")
        (problem,) = mod.check([a], tmp_path)
        assert "no such anchor" in problem

    def test_a_good_anchor_on_a_target_outside_the_checked_scope_is_silent(self, tmp_path):
        """The positive counterpart of the test above.

        A correct anchor into a file outside the checked scope resolves
        silently, proving the on-demand parse works both ways.
        """
        write(tmp_path, "ignored.md", "# Real Heading\n")
        a = write(tmp_path, "a.md", "See [it](ignored.md#real-heading).\n")
        assert mod.check([a], tmp_path) == []


class TestHandbookComplete:
    """check_handbook_complete() tests: every docs/ck chapter must be reachable from index.md."""

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
        """Baseline: every chapter file is linked from index.md, so nothing is reported."""
        files = self._handbook(tmp_path, "no list here\n", "[c](chapter.md)\n")
        assert mod.check_handbook_complete(files, tmp_path) == []

    def test_a_link_carrying_an_anchor_still_counts(self, tmp_path):
        """A link into a chapter that also carries a `#fragment` still counts as linking it.

        The completeness check only cares about the file part.
        """
        files = self._handbook(tmp_path, "no list here\n", "[c](chapter.md#section)\n")
        assert mod.check_handbook_complete(files, tmp_path) == []

    def test_reports_a_chapter_missing_from_the_index(self, tmp_path):
        """A chapter file under docs/ck that index.md never links to is reported by name."""
        files = self._handbook(tmp_path, "[c](chapter.md)\n", "nothing\n")
        (problem,) = mod.check_handbook_complete(files, tmp_path)
        assert "index.md" in problem and "chapter.md" in problem

    def test_a_bare_prose_mention_does_not_count_as_a_link(self, tmp_path):
        """Naming the file is not the same as linking to it.

        A bare mention in prose, with no Markdown link syntax, still leaves
        the chapter reported as unreachable.
        """
        files = self._handbook(tmp_path, "no list here\n", "see chapter.md for detail\n")
        (problem,) = mod.check_handbook_complete(files, tmp_path)
        assert "index.md" in problem and "chapter.md" in problem

    def test_a_mention_inside_a_code_fence_does_not_count_as_a_link(self, tmp_path):
        """A directory listing inside a fenced block names the file without linking it.

        mask_fences blanks it out, so it must not count as reaching the
        chapter.
        """
        files = self._handbook(tmp_path, "no list here\n", "```\nchapter.md\n```\n")
        (problem,) = mod.check_handbook_complete(files, tmp_path)
        assert "index.md" in problem and "chapter.md" in problem

    def test_a_filename_collision_is_not_mistaken_for_a_link(self, tmp_path):
        """Guards against a substring false positive.

        "chapter.md" is a substring of "prefix-chapter.md", so a bare "is
        the filename anywhere in the index text" check would report
        chapter.md reachable because prefix-chapter.md was linked. The
        handbook already has same-shaped filenames (`dedicated-server.md`
        beside other `*-server.md` chapters), so this is one new chapter
        away from being real.
        """
        docs = tmp_path / "docs" / "ck"
        files = [
            write(tmp_path, "docs/ck/index.md", "[c](prefix-chapter.md)\n"),
            write(tmp_path, "docs/ck/chapter.md", "# Chapter\n"),
            write(tmp_path, "docs/ck/prefix-chapter.md", "# Prefix Chapter\n"),
        ]
        assert docs.exists()
        (problem,) = mod.check_handbook_complete(files, tmp_path)
        assert "index.md" in problem and problem.endswith("chapter chapter.md")

    def test_the_readme_is_not_required_to_enumerate_chapters(self, tmp_path):
        """README.md is not checked for chapter links at all.

        Requiring it too would recreate the duplicate list that splitting
        README.md and index.md was meant to avoid.
        """
        files = self._handbook(tmp_path, "just prose\n", "[c](chapter.md)\n")
        assert mod.check_handbook_complete(files, tmp_path) == []

    def test_silent_in_a_repo_without_a_handbook(self, tmp_path):
        """A repository with no docs/ck/index.md is not a handbook at all.

        check_handbook_complete() reports nothing rather than requiring an
        index that was never meant to exist.
        """
        a = write(tmp_path, "a.md", "# Nothing to do\n")
        assert mod.check_handbook_complete([a], tmp_path) == []


class TestMarkdownFiles:
    """A tracked file missing from the working tree used to raise FileNotFoundError.

    Which is the state of every deleted .md at the moment the commit hook
    runs.
    """

    def test_separates_present_from_missing(self, tmp_path):
        """Baseline split: a present tracked file and a deleted one land in different lists.

        A tracked-and-present file lands in `present`; a tracked-but-deleted
        one lands in `missing`, not raising.
        """
        repo = git_repo(tmp_path)
        write(repo, "kept.md", "# Kept\n")
        write(repo, "gone.md", "# Gone\n")
        git(repo, "add", "kept.md", "gone.md")
        (repo / "gone.md").unlink()

        present, missing = mod.markdown_files(repo)
        assert [p.name for p in present] == ["kept.md"]
        assert [p.name for p in missing] == ["gone.md"]

    def test_includes_untracked_files(self, tmp_path):
        """An untracked (not yet `git add`ed) file is included in `present` too.

        Skipping it would report OK on exactly the file most likely to
        carry a broken link: one just written and not yet staged.
        """
        repo = git_repo(tmp_path)
        write(repo, "untracked.md", "# Not staged yet\n")
        present, missing = mod.markdown_files(repo)
        assert [p.name for p in present] == ["untracked.md"]
        assert missing == []

    def test_ignores_files_git_is_told_to_ignore(self, tmp_path):
        """A file under a gitignored directory is excluded entirely.

        It appears in neither `present` nor `missing`.
        """
        repo = git_repo(tmp_path)
        write(repo, ".gitignore", "scratch/\n")
        write(repo, "scratch/notes.md", "# Ignored\n")
        present, missing = mod.markdown_files(repo)
        assert [p.name for p in present] == [] and missing == []


class TestMain:
    """main() and its exit code are what the pre-commit hook actually reads.

    A gate that finds a defect and exits 0 does not block anything.
    """

    def test_exits_zero_on_a_clean_repo(self, tmp_path, capsys):
        """Baseline: a repository with no broken links exits 0 and prints "OK"."""
        repo = git_repo(tmp_path)
        write(repo, "a.md", "# Fine\n\nSee [it](b.md).\n")
        write(repo, "b.md", "# Fine\n")
        assert mod.main(["prog", str(repo)]) == 0
        assert "OK" in capsys.readouterr().out

    def test_exits_nonzero_on_a_broken_link(self, tmp_path, capsys):
        """A broken link makes main() exit 1 and print the problem.

        That output is what the pre-commit hook reads to decide whether to
        block the commit.
        """
        repo = git_repo(tmp_path)
        write(repo, "a.md", "See [it](gone.md).\n")
        assert mod.main(["prog", str(repo)]) == 1
        assert "no such file" in capsys.readouterr().out
