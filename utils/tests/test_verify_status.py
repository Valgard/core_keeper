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
from verify_status import classify
from verify_status import latest_verifications
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
