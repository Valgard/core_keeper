"""Unit tests for the decisions a Steam publish rests on before anything is sent.

Every rule here guards against one shape of the incident that started this
module: `--steam-only` uploaded whatever build had last been left in a shared
folder, labelled with the checkout's version. So the tests ask, rule by rule,
whether a run that would publish something other than the release it names is
stopped — and whether a run that would publish exactly that release is not.

The git-facing tests build real throwaway repositories rather than mocking git:
what they check is a contract with git's own output (porcelain lines, ignore
rules, worktree and detached-HEAD behaviour), and a mock would only confirm this
file's assumptions about it.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import steam_guard

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")

REF_LIVE_100 = {
    "modId": 7,
    "mod": {"modfile": {"id": 2, "version": "1.0.0", "filesize_uncompressed": 100}},
    "files": {
        "data": [
            {"id": 2, "version": "1.0.0", "filesize_uncompressed": 100, "date_added": 2},
            {"id": 1, "version": "0.9.0", "filesize_uncompressed": 90, "date_added": 1},
        ]
    },
}


def _decide(**overrides):
    """decide_pre_upload with a matching, non-override build as the baseline."""
    arguments = {
        "version": "1.0.0",
        "ref": REF_LIVE_100,
        "content": overrides.pop("content", None),
        "content_size": 100,
        "override": False,
        "install_path": None,
    }
    arguments.update(overrides)
    return steam_guard.decide_pre_upload(**arguments)


# --- rule 1: MOD_INSTALL_PATH is never a source ------------------------------


def test_an_override_inside_the_install_path_is_refused(tmp_path):
    """An override folder inside MOD_INSTALL_PATH is refused even though its size matches.

    That folder holds whichever build was left there last — the incident's
    content — so its size proves nothing about which release it is.
    """
    install = tmp_path / "install"
    (install / "Mod").mkdir(parents=True)

    verdict = _decide(content=install / "Mod", override=True, install_path=install)

    assert not verdict.proceed
    assert "MOD_INSTALL_PATH" in verdict.message


def test_override_through_a_symlink_into_the_install_path_is_refused(tmp_path):
    """A symlink that resolves into MOD_INSTALL_PATH is the same folder and is refused.

    Compared lexically, the link's own path lies outside and would pass.
    """
    install = tmp_path / "install"
    (install / "Mod").mkdir(parents=True)
    link = tmp_path / "link"
    link.symlink_to(install / "Mod")

    verdict = _decide(content=link, override=True, install_path=install)

    assert not verdict.proceed and "MOD_INSTALL_PATH" in verdict.message


@pytest.mark.parametrize("spelling", ["relative", "trailing-slash", "dotdot"])
def test_override_given_relative_or_with_a_trailing_slash_is_resolved(
    tmp_path, monkeypatch, spelling
):
    """The override is resolved before the inside-check, however the operator typed it.

    CK_STEAM_CONTENT arrives as a string from the shell, so a relative path,
    a trailing slash or a `..` detour are all ordinary spellings of a folder
    inside MOD_INSTALL_PATH.
    """
    install = tmp_path / "install"
    (install / "Mod").mkdir(parents=True)
    (tmp_path / "elsewhere").mkdir()
    monkeypatch.chdir(tmp_path)
    content = {
        "relative": "install/Mod",
        "trailing-slash": f"{install}/Mod/",
        "dotdot": f"{tmp_path}/elsewhere/../install/Mod",
    }[spelling]

    verdict = _decide(content=Path(content), override=True, install_path=Path(install))

    assert not verdict.proceed and "MOD_INSTALL_PATH" in verdict.message


@pytest.mark.parametrize("spelling", ["relative", "trailing-slash"])
def test_an_oddly_spelled_install_path_still_contains_the_override(tmp_path, monkeypatch, spelling):
    """MOD_INSTALL_PATH comes from .envrc as a string too, and is resolved the same way."""
    install = tmp_path / "install"
    (install / "Mod").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    install_spelled = {"relative": "install", "trailing-slash": f"{install}/"}[spelling]

    verdict = _decide(content=install / "Mod", override=True, install_path=Path(install_spelled))

    assert not verdict.proceed and "MOD_INSTALL_PATH" in verdict.message


def test_an_override_spelled_in_another_case_is_still_inside(tmp_path):
    """On a case-insensitive volume, another capitalisation names the same folder.

    macOS's default APFS is case-insensitive, and resolve() keeps whatever case
    was typed, so a lexical comparison alone would let `/…/INSTALL/Mod` pass.
    """
    install = tmp_path / "install"
    (install / "Mod").mkdir(parents=True)
    if not (tmp_path / "INSTALL").exists():
        pytest.skip("this volume is case-sensitive — two spellings are two folders here")

    verdict = _decide(content=tmp_path / "INSTALL" / "mod", override=True, install_path=install)

    assert not verdict.proceed and "MOD_INSTALL_PATH" in verdict.message


def test_a_sibling_whose_name_extends_the_install_path_is_not_inside(tmp_path):
    """`install-2` is not inside `install`: the check is by path component, not by string prefix."""
    install = tmp_path / "install"
    install.mkdir()
    sibling = tmp_path / "install-2" / "Mod"
    sibling.mkdir(parents=True)

    verdict = _decide(content=sibling, override=True, install_path=install)

    assert verdict.proceed


def test_rule_one_outranks_everything_else(tmp_path):
    """The install-path refusal comes first, whatever the reference says.

    Even for a mod not on mod.io, whose refusal would otherwise say something
    else: the operator should hear the more fundamental problem.
    """
    install = tmp_path / "install"
    (install / "Mod").mkdir(parents=True)

    verdict = _decide(
        content=install / "Mod", override=True, install_path=install, ref={"modId": 0}
    )

    assert not verdict.proceed and "MOD_INSTALL_PATH" in verdict.message


def test_a_build_is_not_judged_by_where_it_lies(tmp_path):
    """Rule 1 is about the override only; a folder this run built is the run's own."""
    install = tmp_path / "install"
    (install / "Mod").mkdir(parents=True)

    verdict = _decide(content=install / "Mod", override=False, install_path=install)

    assert verdict.proceed


def test_an_override_without_an_install_path_is_still_compared(tmp_path):
    """With MOD_INSTALL_PATH unset there is nothing to be inside; the comparison still decides."""
    verdict = _decide(content=tmp_path, override=True, install_path=None, content_size=99)

    assert not verdict.proceed
    assert "does not match what mod.io serves" in verdict.message


# --- rule 2: not on mod.io ---------------------------------------------------


def test_reference_without_modio_asset_is_not_on_modio(tmp_path):
    """A mod the repository records no mod.io id for proceeds, and the run says it compared nothing.

    The Unity side writes `{"modId": 0}` both for a zero id and for a mod with
    no `<Mod>_modio.asset` at all (Review Focus); both read the same here.
    """
    v = steam_guard.decide_pre_upload(
        version="1.0.0",
        ref={"modId": 0},
        content=tmp_path,
        content_size=5,
        override=False,
        install_path=None,
    )
    assert v.proceed and "not on mod.io" in v.message


def test_an_override_for_a_mod_not_on_modio_is_refused(tmp_path):
    """The override is accepted only when mod.io can vouch for it, so a Steam-only mod has none."""
    verdict = _decide(content=tmp_path, override=True, ref={"modId": 0})

    assert not verdict.proceed
    assert "not on mod.io has no override" in verdict.message


# --- rule 3 and R4: a reference that cannot be read fails closed --------------


def test_an_unreadable_reference_is_refused_with_the_hidden_hint(tmp_path):
    """A failed mod.io read refuses, quotes why, and names the hidden-profile remedy.

    Read as "not on mod.io" instead, it would skip every comparison — the
    exact silent degradation this guard exists to prevent.
    """
    verdict = _decide(content=tmp_path, ref={"modId": 7, "error": "HTTP 404: mod not found"})

    assert not verdict.proceed
    assert "HTTP 404: mod not found" in verdict.message
    assert "make it visible on mod.io and re-run" in verdict.message


@pytest.mark.parametrize(
    "ref",
    [
        None,
        [],
        "not a reference",
        {},
        {"modId": 7},
        {"modId": 7, "mod": None, "files": REF_LIVE_100["files"]},
        {"modId": 7, "mod": {}, "files": REF_LIVE_100["files"]},
        {"modId": 7, "mod": REF_LIVE_100["mod"]},
        {"modId": 7, "mod": REF_LIVE_100["mod"], "files": {}},
        {"modId": 7, "mod": REF_LIVE_100["mod"], "files": {"data": "x"}},
        {"modId": 7, "mod": REF_LIVE_100["mod"], "files": {"data": [{"id": 2}]}},
        {"modId": 7, "mod": REF_LIVE_100["mod"], "files": {"data": [{"id": 2, "version": 1}]}},
        {"modId": 7, "mod": REF_LIVE_100["mod"], "files": {"data": ["x"]}},
        {
            "modId": 7,
            "mod": {"modfile": {"id": 2, "filesize_uncompressed": 100}},
            "files": REF_LIVE_100["files"],
        },
        {
            "modId": 7,
            "mod": {"modfile": {"id": 2, "version": "1.0.0"}},
            "files": REF_LIVE_100["files"],
        },
        {
            "modId": 7,
            "mod": {"modfile": {"id": 2, "version": "1.0.0", "filesize_uncompressed": "100"}},
            "files": REF_LIVE_100["files"],
        },
    ],
    ids=[
        "none",
        "list",
        "string",
        "empty-object",
        "id-only",
        "mod-null",
        "mod-without-modfile",
        "no-files",
        "files-without-data",
        "data-not-a-list",
        "entry-without-version",
        "entry-version-not-a-string",
        "entry-not-an-object",
        "live-without-version",
        "live-without-size",
        "live-size-not-a-number",
    ],
)
def test_a_reference_missing_what_it_should_hold_is_refused_not_a_crash(tmp_path, ref):
    """Ruling R4: any reference short of the expected keys refuses as unreadable and never raises.

    The file comes from a Unity run that may have crashed, timed out or met
    an answer of a shape nobody measured; a traceback there would end the run
    without saying which of those it was.
    """
    verdict = _decide(content=tmp_path, ref=ref)

    assert not verdict.proceed
    assert "mod.io reference could not be read" in verdict.message


# --- rule 4: D7, a mod on mod.io cannot run ahead of it ----------------------


def test_a_version_missing_on_modio_is_refused(tmp_path):
    """A checkout whose version mod.io has never seen is refused, with the order to fix it."""
    verdict = _decide(content=tmp_path, version="1.1.0")

    assert not verdict.proceed
    assert "publish to mod.io first" in verdict.message
    assert "1.1.0" in verdict.message


# --- rule 5: superseded ------------------------------------------------------


def test_a_superseded_version_is_refused(tmp_path):
    """A version mod.io has, but no longer serves, means the checkout is behind mod.io."""
    verdict = _decide(content=tmp_path, version="0.9.0", content_size=90)

    assert not verdict.proceed
    assert "mod.io's live version is 1.0.0" in verdict.message
    assert "behind" in verdict.message


# --- rule 6: the size comparison ----------------------------------------------


def test_a_rebuild_with_another_size_is_refused_and_points_to_the_override(tmp_path):
    """A build of the live version whose size differs is refused, naming both causes and the repair.

    Builds of one commit reproduce byte for byte (measured, Ruling R6), so a
    difference means either a checkout that is not the released state — the
    likelier cause, e.g. `<Mod>_Steam.asset` brought over from main to close
    an id gap, whose path ships in the bundle manifest — or a toolchain that
    moved since the release. The way out is the same for both: the release's
    own modfile through the override.
    """
    verdict = _decide(content=tmp_path, content_size=101)

    assert not verdict.proceed
    assert "101 B" in verdict.message and "100 B" in verdict.message
    assert "this checkout is not the released state" in verdict.message
    assert "<Mod>_Steam.asset" in verdict.message
    assert "SDK or game-asset update" in verdict.message
    assert "CK_STEAM_CONTENT=<dir> upload.sh --steam-only" in verdict.message


def test_an_override_with_another_size_is_refused(tmp_path):
    """An override folder whose size differs is not what mod.io serves, and is refused."""
    verdict = _decide(content=tmp_path, content_size=99, override=True)

    assert not verdict.proceed
    assert "the folder does not match what mod.io serves" in verdict.message
    assert "CK_STEAM_CONTENT=" not in verdict.message


def test_the_size_is_compared_with_the_live_modfile(tmp_path):
    """The live modfile is the measure, not an older upload of the same version.

    mod.io can hold one version twice; what it serves is its current modfile.
    """
    ref = json.loads(json.dumps(REF_LIVE_100))
    ref["files"]["data"].append(
        {"id": 0, "version": "1.0.0", "filesize_uncompressed": 77, "date_added": 0}
    )

    assert _decide(content=tmp_path, ref=ref, content_size=100).proceed
    assert not _decide(content=tmp_path, ref=ref, content_size=77).proceed


# --- rule 7 -----------------------------------------------------------------


def test_a_matching_build_proceeds(tmp_path):
    """The live version at the live size proceeds, and the message carries the number it matched."""
    verdict = _decide(content=tmp_path)

    assert verdict.proceed
    assert "matches mod.io (100 bytes)" in verdict.message


def test_a_matching_override_outside_the_install_path_proceeds(tmp_path):
    """The repair route itself: a downloaded modfile outside MOD_INSTALL_PATH, at the live size."""
    install = tmp_path / "install"
    install.mkdir()
    download = tmp_path / "download"
    download.mkdir()

    verdict = _decide(content=download, override=True, install_path=install)

    assert verdict.proceed


# --- reading mod.io's answer -------------------------------------------------


def test_live_modfile_is_the_profiles_current_modfile():
    """The profile's `modfile` is what mod.io serves today."""
    assert steam_guard.live_modfile(REF_LIVE_100)["id"] == 2


@pytest.mark.parametrize(
    "ref",
    [{}, {"modId": 0}, {"mod": None}, {"mod": {"modfile": None}}, {"mod": {"modfile": {}}}, []],
)
def test_live_modfile_is_none_when_there_is_none(ref):
    """No profile, no modfile or an empty one all read as "no live modfile", never a KeyError."""
    assert steam_guard.live_modfile(ref) is None


def test_modfile_for_version_picks_the_newest_upload_of_that_version():
    """One version uploaded twice: the later upload counts, wherever it sits in the list."""
    ref = {
        "files": {
            "data": [
                {"id": 5, "version": "1.0.0", "date_added": 10},
                {"id": 9, "version": "1.0.0", "date_added": 30},
                {"id": 7, "version": "1.0.0", "date_added": 20},
            ]
        }
    }

    assert steam_guard.modfile_for_version(ref, "1.0.0")["id"] == 9


@pytest.mark.parametrize("ref", [REF_LIVE_100, {}, {"files": None}, {"files": {"data": None}}])
def test_modfile_for_version_is_none_for_a_version_it_does_not_hold(ref):
    """An unknown version, or a reference without a file list, has no modfile — not an exception."""
    assert steam_guard.modfile_for_version(ref, "2.0.0") is None


def test_load_reference_reads_the_file_as_utf8(tmp_path):
    """The reference is read as UTF-8 whatever the locale says; mod.io's bodies are UTF-8."""
    path = tmp_path / "ref.json"
    path.write_bytes(json.dumps({"modId": 7, "mod": {"name": "Größe"}}).encode("utf-8"))

    assert steam_guard.load_reference(path)["mod"]["name"] == "Größe"


@pytest.mark.parametrize(
    "content",
    [b"", b"  \n", b"{not json", b"[1, 2]", b"\xff\xfe\x00"],
    ids=["empty", "blank", "unparsable", "not-an-object", "not-utf8"],
)
def test_load_reference_turns_an_unusable_file_into_the_error_shape(tmp_path, content):
    """Ruling R4: an empty or broken reference file becomes an error reference, never an exception.

    An empty file is what a Unity run that died before writing leaves behind
    (upload.sh creates it up front), so it must arrive at the verdict as a
    refusal that says so.
    """
    path = tmp_path / "ref.json"
    path.write_bytes(content)

    ref = steam_guard.load_reference(path)

    assert ref["modId"] is None and ref["error"]
    verdict = _decide(content=tmp_path, ref=ref)
    assert not verdict.proceed and "mod.io reference could not be read" in verdict.message


def test_load_reference_of_a_missing_file_is_the_error_shape(tmp_path):
    """A reference file that does not exist is reported, not raised."""
    ref = steam_guard.load_reference(tmp_path / "absent.json")

    assert ref["modId"] is None and "absent.json" in ref["error"]


# --- the checkout: D3 and the [Unreleased] rule --------------------------------


def _git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout


@pytest.fixture
def repo(tmp_path):
    """A committed mod checkout with the three paths D3 watches and an ignore list."""
    root = tmp_path / "mod"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "Test")
    _git(root, "config", "commit.gpgsign", "false")
    (root / "unity" / "Mod").mkdir(parents=True)
    (root / "unity" / "Mod" / "Mod.cs").write_text("class Mod {}\n")
    (root / "localization").mkdir()
    (root / "localization" / "localization.yaml").write_text("# none\n")
    (root / "CHANGELOG.md").write_text("# Changelog\n\n## [1.0.0] - 2026-10-01\n\nfirst\n")
    (root / "README.md").write_text("readme\n")
    (root / ".gitignore").write_text("unity/Mod/Generated/\n.DS_Store\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "release 1.0.0")
    return root


@needs_git
def test_a_clean_checkout_has_no_problems(repo):
    """A checkout exactly at its commit passes D3 and the changelog rule."""
    assert steam_guard.dirty_paths(repo) == []
    assert steam_guard.checkout_problems(repo) == []


@needs_git
def test_dirty_paths_counts_untracked_and_ignores_ignored(repo):
    """Modified and untracked files under the watched paths count; ignored ones and others do not.

    Untracked counts because ModBuilder collects by folder, not by git status:
    a stray file under unity/ ships. Ignored files are the link helpers,
    `.DS_Store` and generated output, which every checkout has.
    """
    (repo / "unity" / "Mod" / "Mod.cs").write_text("class Mod { int x; }\n")
    (repo / "unity" / "Mod" / "Stray.cs").write_text("class Stray {}\n")
    (repo / "unity" / "Mod" / "Generated").mkdir()
    (repo / "unity" / "Mod" / "Generated" / "Out.cs").write_text("// generated\n")
    (repo / "unity" / ".DS_Store").write_bytes(b"\0")
    (repo / "README.md").write_text("changed, but not by D3's business\n")

    lines = steam_guard.dirty_paths(repo)

    assert sorted(lines) == sorted([" M unity/Mod/Mod.cs", "?? unity/Mod/Stray.cs"])


@needs_git
def test_untracked_files_count_even_when_git_is_told_to_hide_them(repo):
    """A `status.showUntrackedFiles = no` in someone's config must not switch off D3's rule.

    The setting is a display preference, and git status honours it silently;
    the D3 rule is that untracked counts, so the command pins it.
    """
    _git(repo, "config", "status.showUntrackedFiles", "no")
    (repo / "localization" / "extra.yaml").write_text("x: y\n")

    assert steam_guard.dirty_paths(repo) == ["?? localization/extra.yaml"]


@needs_git
def test_a_dirty_changelog_is_a_checkout_problem(repo):
    """CHANGELOG.md supplies the version label, so an uncommitted edit to it is refused too."""
    (repo / "CHANGELOG.md").write_text("# Changelog\n\n## [1.0.1]\n\nnot committed\n\n## [1.0.0]\n")

    problems = steam_guard.checkout_problems(repo)

    assert len(problems) == 1
    assert "CHANGELOG.md" in problems[0]


@needs_git
def test_every_dirty_path_is_its_own_problem(repo):
    """One message per dirty path, so the operator sees the whole list in one run."""
    (repo / "unity" / "Mod" / "A.cs").write_text("a\n")
    (repo / "unity" / "Mod" / "B.cs").write_text("b\n")

    problems = steam_guard.checkout_problems(repo)

    assert len(problems) == 2
    assert any("unity/Mod/A.cs" in p for p in problems)
    assert any("unity/Mod/B.cs" in p for p in problems)


@needs_git
def test_an_empty_unreleased_heading_is_no_checkout_problem(repo):
    """An empty `## [Unreleased]` heading kept by habit refuses nothing (Review Focus)."""
    (repo / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [Unreleased]\n\n## [1.0.0] - 2026-10-01\n\nfirst\n"
    )
    _git(repo, "commit", "-qam", "keep the heading")

    assert steam_guard.checkout_problems(repo) == []


@needs_git
def test_unreleased_notes_are_a_checkout_problem(repo):
    """Committed notes under [Unreleased] put the checkout past the release it is labelled as."""
    (repo / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [Unreleased]\n\n### Fixed\n\n- x\n\n## [1.0.0] - 2026-10-01\n\nfirst\n"
    )
    _git(repo, "commit", "-qam", "note a fix")

    problems = steam_guard.checkout_problems(repo)

    assert len(problems) == 1
    assert "[Unreleased]" in problems[0]


def test_a_checkout_git_cannot_read_is_a_problem_not_a_pass(tmp_path):
    """Outside a repository D3 cannot be checked, and an unchecked D3 must refuse, not pass."""
    (tmp_path / "CHANGELOG.md").write_text("## [1.0.0]\n\nfirst\n")

    problems = steam_guard.checkout_problems(tmp_path)

    assert len(problems) == 1
    assert "git" in problems[0]


@needs_git
# GIT_DIR is git's own environment variable name, not a choice of ours.
def test_an_inherited_GIT_DIR_does_not_answer_for_another_repo(repo, tmp_path, monkeypatch):  # noqa: N802
    """D3 asks the mod's repository even when the caller's environment points git elsewhere.

    GIT_DIR and GIT_INDEX_FILE outrank -C; inherited from a hook they would
    have a dirty checkout reported clean by a decoy.
    """
    (repo / "unity" / "Mod" / "Stray.cs").write_text("class Stray {}\n")
    decoy = tmp_path / "decoy"
    subprocess.run(["git", "init", "-q", str(decoy)], check=True, capture_output=True)
    monkeypatch.setenv("GIT_DIR", str(decoy / ".git"))
    monkeypatch.setenv("GIT_INDEX_FILE", str(decoy / ".git" / "index"))

    assert steam_guard.dirty_paths(repo) == ["?? unity/Mod/Stray.cs"]


# --- the commit the run builds from -------------------------------------------


@needs_git
def test_describe_commit_on_a_branch(repo):
    """On a branch: short hash, branch name and the checkout's absolute path."""
    short = _git(repo, "rev-parse", "--short", "HEAD").strip()

    assert steam_guard.describe_commit(repo) == f"{short} on main ({repo.resolve()})"


@needs_git
def test_describe_commit_in_a_detached_linked_worktree(repo, tmp_path):
    """A linked worktree at a release commit, detached — the repair route — is described as such.

    The path printed is the worktree's, not the main checkout's: which
    checkout the build came from is the whole point of printing it.
    """
    short = _git(repo, "rev-parse", "--short", "HEAD").strip()
    (repo / "unity" / "Mod" / "Mod.cs").write_text("class Mod { int later; }\n")
    _git(repo, "commit", "-qam", "later work")
    tree = tmp_path / "probe"
    _git(repo, "worktree", "add", "-q", "--detach", str(tree), short)

    assert steam_guard.describe_commit(tree) == f"{short}, detached HEAD ({tree.resolve()})"
    assert steam_guard.checkout_problems(tree) == []


def test_describe_commit_outside_a_repository_says_so_instead_of_raising(tmp_path):
    """The description refuses nothing by itself, so a git failure must not end the run here."""
    description = steam_guard.describe_commit(tmp_path)

    assert "unknown" in description and str(tmp_path.resolve()) in description


# --- the size of a content folder --------------------------------------------


def test_folder_size_sums_regular_files_only(tmp_path):
    """Regular files count at any depth; symlinks — to files or to folders — are not followed.

    Steam's `file_size` and mod.io's `filesize_uncompressed` both equal the
    byte total of the folder's own files (measured); a link would add bytes
    the upload does not carry as such.
    """
    content = tmp_path / "content"
    (content / "Bundles").mkdir(parents=True)
    (content / "ModManifest.json").write_bytes(b"x" * 10)
    (content / "Bundles" / "mod.bundle").write_bytes(b"y" * 32)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "big").write_bytes(b"z" * 1000)
    os.symlink(outside / "big", content / "file-link")
    os.symlink(outside, content / "dir-link")

    assert steam_guard.folder_size(content) == 42


def test_folder_size_of_a_folder_given_through_a_symlink_is_its_target(tmp_path):
    """The folder named is measured even when it is itself a link — an override may well be one."""
    content = tmp_path / "content"
    content.mkdir()
    (content / "a").write_bytes(b"x" * 7)
    link = tmp_path / "link"
    link.symlink_to(content)

    assert steam_guard.folder_size(link) == 7


def test_folder_size_of_a_missing_folder_raises(tmp_path):
    """A folder that is not there has no size; reading it as 0 would only defer the error."""
    with pytest.raises(FileNotFoundError):
        steam_guard.folder_size(tmp_path / "absent")


def test_the_exit_codes_are_the_ones_reserved_for_the_guard():
    """11 and 12 sit past ck-workshop's own range in the code space both tools share."""
    assert (steam_guard.EXIT_CONTENT_MISMATCH, steam_guard.EXIT_UNVERIFIED) == (11, 12)


# --- after the upload: the item against mod.io, and the exit code --------------


def _no_sleep(_seconds):
    """A sleep that does not wait."""


def test_old_size_then_new_size_is_a_match():
    """Steam lags the upload: reads of the old size are retried until the new one shows."""
    reads = iter([500, 500, 742])
    out = steam_guard.compare_after_upload(
        742, 500, lambda: next(reads), attempts=3, sleep=_no_sleep
    )
    assert out[0] == 0


def test_a_new_wrong_size_is_a_mismatch():
    """A size that is neither the old one nor mod.io's is final."""
    assert steam_guard.compare_after_upload(742, 500, lambda: 811, sleep=_no_sleep)[0] == 11


def test_still_the_old_size_is_unverified():
    """An item that never changed size leaves the comparison unmade."""
    assert (
        steam_guard.compare_after_upload(742, 500, lambda: 500, attempts=2, sleep=_no_sleep)[0]
        == 12
    )


def test_unreadable_is_unverified():
    """No answer from Steam is not a match."""
    assert (
        steam_guard.compare_after_upload(742, None, lambda: None, attempts=2, sleep=_no_sleep)[0]
        == 12
    )


def test_same_size_reupload_matches_at_once():
    """Re-uploading the same build changes nothing to wait for."""
    assert steam_guard.compare_after_upload(742, 742, lambda: 742, sleep=_no_sleep)[0] == 0


def test_no_expected_size_is_not_compared():
    """Without a size from mod.io there is nothing to compare."""
    assert steam_guard.compare_after_upload(None, 5, lambda: 5)[0] == 0


def test_the_retry_sleeps_between_reads_only():
    """Attempts are spaced by the interval, with no sleep before the first read."""
    sleeps = []
    steam_guard.compare_after_upload(
        742, 500, lambda: 500, attempts=3, interval=2.5, sleep=sleeps.append
    )
    assert sleeps == [2.5, 2.5]


@pytest.mark.parametrize(
    ("steam_rc", "guard_rc", "final"),
    [
        (0, 0, 0),
        (0, 11, 11),
        (7, 11, 11),
        (9, 11, 11),
        (130, 11, 11),
        (0, 12, 12),
        (7, 12, 7),
        (3, 11, 3),
        (5, 11, 5),
        (124, 12, 124),
        (0, 1, 12),
        (0, 2, 12),
        (7, 1, 7),
        (3, 1, 3),
        (3, 2, 3),
    ],
)
def test_combine_exit(steam_rc, guard_rc, final):
    """The Steam stage's own failure wins; otherwise 11 over 12, and a crashed guard is 12."""
    assert steam_guard.combine_exit(steam_rc, guard_rc) == final


def test_steam_size_reads_sizebytes(monkeypatch, tmp_path):
    """The size comes from the item's `sizeBytes`."""
    import steam_backfill

    monkeypatch.setattr(steam_backfill, "read_item", lambda utils, env, fid: {"sizeBytes": 742})
    assert steam_guard.steam_size(tmp_path, {}, 1) == 742


@pytest.mark.parametrize("item", [None, {}, {"sizeBytes": "742"}, {"sizeBytes": True}, []])
def test_steam_size_is_none_for_anything_else(monkeypatch, tmp_path, item):
    """A missing item, field or non-integer is "unreadable", not a number."""
    import steam_backfill

    monkeypatch.setattr(steam_backfill, "read_item", lambda utils, env, fid: item)
    assert steam_guard.steam_size(tmp_path, {}, 1) is None


def test_steam_size_is_none_when_the_reader_raises(monkeypatch, tmp_path):
    """A reader that blows up is an unreadable size."""
    import steam_backfill

    def boom(*_args):
        raise OSError("no ck-workshop")

    monkeypatch.setattr(steam_backfill, "read_item", boom)
    assert steam_guard.steam_size(tmp_path, {}, 1) is None


GUARD = Path(steam_guard.__file__)


def _cli(*args, env=None):
    return subprocess.run(
        [sys.executable, str(GUARD), *args],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, **(env or {})},
    )


def test_cli_combine_prints_the_combined_code():
    """`combine` prints combine_exit's answer."""
    done = _cli("combine", "0", "11")
    assert (done.returncode, done.stdout.strip()) == (0, "11")


@needs_git
def test_cli_checkout_prints_the_commit_or_the_problems(repo):
    """`checkout` prints the commit on a clean checkout and one line per problem otherwise."""
    clean = _cli("checkout", str(repo))
    assert clean.returncode == 0
    assert "on main" in clean.stdout
    (repo / "unity" / "Mod" / "Stray.cs").write_text("x\n")
    dirty = _cli("checkout", str(repo))
    assert dirty.returncode == 1
    assert "Stray.cs" in dirty.stderr


@needs_git
def test_cli_modio_id_refuses_only_a_missing_modio_id(repo):
    """`modio-id` exits 1 when main records a mod.io id the checkout lacks, and only then.

    upload.sh runs it before anything reaches mod.io, in every mode: on modId 0
    a normal publish has CLIPublishHelper call CreateModProfile and create a
    second mod.io profile. A missing Workshop id is not its business — the
    Steam preflight refuses that one, and on the normal path it must only skip
    Steam, not stop the mod.io release.
    """
    modio = repo / "unity" / "Mod" / "Editor" / "Mod_modio.asset"
    modio.parent.mkdir()
    modio.write_text("MonoBehaviour:\n  modId: 6119768\n")
    steam = repo / "unity" / "Mod" / "Mod_Steam.asset"
    steam.write_text("MonoBehaviour:\n  fileId: 3790345467\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "record the ids")
    env = {"MOD_NAME": "Mod"}
    assert _cli("modio-id", str(repo), env=env).returncode == 0

    steam.write_text("MonoBehaviour:\n  fileId: 0\n")
    workshop_gap_only = _cli("modio-id", str(repo), env=env)
    assert (workshop_gap_only.returncode, workshop_gap_only.stderr) == (0, "")

    modio.write_text("MonoBehaviour:\n  modId: 0\n")
    done = _cli("modio-id", str(repo), env=env)
    assert done.returncode == 1
    assert "6119768" in done.stderr and "SECOND mod.io profile" in done.stderr
    assert "Workshop id" not in done.stderr


def _cli_mod(tmp_path, ref_text):
    """A mod directory with a 100-byte build, a changelog and a reference file."""
    repo = tmp_path / "m"
    repo.mkdir()
    (repo / "CHANGELOG.md").write_text("## [1.0.0] - 2026-10-01\n\nfirst\n")
    build = tmp_path / "build"
    build.mkdir()
    (build / "a.bin").write_bytes(b"x" * 100)
    ref = tmp_path / "ref.json"
    ref.write_text(ref_text)
    env = {"MOD_NAME": "Mod", "CK_STEAM_CONTENT": str(build), "CK_MODIO_REF": str(ref)}
    return repo, env


def test_cli_pre_upload_proceeds_on_a_matching_build(tmp_path):
    """`pre-upload` exits 0 when the folder has the live modfile's size."""
    repo, env = _cli_mod(tmp_path, json.dumps(REF_LIVE_100))
    done = _cli("pre-upload", str(repo), env=env)
    assert done.returncode == 0, done.stderr
    assert "matches mod.io" in done.stdout


def test_cli_pre_upload_refuses_a_wrong_size_and_an_empty_reference(tmp_path):
    """`pre-upload` exits 1 on a size mismatch and on a reference with nothing in it."""
    repo, env = _cli_mod(tmp_path, json.dumps(REF_LIVE_100 | {"files": REF_LIVE_100["files"]}))
    (Path(env["CK_STEAM_CONTENT"]) / "b.bin").write_bytes(b"y")
    assert _cli("pre-upload", str(repo), env=env).returncode == 1
    Path(env["CK_MODIO_REF"]).write_text("")
    done = _cli("pre-upload", str(repo), env=env)
    assert done.returncode == 1
    assert "empty" in done.stderr


@pytest.mark.parametrize("ref_text", ["", "not json", "[]", "{}", '{"modId": 7}'])
def test_cli_post_upload_never_crashes_on_an_unusable_reference(tmp_path, ref_text):
    """R4: no usable reference means the comparison could not be made — exit 12, with a message."""
    repo, env = _cli_mod(tmp_path, ref_text)
    done = _cli("post-upload", str(repo), env=env)
    assert done.returncode == 12
    assert "Traceback" not in done.stderr
    assert done.stdout.strip()


def test_cli_post_upload_for_a_mod_not_on_modio_is_not_compared(tmp_path):
    """`modId` 0 exits 0 and says it compared nothing."""
    repo, env = _cli_mod(tmp_path, json.dumps({"modId": 0}))
    done = _cli("post-upload", str(repo), env=env)
    assert done.returncode == 0
    assert "not compared" in done.stdout


def test_cli_post_upload_without_a_recorded_item_is_unverified(tmp_path):
    """A matching modfile but no persisted Workshop id exits 12."""
    repo, env = _cli_mod(tmp_path, json.dumps(REF_LIVE_100))
    assert _cli("post-upload", str(repo), env=env).returncode == 12


def test_cli_steam_size_prints_nothing_without_an_id(tmp_path):
    """No item id: no output, exit 0."""
    repo, env = _cli_mod(tmp_path, "{}")
    done = _cli("steam-size", str(repo), env=env)
    assert (done.returncode, done.stdout) == (0, "")
