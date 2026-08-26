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


def test_an_empty_field_reads_as_absent_not_as_the_next_line():
    # A key with no value must not swallow the newline and capture whatever
    # follows. displayName is the one that matters most: the SDK's settings GUI
    # cannot set it, so empty is the normal state of a freshly created mod —
    # and build_bundle uses it as the Workshop item's TITLE. Reading the line
    # below would publish an item titled "skipSafetyChecks: 0".
    asset = (
        "MonoBehaviour:\n"
        "  metadata:\n"
        "    name: NewMod\n"
        "    displayName: \n"
        "    skipSafetyChecks: 0\n"
        "    requiredOn: 3\n"
    )

    metadata = steam_bundle._read_metadata(asset)

    assert "displayName" not in metadata
    assert metadata["name"] == "NewMod"
    assert metadata["skipSafetyChecks"] == 0
    assert metadata["requiredOn"] == 3


def test_requiredOn_is_read_bitwise_not_looked_up():
    # The SDK's own settings GUI writes -1 ("Everything") when "Client and
    # Server" is picked, and the mod.io side reads the field bitwise, so it
    # tags both. Anything that maps whole values instead drops the tags for
    # that one input — and Steam discards a missing tag without a word.
    tags = steam_bundle.derive_tags({"requiredOn": -1, "skipSafetyChecks": 0}, "Visual")

    assert "Client" in tags and "Server" in tags


def test_an_unknown_application_type_warns_instead_of_going_out_silently(capsys):
    # 0 is legitimate — a mod that gates nothing — but it is also what an unset
    # field reads as, and only the author can tell the two apart. mod.io says so
    # on its own path; saying it on one platform only is how they diverge.
    steam_bundle.derive_tags({"requiredOn": 0, "skipSafetyChecks": 0}, "Visual")

    err = capsys.readouterr().err
    assert "Application Type" in err and "requiredOn" in err


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


def test_check_prerequisites_passes_without_a_built_content_folder(tmp_path):
    # The whole point: this must be callable BEFORE the mod.io build runs,
    # when MOD_INSTALL_PATH/<mod> does not exist yet.
    repo = _repo(tmp_path)
    env = {"MOD_NAME": "DisableDurability", "CK_MODIO_TYPE": "Item"}

    steam_bundle.check_prerequisites(repo, env)


def test_check_prerequisites_reports_a_missing_description_by_name(tmp_path):
    repo = _repo(tmp_path, description=None)
    env = {"MOD_NAME": "DisableDurability", "CK_MODIO_TYPE": "Item"}

    with pytest.raises(ValueError, match="steam-description.txt"):
        steam_bundle.check_prerequisites(repo, env)


def test_check_prerequisites_reports_an_unrecognized_identity_asset(tmp_path):
    repo = _repo(tmp_path)
    identity = repo / "unity" / "DisableDurability" / "DisableDurability_Steam.asset"
    identity.write_text("this is not a Steam asset at all\n")
    env = {"MOD_NAME": "DisableDurability", "CK_MODIO_TYPE": "Item"}

    with pytest.raises(ValueError, match="fileId"):
        steam_bundle.check_prerequisites(repo, env)


def test_check_prerequisites_reports_an_unresolvable_required_dependency(tmp_path):
    repo = _repo(
        tmp_path,
        asset=ASSET.replace(
            "    dependencies: []",
            "    dependencies:\n    - modName: CoreLib\n      required: 1",
        ),
    )
    env = {"MOD_NAME": "DisableDurability", "CK_MODIO_TYPE": "Item"}

    with pytest.raises(ValueError, match="CoreLib"):
        steam_bundle.check_prerequisites(repo, env)


def test_build_bundle_calls_check_prerequisites_first(tmp_path):
    # A missing description must surface even though the content folder is
    # ALSO missing (build_bundle checks that one itself) — check_prerequisites
    # runs first, so its error is the one that surfaces.
    repo = _repo(tmp_path, description=None)
    env = _env(tmp_path, MOD_INSTALL_PATH=str(tmp_path / "nowhere"))

    with pytest.raises(ValueError, match="steam-description.txt"):
        steam_bundle.build_bundle(repo, env, tmp_path / "p.png")


def test_an_unrecognized_identity_asset_aborts_before_any_upload(tmp_path):
    # Task 5's guard, called from here: an existing _Steam.asset without a
    # 'fileId:' line must be caught before the bundle is even assembled, not
    # discovered only after a Workshop item was already created from it.
    repo = _repo(tmp_path)
    identity = repo / "unity" / "DisableDurability" / "DisableDurability_Steam.asset"
    identity.parent.mkdir(parents=True, exist_ok=True)
    identity.write_text("this is not a Steam asset at all\n")

    with pytest.raises(ValueError, match="fileId"):
        steam_bundle.build_bundle(repo, _env(tmp_path), tmp_path / "p.png")


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


def test_an_unresolvable_required_dependency_with_no_cache_names_the_env_var(tmp_path):
    # Distinct from the case above: here STEAM_DEPS_MAP itself is unset, so
    # there is no cache_path to name. The message must say so instead of
    # rendering "None" as if it were a real, actionable file path.
    repo = _repo(
        tmp_path,
        asset=ASSET.replace(
            "    dependencies: []",
            "    dependencies:\n    - modName: CoreLib\n      required: 1",
        ),
    )
    env = _env(tmp_path)

    with pytest.raises(ValueError, match="STEAM_DEPS_MAP"):
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


def test_the_optional_skip_warning_goes_to_stderr_not_stdout(tmp_path, capsys):
    # Task 7 captures the caller's whole stdout as the JSON bundle for the .NET
    # tool. A warning line printed to stdout ahead of that JSON would corrupt
    # the capture and fail the entire publish over a merely-skipped dependency.
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

    steam_bundle.build_bundle(repo, env, tmp_path / "p.png")

    out, err = capsys.readouterr()
    assert out == ""
    assert "SomeOptional" in err


def test_a_malformed_dependency_cache_is_reported_by_name(tmp_path):
    repo = _repo(
        tmp_path,
        asset=ASSET.replace(
            "    dependencies: []",
            "    dependencies:\n    - modName: CoreLib\n      required: 1",
        ),
    )
    cache = tmp_path / "deps.json"
    cache.write_text("not json")
    env = _env(tmp_path, STEAM_DEPS_MAP=str(cache))

    with pytest.raises(ValueError, match=r"deps\.json"):
        steam_bundle.build_bundle(repo, env, tmp_path / "p.png")


def test_a_non_numeric_cached_id_is_reported_by_mod_and_file(tmp_path):
    repo = _repo(
        tmp_path,
        asset=ASSET.replace(
            "    dependencies: []",
            "    dependencies:\n    - modName: CoreLib\n      required: 1",
        ),
    )
    cache = tmp_path / "deps.json"
    cache.write_text('{"CoreLib": "not-a-number"}')
    env = _env(tmp_path, STEAM_DEPS_MAP=str(cache))

    with pytest.raises(ValueError, match=r"CoreLib") as excinfo:
        steam_bundle.build_bundle(repo, env, tmp_path / "p.png")
    assert "deps.json" in str(excinfo.value)


def test_declared_dependencies_are_parsed_with_their_required_flag():
    deps = steam_bundle.parse_dependencies(
        "    dependencies:\n    - modName: CoreLib\n      required: 1\n"
        "    - modName: Other\n      required: 0\n  modPath: x\n"
    )

    assert deps == [("CoreLib", True), ("Other", False)]
