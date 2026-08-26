"""Unit tests for assembling a Steam publish from sources that already exist.

Every value here has exactly one home in the repository, and the point of the
bundle is that none of them is retyped: a title that differs from mod.io, a tag
set that drifts, a changelog that says something else — each is a defect this
module exists to make impossible.
"""

import pytest
import steam_bundle

ASSET = """MonoBehaviour:
  metadata:
    name: DisableDurability
    displayName: Disable Durability
    skipSafetyChecks: 0
    requiredOn: 3
    dependencies: []
  modPath: Assets/DisableDurability
"""

CHANGELOG = """# Changelog

Some preamble that is not an entry.

## [1.1.1] - 2026-08-08

### Added

- A thing.
- Another thing.

## [1.1.0] - 2026-07-01

### Added

- Older, must not be picked.
"""


def _repo(tmp_path, asset=ASSET, changelog=CHANGELOG, description="[b]Bold[/b]"):
    (tmp_path / "unity").mkdir()
    (tmp_path / "unity" / "DisableDurability.asset").write_text(asset)
    (tmp_path / "CHANGELOG.md").write_text(changelog)
    if description is not None:
        (tmp_path / "steam-description.txt").write_text(description)
    logo_dir = tmp_path / "unity" / "DisableDurability" / "Editor"
    logo_dir.mkdir(parents=True)
    from PIL import Image

    Image.new("RGBA", (256, 256), (10, 80, 90, 255)).save(logo_dir / "logo.png")
    return tmp_path


def _env(tmp_path, **overrides):
    content = tmp_path / "build" / "DisableDurability"
    content.mkdir(parents=True, exist_ok=True)
    env = {
        "MOD_NAME": "DisableDurability",
        "CK_MODIO_TYPE": "Item|Overhaul|Quality of Life",
        "MOD_INSTALL_PATH": str(tmp_path / "build"),
    }
    env.update(overrides)
    return env


def test_the_topmost_changelog_entry_is_the_version():
    version, body = steam_bundle.parse_changelog(CHANGELOG)

    assert version == "1.1.1"
    assert "A thing." in body
    assert "Older, must not be picked." not in body


def test_the_title_is_the_display_name_not_the_internal_name(tmp_path):
    bundle = steam_bundle.build_bundle(
        _repo(tmp_path), _env(tmp_path), tmp_path / "p.png"
    )

    assert bundle["title"] == "Disable Durability"


def test_the_title_falls_back_to_the_internal_name(tmp_path):
    repo = _repo(
        tmp_path, asset=ASSET.replace("    displayName: Disable Durability\n", "")
    )

    bundle = steam_bundle.build_bundle(repo, _env(tmp_path), tmp_path / "p.png")

    assert bundle["title"] == "DisableDurability"


def test_tags_combine_all_three_groups(tmp_path):
    bundle = steam_bundle.build_bundle(
        _repo(tmp_path), _env(tmp_path), tmp_path / "p.png"
    )

    assert set(bundle["tags"]) == {
        "Item",
        "Overhaul",
        "Quality of Life",
        "Client",
        "Server",
        "Script",
    }


def test_requiredOn_1_is_client_only():
    tags = steam_bundle.derive_tags({"requiredOn": 1, "skipSafetyChecks": 0}, "Visual")

    assert "Client" in tags and "Server" not in tags


def test_requiredOn_0_produces_no_application_type_tag():
    tags = steam_bundle.derive_tags({"requiredOn": 0, "skipSafetyChecks": 0}, "Visual")

    assert "Client" not in tags and "Server" not in tags


def test_elevated_access_changes_the_access_tag():
    tags = steam_bundle.derive_tags({"requiredOn": 1, "skipSafetyChecks": 1}, "Library")

    assert "Script (Elevated Access)" in tags and "Script" not in tags


def test_a_new_mod_gets_hidden_visibility_and_no_file_id(tmp_path):
    bundle = steam_bundle.build_bundle(
        _repo(tmp_path), _env(tmp_path), tmp_path / "p.png"
    )

    assert bundle["fileId"] == 0
    assert bundle["visibility"] == "hidden"


def test_an_existing_mod_keeps_its_visibility(tmp_path):
    repo = _repo(tmp_path)
    asset = repo / "unity" / "DisableDurability" / "DisableDurability_Steam.asset"
    import steam_identity

    steam_identity.write_file_id(asset, 3790345467)

    bundle = steam_bundle.build_bundle(repo, _env(tmp_path), tmp_path / "p.png")

    assert bundle["fileId"] == 3790345467
    assert bundle["visibility"] == "unchanged"


def test_a_missing_description_is_reported_by_name(tmp_path):
    repo = _repo(tmp_path, description=None)

    with pytest.raises(ValueError, match="steam-description.txt"):
        steam_bundle.build_bundle(repo, _env(tmp_path), tmp_path / "p.png")


def test_a_missing_content_folder_is_reported(tmp_path):
    repo = _repo(tmp_path)
    env = _env(tmp_path, MOD_INSTALL_PATH=str(tmp_path / "nowhere"))

    with pytest.raises(ValueError, match="build|content|nowhere"):
        steam_bundle.build_bundle(repo, env, tmp_path / "p.png")


def test_dependencies_come_from_the_asset_not_hardcoded_empty():
    # The interface promises "list[tuple[str, bool]]" — a fixture whose asset
    # always declares zero dependencies (as ASSET does above) cannot tell an
    # implementation that reads metadata.dependencies apart from one that just
    # returns []. disable-durability itself already depends on CoreLib and
    # ModSettingsMenu, so this is not a hypothetical case.
    asset = ASSET.replace(
        "    dependencies: []\n",
        "    dependencies:\n    - modName: CoreLib\n      required: 1\n    - modName: ModSettingsMenu\n      required: 0\n",
    )

    assert steam_bundle.parse_dependencies(asset) == [
        ("CoreLib", True),
        ("ModSettingsMenu", False),
    ]


def test_a_declared_dependency_is_resolved_from_the_cache(tmp_path):
    repo = _repo(
        tmp_path,
        asset=ASSET.replace(
            "    dependencies: []",
            "    dependencies:\n    - modName: CoreLib\n      required: 1",
        ),
    )
    cache = tmp_path / "deps.json"
    cache.write_text('{"CoreLib": 3000000001}')
    env = _env(tmp_path, STEAM_DEPS_MAP=str(cache))

    bundle = steam_bundle.build_bundle(repo, env, tmp_path / "p.png")

    assert bundle["dependencies"] == [
        {"name": "CoreLib", "fileId": 3000000001, "required": True}
    ]


def test_an_unresolvable_required_dependency_aborts(tmp_path):
    repo = _repo(
        tmp_path,
        asset=ASSET.replace(
            "    dependencies: []",
            "    dependencies:\n    - modName: CoreLib\n      required: 1",
        ),
    )
    cache = tmp_path / "deps.json"
    cache.write_text("{}")
    env = _env(tmp_path, STEAM_DEPS_MAP=str(cache))

    with pytest.raises(ValueError, match="CoreLib"):
        steam_bundle.build_bundle(repo, env, tmp_path / "p.png")


def test_an_unresolvable_optional_dependency_is_skipped(tmp_path):
    repo = _repo(
        tmp_path,
        asset=ASSET.replace(
            "    dependencies: []",
            "    dependencies:\n    - modName: SomeOptional\n      required: 0",
        ),
    )
    cache = tmp_path / "deps.json"
    cache.write_text("{}")
    env = _env(tmp_path, STEAM_DEPS_MAP=str(cache))

    bundle = steam_bundle.build_bundle(repo, env, tmp_path / "p.png")

    assert bundle["dependencies"] == []


def test_declared_dependencies_are_parsed_with_their_required_flag():
    deps = steam_bundle.parse_dependencies(
        "    dependencies:\n    - modName: CoreLib\n      required: 1\n"
        "    - modName: Other\n      required: 0\n  modPath: x\n"
    )

    assert deps == [("CoreLib", True), ("Other", False)]
