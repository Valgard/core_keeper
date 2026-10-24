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

import http.client
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
    """decide_pre_upload with a matching, non-override build as the baseline.

    The checkout records the id the reference names, unless a test says
    otherwise: a reference for `{"modId": 0}` passes `recorded_id=0`.
    """
    ref = overrides.get("ref", REF_LIVE_100)
    recorded = ref.get("modId") if isinstance(ref, dict) else 7
    arguments = {
        "version": "1.0.0",
        "ref": REF_LIVE_100,
        "content": overrides.pop("content", None),
        "content_size": 100,
        "override": False,
        "install_path": None,
        "recorded_id": recorded if steam_guard._whole_number(recorded) else 7,
        "litter": (),
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
    no `<Mod>_modio.asset` at all; with the checkout recording none either,
    both read the same here.
    """
    v = steam_guard.decide_pre_upload(
        version="1.0.0",
        ref={"modId": 0},
        content=tmp_path,
        content_size=5,
        override=False,
        install_path=None,
        recorded_id=0,
        litter=(),
    )
    assert v.proceed and "not on mod.io" in v.message


def test_an_override_for_a_mod_not_on_modio_is_refused(tmp_path):
    """The override is accepted only when mod.io can vouch for it, so a Steam-only mod has none."""
    verdict = _decide(content=tmp_path, override=True, ref={"modId": 0})

    assert not verdict.proceed
    assert "not on mod.io has no override" in verdict.message


# --- the reference against the checkout's own mod.io id -----------------------


def test_a_zero_modid_while_the_checkout_records_an_id_is_refused(tmp_path):
    """Unity reporting modId 0 for a checkout that records one is not "not on mod.io".

    `LoadAssetAtPath` returns null for an asset Unity did not import or could
    not load, and the helper then writes `{"modId": 0}`. Read as "not on
    mod.io", that would publish uncompared — the incident's failure class.
    """
    verdict = _decide(content=tmp_path, ref={"modId": 0}, recorded_id=6119768)

    assert not verdict.proceed
    assert "Unity did not see the mod.io id the checkout records" in verdict.message
    assert "6119768" in verdict.message


def test_a_reference_for_another_id_than_the_checkout_records_is_refused(tmp_path):
    """A reference naming a different mod.io id came from another checkout's asset, not this one."""
    verdict = _decide(content=tmp_path, recorded_id=8)

    assert not verdict.proceed
    assert "8" in verdict.message and "7" in verdict.message


def test_a_reference_with_an_id_the_checkout_does_not_record_is_refused(tmp_path):
    """The checkout records no mod.io id, yet Unity read one: it saw another checkout's asset."""
    verdict = _decide(content=tmp_path, recorded_id=0)

    assert not verdict.proceed
    assert "records no mod.io id" in verdict.message


@pytest.mark.parametrize(
    ("ref", "recorded"),
    [
        ({"modId": 0, "error": "HTTP 500"}, 0),
        ({"modId": False}, 0),
        ({"modId": 0.0}, 0),
        ({"modId": "0"}, 0),
        ({"modId": None}, 0),
        ({"modId": 7.0, "mod": REF_LIVE_100["mod"], "files": REF_LIVE_100["files"]}, 7),
        ({"modId": True, "mod": REF_LIVE_100["mod"], "files": REF_LIVE_100["files"]}, 1),
        ({"modId": -7, "mod": REF_LIVE_100["mod"], "files": REF_LIVE_100["files"]}, 0),
    ],
    ids=[
        "zero-with-error",
        "false",
        "zero-float",
        "zero-string",
        "null",
        "float",
        "true",
        "negative",
    ],
)
def test_a_modid_that_is_not_a_whole_number_or_carries_an_error_is_refused(tmp_path, ref, recorded):
    """Only a whole-number modId without "error" counts; "error" is looked at first.

    `{"modId": 0, "error": …}` is representable — the C# factory takes any id —
    and read in the other order it would proceed as "not on mod.io".
    """
    verdict = _decide(content=tmp_path, ref=ref, recorded_id=recorded)

    assert not verdict.proceed
    assert "mod.io reference could not be read" in verdict.message


# --- rule 3: a reference that cannot be read fails closed ---------------------


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
    """Any reference short of the expected keys refuses as unreadable and never raises.

    The file comes from a Unity run that may have crashed, timed out or met
    an answer of a shape nobody measured; a traceback there would end the run
    without saying which of those it was.
    """
    verdict = _decide(content=tmp_path, ref=ref)

    assert not verdict.proceed
    assert "mod.io reference could not be read" in verdict.message


# --- rule 4: a mod on mod.io cannot run ahead of it ---------------------------


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

    Builds of one commit reproduce byte for byte (measured, see
    docs/build-environment.md), so a difference means either a checkout that
    is not the released state or a toolchain that moved since the release.
    Neither is known to be the likelier, so both are offered as possibilities.
    A `<Mod>_Steam.asset` brought over from main to close an id gap is one
    such difference only when the release commit had no such file at all: its
    path ships in the bundle manifest, its contents do not. The way out is the
    same for both: the release's own modfile through the override.
    """
    verdict = _decide(content=tmp_path, content_size=101)

    assert not verdict.proceed
    assert "101 B" in verdict.message and "100 B" in verdict.message
    assert "this checkout is not the released state" in verdict.message
    assert "<Mod>_Steam.asset" in verdict.message
    assert "had no such file" in verdict.message
    assert "likelier" not in verdict.message
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


# A version uploaded twice, the older upload made live again by hand: the live
# one (id 2, 100 B) is what mod.io serves, the newer one (id 3, 101 B) is not.
REF_TWICE_OLDER_LIVE = {
    "modId": 7,
    "mod": {"modfile": {"id": 2, "version": "1.0.0", "filesize_uncompressed": 100}},
    "files": {
        "data": [
            {"id": 3, "version": "1.0.0", "filesize_uncompressed": 101, "date_added": 30},
            {"id": 2, "version": "1.0.0", "filesize_uncompressed": 100, "date_added": 20},
            {"id": 1, "version": "0.9.0", "filesize_uncompressed": 90, "date_added": 10},
        ]
    },
}


def test_reference_modfile_is_the_live_one_when_it_carries_the_version():
    """The live modfile wins over a newer upload of the same version: it is what mod.io serves."""
    assert steam_guard.reference_modfile(REF_TWICE_OLDER_LIVE, "1.0.0")["id"] == 2


def test_reference_modfile_falls_back_to_the_newest_upload_of_the_version():
    """With another version live — mod.io not caught up yet — the newest upload of it counts."""
    ref = json.loads(json.dumps(REF_TWICE_OLDER_LIVE))
    ref["mod"]["modfile"] = {"id": 1, "version": "0.9.0", "filesize_uncompressed": 90}

    assert steam_guard.reference_modfile(ref, "1.0.0")["id"] == 3
    assert steam_guard.reference_modfile(ref, "2.0.0") is None


def test_pre_upload_judges_a_version_uploaded_twice_by_the_live_upload(tmp_path):
    """Pre- and post-upload pick the same modfile, so a pass before cannot end in a false 11."""
    assert _decide(content=tmp_path, ref=REF_TWICE_OLDER_LIVE, content_size=100).proceed
    assert not _decide(content=tmp_path, ref=REF_TWICE_OLDER_LIVE, content_size=101).proceed


# --- Finder metadata in the content folder ------------------------------------


def test_finder_litter_lists_every_ds_store(tmp_path):
    """Every `.DS_Store` under the folder is found, at any depth, by its path inside the folder."""
    (tmp_path / "Bundles").mkdir()
    (tmp_path / ".DS_Store").write_bytes(b"\0")
    (tmp_path / "Bundles" / ".DS_Store").write_bytes(b"\0")
    (tmp_path / "Bundles" / "mod.bundle").write_bytes(b"x")

    assert steam_guard.finder_litter(tmp_path) == [".DS_Store", "Bundles/.DS_Store"]


def test_finder_litter_of_a_missing_folder_is_empty(tmp_path):
    """A missing folder has no litter; its absence is folder_size's to report."""
    assert steam_guard.finder_litter(tmp_path / "absent") == []


def test_content_with_finder_metadata_is_refused_naming_the_files(tmp_path):
    """A `.DS_Store` would be uploaded with the content and change its size, so it is refused.

    Finder writes one into a folder it opens — an unpacked override folder is
    the likely case — and the refusal names each file so it can be removed.
    """
    verdict = _decide(content=tmp_path, override=True, litter=[".DS_Store", "Bundles/.DS_Store"])

    assert not verdict.proceed
    assert ".DS_Store" in verdict.message and "Bundles/.DS_Store" in verdict.message


def test_finder_metadata_is_refused_for_a_mod_not_on_modio_too(tmp_path):
    """Without a comparison nothing else would catch it, and it would ship to Steam as content."""
    verdict = _decide(content=tmp_path, ref={"modId": 0}, litter=[".DS_Store"])

    assert not verdict.proceed and ".DS_Store" in verdict.message


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
    """One version uploaded twice: the later upload by `date_added` counts, wherever it sits.

    The newest upload carries the smallest id here, so an ordering by id
    instead of by date would pick another entry.
    """
    ref = {
        "files": {
            "data": [
                {"id": 5, "version": "1.0.0", "date_added": 10},
                {"id": 2, "version": "1.0.0", "date_added": 30},
                {"id": 9, "version": "1.0.0", "date_added": 20},
            ]
        }
    }

    assert steam_guard.modfile_for_version(ref, "1.0.0")["id"] == 2


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
    """An empty or broken reference file becomes an error reference, never an exception.

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


def test_an_empty_reference_names_its_possible_causes_not_one_of_them(tmp_path):
    """Nothing says which producer left the file empty, so the text offers each, as a possibility.

    A Unity run that ended early is one; a stale compiled copy of the helper
    that never writes the file is another, and so is a write that failed.
    Blaming the first alone sends the operator after the wrong one.
    """
    path = tmp_path / "ref.json"
    path.write_text("")

    error = steam_guard.load_reference(path)["error"]

    assert "empty" in error
    assert "stale" in error and "link.sh" in error
    assert "could not write the mod.io reference" in error


# --- the checkout: uncommitted paths and the [Unreleased] rule --------------


def _git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout


@pytest.fixture
def repo(tmp_path):
    """A committed mod checkout with the three paths the checkout rule watches, and ignores."""
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
    """A checkout exactly at its commit passes the uncommitted-paths rule and the changelog rule."""
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
    (repo / "README.md").write_text("changed, but outside the watched paths\n")

    lines = steam_guard.dirty_paths(repo)

    assert sorted(lines) == sorted([" M unity/Mod/Mod.cs", "?? unity/Mod/Stray.cs"])


@needs_git
def test_untracked_files_count_even_when_git_is_told_to_hide_them(repo):
    """A `status.showUntrackedFiles = no` in someone's config must not switch off the rule.

    The setting is a display preference, and git status honours it silently;
    the checkout rule is that untracked counts, so the command pins it.
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
    """An empty `## [Unreleased]` heading kept by habit refuses nothing."""
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
    """Outside a repository the checkout cannot be checked, and an unchecked one must refuse."""
    (tmp_path / "CHANGELOG.md").write_text("## [1.0.0]\n\nfirst\n")

    problems = steam_guard.checkout_problems(tmp_path)

    assert len(problems) == 1
    assert "git" in problems[0]


@needs_git
# GIT_DIR is git's own environment variable name, not a choice of ours.
def test_an_inherited_GIT_DIR_does_not_answer_for_another_repo(repo, tmp_path, monkeypatch):  # noqa: N802
    """The checkout rule asks the mod's repository even when the environment points git elsewhere.

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


def test_a_verdict_has_no_truth_value(tmp_path):
    """`if decide_pre_upload(...)` must fail loudly: a NamedTuple of two fields is always truthy.

    Read that way, every refusal would pass. The error names `.proceed`, the
    field the caller meant.
    """
    verdict = _decide(content=tmp_path, content_size=101)

    with pytest.raises(TypeError, match="proceed"):
        bool(verdict)
    with pytest.raises(TypeError, match="proceed"):
        assert verdict


# --- after the upload: the item against mod.io, and the exit code --------------

NEW_ITEM = steam_guard.SizeBefore.NEW_ITEM
UNKNOWN = steam_guard.SizeBefore.UNKNOWN


def _no_sleep(_seconds):
    """A sleep that does not wait."""


class _Reads:
    """A Steam size reader that replays `values`, repeating the last, and counts its calls."""

    def __init__(self, *values):
        self.values = list(values)
        self.calls = 0

    def __call__(self):
        value = self.values[min(self.calls, len(self.values) - 1)]
        self.calls += 1
        return value


def _compare(expected, before, reads, attempts=6):
    """compare_after_upload with no waiting between reads."""
    return steam_guard.compare_after_upload(
        expected, before, reads, attempts=attempts, sleep=_no_sleep
    )


def test_old_size_then_new_size_is_a_match():
    """Steam lags the upload: reads of the old size are retried until the new one shows."""
    assert _compare(742, 500, _Reads(500, 500, 742), attempts=3)[0] == 0


def test_a_known_item_with_a_wrong_size_is_a_mismatch_at_once():
    """With the old size known, a size that is neither it nor mod.io's is final — no waiting."""
    reads = _Reads(811)

    assert _compare(742, 500, reads)[0] == 11
    assert reads.calls == 1


def test_still_the_old_size_is_unverified():
    """An item that never changed size leaves the comparison unmade."""
    code, message = _compare(742, 500, _Reads(500), attempts=2)

    assert code == 12
    assert "500 B" in message


def test_a_known_item_whose_reads_fail_is_unverified_not_a_mismatch():
    """A failed read of an item whose old size is known is waited out, and never concluded as 11.

    A transient network error after an update is the realistic case; an 11
    there would be the loudest false alarm the pipeline has.
    """
    assert _compare(742, 500, _Reads(None), attempts=3)[0] == 12
    reads = _Reads(None, 742)
    assert _compare(742, 500, reads, attempts=3)[0] == 0
    assert reads.calls == 2


@pytest.mark.parametrize("before", [500, NEW_ITEM, UNKNOWN])
def test_unreadable_is_unverified(before):
    """No answer from Steam is not a match, whatever is known about the size before."""
    assert _compare(742, before, _Reads(None), attempts=2)[0] == 12


def test_same_size_reupload_matches_at_once():
    """Re-uploading the same build changes nothing to wait for."""
    assert _compare(742, 742, _Reads(742))[0] == 0


@pytest.mark.parametrize("expected", [None, 0])
def test_no_expected_size_is_unverified(expected):
    """Without a size from mod.io the comparison is not made: 12, never a silent pass."""
    assert steam_guard.compare_after_upload(expected, 5, _Reads(5))[0] == 12


def test_a_new_item_reading_zero_until_its_size_shows_is_a_match():
    """A first publish has no size before it, and Steam may report 0 until the content shows.

    0 is "not yet", not the item's size — no uploaded build is 0 bytes. Before
    this rule, a first 0 ended a correct first publish in exit 11.
    """
    reads = _Reads(0, 0, 742)

    assert _compare(742, NEW_ITEM, reads)[0] == 0
    assert reads.calls == 3


def test_a_new_item_that_stays_at_zero_is_unverified():
    """A size that never shows is a comparison not made (12), never a mismatch."""
    reads = _Reads(0)
    code, message = _compare(742, NEW_ITEM, reads, attempts=4)

    assert code == 12
    assert reads.calls == 4
    assert "0 B" in message


def test_a_new_item_with_a_wrong_size_is_a_mismatch_only_after_the_last_read():
    """Without a size from before, nothing tells a lagging read from a final one.

    So a wrong nonzero size is concluded only once every attempt is used, from
    the last read.
    """
    reads = _Reads(811)

    assert _compare(742, NEW_ITEM, reads, attempts=5)[0] == 11
    assert reads.calls == 5


def test_a_new_item_whose_wrong_read_settles_on_the_right_size_is_a_match():
    """An early wrong size on a new item is waited out, not judged."""
    assert _compare(742, NEW_ITEM, _Reads(811, 742), attempts=5)[0] == 0


def test_a_new_item_whose_last_read_fails_is_unverified():
    """The verdict on a new item is the last read's: unreadable there is 12, whatever came first."""
    assert _compare(742, NEW_ITEM, _Reads(811, 811, None), attempts=3)[0] == 12


def test_a_new_items_unreadable_size_says_why_and_how_to_check_later():
    """A first publish's 12 names the likely reason and the command that finishes the check.

    A new item is created hidden, and whether the public Web API shows a
    hidden item is not measured — so the reason is offered as a possibility,
    with the follow-up that settles it once the item is visible.
    """
    code, message = _compare(742, NEW_ITEM, _Reads(None), attempts=2)

    assert code == 12
    assert "new" in message and "visible" in message and "unverified" in message
    assert "steam-size" in message and "742" in message


@pytest.mark.parametrize(("values", "code"), [((0, 742), 0), ((0,), 12)])
def test_a_zero_read_of_a_known_item_is_never_a_mismatch(values, code):
    """With a size from before, 0 is neither that size nor mod.io's — and still only "not yet"."""
    assert _compare(742, 500, _Reads(*values), attempts=3)[0] == code


def test_an_existing_item_with_an_unknown_before_is_never_a_mismatch():
    """The old size is unknown, so a lagging old read cannot be told from other content — 12."""
    code, message = _compare(742, UNKNOWN, _Reads(500), attempts=3)

    assert code == 12
    assert "is unknown" in message


def test_an_unknown_before_still_matches_when_the_size_arrives():
    """An unknown old size does not stop a read equal to mod.io's from matching."""
    assert _compare(742, UNKNOWN, _Reads(500, 742), attempts=3)[0] == 0


@pytest.mark.parametrize("before", [0, -5, None])
def test_a_before_that_is_no_size_is_unknown_not_new(before):
    """0 is never a size, before the upload either; nor is an empty value a new item.

    Read as known, a before of 0 would conclude 11 from the first lagging
    read; read as new, a missing value would conclude 11 from the last one.
    Only the explicit new-item state may do that.
    """
    code, message = _compare(742, before, _Reads(500), attempts=3)

    assert code == 12
    assert "is unknown" in message


def test_the_retry_sleeps_between_reads_only():
    """Attempts are spaced by the interval, with no sleep before the first read."""
    sleeps = []
    steam_guard.compare_after_upload(
        742, 500, _Reads(500), attempts=3, interval=2.5, sleep=sleeps.append
    )
    assert sleeps == [2.5, 2.5]


def test_the_default_sleep_is_looked_up_when_called(monkeypatch):
    """Without a `sleep` argument the comparison uses `time.sleep` as it is at call time.

    Bound as a default when the function was defined, a stub of `time.sleep`
    would never take effect, and a CLI test would sleep through every attempt.
    """
    sleeps = []
    monkeypatch.setattr(steam_guard.time, "sleep", sleeps.append)

    steam_guard.compare_after_upload(742, 500, _Reads(500), attempts=3, interval=2.5)

    assert sleeps == [2.5, 2.5]


@pytest.mark.parametrize(
    ("raw", "parsed"),
    [
        ("742", 742),
        (" 742\n", 742),
        ("none", NEW_ITEM),
        ("unreadable", UNKNOWN),
        ("", UNKNOWN),
        (None, UNKNOWN),
        ("0", UNKNOWN),
        ("-5", UNKNOWN),
        ("garbage", UNKNOWN),
        ("none\nunreadable", UNKNOWN),
        ("\N{FULLWIDTH DIGIT SEVEN}\N{FULLWIDTH DIGIT FOUR}", UNKNOWN),
    ],
    ids=[
        "number",
        "padded",
        "new",
        "unreadable",
        "empty",
        "unset",
        "zero",
        "negative",
        "garbage",
        "two-lines",
        "fullwidth-digits",
    ],
)
def test_parse_size_before(raw, parsed):
    """CK_STEAM_SIZE_BEFORE is one of three states; anything not plainly one of them is unknown.

    An empty value is what a crashed `steam-size` leaves when nothing else
    catches it, and it must not read as "new item" — the one state allowed to
    conclude a mismatch without a size from before.
    """
    assert steam_guard.parse_size_before(raw) == parsed


def test_parse_size_before_names_a_value_it_does_not_know(capsys):
    """An unrecognised value is reported once, so a changed producer does not go unnoticed."""
    assert steam_guard.parse_size_before("garbage") is UNKNOWN
    assert "garbage" in capsys.readouterr().err


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
        (9, 12, 9),
        (130, 12, 130),
        (3, 11, 3),
        (5, 11, 5),
        (124, 12, 124),
        (0, 1, 12),
        (0, 2, 12),
        (7, 1, 7),
        (3, 1, 3),
        (3, 2, 3),
        (1, 11, 1),
        (10, 11, 10),
        (10, 12, 10),
        (2, 11, 2),
        (4, 11, 4),
        (6, 12, 6),
        (1, 0, 1),
    ],
)
def test_combine_exit(steam_rc, guard_rc, final):
    """Only a Steam code after which the upload may have gone through can be changed.

    Those are 0, 7, 9 and 130; any other Steam code — ck-workshop's 2-6,
    `timeout`'s 124, or one nobody has assigned yet — passes through as it is.
    Among the four, 11 outranks all, 12 only 0, and a crashed guard counts as 12.
    """
    assert steam_guard.combine_exit(steam_rc, guard_rc) == final


def _details(monkeypatch, result):
    """Make the Web API reader return `result`, or raise it when it is an exception."""
    import steam_retag

    def fake(file_id):
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(steam_retag, "item_details", fake)


@pytest.mark.parametrize("size", ["80420", 80420])
def test_steam_size_reads_file_size(monkeypatch, capsys, size):
    """The size is the Web API's `file_size`, a string; a number is accepted too."""
    _details(monkeypatch, {"result": 1, "file_size": size})

    assert steam_guard.steam_size(1) == 80420
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize(
    ("details", "cause"),
    [
        ({"result": 9, "file_size": "80420"}, "result 9"),
        ({"result": 1}, "file_size"),
        ({"result": 1, "file_size": "lots"}, "file_size"),
        ({"result": 1, "file_size": None}, "file_size"),
        ({"result": 1, "file_size": True}, "file_size"),
        ({"result": 1, "file_size": "-5"}, "file_size"),
        ({}, "result None"),
        (None, "unexpected"),
        ([], "unexpected"),
    ],
)
def test_steam_size_is_none_for_anything_else_and_says_why(monkeypatch, capsys, details, cause):
    """A hidden or deleted item, or a size that is no whole number, is unreadable, and said."""
    _details(monkeypatch, details)

    assert steam_guard.steam_size(1) is None
    err = capsys.readouterr().err
    assert cause in err
    assert len(err.strip().splitlines()) == 1


@pytest.mark.parametrize(
    "error",
    [
        OSError("offline"),
        ValueError("unexpected shape"),
        TimeoutError("timed out"),
        http.client.IncompleteRead(b"partial"),
    ],
)
def test_steam_size_is_none_when_the_fetch_raises_and_says_why(monkeypatch, capsys, error):
    """A network error, a certificate fault or a bad response is an unreadable size, and says so."""
    _details(monkeypatch, error)

    assert steam_guard.steam_size(1) is None
    err = capsys.readouterr().err
    assert type(error).__name__ in err
    assert len(err.strip().splitlines()) == 1


def test_steam_size_lets_a_programming_error_through(monkeypatch):
    """A bug is not an unreadable size: it surfaces, and the callers turn a crash into "unknown"."""
    _details(monkeypatch, TypeError("a renamed argument"))

    with pytest.raises(TypeError):
        steam_guard.steam_size(1)


GUARD = Path(steam_guard.__file__)

# The variables upload.sh hands the guard; inherited from the shell running
# the tests, they would change what a CLI test checks without the test saying so.
GUARD_ENV = (
    "CK_STEAM_OVERRIDE",
    "CK_STEAM_CONTENT",
    "CK_MODIO_REF",
    "CK_STEAM_SIZE_BEFORE",
    "MOD_INSTALL_PATH",
    "MOD_NAME",
)


def _cli(*args, env=None):
    """Run steam_guard.py as upload.sh does, in a clean environment plus `env`."""
    inherited = {k: v for k, v in os.environ.items() if k not in GUARD_ENV}
    return subprocess.run(
        [sys.executable, str(GUARD), *args],
        capture_output=True,
        text=True,
        check=False,
        env={**inherited, **(env or {})},
    )


def test_cli_combine_prints_the_combined_code():
    """`combine` prints combine_exit's answer."""
    done = _cli("combine", "0", "11")
    assert (done.returncode, done.stdout.strip()) == (0, "11")


def test_cli_refuses_an_unknown_command_and_a_missing_mod_name(tmp_path):
    """A mistyped command or a missing MOD_NAME exits 2, never 0 — upload.sh reads 0 as a pass."""
    assert steam_guard.main(["x", "pre-uplaod", str(tmp_path)], env={"MOD_NAME": "M"}) == 2
    assert steam_guard.main(["x", "pre-upload", str(tmp_path)], env={}) == 2


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
def test_cli_modio_id_refuses_a_missing_or_different_modio_id(repo):
    """`modio-id` exits 1 when the checkout lacks main's mod.io id or has another, and only then.

    upload.sh runs it before anything reaches mod.io, in every mode: on modId 0
    a normal publish has CLIPublishHelper call CreateModProfile and create a
    second mod.io profile, and on another id it uploads to that profile. A
    missing Workshop id is not its business — the Steam preflight refuses that
    one, and on the normal path it must only skip Steam, not stop the release.
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

    modio.write_text("MonoBehaviour:\n  modId: 999\n")
    other = _cli("modio-id", str(repo), env=env)
    assert other.returncode == 1
    assert "999" in other.stderr and "6119768" in other.stderr


def _cli_mod(tmp_path, ref_text, *, modio_id=7):
    """A mod directory with a 100-byte build, a changelog and a reference file.

    The checkout's own `<Mod>_modio.asset` records `modio_id` — the reference
    fixtures name 7 — or is absent for None.
    """
    repo = tmp_path / "m"
    repo.mkdir()
    (repo / "CHANGELOG.md").write_text("## [1.0.0] - 2026-10-01\n\nfirst\n")
    if modio_id is not None:
        asset = repo / "unity" / "Mod" / "Editor" / "Mod_modio.asset"
        asset.parent.mkdir(parents=True)
        asset.write_text(f"MonoBehaviour:\n  modId: {modio_id}\n")
    build = tmp_path / "build"
    build.mkdir()
    (build / "a.bin").write_bytes(b"x" * 100)
    ref = tmp_path / "ref.json"
    ref.write_text(ref_text)
    env = {"MOD_NAME": "Mod", "CK_STEAM_CONTENT": str(build), "CK_MODIO_REF": str(ref)}
    return repo, env


def _workshop_id(repo, file_id=123):
    """Record a Workshop item id in the mod directory, as a publish leaves it."""
    asset = repo / "unity" / "Mod" / "Mod_Steam.asset"
    asset.parent.mkdir(parents=True, exist_ok=True)
    asset.write_text(f"MonoBehaviour:\n  fileId: {file_id}\n")


def test_cli_pre_upload_proceeds_on_a_matching_build(tmp_path):
    """`pre-upload` exits 0 when the folder has the live modfile's size."""
    repo, env = _cli_mod(tmp_path, json.dumps(REF_LIVE_100))
    done = _cli("pre-upload", str(repo), env=env)
    assert done.returncode == 0, done.stderr
    assert "matches mod.io" in done.stdout


def test_cli_pre_upload_refuses_a_wrong_size_and_an_empty_reference(tmp_path):
    """`pre-upload` exits 1 on a size mismatch and on a reference with nothing in it."""
    repo, env = _cli_mod(tmp_path, json.dumps(REF_LIVE_100))
    (Path(env["CK_STEAM_CONTENT"]) / "b.bin").write_bytes(b"y")
    assert _cli("pre-upload", str(repo), env=env).returncode == 1
    Path(env["CK_MODIO_REF"]).write_text("")
    done = _cli("pre-upload", str(repo), env=env)
    assert done.returncode == 1
    assert "empty" in done.stderr


def test_cli_pre_upload_refuses_an_override_inside_the_install_path(tmp_path):
    """Through the variables upload.sh exports: an override inside MOD_INSTALL_PATH is refused.

    The same folder without CK_STEAM_OVERRIDE is the run's own build and is
    judged by its size alone — so the refusal rests on reading both variables
    under the names upload.sh exports them by.
    """
    repo, env = _cli_mod(tmp_path, json.dumps(REF_LIVE_100))
    install = tmp_path / "install"
    (install / "Mod").mkdir(parents=True)
    (install / "Mod" / "a.bin").write_bytes(b"x" * 100)
    env |= {"CK_STEAM_CONTENT": str(install / "Mod"), "MOD_INSTALL_PATH": str(install)}

    refused = _cli("pre-upload", str(repo), env=env | {"CK_STEAM_OVERRIDE": "1"})
    assert refused.returncode == 1
    assert "MOD_INSTALL_PATH" in refused.stderr

    as_build = _cli("pre-upload", str(repo), env=env)
    assert as_build.returncode == 0, as_build.stderr
    assert "matches mod.io" in as_build.stdout


def test_cli_pre_upload_refuses_an_override_for_a_mod_not_on_modio(tmp_path):
    """CK_STEAM_OVERRIDE alone, with the folder outside MOD_INSTALL_PATH, is read and refused."""
    repo, env = _cli_mod(tmp_path, json.dumps({"modId": 0}), modio_id=0)

    done = _cli("pre-upload", str(repo), env=env | {"CK_STEAM_OVERRIDE": "1"})

    assert done.returncode == 1
    assert "not on mod.io has no override" in done.stderr


def test_cli_pre_upload_refuses_when_unity_did_not_see_the_checkouts_id(tmp_path):
    """The checkout records mod.io id 7, Unity reported 0: refused, not published uncompared."""
    repo, env = _cli_mod(tmp_path, json.dumps({"modId": 0}), modio_id=7)

    done = _cli("pre-upload", str(repo), env=env)

    assert done.returncode == 1
    assert "Unity did not see the mod.io id the checkout records" in done.stderr


def test_cli_pre_upload_refuses_an_unreadable_checkout_asset(tmp_path):
    """A `<Mod>_modio.asset` that exists but cannot be read is no answer, so it refuses."""
    repo, env = _cli_mod(tmp_path, json.dumps(REF_LIVE_100), modio_id=None)
    (repo / "unity" / "Mod" / "Editor" / "Mod_modio.asset").mkdir(parents=True)

    done = _cli("pre-upload", str(repo), env=env)

    assert done.returncode == 1
    assert "Mod_modio.asset" in done.stderr


def test_cli_pre_upload_refuses_finder_metadata_in_the_content(tmp_path):
    """A `.DS_Store` in the folder is refused by name, before its size can mislead anyone."""
    repo, env = _cli_mod(tmp_path, json.dumps(REF_LIVE_100))
    (Path(env["CK_STEAM_CONTENT"]) / ".DS_Store").write_bytes(b"\0" * 6)

    done = _cli("pre-upload", str(repo), env=env)

    assert done.returncode == 1
    assert ".DS_Store" in done.stderr


def test_cli_pre_upload_refuses_an_unset_content_folder(tmp_path):
    """Without CK_STEAM_CONTENT there is no folder to judge, and the working directory is none."""
    repo, env = _cli_mod(tmp_path, json.dumps(REF_LIVE_100))
    del env["CK_STEAM_CONTENT"]

    done = _cli("pre-upload", str(repo), env=env)

    assert done.returncode == 1
    assert "CK_STEAM_CONTENT" in done.stderr


def test_cli_pre_upload_refuses_a_missing_folder_for_a_mod_on_modio(tmp_path):
    """A folder that is not there cannot be compared, so a mod on mod.io refuses on it."""
    repo, env = _cli_mod(tmp_path, json.dumps(REF_LIVE_100))
    env["CK_STEAM_CONTENT"] = str(tmp_path / "absent")

    done = _cli("pre-upload", str(repo), env=env)

    assert done.returncode == 1
    assert "could not be measured" in done.stderr


@pytest.mark.parametrize("ref_text", ["", "not json", "[]", "{}", '{"modId": 7}'])
def test_cli_post_upload_never_crashes_on_an_unusable_reference(tmp_path, ref_text):
    """No usable reference means the comparison could not be made — exit 12, with a message."""
    repo, env = _cli_mod(tmp_path, ref_text)
    done = _cli("post-upload", str(repo), env=env)
    assert done.returncode == 12
    assert "Traceback" not in done.stderr
    assert done.stdout.strip()


@pytest.mark.parametrize(
    "ref",
    [{"modId": 0, "error": "HTTP 500"}, {"modId": False}, {"modId": 0.0}],
    ids=["zero-with-error", "false", "zero-float"],
)
def test_cli_post_upload_does_not_take_a_malformed_zero_for_not_on_modio(tmp_path, ref):
    """Post-upload classifies as pre-upload does: these are unusable (12), not "not on mod.io"."""
    repo, env = _cli_mod(tmp_path, json.dumps(ref), modio_id=0)

    done = _cli("post-upload", str(repo), env=env)

    assert done.returncode == 12
    assert "not compared" not in done.stdout


def test_cli_post_upload_for_a_mod_not_on_modio_is_not_compared(tmp_path):
    """`modId` 0, and none recorded by the checkout either, exits 0 and says it compared nothing."""
    repo, env = _cli_mod(tmp_path, json.dumps({"modId": 0}), modio_id=0)
    done = _cli("post-upload", str(repo), env=env)
    assert done.returncode == 0
    assert "not compared" in done.stdout


def test_cli_post_upload_when_unity_did_not_see_the_checkouts_id_is_12(tmp_path):
    """The checkout records an id, Unity reported 0: the comparison was not made — 12, not 0."""
    repo, env = _cli_mod(tmp_path, json.dumps({"modId": 0}), modio_id=7)

    done = _cli("post-upload", str(repo), env=env)

    assert done.returncode == 12
    assert "Unity did not see the mod.io id the checkout records" in done.stdout


def test_cli_post_upload_without_a_recorded_item_is_unverified(tmp_path):
    """A matching modfile but no persisted Workshop id exits 12."""
    repo, env = _cli_mod(tmp_path, json.dumps(REF_LIVE_100))
    assert _cli("post-upload", str(repo), env=env).returncode == 12


def _post_upload(monkeypatch, repo, env, reads, before):
    """`post-upload` through main(), with Steam's reads stubbed and no waiting."""
    monkeypatch.setattr(steam_guard, "steam_size", lambda _file_id: reads())
    monkeypatch.setattr(steam_guard.time, "sleep", _no_sleep)
    return steam_guard.main(
        ["steam_guard.py", "post-upload", str(repo)], env={**env, "CK_STEAM_SIZE_BEFORE": before}
    )


def test_cli_post_upload_matches_the_uncompressed_size_of_this_version(
    monkeypatch, tmp_path, capsys
):
    """The success path: Steam's size equals `filesize_uncompressed` of this version's modfile.

    Not `filesize`, the compressed download — Steam reports the content
    total — and not another version's modfile.
    """
    ref = {
        "modId": 7,
        "mod": {
            "modfile": {
                "id": 2,
                "version": "1.0.0",
                "filesize": 40,
                "filesize_uncompressed": 100,
            }
        },
        "files": {
            "data": [
                {
                    "id": 2,
                    "version": "1.0.0",
                    "filesize": 40,
                    "filesize_uncompressed": 100,
                    "date_added": 2,
                },
                {"id": 1, "version": "0.9.0", "filesize_uncompressed": 90, "date_added": 1},
            ]
        },
    }
    repo, env = _cli_mod(tmp_path, json.dumps(ref))
    _workshop_id(repo)

    assert _post_upload(monkeypatch, repo, env, _Reads(100), "500") == 0
    assert "matches mod.io (100 bytes)" in capsys.readouterr().out
    reads = _Reads(40)
    assert _post_upload(monkeypatch, repo, env, reads, "500") == 11
    assert reads.calls == 1


def test_cli_post_upload_compares_the_live_upload_of_a_version_uploaded_twice(
    monkeypatch, tmp_path
):
    """Post-upload picks the modfile pre-upload judged: the live one, not a newer upload of it."""
    repo, env = _cli_mod(tmp_path, json.dumps(REF_TWICE_OLDER_LIVE))
    _workshop_id(repo)

    assert _post_upload(monkeypatch, repo, env, _Reads(100), "500") == 0


def test_cli_post_upload_parses_a_numeric_before(monkeypatch, tmp_path):
    """A number in CK_STEAM_SIZE_BEFORE is the item's old size: a different size is final at once.

    The common case — every update of an existing item. Ignored, the number
    would leave the old size unknown, and the same run would end in 12.
    """
    repo, env = _cli_mod(tmp_path, json.dumps(REF_LIVE_100))
    _workshop_id(repo)
    reads = _Reads(811)

    assert _post_upload(monkeypatch, repo, env, reads, "500") == 11
    assert reads.calls == 1


@pytest.mark.parametrize("before", ["unreadable", "", "garbage", "0"])
def test_cli_post_upload_unknown_before_with_a_stale_read_is_12(monkeypatch, tmp_path, before):
    """An unknown old size — unreadable, empty from a crash, garbled, 0 — never ends in 11."""
    repo, env = _cli_mod(tmp_path, json.dumps(REF_LIVE_100))
    _workshop_id(repo)

    assert _post_upload(monkeypatch, repo, env, _Reads(55), before) == 12


def test_cli_post_upload_new_item_with_a_wrong_last_read_is_11(monkeypatch, tmp_path):
    """Only steam-size's explicit `none` — no item before the upload — may conclude 11 blind."""
    repo, env = _cli_mod(tmp_path, json.dumps(REF_LIVE_100))
    _workshop_id(repo)

    assert _post_upload(monkeypatch, repo, env, _Reads(55), "none") == 11


@pytest.mark.parametrize("size", [0, None, "100"])
def test_post_upload_is_12_when_modio_has_no_size(tmp_path, size, monkeypatch, capsys):
    """A mod.io size of 0 (or missing, non-numeric) leaves the comparison unmade: 12, said so."""
    ref = json.loads(json.dumps(REF_LIVE_100))
    ref["files"]["data"][0]["filesize_uncompressed"] = size
    ref["mod"]["modfile"]["filesize_uncompressed"] = size
    repo, env = _cli_mod(tmp_path, json.dumps(ref))
    _workshop_id(repo)

    assert _post_upload(monkeypatch, repo, env, _Reads(0), "500") == 12
    assert "no size on record" in capsys.readouterr().out


@pytest.mark.parametrize("size", [0, None, "100", True, -5])
def test_pre_upload_refuses_a_modio_size_that_is_no_size(tmp_path, size):
    """A live modfile size of 0 (or missing, non-numeric) is no size: unreadable, not compared."""
    ref = json.loads(json.dumps(REF_LIVE_100))
    ref["files"]["data"][0]["filesize_uncompressed"] = size
    ref["mod"]["modfile"]["filesize_uncompressed"] = size
    verdict = _decide(content=tmp_path, ref=ref, content_size=0 if size == 0 else 100)
    assert not verdict.proceed
    assert "no size" in verdict.message


def test_cli_steam_size_prints_none_without_an_id(tmp_path):
    """No item id: the explicit `none`, exit 0 — never an empty answer, which a crash also gives."""
    repo, env = _cli_mod(tmp_path, "{}")
    done = _cli("steam-size", str(repo), env=env)
    assert (done.returncode, done.stdout) == (0, "none\n")


def test_cli_steam_size_prints_a_sentinel_for_an_unreadable_existing_item(
    monkeypatch, tmp_path, capsys
):
    """An item with an id whose size cannot be read, or reads 0, prints `unreadable`; exit 0."""
    repo = tmp_path / "m"
    _workshop_id(repo)
    for size, printed in ((None, "unreadable"), (0, "unreadable"), (80420, "80420")):
        monkeypatch.setattr(steam_guard, "steam_size", lambda _file_id, size=size: size)
        assert steam_guard._cmd_steam_size(repo, "Mod", {}) == 0
        assert capsys.readouterr().out.strip() == printed


def test_cli_steam_size_prints_unreadable_when_the_asset_cannot_be_read(tmp_path):
    """An identity asset that cannot be read is an item of unknown size, not a new one."""
    repo, env = _cli_mod(tmp_path, "{}")
    (repo / "unity" / "Mod" / "Mod_Steam.asset").mkdir(parents=True)

    done = _cli("steam-size", str(repo), env=env)

    assert (done.returncode, done.stdout) == (0, "unreadable\n")
    assert "Mod_Steam.asset" in done.stderr
