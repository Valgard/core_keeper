"""Unit tests for new_mod.py — the deterministic new-mod scaffold generator."""

import json
import pathlib
import re as _re

import new_mod as nm
import pytest
import steam_identity

# --- identity derivation (the three-level naming convention) ----------------


def test_derive_pascal_joins_capitalized_segments():
    """Each hyphen-separated segment is capitalised and joined with no separator."""
    assert nm.derive_pascal("faster-pet-talents") == "FasterPetTalents"


def test_derive_pascal_single_segment():
    """A kebab name with no hyphen is just capitalised, not left alone or rejected."""
    assert nm.derive_pascal("itemchecklist") == "Itemchecklist"


def test_derive_pascal_keeps_digits():
    """A four-segment name is joined correctly, not truncated or mis-split.

    Despite the name, the fixture carries no digit — it does not exercise
    digit-preservation at all, only that capitalize() on a longer chain of
    segments still joins them correctly.
    """
    assert nm.derive_pascal("simple-crafting-pool-extender") == "SimpleCraftingPoolExtender"


def test_derive_title_spaces_capitalized_segments():
    """Each segment is capitalised and joined with a space, not the PascalCase concatenation."""
    assert nm.derive_title("faster-pet-talents") == "Faster Pet Talents"


def test_validate_kebab_accepts_lowercase_hyphenated():
    """A well-formed kebab-case name passes without raising."""
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
    """Each way a kebab name can be malformed is individually rejected.

    Empty, upper-case, a leading/trailing/doubled hyphen, an underscore, and
    a space are each covered by this one parametrized fixture.
    """
    with pytest.raises(ValueError):
        nm.validate_kebab(bad)


# --- mod.io Type tags -------------------------------------------------------


def test_parse_modio_type_splits_on_pipes_and_trims():
    """A pipe-separated list is split into its values.

    The whitespace around each pipe is trimmed from each value.
    """
    assert nm.parse_modio_type("Visual| Quality of Life |Library") == [
        "Visual",
        "Quality of Life",
        "Library",
    ]


def test_parse_modio_type_keeps_inner_spaces():
    """A single value's own internal spaces survive the split.

    Only the pipe is a separator, not whitespace.
    """
    # The values themselves contain spaces — that is why the separator is a pipe
    # and not a comma.
    assert nm.parse_modio_type("Quality of Life") == ["Quality of Life"]


@pytest.mark.parametrize("bad", ["", "|", " | ", "  "])
def test_parse_modio_type_rejects_effectively_empty(bad):
    """An empty string, a bare pipe, and whitespace-only variants are all rejected.

    None of them are parsed into a list of blank values.
    """
    with pytest.raises(ValueError):
        nm.parse_modio_type(bad)


# --- GUIDs ------------------------------------------------------------------


def test_new_guid_is_32_lowercase_hex():
    """A generated GUID is exactly 32 lowercase hex characters, the shape Unity's YAML expects."""
    import re

    assert re.fullmatch(r"[0-9a-f]{32}", nm.new_guid())


def test_new_guid_is_unique_per_call():
    """Two calls in a row produce different GUIDs — a scaffold cannot collide with itself."""
    assert nm.new_guid() != nm.new_guid()


# --- FAKE_MOD_ID allocation -------------------------------------------------


def test_next_fake_mod_id_is_one_below_minimum_existing():
    """The next free id is one below the LOWEST existing id, not the LAST one in the list.

    The fixture is deliberately unsorted with its minimum NOT in the last
    position: `[9999999, 9999994, 9999993]` (the old fixture) is already
    sorted descending, so a plausible off-by-one implementation
    `existing_ids[-1] - 1` returns the same 9999992 as the real `min(...) - 1`
    and this test could not tell them apart. Here the last element
    (9999994) is not the minimum (9999993), so the two implementations
    diverge: `existing_ids[-1] - 1` would give 9999993, not 9999992.
    """
    # existing IDs count downward from 9999999; the next free is min - 1, not
    # one below whatever happens to be last in the list.
    assert nm.next_fake_mod_id([9999993, 9999999, 9999994]) == 9999992


def test_next_fake_mod_id_defaults_when_none_found():
    """With no existing ids, allocation starts at the base value 9999999."""
    assert nm.next_fake_mod_id([]) == 9999999


# --- asmdef builders --------------------------------------------------------


def test_runtime_asmdef_is_valid_json_named_after_mod():
    """The generated asmdef is parseable JSON.

    Its "name" field is the mod's own PascalCase name.
    """
    data = json.loads(nm.build_runtime_asmdef("FasterPetTalents", ["0Harmony.dll"]))
    assert data["name"] == "FasterPetTalents"


def test_runtime_asmdef_includes_the_unity_references():
    """Core Unity/game assemblies are always referenced, regardless of the scanned DLL list.

    Burst, Entities, NetCode, and PugMod.SDK in particular.
    """
    data = json.loads(nm.build_runtime_asmdef("Mod", []))
    for ref in ("Unity.Burst", "Unity.Entities", "Unity.NetCode", "PugMod.SDK"):
        assert ref in data["references"]


def test_runtime_asmdef_precompiled_refs_are_the_scanned_dlls():
    """The generated precompiledReferences list is exactly the dll_names handed in, unmodified.

    The wiring is under test here, not the DLL-scanning step itself.
    """
    dlls = ["Pug.Other.dll", "0Harmony.dll"]
    data = json.loads(nm.build_runtime_asmdef("Mod", dlls))
    assert data["precompiledReferences"] == dlls


def test_runtime_asmdef_overrides_refs_and_is_not_autoreferenced():
    """The asmdef declares its own reference list explicitly.

    Not Unity's implicit auto-referencing.
    """
    data = json.loads(nm.build_runtime_asmdef("Mod", []))
    assert data["overrideReferences"] is True
    assert data["autoReferenced"] is False


def test_runtime_asmdef_omits_corelib_unless_requested():
    """Without corelib=True, CoreLib is absent from references.

    A mod that never asked for it gets no dependency.
    """
    data = json.loads(nm.build_runtime_asmdef("Mod", []))
    assert "CoreLib" not in data["references"]


def test_runtime_asmdef_references_corelib_when_requested():
    """corelib=True appends CoreLib to references, the compile-time half of the dependency.

    The loader dependency in the .asset is not enough: without this assembly
    reference the mod's own sources cannot compile against CoreLib types
    (CS0246). Every CoreLib mod in the family carries both.
    """
    # The loader dependency in the .asset is not enough: without this assembly
    # reference the mod's own sources cannot compile against CoreLib types
    # (CS0246). Every CoreLib mod in the family carries both.
    data = json.loads(nm.build_runtime_asmdef("Mod", [], corelib=True))
    assert data["references"][-1] == "CoreLib"


def test_editor_asmdef_references_runtime_modsdk_and_pugmod():
    """The editor asmdef is named "<Mod>.Editor" and is restricted to the Editor platform.

    It references the runtime asmdef plus ModSDK.Editor and PugMod.SDK, and
    precompiles against modio.UnityPlugin.dll.
    """
    data = json.loads(nm.build_editor_asmdef("FasterPetTalents"))
    assert data["name"] == "FasterPetTalents.Editor"
    assert data["references"] == ["FasterPetTalents", "ModSDK.Editor", "PugMod.SDK"]
    assert data["includePlatforms"] == ["Editor"]
    assert "modio.UnityPlugin.dll" in data["precompiledReferences"]


# --- ModBuilderSettings .asset YAML (GUID-rule core) ------------------------


def test_asset_binds_verbatim_sdk_script_guid():
    """The .asset's m_Script line binds the exact SDK ModBuilderSettings script GUID.

    Byte for byte — this is the line Unity uses to recognise the asset's type.
    """
    y = nm.build_asset_yaml("Mod", "Mod", metadata_guid="a" * 32, required_on=3)
    assert "m_Script: {fileID: 11500000, guid: bc43e4983a160e543856e5ba0421c9e1, type: 3}" in y


def test_asset_carries_identity_and_fresh_metadata_guid():
    """Name, kebab name, display name, requiredOn, and modPath each land in the YAML.

    Each comes from its own respective argument, and the caller-supplied
    metadata_guid is used verbatim rather than generated fresh.
    """
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
    """With no dependencies argument, the YAML renders an explicit empty list.

    Not an omitted key.
    """
    y = nm.build_asset_yaml("Mod", "Mod", metadata_guid="a" * 32, required_on=3)
    assert "dependencies: []" in y


def test_asset_dependencies_render_corelib_when_requested():
    """A (modName, required) dependency pair renders as a YAML list entry.

    It replaces the empty-list default entirely.
    """
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


@pytest.mark.parametrize("value", [0, 1, 2, 3])
def test_asset_writes_the_chosen_required_on(value):
    """Every value of the ModExistsOn flags enum (0-3) is written through verbatim.

    Not just the common ones.
    """
    y = nm.build_asset_yaml("Mod", "Mod", metadata_guid="a" * 32, required_on=value)
    assert f"requiredOn: {value}" in y


def test_asset_refuses_to_guess_required_on():
    """Omitting required_on raises TypeError — there is no default to silently fall back to.

    No default on purpose. The old default of 3 shipped three mods that
    needlessly blocked joining unmodded servers, and it also hid that
    build_plan never passed the argument through at all.
    """
    # No default on purpose. The old default of 3 shipped three mods that
    # needlessly blocked joining unmodded servers, and it also hid that
    # build_plan never passed the argument through at all.
    with pytest.raises(TypeError):
        nm.build_asset_yaml("Mod", "Mod", metadata_guid="a" * 32)


# --- _modio.asset YAML (internal cross-reference) ---------------------------


def test_modio_asset_binds_verbatim_sdk_script_guid():
    """The _modio.asset's m_Script line binds the SDK's mod.io-settings script GUID.

    Distinct from the ModBuilderSettings script GUID the .asset itself uses.
    """
    y = nm.build_modio_asset_yaml("Mod", modsettings_guid="b" * 32)
    assert "m_Script: {fileID: 11500000, guid: d83df2ae64ce1e94f9c006b9d326bf02, type: 3}" in y


def test_modio_asset_modid_zero_and_cross_refs_the_asset_meta():
    """A fresh _modio.asset starts with modId: 0, meaning never published.

    Its modSettings field points at the caller-supplied .asset.meta guid.
    """
    y = nm.build_modio_asset_yaml("FasterPetTalents", modsettings_guid="c" * 32)
    assert "m_Name: FasterPetTalents_modio" in y
    assert "modId: 0" in y
    assert "modSettings: {fileID: 11400000, guid: " + "c" * 32 + ", type: 2}" in y


# --- _Steam.asset YAML (Workshop identity) ----------------------------------


def test_steam_asset_has_no_item_id_until_the_first_publish():
    """A fresh _Steam.asset starts with fileId: 0.

    Mirroring how _modio.asset starts with modId: 0.
    """
    y = nm.build_steam_asset_yaml("FasterPetTalents")
    assert "m_Name: FasterPetTalents_Steam" in y
    assert "fileId: 0" in y
    assert "modName: FasterPetTalents" in y


def test_steam_asset_is_what_a_publish_recognizes(tmp_path):
    """The property the whole file exists for — checked with the publish's own readers.

    A publish reads this asset BY PATH and decides from its `fileId:` line
    whether the mod has ever been published. A scaffolded file the reader
    rejects is worse than no file at all: `ensure_recognizable` would abort the
    publish, and a shape it accepted but misread would look present while
    reading as "never published", after which the next publish creates a second
    Workshop item.
    """
    asset = tmp_path / "FasterPetTalents_Steam.asset"
    asset.write_text(nm.build_steam_asset_yaml("FasterPetTalents"))

    steam_identity.ensure_recognizable(asset)  # raises if a publish would balk
    assert steam_identity.read_file_id(asset) is None  # no item yet, not a zero id


# --- .meta builders ---------------------------------------------------------


def test_folder_meta_marks_folder_asset_with_guid():
    """A folder's .meta carries the given guid, folderAsset: yes, and a DefaultImporter.

    The importer Unity uses for directories specifically.
    """
    m = nm.build_folder_meta("e" * 32)
    assert "fileFormatVersion: 2" in m
    assert "guid: " + "e" * 32 in m
    assert "folderAsset: yes" in m
    assert "DefaultImporter" in m


def test_script_meta_is_minimal_guid_carrier():
    """A .cs.meta carries only the version and guid, with no importer block.

    Unity regenerates that block on import, so a stale one is never shipped.
    """
    m = nm.build_script_meta("f" * 32)
    assert "fileFormatVersion: 2" in m
    assert "guid: " + "f" * 32 in m
    # minimal form: no importer block (Unity regenerates it on import)
    assert "Importer" not in m


def test_native_asset_meta_points_at_main_object():
    """A native asset's .meta (e.g. a ScriptableObject) carries the guid.

    Plus NativeFormatImporter and the standard mainObjectFileID 11400000.
    """
    m = nm.build_native_asset_meta("1" * 32)
    assert "guid: " + "1" * 32 in m
    assert "NativeFormatImporter" in m
    assert "mainObjectFileID: 11400000" in m


def test_asmdef_meta_uses_assembly_definition_importer():
    """An .asmdef.meta carries the guid and Unity's AssemblyDefinitionImporter.

    Not a generic or native importer.
    """
    m = nm.build_asmdef_meta("2" * 32)
    assert "guid: " + "2" * 32 in m
    assert "AssemblyDefinitionImporter" in m


def test_texture_meta_carries_texture_importer():
    """A .png.meta carries the guid and Unity's TextureImporter.

    The importer type Unity needs to treat the file as an image asset.
    """
    m = nm.build_texture_meta("3" * 32)
    assert "guid: " + "3" * 32 in m
    assert "TextureImporter" in m


# --- parametric text files --------------------------------------------------


def test_bootstrap_cs_declares_imod_in_mod_namespace():
    """The generated Mod.cs opens a namespace matching the mod and declares "<Mod>Mod : IMod".

    It also stubs all five IMod lifecycle methods.
    """
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
    """The generated .envrc exports the mod's identity: name, kebab id, summary, fake mod id.

    It also sources the parent .envrc, inheriting SDK_PATH and the rest.
    """
    env = _envrc()
    assert 'MOD_NAME="FasterPetTalents"' in env
    assert 'MOD_NAME_ID="faster-pet-talents"' in env
    assert 'MOD_SUMMARY="Does a thing."' in env
    assert 'FAKE_MOD_ID="9999992"' in env
    assert "source_up_if_exists" in env  # inherits SDK_PATH etc. from parent


def test_envrc_exports_the_modio_type_tags():
    """CK_MODIO_TYPE is exported into .envrc, not left for the author to add later.

    Without CK_MODIO_TYPE the publish aborts in CLIPublishHelper before it
    uploads anything, so a scaffold that omits it builds but cannot ship.
    """
    # Without CK_MODIO_TYPE the publish aborts in CLIPublishHelper before it
    # uploads anything, so a scaffold that omits it builds but cannot ship.
    assert 'export CK_MODIO_TYPE="Visual|Quality of Life"' in _envrc()


def test_envrc_wires_localisation_from_the_start():
    """LOC_YAML and LOC_OUT are already exported in a fresh .envrc, not left for a later retrofit.

    Safe to pre-arm since LocalizationGenerator skips a table with no terms:
    writing the first term is then the only step, instead of a retrofit that
    has shipped mods with zero localisation when forgotten.
    """
    # Safe to pre-arm since LocalizationGenerator skips a table with no terms:
    # writing the first term is then the only step, instead of a retrofit that has
    # shipped mods with zero localisation when forgotten.
    env = _envrc()
    assert 'export LOC_YAML="$PWD/localization/localization.yaml"' in env
    assert 'export LOC_OUT="$PWD/unity/$MOD_NAME/Localization/Generated"' in env


def test_localization_template_is_inert():
    """The scaffolded localization.yaml is all comments.

    The load-bearing property of the template, not a style check: LOC_YAML is
    wired active, and the generator fails on a table that HAS content but
    yields no term. One uncommented namespace header here would break the
    very first build of every scaffolded mod. Mirrors
    LocYaml.HasAuthoredContent, which is the authority.
    """
    # The load-bearing property of the template, not a style check: LOC_YAML is
    # wired active, and the generator fails on a table that HAS content but
    # yields no term. One uncommented namespace header here would break the very
    # first build of every scaffolded mod. Mirrors LocYaml.HasAuthoredContent,
    # which is the authority.
    yaml = nm.build_localization_yaml("FasterPetTalents")
    authored = [
        line for line in yaml.splitlines() if line.strip() and not line.lstrip().startswith("#")
    ]
    assert not authored, f"template would parse as content: {authored}"
    # Still has to show the shape, or it teaches nothing.
    assert "FasterPetTalents-Config:" in yaml


def test_gitignore_excludes_the_generated_localisation_output():
    """The generated Localization output folder and its .meta are both ignored.

    Both entries are keyed to the mod's own PascalCase path.
    """
    gi = nm.build_gitignore("FasterPetTalents")
    assert "unity/FasterPetTalents/Localization/Generated/" in gi
    assert "unity/FasterPetTalents/Localization/Generated.meta" in gi


def test_gitignore_ignores_envrc_and_editor_helpers_by_mod_name():
    """.envrc and the mod-specific Editor helper scripts are ignored.

    The latter are keyed to the mod's own PascalCase path.
    """
    gi = nm.build_gitignore("FasterPetTalents")
    assert ".envrc" in gi
    assert "unity/FasterPetTalents/Editor/CLIBuildHelper.cs" in gi
    assert "unity/FasterPetTalents/Editor/LocalizationGenerator.cs.meta" in gi


def test_gitignore_excludes_superpowers_process_artifacts():
    """docs/superpowers/ is ignored specifically, not via a broad docs/ entry.

    Plans and brainstorming scratch are slop once implemented; docs/specs/
    and docs/adrs/ stay tracked, so the entry has to be the narrow one.
    """
    # Plans and brainstorming scratch are slop once implemented; docs/specs/ and
    # docs/adrs/ stay tracked, so the entry has to be the narrow one.
    gi = nm.build_gitignore("FasterPetTalents")
    assert "docs/superpowers/" in gi
    assert "\ndocs/\n" not in gi


def test_changelog_starts_at_0_1_0():
    """A fresh CHANGELOG.md opens with a "## [0.1.0]" entry.

    The version every scaffold starts at.
    """
    cl = nm.build_changelog()
    assert "## [0.1.0]" in cl


def test_steam_description_is_bbcode_not_markdown():
    """The Steam description is rendered in BBCode ([b], [h2], [list]), not Markdown.

    The Workshop renders BBCode; a stray '##' or '**' would show up
    literally on the item page instead of as a heading or bold run.
    """
    # The Workshop renders BBCode; a stray '##' or '**' would show up literally
    # on the item page instead of as a heading or bold run.
    text = nm.build_steam_description("Faster Pet Talents", "Speeds up pet talents.")
    assert "[b]Faster Pet Talents[/b]" in text
    assert "Speeds up pet talents." in text
    assert "[h2]Features[/h2]" in text
    assert "[list]" in text and "[/list]" in text
    assert "##" not in text
    assert "**" not in text


# --- formatting-gate files ---------------------------------------------------


def test_csharpierrc_pins_print_width_160():
    """.csharpierrc is exactly {"printWidth": 160}.

    This repo's deliberate override of CSharpier's 100-column default.
    """
    data = json.loads(nm.build_csharpierrc())
    assert data == {"printWidth": 160}


def test_csharpierignore_exists_and_stops_the_upward_search():
    """.csharpierignore exists, its own comment explaining why it must not be deleted.

    Not cosmetic: CSharpier's ignore-file search walks past the git boundary
    into core_keeper/, whose .csharpierignore is an allowlist for utils/
    only. Measured in a git repo holding one misformatted source: `csharpier
    check` reports "Checked 0 files" without a local ignore file and
    "Checked 1 files" with one. So a scaffolded mod without this ships a
    gate that passes while checking nothing.
    """
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
    """The pre-commit config runs `dotnet csharpier check` at both hook stages.

    Both pre-commit and pre-push, not just one.
    """
    cfg = nm.build_precommit_config()
    assert "entry: dotnet csharpier check" in cfg
    assert "- pre-commit" in cfg
    assert "- pre-push" in cfg


def test_dotnet_tools_json_pins_csharpier():
    """dotnet-tools.json is rooted (isRoot: true) and pins csharpier to version 1.3.0.

    With the "csharpier" command entry present too.
    """
    data = json.loads(nm.build_dotnet_tools_json())
    assert data["isRoot"] is True
    assert data["tools"]["csharpier"]["version"] == "1.3.0"
    assert data["tools"]["csharpier"]["commands"] == ["csharpier"]


# --- placeholder PNG --------------------------------------------------------


def test_placeholder_png_has_signature_and_chunks():
    """The placeholder logo is a structurally valid PNG, not just arbitrary bytes.

    It carries the 8-byte signature plus IHDR and IEND chunks.
    """
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
    """Both plugin roots (CoreKeeper and CoreKeeperModSDK) are scanned recursively.

    Results are sorted, and a non-.dll file in the tree is ignored.
    """
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
    """A .dll under a sibling plugin folder or elsewhere in Assets/ is not picked up.

    Only the two named plugin roots count.
    """
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
    """The same basename found at two different nested paths is reported only once."""
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
    """build_plan() returns exactly this file set for a mod without CoreLib.

    Nothing missing, nothing extra.
    """
    paths = set(_plan_dict().keys())
    assert paths == {
        ".envrc",
        ".envrc.example",
        ".gitignore",
        "CHANGELOG.md",
        "steam-description.txt",
        "localization/localization.yaml",
        ".csharpierrc",
        ".csharpierignore",
        ".pre-commit-config.yaml",
        ".config/dotnet-tools.json",
        "unity/FasterPetTalents.asset",
        "unity/FasterPetTalents.asset.meta",
        "unity/FasterPetTalents.meta",
        "unity/FasterPetTalents/FasterPetTalents.asmdef",
        "unity/FasterPetTalents/FasterPetTalents.asmdef.meta",
        "unity/FasterPetTalents/FasterPetTalents_Steam.asset",
        "unity/FasterPetTalents/FasterPetTalents_Steam.asset.meta",
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
    """The _modio.asset's modSettings field points at the plan's own asset.meta guid.

    Not a placeholder value.
    """
    plan = _plan_dict()
    asset_meta_guid = _guid(plan["unity/FasterPetTalents.asset.meta"])
    modio = plan["unity/FasterPetTalents/Editor/FasterPetTalents_modio.asset"]
    ref = _re.search(r"modSettings: \{fileID: 11400000, guid: ([0-9a-f]{32})", modio).group(1)
    assert ref == asset_meta_guid


def test_plan_all_meta_guids_are_unique():
    """Every .meta file across the whole plan carries a distinct guid.

    No two files were accidentally stamped with the same one.
    """
    plan = _plan_dict()
    meta_guids = [_guid(c) for p, c in plan.items() if p.endswith(".meta")]
    assert len(meta_guids) == len(set(meta_guids))


def test_plan_asset_metadata_guid_differs_from_asset_file_guid():
    """The .asset's internal metadata.guid and its .asset.meta's file guid are distinct.

    Not the same value reused for both.
    """
    # the internal metadata.guid must not equal the .asset.meta file guid
    plan = _plan_dict()
    asset = plan["unity/FasterPetTalents.asset"]
    metadata_guid = _re.search(r"metadata:\n    guid: ([0-9a-f]{32})", asset).group(1)
    asset_meta_guid = _guid(plan["unity/FasterPetTalents.asset.meta"])
    assert metadata_guid != asset_meta_guid


def test_plan_corelib_flag_sets_both_wirings():
    """corelib=True sets both the .asset's loader dependency and the asmdef's reference.

    Loader dependency and compile-time assembly reference are separate; the
    flag has to set both or the mod loads CoreLib but cannot compile against
    it.
    """
    # Loader dependency and compile-time assembly reference are separate; the
    # flag has to set both or the mod loads CoreLib but cannot compile against it.
    plan = _plan_dict(corelib=True)
    assert "- modName: CoreLib" in plan["unity/FasterPetTalents.asset"]
    asmdef = json.loads(plan["unity/FasterPetTalents/FasterPetTalents.asmdef"])
    assert "CoreLib" in asmdef["references"]


def test_plan_without_corelib_wires_neither():
    """Without corelib=True, neither wiring to CoreLib is written.

    Not the .asset's loader dependency, and not the asmdef's reference.
    """
    plan = _plan_dict()
    assert "dependencies: []" in plan["unity/FasterPetTalents.asset"]
    asmdef = json.loads(plan["unity/FasterPetTalents/FasterPetTalents.asmdef"])
    assert "CoreLib" not in asmdef["references"]


def test_plan_passes_required_on_and_modio_type_through():
    """build_plan() actually forwards required_on and modio_type into its generated files.

    Both used to stop here: required_on was accepted by build_asset_yaml but
    never handed to it, and CK_MODIO_TYPE did not exist at all.
    """
    # Both used to stop here: required_on was accepted by build_asset_yaml but
    # never handed to it, and CK_MODIO_TYPE did not exist at all.
    plan = _plan_dict(required_on=2, modio_type="World|Library")
    assert "requiredOn: 2" in plan["unity/FasterPetTalents.asset"]
    assert 'export CK_MODIO_TYPE="World|Library"' in plan[".envrc.example"]


def test_plan_name_override_changes_pascal_identity():
    """An explicit name= override changes the PascalCase identity used for generated paths.

    Independent of the kebab argument it would otherwise derive from.
    """
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
    """write_plan() writes both a text entry (.envrc) and a binary one (the PNG logo).

    Not just one or the other.
    """
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
    """FAKE_MOD_ID is read out of every sibling mod's .envrc.example.

    A new mod's id allocation sees the whole family, not just one repo.
    """
    (tmp_path / "mod-a").mkdir()
    (tmp_path / "mod-a/.envrc.example").write_text('export FAKE_MOD_ID="9999994"\n')
    (tmp_path / "mod-b").mkdir()
    (tmp_path / "mod-b/.envrc.example").write_text('export FAKE_MOD_ID="9999993"\n')
    assert sorted(nm.scan_existing_fake_mod_ids(tmp_path)) == [9999993, 9999994]


def test_resolve_mods_dir_never_points_inside_a_worktree(tmp_path, monkeypatch):
    """From inside a git worktree, resolve_mods_dir() resolves to the MAIN checkout.

    Mirrors test_mod_source.py's
    test_default_workspace_resolves_a_worktree_to_the_main_checkout for this
    sibling tool. The old version of this test called the real
    resolve_mods_dir() with nothing faked at all, which only ever exercises
    whichever checkout the suite happens to run from — in the main checkout
    the assertions held no matter whether the worktree-detection branch was
    correct, broken, or deleted outright, because `here.parent` (the naive
    fallback) and the git-resolved answer are the SAME directory there. Faking
    `git rev-parse --git-common-dir`'s answer forces the actual branch: a
    naive `here.parent` fallback would return wherever this file's own
    directory sits, not `main_checkout`, and the two are made to differ on
    purpose by rooting both under a fresh tmp_path.
    """
    main_checkout = tmp_path / "core_keeper"
    (main_checkout / "utils").mkdir(parents=True)
    (main_checkout / "utils" / "new_mod.py").write_text("# stand-in for the real module")
    common_dir = main_checkout / ".git"
    common_dir.mkdir()

    monkeypatch.setattr(
        nm.subprocess,
        "run",
        lambda *a, **kw: type("Proc", (), {"returncode": 0, "stdout": f"{common_dir}\n"})(),
    )

    resolved = nm.resolve_mods_dir()
    assert resolved == main_checkout
    assert ".worktrees" not in resolved.parts
    assert (resolved / "utils" / "new_mod.py").is_file()


def test_resolve_mods_dir_falls_back_to_the_grandparent_without_git(monkeypatch):
    """Outside a git checkout, resolve_mods_dir() falls back to the plain grandparent.

    The grandparent of this file itself, when git is unavailable or errors.
    """
    monkeypatch.setattr(
        nm.subprocess,
        "run",
        lambda *a, **kw: type("Proc", (), {"returncode": 128, "stdout": ""})(),
    )
    expected = nm.pathlib.Path(nm.__file__).resolve().parent.parent
    assert nm.resolve_mods_dir() == expected


def test_resolve_sdk_path_prefers_environment(tmp_path):
    """SDK_PATH from the environment wins outright.

    resolve_sdk_path() does not even look at .envrc when it is set.
    """
    assert nm.resolve_sdk_path(tmp_path, {"SDK_PATH": "/x/sdk"}) == "/x/sdk"


def test_resolve_sdk_path_falls_back_to_parent_envrc(tmp_path):
    """Without SDK_PATH in the environment, it falls back to the parent .envrc.

    Parsed out of core_keeper/.envrc specifically.
    """
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
    """dry_run=True computes and returns the plan, but writes nothing to disk.

    The result still carries the mod name and target path.
    """
    result = _scaffold(tmp_path, dry_run=True)
    assert not (tmp_path / "faster-pet-talents").exists()
    assert result["mod_name"] == "FasterPetTalents"
    assert result["target"].name == "faster-pet-talents"


def test_scaffold_reports_the_publish_relevant_choices(tmp_path):
    """scaffold()'s result echoes back the resolved required_on int and modio_type list.

    For the caller to display before committing to a real write.
    """
    result = _scaffold(tmp_path, required_on=3, modio_type="Item|World", dry_run=True)
    assert result["required_on"] == 3
    assert result["modio_types"] == ["Item", "World"]


def test_scaffold_rejects_an_empty_modio_type(tmp_path):
    """A modio_type that parses to nothing but whitespace/pipes raises ValueError.

    Even under dry_run.
    """
    with pytest.raises(ValueError):
        _scaffold(tmp_path, modio_type="  |  ", dry_run=True)


def test_scaffold_normalises_modio_type_spacing(tmp_path):
    """Stray spaces around a modio_type's pipes and values are trimmed.

    Before they ever reach the written .envrc.
    """
    plan = dict(_scaffold(tmp_path, modio_type=" Visual | World ", dry_run=True)["plan"])
    assert 'export CK_MODIO_TYPE="Visual|World"' in plan[".envrc"]


def test_scaffold_aborts_if_target_exists(tmp_path):
    """scaffold() refuses to run when the target directory already exists.

    Even under dry_run — it never risks overwriting an existing mod.
    """
    (tmp_path / "faster-pet-talents").mkdir()
    with pytest.raises(FileExistsError):
        _scaffold(tmp_path, dry_run=True)


def test_scaffold_writes_tree_without_finalize(tmp_path, monkeypatch):
    """finalize=False still writes the full file tree to disk, but skips git-init and SDK-link.

    Both finalize-only steps are monkeypatched to record a call rather than
    act, so a scaffold() that ignored the flag and ran them regardless would
    be caught here — the old version of this test only checked that the
    plan's files landed on disk, which is true whether or not the finalize
    steps also ran, so it could not distinguish "skipped" from "ran anyway".
    """
    calls = []
    monkeypatch.setattr(nm, "_git_init_and_commit", lambda target: calls.append("git"))
    monkeypatch.setattr(nm, "_run_link", lambda target, sdk_path, mod_name: calls.append("link"))

    _scaffold(tmp_path, finalize=False)

    root = tmp_path / "faster-pet-talents"
    assert (root / "unity/FasterPetTalents.asset").is_file()
    assert (root / "unity/FasterPetTalents/FasterPetTalentsMod.cs").is_file()
    assert calls == []


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
    """Each of --summary, --required-on, and --modio-type is individually required.

    All three end up in the mod.io listing, and two of them abort the
    publish when missing — so none of them may be guessed at scaffold time.
    """
    # All three end up in the mod.io listing, and two of them abort the publish
    # when missing — so none of them may be guessed at scaffold time.
    i = _MIN_ARGS.index(drop)
    argv = _MIN_ARGS[:i] + _MIN_ARGS[i + 2 :]
    with pytest.raises(SystemExit):
        nm.parse_args(argv)


@pytest.mark.parametrize("value", ["4", "-1", "two"])
def test_parse_args_rejects_a_required_on_outside_the_flags_enum(value):
    """A value outside 0-3 (4, -1) and a non-numeric value ("two") are all rejected.

    Not just out-of-range integers.
    """
    with pytest.raises(SystemExit):
        nm.parse_args([*_MIN_ARGS, "--required-on", value])


@pytest.mark.parametrize("value", [0, 1, 2, 3])
def test_every_accepted_required_on_has_a_label(value):
    """Every required_on value argparse accepts also has a REQUIRED_ON_LABELS entry.

    0 (ModExistsOn.None) is a legitimate choice for a mod that must never
    gate a connection in either direction; it publishes with no Application
    Type tag. The label lookup is not cosmetic -- the CLI echoes
    REQUIRED_ON_LABELS[required_on] once scaffolding has succeeded, so a
    value argparse accepts but the table lacks is a KeyError at the very end
    of an otherwise complete run.
    """
    # 0 (ModExistsOn.None) is a legitimate choice for a mod that must never gate
    # a connection in either direction; it publishes with no Application Type
    # tag. The label lookup is not cosmetic -- the CLI echoes
    # REQUIRED_ON_LABELS[required_on] once scaffolding has succeeded, so a value
    # argparse accepts but the table lacks is a KeyError at the very end of an
    # otherwise complete run.
    ns = nm.parse_args([*_MIN_ARGS, "--required-on", str(value)])
    assert ns.required_on == value
    assert value in nm.REQUIRED_ON_LABELS


def test_parse_args_defaults_and_flags():
    """A minimal argv plus --corelib parses to the expected namespace.

    Kebab positional, the three required options, corelib True, dry_run
    defaulting False.
    """
    ns = nm.parse_args([*_MIN_ARGS, "--corelib"])
    assert ns.kebab == "faster-pet-talents"
    assert ns.summary == "Does X"
    assert ns.required_on == 1
    assert ns.modio_type == "Quality of Life"
    assert ns.corelib is True
    assert ns.dry_run is False


def test_envrc_reserves_the_discord_forum_tags_empty():
    """CK_DISCORD_TAGS is exported but deliberately blank, not simply absent.

    Written blank on purpose: a fresh mod has no #available-mods post yet,
    so its forum tags are unknowable here. discord_post.py refuses to
    render a post while they are empty, which is the moment they can
    actually be chosen.
    """
    # Written blank on purpose: a fresh mod has no #available-mods post yet, so
    # its forum tags are unknowable here. discord_post.py refuses to render a
    # post while they are empty, which is the moment they can actually be chosen.
    assert 'export CK_DISCORD_TAGS=""' in _envrc()


def test_envrc_scaffolds_the_discord_thread_and_media_variables():
    """CK_DISCORD_THREAD and CK_DISCORD_MEDIA are both scaffolded, empty.

    Both are empty on purpose and mean different things when empty: no
    thread yet, and nothing to show beyond the logo. A generated repo that
    lacks them makes discord_post.py look broken for a new mod.
    """
    text = _envrc()

    assert 'export CK_DISCORD_THREAD=""' in text
    assert 'export CK_DISCORD_MEDIA=""' in text


def test_steam_asset_lands_where_every_publish_looks_for_it():
    """Not "the path looks right" but "the path is the one the publish computes".

    steam_identity.asset_path is the single authority on this location, and a
    reader that computes it differently from the writer does not read a
    different file -- it reads nothing. Asserting a literal string here would
    pass while both sides drifted together out of agreement with each other.
    """
    expected = steam_identity.asset_path(pathlib.Path(""), "FasterPetTalents")
    assert expected.as_posix() in _plan_dict()
