"""Unit tests for new_mod.py — the deterministic new-mod scaffold generator."""

import json
import re as _re

import pytest

import new_mod as nm


# --- identity derivation (the three-level naming convention) ----------------


def test_derive_pascal_joins_capitalized_segments():
    assert nm.derive_pascal("faster-pet-talents") == "FasterPetTalents"


def test_derive_pascal_single_segment():
    assert nm.derive_pascal("itemchecklist") == "Itemchecklist"


def test_derive_pascal_keeps_digits():
    assert (
        nm.derive_pascal("simple-crafting-pool-extender")
        == "SimpleCraftingPoolExtender"
    )


def test_derive_title_spaces_capitalized_segments():
    assert nm.derive_title("faster-pet-talents") == "Faster Pet Talents"


def test_validate_kebab_accepts_lowercase_hyphenated():
    nm.validate_kebab("faster-pet-talents")  # must not raise


@pytest.mark.parametrize(
    "bad",
    [
        "",  # empty
        "Faster-Pet",  # uppercase
        "-leading",  # leading hyphen
        "trailing-",  # trailing hyphen
        "double--hyphen",  # empty segment
        "has_underscore",  # underscore not allowed
        "has space",  # space not allowed
    ],
)
def test_validate_kebab_rejects_malformed(bad):
    with pytest.raises(ValueError):
        nm.validate_kebab(bad)


# --- GUIDs ------------------------------------------------------------------


def test_new_guid_is_32_lowercase_hex():
    import re

    assert re.fullmatch(r"[0-9a-f]{32}", nm.new_guid())


def test_new_guid_is_unique_per_call():
    assert nm.new_guid() != nm.new_guid()


# --- FAKE_MOD_ID allocation -------------------------------------------------


def test_next_fake_mod_id_is_one_below_minimum_existing():
    # existing IDs count downward from 9999999; the next free is min - 1
    assert nm.next_fake_mod_id([9999999, 9999994, 9999993]) == 9999992


def test_next_fake_mod_id_defaults_when_none_found():
    assert nm.next_fake_mod_id([]) == 9999999


# --- asmdef builders --------------------------------------------------------


def test_runtime_asmdef_is_valid_json_named_after_mod():
    data = json.loads(nm.build_runtime_asmdef("FasterPetTalents", ["0Harmony.dll"]))
    assert data["name"] == "FasterPetTalents"


def test_runtime_asmdef_includes_the_unity_references():
    data = json.loads(nm.build_runtime_asmdef("Mod", []))
    for ref in ("Unity.Burst", "Unity.Entities", "Unity.NetCode", "PugMod.SDK"):
        assert ref in data["references"]


def test_runtime_asmdef_precompiled_refs_are_the_scanned_dlls():
    dlls = ["Pug.Other.dll", "0Harmony.dll"]
    data = json.loads(nm.build_runtime_asmdef("Mod", dlls))
    assert data["precompiledReferences"] == dlls


def test_runtime_asmdef_overrides_refs_and_is_not_autoreferenced():
    data = json.loads(nm.build_runtime_asmdef("Mod", []))
    assert data["overrideReferences"] is True
    assert data["autoReferenced"] is False


def test_editor_asmdef_references_runtime_modsdk_and_pugmod():
    data = json.loads(nm.build_editor_asmdef("FasterPetTalents"))
    assert data["name"] == "FasterPetTalents.Editor"
    assert data["references"] == ["FasterPetTalents", "ModSDK.Editor", "PugMod.SDK"]
    assert data["includePlatforms"] == ["Editor"]
    assert "modio.UnityPlugin.dll" in data["precompiledReferences"]


# --- ModBuilderSettings .asset YAML (GUID-rule core) ------------------------


def test_asset_binds_verbatim_sdk_script_guid():
    y = nm.build_asset_yaml("Mod", "Mod", metadata_guid="a" * 32)
    assert (
        "m_Script: {fileID: 11500000, guid: bc43e4983a160e543856e5ba0421c9e1, type: 3}"
        in y
    )


def test_asset_carries_identity_and_fresh_metadata_guid():
    y = nm.build_asset_yaml(
        "FasterPetTalents", "Faster Pet Talents", metadata_guid="d" * 32
    )
    assert "m_Name: FasterPetTalents" in y
    assert "name: FasterPetTalents" in y
    assert "displayName: Faster Pet Talents" in y
    assert "guid: " + "d" * 32 in y
    assert "requiredOn: 3" in y
    assert "modPath: Assets/FasterPetTalents" in y


def test_asset_dependencies_empty_by_default():
    y = nm.build_asset_yaml("Mod", "Mod", metadata_guid="a" * 32)
    assert "dependencies: []" in y


def test_asset_dependencies_render_corelib_when_requested():
    y = nm.build_asset_yaml(
        "Mod", "Mod", metadata_guid="a" * 32, dependencies=[("CoreLib", 1)]
    )
    assert "dependencies: []" not in y
    assert "- modName: CoreLib" in y
    assert "required: 1" in y


# --- _modio.asset YAML (internal cross-reference) ---------------------------


def test_modio_asset_binds_verbatim_sdk_script_guid():
    y = nm.build_modio_asset_yaml("Mod", modsettings_guid="b" * 32)
    assert (
        "m_Script: {fileID: 11500000, guid: d83df2ae64ce1e94f9c006b9d326bf02, type: 3}"
        in y
    )


def test_modio_asset_modid_zero_and_cross_refs_the_asset_meta():
    y = nm.build_modio_asset_yaml("FasterPetTalents", modsettings_guid="c" * 32)
    assert "m_Name: FasterPetTalents_modio" in y
    assert "modId: 0" in y
    assert "modSettings: {fileID: 11400000, guid: " + "c" * 32 + ", type: 2}" in y


# --- .meta builders ---------------------------------------------------------


def test_folder_meta_marks_folder_asset_with_guid():
    m = nm.build_folder_meta("e" * 32)
    assert "fileFormatVersion: 2" in m
    assert "guid: " + "e" * 32 in m
    assert "folderAsset: yes" in m
    assert "DefaultImporter" in m


def test_script_meta_is_minimal_guid_carrier():
    m = nm.build_script_meta("f" * 32)
    assert "fileFormatVersion: 2" in m
    assert "guid: " + "f" * 32 in m
    # minimal form: no importer block (Unity regenerates it on import)
    assert "Importer" not in m


def test_native_asset_meta_points_at_main_object():
    m = nm.build_native_asset_meta("1" * 32)
    assert "guid: " + "1" * 32 in m
    assert "NativeFormatImporter" in m
    assert "mainObjectFileID: 11400000" in m


def test_asmdef_meta_uses_assembly_definition_importer():
    m = nm.build_asmdef_meta("2" * 32)
    assert "guid: " + "2" * 32 in m
    assert "AssemblyDefinitionImporter" in m


def test_texture_meta_carries_texture_importer():
    m = nm.build_texture_meta("3" * 32)
    assert "guid: " + "3" * 32 in m
    assert "TextureImporter" in m


# --- parametric text files --------------------------------------------------


def test_bootstrap_cs_declares_imod_in_mod_namespace():
    cs = nm.build_bootstrap_cs("FasterPetTalents")
    assert "namespace FasterPetTalents" in cs
    assert "class FasterPetTalentsMod : IMod" in cs
    for method in ("EarlyInit", "Init", "ModObjectLoaded", "Shutdown", "Update"):
        assert method in cs


def test_envrc_sets_identity_and_inherits_parent():
    env = nm.build_envrc(
        "FasterPetTalents",
        "faster-pet-talents",
        summary="Does a thing.",
        fake_mod_id=9999992,
    )
    assert 'MOD_NAME="FasterPetTalents"' in env
    assert 'MOD_NAME_ID="faster-pet-talents"' in env
    assert 'MOD_SUMMARY="Does a thing."' in env
    assert 'FAKE_MOD_ID="9999992"' in env
    assert "source_up_if_exists" in env  # inherits SDK_PATH etc. from parent


def test_gitignore_ignores_envrc_and_editor_helpers_by_mod_name():
    gi = nm.build_gitignore("FasterPetTalents")
    assert ".envrc" in gi
    assert "unity/FasterPetTalents/Editor/CLIBuildHelper.cs" in gi
    assert "unity/FasterPetTalents/Editor/LocalizationGenerator.cs.meta" in gi


def test_changelog_starts_at_0_1_0():
    cl = nm.build_changelog()
    assert "## [0.1.0]" in cl


# --- formatting-gate files ---------------------------------------------------


def test_csharpierrc_pins_print_width_160():
    data = json.loads(nm.build_csharpierrc())
    assert data == {"printWidth": 160}


def test_csharpierignore_exists_and_stops_the_upward_search():
    # Not cosmetic: CSharpier's ignore-file search walks past the git boundary
    # into core_keeper/, whose .csharpierignore is an allowlist for utils/ only.
    # Measured in a git repo holding one misformatted source: `csharpier check`
    # reports "Checked 0 files" without a local ignore file and "Checked 1
    # files" with one. So a scaffolded mod without this ships a gate that
    # passes while checking nothing.
    text = nm.build_csharpierignore()
    assert ".worktrees/" in text
    # The comment has to say why the file is required, or the next person
    # deletes it as a stray worktree rule.
    assert "zero files" in text


def test_precommit_config_runs_csharpier_check_at_both_stages():
    cfg = nm.build_precommit_config()
    assert "entry: dotnet csharpier check" in cfg
    assert "- pre-commit" in cfg
    assert "- pre-push" in cfg


def test_dotnet_tools_json_pins_csharpier():
    data = json.loads(nm.build_dotnet_tools_json())
    assert data["isRoot"] is True
    assert data["tools"]["csharpier"]["version"] == "1.3.0"
    assert data["tools"]["csharpier"]["commands"] == ["csharpier"]


# --- placeholder PNG --------------------------------------------------------


def test_placeholder_png_has_signature_and_chunks():
    png = nm.placeholder_png_bytes()
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert b"IHDR" in png
    assert b"IEND" in png


# --- live DLL scan ----------------------------------------------------------


def _make_sdk(tmp_path, layout):
    for rel in layout:
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"")
    return tmp_path


def test_scan_dlls_returns_sorted_basenames_from_both_plugin_dirs(tmp_path):
    _make_sdk(
        tmp_path,
        [
            "Assets/Plugins/CoreKeeper/Pug.Other.dll",
            "Assets/Plugins/CoreKeeper/sub/Affixes.dll",
            "Assets/Plugins/CoreKeeperModSDK/0Harmony.dll",
            "Assets/Plugins/CoreKeeper/notes.txt",  # non-dll ignored
        ],
    )
    assert nm.scan_dlls(tmp_path) == ["0Harmony.dll", "Affixes.dll", "Pug.Other.dll"]


def test_scan_dlls_ignores_dlls_outside_the_two_plugin_dirs(tmp_path):
    _make_sdk(
        tmp_path,
        [
            "Assets/Plugins/CoreKeeper/keep.dll",
            "Assets/Plugins/Other/skip.dll",
            "Assets/elsewhere/skip2.dll",
        ],
    )
    assert nm.scan_dlls(tmp_path) == ["keep.dll"]


def test_scan_dlls_dedups_same_basename(tmp_path):
    _make_sdk(
        tmp_path,
        [
            "Assets/Plugins/CoreKeeper/dup.dll",
            "Assets/Plugins/CoreKeeper/nested/dup.dll",
        ],
    )
    assert nm.scan_dlls(tmp_path) == ["dup.dll"]


# --- the full file plan -----------------------------------------------------


def _plan_dict(**kw):
    kw.setdefault("summary", "x")
    kw.setdefault("dll_names", ["0Harmony.dll"])
    kw.setdefault("fake_mod_id", 9999992)
    return dict(nm.build_plan("faster-pet-talents", **kw))


def test_plan_contains_the_expected_file_set():
    paths = set(_plan_dict().keys())
    assert paths == {
        ".envrc",
        ".envrc.example",
        ".gitignore",
        "CHANGELOG.md",
        ".csharpierrc",
        ".csharpierignore",
        ".pre-commit-config.yaml",
        ".config/dotnet-tools.json",
        "unity/FasterPetTalents.asset",
        "unity/FasterPetTalents.asset.meta",
        "unity/FasterPetTalents.meta",
        "unity/FasterPetTalents/FasterPetTalents.asmdef",
        "unity/FasterPetTalents/FasterPetTalents.asmdef.meta",
        "unity/FasterPetTalents/FasterPetTalentsMod.cs",
        "unity/FasterPetTalents/FasterPetTalentsMod.cs.meta",
        "unity/FasterPetTalents/Editor.meta",
        "unity/FasterPetTalents/Editor/FasterPetTalents.Editor.asmdef",
        "unity/FasterPetTalents/Editor/FasterPetTalents.Editor.asmdef.meta",
        "unity/FasterPetTalents/Editor/FasterPetTalents_modio.asset",
        "unity/FasterPetTalents/Editor/FasterPetTalents_modio.asset.meta",
        "unity/FasterPetTalents/Editor/logo.png",
        "unity/FasterPetTalents/Editor/logo.png.meta",
    }


def _guid(text):
    return _re.search(r"guid: ([0-9a-f]{32})", text).group(1)


def test_plan_modio_cross_references_the_asset_meta_guid():
    plan = _plan_dict()
    asset_meta_guid = _guid(plan["unity/FasterPetTalents.asset.meta"])
    modio = plan["unity/FasterPetTalents/Editor/FasterPetTalents_modio.asset"]
    ref = _re.search(
        r"modSettings: \{fileID: 11400000, guid: ([0-9a-f]{32})", modio
    ).group(1)
    assert ref == asset_meta_guid


def test_plan_all_meta_guids_are_unique():
    plan = _plan_dict()
    meta_guids = [_guid(c) for p, c in plan.items() if p.endswith(".meta")]
    assert len(meta_guids) == len(set(meta_guids))


def test_plan_asset_metadata_guid_differs_from_asset_file_guid():
    # the internal metadata.guid must not equal the .asset.meta file guid
    plan = _plan_dict()
    asset = plan["unity/FasterPetTalents.asset"]
    metadata_guid = _re.search(r"metadata:\n    guid: ([0-9a-f]{32})", asset).group(1)
    asset_meta_guid = _guid(plan["unity/FasterPetTalents.asset.meta"])
    assert metadata_guid != asset_meta_guid


def test_plan_corelib_flag_adds_dependency():
    plan = _plan_dict(corelib=True)
    assert "- modName: CoreLib" in plan["unity/FasterPetTalents.asset"]


def test_plan_name_override_changes_pascal_identity():
    plan = dict(
        nm.build_plan(
            "corelib", summary="x", dll_names=[], fake_mod_id=1, name="CoreLib"
        )
    )
    assert "unity/CoreLib.asset" in plan


def test_write_plan_writes_text_and_binary(tmp_path):
    plan = nm.build_plan("faster-pet-talents", summary="x", dll_names=[], fake_mod_id=1)
    nm.write_plan(plan, tmp_path)
    assert (tmp_path / ".envrc").is_file()
    logo = (tmp_path / "unity/FasterPetTalents/Editor/logo.png").read_bytes()
    assert logo[:8] == b"\x89PNG\r\n\x1a\n"


# --- fs-facing orchestration helpers ----------------------------------------


def test_scan_existing_fake_mod_ids_reads_sibling_envrc_examples(tmp_path):
    (tmp_path / "mod-a").mkdir()
    (tmp_path / "mod-a/.envrc.example").write_text('export FAKE_MOD_ID="9999994"\n')
    (tmp_path / "mod-b").mkdir()
    (tmp_path / "mod-b/.envrc.example").write_text('export FAKE_MOD_ID="9999993"\n')
    assert sorted(nm.scan_existing_fake_mod_ids(tmp_path)) == [9999993, 9999994]


def test_resolve_sdk_path_prefers_environment(tmp_path):
    assert nm.resolve_sdk_path(tmp_path, {"SDK_PATH": "/x/sdk"}) == "/x/sdk"


def test_resolve_sdk_path_falls_back_to_parent_envrc(tmp_path):
    (tmp_path / ".envrc").write_text('export SDK_PATH="/from/envrc"\n')
    assert nm.resolve_sdk_path(tmp_path, {}) == "/from/envrc"


# --- scaffold (top-level orchestration) -------------------------------------


def test_scaffold_dry_run_writes_nothing(tmp_path):
    result = nm.scaffold(
        "faster-pet-talents",
        summary="x",
        mods_dir=tmp_path,
        sdk_path=tmp_path,
        dry_run=True,
    )
    assert not (tmp_path / "faster-pet-talents").exists()
    assert result["mod_name"] == "FasterPetTalents"
    assert result["target"].name == "faster-pet-talents"


def test_scaffold_aborts_if_target_exists(tmp_path):
    (tmp_path / "faster-pet-talents").mkdir()
    with pytest.raises(FileExistsError):
        nm.scaffold(
            "faster-pet-talents",
            summary="x",
            mods_dir=tmp_path,
            sdk_path=tmp_path,
            dry_run=True,
        )


def test_scaffold_writes_tree_without_finalize(tmp_path):
    nm.scaffold(
        "faster-pet-talents",
        summary="x",
        mods_dir=tmp_path,
        sdk_path=tmp_path,
        finalize=False,
    )
    root = tmp_path / "faster-pet-talents"
    assert (root / "unity/FasterPetTalents.asset").is_file()
    assert (root / "unity/FasterPetTalents/FasterPetTalentsMod.cs").is_file()


# --- CLI argument parsing ---------------------------------------------------


def test_parse_args_requires_summary():
    with pytest.raises(SystemExit):
        nm.parse_args(["faster-pet-talents"])


def test_parse_args_defaults_and_flags():
    ns = nm.parse_args(["faster-pet-talents", "--summary", "Does X", "--corelib"])
    assert ns.kebab == "faster-pet-talents"
    assert ns.summary == "Does X"
    assert ns.corelib is True
    assert ns.dry_run is False
