"""Unit tests for reading and writing the Workshop file id.

The asset is the SDK's own <Mod>_Steam.asset, and we address it by path rather
than by the modName field inside it. That field is written from the display
title and looked up by metadata.name, so it goes stale the moment a readable
title is used (CoreKeeperModSDK#11) — reading it would inherit the defect.
"""

import shutil
import subprocess

import pytest
import steam_identity

ASSET = """%YAML 1.1
%TAG !u! tag:unity3d.com,2011:
--- !u!114 &11400000
MonoBehaviour:
  m_Name: DisableDurability_Steam
  fileId: 3790345467
  modOwner: 10000000000000000
  modName: Disable Durability
  selectedPath: /var/folders/x/T/BuiltMods/DisableDurability
  tags:
  - Client
  - Script
"""


def test_reads_the_file_id(tmp_path):
    asset = tmp_path / "DisableDurability_Steam.asset"
    asset.write_text(ASSET)

    assert steam_identity.read_file_id(asset) == 3790345467


def test_a_stale_modName_does_not_affect_the_read(tmp_path):
    asset = tmp_path / "DisableDurability_Steam.asset"
    asset.write_text(
        ASSET.replace("modName: Disable Durability", "modName: something else entirely")
    )

    assert steam_identity.read_file_id(asset) == 3790345467


def test_a_missing_asset_reads_as_no_id(tmp_path):
    assert steam_identity.read_file_id(tmp_path / "absent.asset") is None


def test_a_zero_id_reads_as_no_id(tmp_path):
    asset = tmp_path / "x_Steam.asset"
    asset.write_text(ASSET.replace("fileId: 3790345467", "fileId: 0"))

    assert steam_identity.read_file_id(asset) is None


def test_writing_updates_an_existing_asset_and_leaves_the_rest_alone(tmp_path):
    asset = tmp_path / "DisableDurability_Steam.asset"
    asset.write_text(ASSET)

    steam_identity.write_file_id(asset, 4242424242)

    text = asset.read_text()
    assert steam_identity.read_file_id(asset) == 4242424242
    assert "modOwner: 10000000000000000" in text
    assert "m_Name: DisableDurability_Steam" in text


def test_writing_creates_the_asset_when_absent(tmp_path):
    asset = tmp_path / "NewMod_Steam.asset"

    steam_identity.write_file_id(asset, 99)

    text = asset.read_text()
    assert steam_identity.read_file_id(asset) == 99
    assert text.startswith("%YAML 1.1")
    assert "m_Name: NewMod_Steam" in text
    assert "modName: NewMod" in text


def test_creating_the_asset_also_writes_its_meta(tmp_path):
    asset = tmp_path / "NewMod_Steam.asset"

    steam_identity.write_file_id(asset, 99)

    meta = asset.with_suffix(".asset.meta")
    text = meta.read_text()
    guid = next(
        line.split("guid: ")[1]
        for line in text.splitlines()
        if line.startswith("guid: ")
    )
    assert len(guid) == 32 and int(guid, 16) >= 0, guid
    assert "fileFormatVersion: 2" in text
    assert "mainObjectFileID: 11400000" in text


def test_two_created_assets_do_not_share_a_guid(tmp_path):
    first = tmp_path / "A" / "A_Steam.asset"
    second = tmp_path / "B" / "B_Steam.asset"

    steam_identity.write_file_id(first, 1)
    steam_identity.write_file_id(second, 2)

    assert (
        first.with_suffix(".asset.meta").read_text()
        != second.with_suffix(".asset.meta").read_text()
    )


def test_updating_an_asset_leaves_an_existing_meta_untouched(tmp_path):
    # The GUID is Unity's, and once it exists something may reference it. A
    # publish updates the id inside the asset and must not touch its identity.
    asset = tmp_path / "DisableDurability_Steam.asset"
    asset.write_text(ASSET)
    meta = asset.with_suffix(".asset.meta")
    meta.write_text("fileFormatVersion: 2\nguid: 0123456789abcdef0123456789abcdef\n")

    steam_identity.write_file_id(asset, 4242424242)

    assert "guid: 0123456789abcdef0123456789abcdef" in meta.read_text()


def test_creating_an_asset_beside_an_existing_meta_keeps_that_meta(tmp_path):
    # Asset deleted, meta left behind: its GUID is still the one Unity knows.
    asset = tmp_path / "NewMod_Steam.asset"
    meta = asset.with_suffix(".asset.meta")
    meta.write_text("fileFormatVersion: 2\nguid: 0123456789abcdef0123456789abcdef\n")

    steam_identity.write_file_id(asset, 7)

    assert "guid: 0123456789abcdef0123456789abcdef" in meta.read_text()


def test_creating_fills_every_field_the_sdk_window_reads(tmp_path):
    asset = tmp_path / "NewMod_Steam.asset"

    steam_identity.write_file_id(
        asset,
        99,
        mod_owner=10000000000000000,
        selected_path="/Users/x/Library/Caches/CoreKeeperMods/NewMod",
        tags=["Client", "Script", "Quality of Life"],
    )

    text = asset.read_text()
    assert "modOwner: 10000000000000000" in text
    assert "selectedPath: /Users/x/Library/Caches/CoreKeeperMods/NewMod" in text
    assert "tags:\n  - Client\n  - Script\n  - Quality of Life\n" in text


def test_updating_refreshes_those_fields_too(tmp_path):
    # The SDK window's own values go stale — the build path moved once already.
    # A publish knows the current ones, so it corrects them rather than leaving
    # the window pointed at a directory that no longer exists.
    asset = tmp_path / "DisableDurability_Steam.asset"
    asset.write_text(ASSET)

    steam_identity.write_file_id(
        asset,
        4242424242,
        mod_owner=10000000000000000,
        selected_path="/new/path/DisableDurability",
        tags=["Client"],
    )

    text = asset.read_text()
    assert "selectedPath: /new/path/DisableDurability" in text
    assert "tags:\n  - Client\n" in text
    assert "/var/folders" not in text
    assert "- Script" not in text  # the old list is replaced, not appended to
    assert "modName: Disable Durability" in text  # still not ours to touch


def test_omitted_fields_are_left_exactly_as_they_were(tmp_path):
    # A caller without a live Steam session cannot know modOwner; passing
    # nothing must not blank out what is already there.
    asset = tmp_path / "DisableDurability_Steam.asset"
    asset.write_text(ASSET)

    steam_identity.write_file_id(asset, 4242424242)

    text = asset.read_text()
    assert "modOwner: 10000000000000000" in text
    assert "selectedPath: /var/folders/x/T/BuiltMods/DisableDurability" in text
    assert "tags:\n  - Client\n  - Script\n" in text


def test_an_empty_tag_list_is_written_as_the_sdk_writes_it(tmp_path):
    asset = tmp_path / "NewMod_Steam.asset"

    steam_identity.write_file_id(asset, 99, tags=[])

    assert "tags: []" in asset.read_text()


def test_writing_refuses_an_existing_file_it_does_not_recognize(tmp_path):
    asset = tmp_path / "Unrecognized_Steam.asset"
    original = "this is not a Steam asset at all\n"
    asset.write_text(original)

    with pytest.raises(ValueError, match="fileId"):
        steam_identity.write_file_id(asset, 99)

    # The whole point of the guard: an unrecognized file must be left exactly
    # as it was, never silently replaced by a fresh template.
    assert asset.read_text() == original


def test_a_permission_error_is_not_read_as_no_id(tmp_path):
    # Only a MISSING file may read as "no id". An existing file that cannot be
    # read for some other reason is a real problem with an asset that DOES
    # exist, and folding it into "no id" would make a publish create a second
    # Workshop item over one whose id merely could not be read.
    asset = tmp_path / "DisableDurability_Steam.asset"
    asset.write_text(ASSET)
    asset.chmod(0)

    try:
        with pytest.raises(PermissionError):
            steam_identity.read_file_id(asset)
    finally:
        asset.chmod(0o644)  # so tmp_path cleanup can remove it


def test_ensure_recognizable_accepts_a_missing_asset(tmp_path):
    # A mod's first publish: nothing to recognize yet, nothing to reject.
    steam_identity.ensure_recognizable(tmp_path / "absent.asset")


def test_ensure_recognizable_accepts_a_valid_asset(tmp_path):
    asset = tmp_path / "DisableDurability_Steam.asset"
    asset.write_text(ASSET)

    steam_identity.ensure_recognizable(asset)


def test_ensure_recognizable_rejects_what_write_file_id_would_refuse(tmp_path):
    # The whole point: this must raise on the SAME files write_file_id
    # refuses, and it must do so before any Steam call, not after.
    asset = tmp_path / "Unrecognized_Steam.asset"
    asset.write_text("this is not a Steam asset at all\n")

    with pytest.raises(ValueError, match="fileId"):
        steam_identity.ensure_recognizable(asset)


def test_the_asset_path_is_where_a_mod_repo_keeps_it(tmp_path):
    assert (
        steam_identity.asset_path(tmp_path, "DisableDurability")
        == tmp_path / "unity" / "DisableDurability" / "DisableDurability_Steam.asset"
    )


# --- is the id durable, or one `git clean` from gone? ---------------------

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


@pytest.fixture
def repo(tmp_path):
    """A real git repo with the asset in it — untracked until `add` is called.

    Against the real binary rather than a mock: what is being checked here is
    an exit code contract with git itself (0 tracked / 1 untracked / 128 not a
    repo), and a mock would only assert that this file's own assumptions match
    themselves.
    """
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    asset = steam_identity.asset_path(tmp_path, "DisableDurability")
    asset.parent.mkdir(parents=True)
    asset.write_text(ASSET)
    return asset


@needs_git
def test_a_committed_asset_is_seen_as_tracked(repo):
    subprocess.run(["git", "-C", str(repo.parent), "add", repo.name], check=True)

    assert steam_identity.is_tracked(repo) is True


@needs_git
def test_an_untracked_asset_is_seen_as_untracked(repo):
    assert steam_identity.is_tracked(repo) is False


def test_outside_a_repo_the_question_has_no_answer(tmp_path):
    # Not False: "git cannot tell us" and "git says no" must not collapse into
    # one, or an unusual setup would be reported as a hazard it is not in.
    asset = tmp_path / "Loose_Steam.asset"
    asset.write_text(ASSET)

    assert steam_identity.is_tracked(asset) is None


@needs_git
def test_without_git_the_question_has_no_answer(repo, monkeypatch):
    # Deliberately an asset that IS in a repo and IS untracked, so a real
    # answer of False is available — and must still come back as None once the
    # binary is gone. In a non-repo directory both paths return None and the
    # test could not tell them apart.
    monkeypatch.setattr(steam_identity.shutil, "which", lambda _: None)

    assert steam_identity.is_tracked(repo) is None


@needs_git
def test_an_inherited_GIT_DIR_does_not_answer_for_another_repo(
    repo, tmp_path, monkeypatch
):
    # GIT_DIR and GIT_INDEX_FILE outrank -C. Inherited from whatever invoked
    # the publish, they would have git answer about a different repository —
    # and the answer that costs something is the false "tracked", which would
    # withhold the warning on the one asset that needs it. Same defence
    # check_docs_wrapping.markdown_files already documents.
    subprocess.run(["git", "-C", str(repo.parent), "add", repo.name], check=True)
    decoy = tmp_path / "decoy"
    subprocess.run(["git", "init", "-q", str(decoy)], check=True)
    monkeypatch.setenv("GIT_DIR", str(decoy / ".git"))
    monkeypatch.setenv("GIT_INDEX_FILE", str(decoy / ".git" / "index"))

    assert steam_identity.is_tracked(repo) is True


@needs_git
def test_ensure_recognizable_warns_about_an_untracked_asset(repo, capsys):
    steam_identity.ensure_recognizable(repo)

    err = capsys.readouterr().err
    assert "not tracked by git" in err
    # The message has to carry the fix, not just the diagnosis: this is read
    # in the middle of a publish, by someone who is not thinking about git.
    assert f"git add {repo}" in err


@needs_git
def test_ensure_recognizable_stays_quiet_about_a_tracked_asset(repo, capsys):
    subprocess.run(["git", "-C", str(repo.parent), "add", repo.name], check=True)

    steam_identity.ensure_recognizable(repo)

    assert capsys.readouterr().err == ""


def test_ensure_recognizable_stays_quiet_when_git_cannot_answer(tmp_path, capsys):
    asset = tmp_path / "Loose_Steam.asset"
    asset.write_text(ASSET)

    steam_identity.ensure_recognizable(asset)

    assert capsys.readouterr().err == ""


def test_ensure_recognizable_says_nothing_about_an_asset_that_does_not_exist(
    tmp_path, capsys
):
    # A mod's first publish. There is no file to track yet, so a warning here
    # would be advice about something that does not exist.
    steam_identity.ensure_recognizable(tmp_path / "absent.asset")

    assert capsys.readouterr().err == ""


@needs_git
def test_a_bad_asset_is_refused_before_it_is_judged_on_tracking(repo, capsys):
    # Order matters: an asset that will not hold an id at all is the bigger
    # problem, and burying that raise under a git note would read as advice.
    repo.write_text("this is not a Steam asset at all\n")

    with pytest.raises(ValueError, match="fileId"):
        steam_identity.ensure_recognizable(repo)

    assert capsys.readouterr().err == ""
