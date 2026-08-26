"""Unit tests for reading and writing the Workshop file id.

The asset is the SDK's own <Mod>_Steam.asset, and we address it by path rather
than by the modName field inside it. That field is written from the display
title and looked up by metadata.name, so it goes stale the moment a readable
title is used (CoreKeeperModSDK#11) — reading it would inherit the defect.
"""

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

    assert steam_identity.read_file_id(asset) == 99
    assert asset.read_text().startswith("%YAML 1.1")
