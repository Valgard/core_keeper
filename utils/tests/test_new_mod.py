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


# --- mod.io Type tags -------------------------------------------------------


def test_parse_modio_type_splits_on_pipes_and_trims():
    assert nm.parse_modio_type("Visual| Quality of Life |Library") == [
        "Visual",
        "Quality of Life",
        "Library",
    ]


def test_parse_modio_type_keeps_inner_spaces():
    # The values themselves contain spaces — that is why the separator is a pipe
    # and not a comma.
    assert nm.parse_modio_type("Quality of Life") == ["Quality of Life"]


@pytest.mark.parametrize("bad", ["", "|", " | ", "  "])
def test_parse_modio_type_rejects_effectively_empty(bad):
    with pytest.raises(ValueError):
        nm.parse_modio_type(bad)


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


def test_runtime_asmdef_omits_corelib_unless_requested():
    data = json.loads(nm.build_runtime_asmdef("Mod", []))
    assert "CoreLib" not in data["references"]


def test_runtime_asmdef_references_corelib_when_requested():
    # The loader dependency in the .asset is not enough: without this assembly
    # reference the mod's own sources cannot compile against CoreLib types
    # (CS0246). Every CoreLib mod in the family carries both.
    data = json.loads(nm.build_runtime_asmdef("Mod", [], corelib=True))
    assert data["references"][-1] == "CoreLib"


def test_editor_asmdef_references_runtime_modsdk_and_pugmod():
    data = json.loads(nm.build_editor_asmdef("FasterPetTalents"))
    assert data["name"] == "FasterPetTalents.Editor"
    assert data["references"] == ["FasterPetTalents", "ModSDK.Editor", "PugMod.SDK"]
    assert data["includePlatforms"] == ["Editor"]
    assert "modio.UnityPlugin.dll" in data["precompiledReferences"]


# --- ModBuilderSettings .asset YAML (GUID-rule core) ------------------------


def test_asset_binds_verbatim_sdk_script_guid():
    y = nm.build_asset_yaml("Mod", "Mod", metadata_guid="a" * 32, required_on=3)
    assert (
        "m_Script: {fileID: 11500000, guid: bc43e4983a160e543856e5ba0421c9e1, type: 3}"
        in y
    )


def test_asset_carries_identity_and_fresh_metadata_guid():
    y = nm.build_asset_yaml(
        "FasterPetTalents",
        "Faster Pet Talents",
        metadata_guid="d" * 32,
        required_on=3,
    )
    assert "m_Name: FasterPetTalents" in y
    assert "name: FasterPetTalents" in y
    assert "displayName: Faster Pet Talents" in y
    assert "guid: " + "d" * 32 in y
    assert "requiredOn: 3" in y
    assert "modPath: Assets/FasterPetTalents" in y


def test_asset_dependencies_empty_by_default():
    y = nm.build_asset_yaml("Mod", "Mod", metadata_guid="a" * 32, required_on=3)
    assert "dependencies: []" in y


def test_asset_dependencies_render_corelib_when_requested():
    y = nm.build_asset_yaml(
        "Mod",
        "Mod",
        metadata_guid="a" * 32,
        dependencies=[("CoreLib", 1)],
        required_on=3,
    )
    assert "dependencies: []" not in y
    assert "- modName: CoreLib" in y
    assert "required: 1" in y


@pytest.mark.parametrize("value", [1, 2, 3])
def test_asset_writes_the_chosen_required_on(value):
    y = nm.build_asset_yaml("Mod", "Mod", metadata_guid="a" * 32, required_on=value)
    assert f"requiredOn: {value}" in y


def test_asset_refuses_to_guess_required_on():
    # No default on purpose. The old default of 3 shipped three mods that
    # needlessly blocked joining unmodded servers, and it also hid that
    # build_plan never passed the argument through at all.
    with pytest.raises(TypeError):
        nm.build_asset_yaml("Mod", "Mod", metadata_guid="a" * 32)


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


def _envrc(**kw):
    kw.setdefault("summary", "Does a thing.")
    kw.setdefault("fake_mod_id", 9999992)
    kw.setdefault("modio_type", "Visual|Quality of Life")
    return nm.build_envrc("FasterPetTalents", "faster-pet-talents", **kw)


def test_envrc_sets_identity_and_inherits_parent():
    env = _envrc()
    assert 'MOD_NAME="FasterPetTalents"' in env
    assert 'MOD_NAME_ID="faster-pet-talents"' in env
    assert 'MOD_SUMMARY="Does a thing."' in env
    assert 'FAKE_MOD_ID="9999992"' in env
    assert "source_up_if_exists" in env  # inherits SDK_PATH etc. from parent


def test_envrc_exports_the_modio_type_tags():
    # Without CK_MODIO_TYPE the publish aborts in CLIPublishHelper before it
    # uploads anything, so a scaffold that omits it builds but cannot ship.
    assert 'export CK_MODIO_TYPE="Visual|Quality of Life"' in _envrc()


def test_envrc_leaves_the_localisation_pair_commented_out():
    # Unset means "skip localisation". A set LOC_YAML pointing at a YAML with no
    # terms fails the build instead (LocalizationGenerator rejects 0 terms), so
    # the scaffold must not pre-arm these for a mod that has no text yet.
    env = _envrc()
    assert "# export LOC_YAML=" in env
    assert "# export LOC_OUT=" in env
    assert "\nexport LOC_YAML=" not in env
    assert "\nexport LOC_OUT=" not in env


def test_gitignore_ignores_envrc_and_editor_helpers_by_mod_name():
    gi = nm.build_gitignore("FasterPetTalents")
    assert ".envrc" in gi
    assert "unity/FasterPetTalents/Editor/CLIBuildHelper.cs" in gi
    assert "unity/FasterPetTalents/Editor/LocalizationGenerator.cs.meta" in gi


def test_gitignore_excludes_superpowers_process_artifacts():
    # Plans and brainstorming scratch are slop once implemented; docs/specs/ and
    # docs/adrs/ stay tracked, so the entry has to be the narrow one.
    gi = nm.build_gitignore("FasterPetTalents")
    assert "docs/superpowers/" in gi
    assert "\ndocs/\n" not in gi


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
    kw.setdefault("required_on", 1)
    kw.setdefault("modio_type", "Quality of Life")
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


def test_plan_corelib_flag_sets_both_wirings():
    # Loader dependency and compile-time assembly reference are separate; the
    # flag has to set both or the mod loads CoreLib but cannot compile against it.
    plan = _plan_dict(corelib=True)
    assert "- modName: CoreLib" in plan["unity/FasterPetTalents.asset"]
    asmdef = json.loads(plan["unity/FasterPetTalents/FasterPetTalents.asmdef"])
    assert "CoreLib" in asmdef["references"]


def test_plan_without_corelib_wires_neither():
    plan = _plan_dict()
    assert "dependencies: []" in plan["unity/FasterPetTalents.asset"]
    asmdef = json.loads(plan["unity/FasterPetTalents/FasterPetTalents.asmdef"])
    assert "CoreLib" not in asmdef["references"]


def test_plan_passes_required_on_and_modio_type_through():
    # Both used to stop here: required_on was accepted by build_asset_yaml but
    # never handed to it, and CK_MODIO_TYPE did not exist at all.
    plan = _plan_dict(required_on=2, modio_type="World|Library")
    assert "requiredOn: 2" in plan["unity/FasterPetTalents.asset"]
    assert 'export CK_MODIO_TYPE="World|Library"' in plan[".envrc.example"]


def test_plan_name_override_changes_pascal_identity():
    plan = dict(
        nm.build_plan(
            "corelib",
            summary="x",
            dll_names=[],
            fake_mod_id=1,
            required_on=3,
            modio_type="Library",
            name="CoreLib",
        )
    )
    assert "unity/CoreLib.asset" in plan


def test_write_plan_writes_text_and_binary(tmp_path):
    plan = nm.build_plan(
        "faster-pet-talents",
        summary="x",
        dll_names=[],
        fake_mod_id=1,
        required_on=1,
        modio_type="Other",
    )
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


def test_resolve_mods_dir_never_points_inside_a_worktree():
    # From .worktrees/<branch>/utils/ the naive grandparent would scaffold the
    # new mod into the worktree (deleted on cleanup) and, seeing no siblings,
    # allocate FAKE_MOD_ID 9999999 — disable-durability's.
    resolved = nm.resolve_mods_dir()
    assert ".worktrees" not in resolved.parts
    assert (resolved / "utils" / "new_mod.py").is_file()


def test_resolve_mods_dir_falls_back_to_the_grandparent_without_git(monkeypatch):
    monkeypatch.setattr(
        nm.subprocess,
        "run",
        lambda *a, **kw: type("Proc", (), {"returncode": 128, "stdout": ""})(),
    )
    expected = nm.pathlib.Path(nm.__file__).resolve().parent.parent
    assert nm.resolve_mods_dir() == expected


def test_resolve_sdk_path_prefers_environment(tmp_path):
    assert nm.resolve_sdk_path(tmp_path, {"SDK_PATH": "/x/sdk"}) == "/x/sdk"


def test_resolve_sdk_path_falls_back_to_parent_envrc(tmp_path):
    (tmp_path / ".envrc").write_text('export SDK_PATH="/from/envrc"\n')
    assert nm.resolve_sdk_path(tmp_path, {}) == "/from/envrc"


# --- scaffold (top-level orchestration) -------------------------------------


def _scaffold(tmp_path, **kw):
    kw.setdefault("summary", "x")
    kw.setdefault("mods_dir", tmp_path)
    kw.setdefault("sdk_path", tmp_path)
    kw.setdefault("required_on", 1)
    kw.setdefault("modio_type", "Quality of Life")
    return nm.scaffold("faster-pet-talents", **kw)


def test_scaffold_dry_run_writes_nothing(tmp_path):
    result = _scaffold(tmp_path, dry_run=True)
    assert not (tmp_path / "faster-pet-talents").exists()
    assert result["mod_name"] == "FasterPetTalents"
    assert result["target"].name == "faster-pet-talents"


def test_scaffold_reports_the_publish_relevant_choices(tmp_path):
    result = _scaffold(tmp_path, required_on=3, modio_type="Item|World", dry_run=True)
    assert result["required_on"] == 3
    assert result["modio_types"] == ["Item", "World"]


def test_scaffold_rejects_an_empty_modio_type(tmp_path):
    with pytest.raises(ValueError):
        _scaffold(tmp_path, modio_type="  |  ", dry_run=True)


def test_scaffold_normalises_modio_type_spacing(tmp_path):
    plan = dict(
        _scaffold(tmp_path, modio_type=" Visual | World ", dry_run=True)["plan"]
    )
    assert 'export CK_MODIO_TYPE="Visual|World"' in plan[".envrc"]


def test_scaffold_aborts_if_target_exists(tmp_path):
    (tmp_path / "faster-pet-talents").mkdir()
    with pytest.raises(FileExistsError):
        _scaffold(tmp_path, dry_run=True)


def test_scaffold_writes_tree_without_finalize(tmp_path):
    _scaffold(tmp_path, finalize=False)
    root = tmp_path / "faster-pet-talents"
    assert (root / "unity/FasterPetTalents.asset").is_file()
    assert (root / "unity/FasterPetTalents/FasterPetTalentsMod.cs").is_file()


# --- CLI argument parsing ---------------------------------------------------


_MIN_ARGS = [
    "faster-pet-talents",
    "--summary",
    "Does X",
    "--required-on",
    "1",
    "--modio-type",
    "Quality of Life",
]


@pytest.mark.parametrize("drop", ["--summary", "--required-on", "--modio-type"])
def test_parse_args_requires_every_publish_relevant_option(drop):
    # All three end up in the mod.io listing, and two of them abort the publish
    # when missing — so none of them may be guessed at scaffold time.
    i = _MIN_ARGS.index(drop)
    argv = _MIN_ARGS[:i] + _MIN_ARGS[i + 2 :]
    with pytest.raises(SystemExit):
        nm.parse_args(argv)


def test_parse_args_rejects_a_required_on_outside_the_flags_enum():
    with pytest.raises(SystemExit):
        nm.parse_args(_MIN_ARGS + ["--required-on", "0"])


def test_parse_args_defaults_and_flags():
    ns = nm.parse_args(_MIN_ARGS + ["--corelib"])
    assert ns.kebab == "faster-pet-talents"
    assert ns.summary == "Does X"
    assert ns.required_on == 1
    assert ns.modio_type == "Quality of Life"
    assert ns.corelib is True
    assert ns.dry_run is False
