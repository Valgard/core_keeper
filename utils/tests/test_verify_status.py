"""Tests for verify_status.

The rule under test is the ck-verify-chapter skill's: a verification vouches
for the chapter's text as of its commit and for the build in its subject line,
and expires when either moves. The pure pieces are tested directly; one test
builds a throwaway repository, because reading the commit history is where a
wrong `--grep` or a stray `.md` in a subject line would go unnoticed.
"""

import subprocess

import pytest
from verify_status import Verification
from verify_status import changed_words
from verify_status import classify
from verify_status import latest_verifications
from verify_status import normalise
from verify_status import parse_build
from verify_status import parse_subject


class TestParseSubject:
    """Coverage for parse_subject() -- reading chapter and build off a commit subject."""

    def test_plain_chapter_name(self):
        """The usual form yields the chapter name and the full build string."""
        assert parse_subject("docs(ck): verify harmony-and-ecs against 1.3.0.5-cb48") == (
            "harmony-and-ecs",
            "1.3.0.5-cb48",
        )

    def test_chapter_with_md_suffix(self):
        """A subject naming the file rather than the chapter counts for the same chapter."""
        assert parse_subject("docs(ck): verify platforms.md against 1.2.1.5-8be0") == (
            "platforms",
            "1.2.1.5-8be0",
        )

    def test_unrelated_subject(self):
        """A subject that is not a verification commit yields nothing."""
        assert parse_subject("docs(ck): verify harmony-and-ecs claims") is None
        assert parse_subject("fix(skill): re-anchor ck-verify-chapter's citations") is None


class TestParseBuild:
    """Coverage for parse_build() -- splitting a build string into its parts."""

    def test_full_build_with_hash(self):
        """The hash is dropped; the four numeric parts remain."""
        assert parse_build("1.3.0.5-cb48") == (1, 3, 0, 5)

    def test_bare_build(self):
        """A build without a hash parses the same way."""
        assert parse_build("1.2.1.5") == (1, 2, 1, 5)

    def test_malformed(self):
        """A string that is not a four-part build is refused rather than half-read."""
        with pytest.raises(ValueError):
            parse_build("1.3-cb48")


def _v(build="1.3.0.5-cb48", added=0, deleted=0):
    return Verification(chapter="c", commit="abc1234", build=build, added=added, deleted=deleted)


class TestClassify:
    """Coverage for classify() -- the skill's validity rule."""

    def test_never_verified(self):
        """No verification commit at all is unverified."""
        assert classify(None, "1.3.0.5-cb48").state == "unverified"

    def test_same_build_unchanged(self):
        """Same build, no text change since: verified."""
        assert classify(_v(), "1.3.0.5-cb48").state == "verified"

    def test_minor_update_voids_unchanged_text(self):
        """A different first three parts voids the verdict even with no line changed."""
        status = classify(_v(build="1.2.1.5-8be0"), "1.3.0.5-cb48")
        assert status.state == "unverified"
        assert "1.2.1.5-8be0" in status.detail

    def test_major_update_voids(self):
        """A major update voids the verdict like a minor one."""
        assert classify(_v(build="1.3.0.5-cb48"), "2.0.0.1-0000").state == "unverified"

    def test_any_changed_line_makes_it_partial(self):
        """A single changed line is enough -- no size threshold."""
        status = classify(_v(added=1), "1.3.0.5-cb48")
        assert status.state == "partial"
        assert "+1/-0" in status.detail

    def test_hotfix_only(self):
        """Only the fourth part differing: the verdict stands, pending the citation check."""
        status = classify(_v(build="1.3.0.4-511d"), "1.3.0.5-cb48")
        assert status.state == "hotfix"

    def test_hotfix_and_changed_text(self):
        """Both a hotfix and changed text: partial, and the hotfix is still named."""
        status = classify(_v(build="1.3.0.4-511d", deleted=3), "1.3.0.5-cb48")
        assert status.state == "partial"
        assert "hotfix" in status.detail

    def test_same_numbers_different_hash(self):
        """A differing hash on the same four parts is a different build -- treat it as a hotfix."""
        assert classify(_v(build="1.3.0.5-aaaa"), "1.3.0.5-cb48").state == "hotfix"


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _commit(repo, path, text, message):
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)
    _git(repo, "add", path)
    _git(repo, "commit", "-q", "-m", message)


class TestLatestVerifications:
    """Coverage for latest_verifications() against a real, throwaway history."""

    @pytest.fixture
    def repo(self, tmp_path):
        """An empty repository with a committer identity and no signing."""
        _git(tmp_path, "init", "-q")
        _git(tmp_path, "config", "user.email", "test@example.invalid")
        _git(tmp_path, "config", "user.name", "Test")
        _git(tmp_path, "config", "commit.gpgsign", "false")
        return tmp_path

    def test_latest_wins_and_changes_are_counted(self, repo):
        """The newest verification counts, and lines changed after it are counted against it."""
        _commit(repo, "docs/ck/a.md", "one\n", "docs(ck): add a")
        _commit(repo, "docs/ck/a.md", "one\ntwo\n", "docs(ck): verify a against 1.2.1.5-8be0")
        _commit(
            repo, "docs/ck/a.md", "one\ntwo\nthree\n", "docs(ck): verify a.md against 1.3.0.5-cb48"
        )
        _commit(repo, "docs/ck/a.md", "one\nTWO\nthree\nfour\n", "docs(ck): edit a")

        found = latest_verifications(repo)

        assert set(found) == {"a"}
        assert found["a"].build == "1.3.0.5-cb48"
        assert (found["a"].added, found["a"].deleted) == (2, 1)

    def test_uncommitted_edit_counts(self, repo):
        """An edit not yet committed is just as unverified as a committed one."""
        _commit(repo, "docs/ck/a.md", "one\n", "docs(ck): verify a against 1.3.0.5-cb48")
        (repo / "docs/ck/a.md").write_text("one\ntwo\n")

        assert latest_verifications(repo)["a"].added == 1


class TestNormalise:
    """Coverage for normalise() -- what counts as a change to a chapter's prose.

    The defect the whole symbol-anchoring effort opens with: `harmony-and-ecs`
    lost its verification tick to a diff of 31 changed lines of which 31 were
    citation numbers and none was prose. Counting raw lines cannot tell those
    apart; normalising the citations away can.

    That figure is a measurement of hotfix commit `7788522`, which changed 31
    lines and 36 words of that chapter and nothing else; `normalise` reduces
    it to 0/0 in either unit. It is not a measurement of the chapter's
    distance from its verification commit today, which has moved with every
    ordinary edit since and is mostly prose -- checking the claim against the
    working tree gives a different number and makes this read like a lie.

    The two units are both named because the comparison moved from one to the
    other: `changed_words` counts words now, so the figure this docstring
    would be checked against is 36 rather than 31.
    """

    def test_a_citation_renumbered_in_place_is_not_a_change(self):
        """One hotfix moved 320 such lines across nine chapters."""
        before = "the call `Pug.Other:441234` does it\n"
        after = "the call `Pug.Other:441567` does it\n"
        assert normalise(before) == normalise(after)

    def test_a_citation_migrated_to_the_new_grammar_is_not_a_change(self):
        """Both notations canonicalise to one placeholder.

        Without this the migration commit reads as prose and fells the tick of
        every chapter it touches -- the exact failure this design exists to
        remove, reintroduced by the step meant to carry it.
        """
        before = "the call `Pug.Other:370859` does it\n"
        after = "the call `Pug.Other:SmallTitleUIBackground:UpdateTextAndBackground:29` does it\n"
        assert normalise(before) == normalise(after)

    def test_prose_around_a_citation_still_counts_as_a_change(self):
        """The point is to ignore the number, not the sentence."""
        assert normalise("the call `A:1` does it\n") != normalise("the call `A:1` fails\n")

    def test_a_chapter_with_no_citations_normalises_to_itself(self):
        """Most lines have none, and most chapters are not migrated yet."""
        text = "ordinary prose\nwith two lines\n"
        assert normalise(text) == text

    def test_two_different_citations_on_one_line_both_normalise(self):
        """A line can carry several, and one left behind would read as a change."""
        before = "between `A:1` and `A:2`\n"
        after = "between `A:9` and `A:8`\n"
        assert normalise(before) == normalise(after)


class TestChangedWords:
    """Coverage for changed_words() -- the numbers latest_verifications judges by.

    Words rather than lines, because anchoring a chapter's citations forces a
    rewrap: an anchored citation is some 40 characters longer than the number
    it replaces, so every paragraph holding one overflows the width the file
    is written at. Measured on `harmony-and-ecs` against its verification
    commit `4bad12e`: the migration plus that rewrap reads as 427 added and
    300 deleted lines, against 557/0 for the prose actually written since the
    pass. Word-wise the migration is 0/0 and the prose is still 557/0.

    `normalise` already folds both citation notations onto one placeholder,
    which is why the rewrite alone cost nothing even line-wise. What it
    cannot fold is prose moving between lines, and that is what this measures
    instead.
    """

    @pytest.fixture
    def repo(self, tmp_path):
        """An empty repository with a committer identity and no signing."""
        _git(tmp_path, "init", "-q")
        _git(tmp_path, "config", "user.email", "test@example.invalid")
        _git(tmp_path, "config", "user.name", "Test")
        _git(tmp_path, "config", "commit.gpgsign", "false")
        return tmp_path

    def _head(self, repo):
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
        ).stdout.strip()

    def test_a_citation_only_diff_counts_as_nothing(self, repo):
        """End to end through git, where the numstat call used to be."""
        _commit(repo, "docs/ck/a.md", "the call `A:100` does it\n", "docs(ck): add a")
        commit = self._head(repo)
        (repo / "docs/ck/a.md").write_text("the call `A:200` does it\n")

        assert changed_words(repo, commit, "a") == (0, 0)

    def test_a_rewrapped_paragraph_counts_as_nothing(self, repo):
        """The defect this change exists to remove, at its smallest reproducible size.

        Not one word of the paragraph changed; only where the breaks fall.
        Line-wise that is every line of it, which is how anchoring a
        chapter's citations would have cost the chapter its verdict -- the
        step meant to carry the programme reintroducing the failure it exists
        to remove.
        """
        _commit(repo, "docs/ck/a.md", "one two three\nfour five six\n", "docs(ck): add a")
        commit = self._head(repo)
        (repo / "docs/ck/a.md").write_text("one two\nthree four\nfive six\n")

        assert changed_words(repo, commit, "a") == (0, 0)

    def test_a_single_edit_among_common_words_is_not_inflated(self, repo):
        """One added word counts as one, in a paragraph full of repeated words.

        `difflib`'s `autojunk` drops any element appearing in over 1 % of a
        sequence longer than 200, and a chapter is 13,000 words of which the
        commonest are far more than 1 %. Measured on this very input: (201,
        200) with the heuristic on, (1, 0) with it off. Identical input is
        (0, 0) either way, so what this pins is the figure and not the
        verdict -- but the figure is what a reader uses to decide whether a
        chapter needs re-reading, and a one-word edit that reads as a rewrite
        is the quiet form of the problem this file exists to solve.
        """
        before = " ".join(["the"] * 200 + ["anchor"] + ["the"] * 200) + "\n"
        after = " ".join(["the"] * 200 + ["anchor", "added"] + ["the"] * 200) + "\n"
        _commit(repo, "docs/ck/a.md", before, "docs(ck): add a")
        commit = self._head(repo)
        (repo / "docs/ck/a.md").write_text(after)

        assert changed_words(repo, commit, "a") == (1, 0)

    def test_a_prose_edit_is_counted(self, repo):
        """A real change still counts, or the normaliser would hide everything.

        Two words become one, which is why this is (1, 2) and not the (1, 1)
        the line comparison reported: the unit is the word now, and a
        replacement is counted on both sides.
        """
        _commit(repo, "docs/ck/a.md", "the call `A:100` does it\n", "docs(ck): add a")
        commit = self._head(repo)
        (repo / "docs/ck/a.md").write_text("the call `A:100` fails\n")

        assert changed_words(repo, commit, "a") == (1, 2)

    def test_a_deleted_line_whose_text_begins_like_a_diff_header_is_counted(self, repo):
        """`---` is ordinary Markdown, and the marker made the diff line `----`.

        Kept as a regression guard although the mechanism is gone: the line
        version read unified-diff output and had to skip two file headers by
        position, so a prefix test discarded this deletion -- *under*-counting,
        in a function whose caller has no threshold, which would have printed a
        chapter with real prose changes as verified. Comparing word sequences
        has no diff text to mistake anything in, so the defect is now absent
        rather than fixed, and this says what would have to come back for it
        to return.
        """
        _commit(repo, "docs/ck/a.md", "one\n---\nthree\n", "docs(ck): add a")
        commit = self._head(repo)
        (repo / "docs/ck/a.md").write_text("one\nthree\n")

        assert changed_words(repo, commit, "a") == (0, 1)

    def test_an_added_line_whose_text_begins_like_a_diff_header_is_counted(self, repo):
        """The same for `+++`, which a chapter could write in a diff example.

        Also structurally absent now, and kept for the same reason.
        """
        _commit(repo, "docs/ck/a.md", "one\n", "docs(ck): add a")
        commit = self._head(repo)
        (repo / "docs/ck/a.md").write_text("one\n++added\n")

        assert changed_words(repo, commit, "a") == (1, 0)

    def test_a_chapter_that_did_not_exist_at_that_commit_counts_as_all_added(self, repo):
        """`git show` and `git diff --numstat` fail on different things.

        numstat does not see an untracked file; `git show` does not see a path
        that was absent from the commit. Claiming parity and then testing it on
        an untracked file checks the intersection, not the difference: measured,
        a tracked chapter added after its verification gave `5 0` under numstat
        and `(0, 0)` here, which prints as *verified*. A rename of `docs/ck/`
        would promote every stale verdict in one go.
        """
        _commit(repo, "docs/ck/a.md", "one\n", "docs(ck): verify a against 1.3.0.5-cb48")
        commit = self._head(repo)
        _commit(repo, "docs/ck/b.md", "one\ntwo\nthree\nfour\nfive\n", "docs(ck): add b")

        assert changed_words(repo, commit, "b") == (5, 0)

    def test_a_chapter_that_exists_nowhere_counts_as_nothing(self, repo):
        """Absent from the commit and absent now is the one case that is really zero."""
        _commit(repo, "docs/ck/a.md", "one\n", "docs(ck): add a")
        commit = self._head(repo)

        assert changed_words(repo, commit, "gone") == (0, 0)

    def test_a_renumbering_does_not_cost_a_chapter_its_tick(self, repo):
        """The whole point, through latest_verifications rather than in isolation."""
        _commit(
            repo,
            "docs/ck/a.md",
            "the call `A:100` does it\n",
            "docs(ck): verify a against 1.3.0.5-cb48",
        )
        (repo / "docs/ck/a.md").write_text("the call `A:200` does it\n")

        found = latest_verifications(repo)["a"]
        assert (found.added, found.deleted) == (0, 0)
