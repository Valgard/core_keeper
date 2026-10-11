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
from verify_status import changed_lines
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


class TestChangedLines:
    """Coverage for changed_lines() -- the numbers latest_verifications judges by."""

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

        assert changed_lines(repo, commit, "a") == (0, 0)

    def test_a_prose_edit_is_counted(self, repo):
        """A real change still counts, or the normaliser would hide everything."""
        _commit(repo, "docs/ck/a.md", "the call `A:100` does it\n", "docs(ck): add a")
        commit = self._head(repo)
        (repo / "docs/ck/a.md").write_text("the call `A:100` fails\n")

        assert changed_lines(repo, commit, "a") == (1, 1)

    def test_a_chapter_absent_at_that_commit_counts_as_nothing(self, repo):
        """Today's behaviour for a chapter the verification predates."""
        _commit(repo, "docs/ck/a.md", "one\n", "docs(ck): add a")
        commit = self._head(repo)
        (repo / "docs/ck/b.md").write_text("two\n")

        assert changed_lines(repo, commit, "b") == (0, 0)

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
