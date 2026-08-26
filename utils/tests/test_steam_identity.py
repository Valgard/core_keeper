"""Unit tests for reading and writing the Workshop file id.

The asset is the SDK's own <Mod>_Steam.asset, and we address it by path rather
than by the modName field inside it. That field is written from the display
title and looked up by metadata.name, so it goes stale the moment a readable
title is used (CoreKeeperModSDK#11) — reading it would inherit the defect.
"""

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
