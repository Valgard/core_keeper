#!/usr/bin/env python3
"""Deterministic new-mod scaffold generator (see
docs/specs/2026-06-28-new-mod-scaffold-generator-design.md)."""

import argparse
import json
import os
import pathlib
import re
import struct
import subprocess
import sys
import uuid
import zlib

# The Workshop identity asset's shape lives with the code that reads and writes
# it during a publish, not here. Scaffolding it from a second copy of the same
# YAML would let the two drift, and the failure that causes is silent: a
# publish reads the asset BY PATH, so a shape it does not recognise reads as
# "this mod has never been published" and creates a second Workshop item.
import steam_identity

# The 14 Unity engine assemblies the wizard hardcodes into a mod's runtime
# asmdef (ModBuilderWindow.CreateNewMod, ModBuilderWindow.cs:77-90). The game
# DLLs are appended at scaffold time from a live filesystem scan.
UNITY_REFERENCES = [
    "Unity.Burst",
    "Unity.Collections",
    "Unity.Entities",
    "Unity.Entities.Hybrid",
    "Unity.Jobs",
    "Unity.Mathematics",
    "Unity.NetCode",
    "Unity.NetCode.Physics",
    "Unity.Networking.Transport",
    "Unity.Physics",
    "Unity.Physics.Hybrid",
    "Unity.Properties",
    "Unity.Transforms",
    "PugMod.SDK",
]

# Fake mod.io IDs count downward from here; new mods take the next free below
# the lowest already in use.
_FAKE_MOD_ID_BASE = 9999999

# ModMetadata.ModExistsOn ([Flags], PugMod.SDK) — for the CLI's echo, so the
# chosen value is legible in the scaffold output rather than a bare number.
REQUIRED_ON_LABELS = {
    0: "Neither (no Application Type tag)",
    1: "Client",
    2: "Server",
    3: "Client and Server",
}

# Verbatim SDK MonoScript GUIDs — these bind a generated ScriptableObject to its
# SDK class. They are SDK-clone-stable (every existing mod shares them); if a
# future SDK update changes them, these two constants are the single edit point.
MODBUILDERSETTINGS_SCRIPT_GUID = "bc43e4983a160e543856e5ba0421c9e1"
MODIO_SCRIPT_GUID = "d83df2ae64ce1e94f9c006b9d326bf02"

# A kebab id is one or more lowercase-alphanumeric segments joined by single
# hyphens. This is the single source of identity; Pascal and Title derive from
# it, which makes the three-level naming convention impossible to break.
_KEBAB_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def validate_kebab(name: str) -> None:
    """Raise ValueError unless *name* is a well-formed kebab-case id."""
    if not _KEBAB_RE.match(name):
        raise ValueError(
            f"invalid kebab name {name!r}: expected lowercase alphanumeric "
            f"segments joined by single hyphens (e.g. 'faster-pet-talents')"
        )


def parse_modio_type(value: str) -> list:
    """Split a pipe-separated CK_MODIO_TYPE into its mod.io "Type" tag values.

    Pipe- rather than comma-separated because the values themselves contain
    spaces ("Quality of Life"). Deliberately **not** validated against a value
    list: mod.io's tag taxonomy is the authority and CLIPublishHelper reads it
    live for exactly that reason, so a copy here would be one more list that
    goes stale silently. Emptiness is rejected, though — `--modio-type "|"`
    would otherwise satisfy argparse and only surface as an aborted publish."""
    values = [part.strip() for part in value.split("|")]
    values = [part for part in values if part]
    if not values:
        raise ValueError(
            'invalid --modio-type: expected pipe-separated mod.io "Type" tags, '
            'e.g. "Visual|Quality of Life"'
        )
    return values


def derive_pascal(kebab: str) -> str:
    """kebab-case -> PascalCase MOD_NAME (e.g. faster-pet-talents -> FasterPetTalents)."""
    return "".join(segment.capitalize() for segment in kebab.split("-"))


def derive_title(kebab: str) -> str:
    """kebab-case -> Title Case displayName (e.g. faster-pet-talents -> Faster Pet Talents)."""
    return " ".join(segment.capitalize() for segment in kebab.split("-"))


def new_guid() -> str:
    """A fresh Unity-style asset GUID: 32 lowercase hex chars."""
    return uuid.uuid4().hex


def next_fake_mod_id(existing_ids) -> int:
    """The next free fake mod.io ID: one below the lowest existing, or the base
    if none are in use yet."""
    if not existing_ids:
        return _FAKE_MOD_ID_BASE
    return min(existing_ids) - 1


# --- asmdef builders --------------------------------------------------------


def build_runtime_asmdef(mod_name: str, dll_names, corelib: bool = False) -> str:
    """The mod's runtime assembly definition: the 14 Unity references plus the
    live-scanned game DLLs as precompiled references. Mirrors the object the
    wizard assembles in ModBuilderWindow.cs:96-119.

    A CoreLib mod needs *two* separate wirings, and having only one is a
    scaffold that fails late: the `.asset` dependency makes the loader require
    CoreLib at runtime, while this assembly reference is what lets the mod's own
    sources compile against CoreLib types at all (the assembly comes from the
    SDK's `ck.modding.corelib` UPM package, not from `Assets/`). Without it the
    first `using CoreLib;` fails with CS0246."""
    references = list(UNITY_REFERENCES)
    if corelib:
        references.append("CoreLib")
    data = {
        "name": mod_name,
        "references": references,
        "includePlatforms": [],
        "excludePlatforms": [],
        "allowUnsafeCode": False,
        "overrideReferences": True,
        "precompiledReferences": list(dll_names),
        "autoReferenced": False,
        "defineConstraints": [],
        "versionDefines": [],
        "useGUIDs": False,
    }
    return json.dumps(data, indent=2)


def build_editor_asmdef(mod_name: str) -> str:
    """The mod's Editor assembly definition — Editor-only, references the
    runtime assembly plus the SDK editor assemblies, pulls in the modio plugin
    so the shared CLI*Helper sources compile."""
    data = {
        "name": f"{mod_name}.Editor",
        "rootNamespace": f"{mod_name}.Editor",
        "references": [mod_name, "ModSDK.Editor", "PugMod.SDK"],
        "includePlatforms": ["Editor"],
        "excludePlatforms": [],
        "allowUnsafeCode": False,
        "overrideReferences": True,
        "precompiledReferences": ["modio.UnityPlugin.dll"],
        "autoReferenced": False,
        "defineConstraints": [],
        "versionDefines": [],
        "noEngineReferences": False,
    }
    return json.dumps(data, indent=4)


# --- ScriptableObject .asset YAML builders ----------------------------------


def _render_dependencies(dependencies) -> str:
    """The `dependencies:` value inside the metadata block — `[]` when empty,
    otherwise a YAML list of `- modName: X` / `required: N` entries."""
    if not dependencies:
        return "    dependencies: []"
    lines = ["    dependencies:"]
    for mod_name, required in dependencies:
        lines.append(f"    - modName: {mod_name}")
        lines.append(f"      required: {required}")
    return "\n".join(lines)


def build_asset_yaml(
    mod_name: str,
    display_name: str,
    metadata_guid: str,
    dependencies=None,
    *,
    required_on: int,
) -> str:
    """The ModBuilderSettings `.asset` — the build entry point. Binds the SDK
    ModBuilderSettings class verbatim; `metadata.guid` must be freshly unique
    per mod or the loader crashes with "Data block loader already added".

    `required_on` is deliberately keyword-only and has **no default**. It used
    to default to 3, which is how three published mods ended up needlessly
    blocking joins to unmodded servers, and the default also hid that
    `build_plan` was not passing the value through at all. A missing argument
    is now a TypeError instead of a silently wrong manifest."""
    return f"""%YAML 1.1
%TAG !u! tag:unity3d.com,2011:
--- !u!114 &11400000
MonoBehaviour:
  m_ObjectHideFlags: 0
  m_CorrespondingSourceObject: {{fileID: 0}}
  m_PrefabInstance: {{fileID: 0}}
  m_PrefabAsset: {{fileID: 0}}
  m_GameObject: {{fileID: 0}}
  m_Enabled: 1
  m_EditorHideFlags: 0
  m_Script: {{fileID: 11500000, guid: {MODBUILDERSETTINGS_SCRIPT_GUID}, type: 3}}
  m_Name: {mod_name}
  m_EditorClassIdentifier:
  metadata:
    guid: {metadata_guid}
    name: {mod_name}
    displayName: {display_name}
    skipSafetyChecks: 0
    disableScripts: 0
    accessesExtraAssemblies: 1
    disableHarmonyPatching: 0
    requiredOn: {required_on}
    files: []
{_render_dependencies(dependencies)}
  modPath: Assets/{mod_name}
  forceReimport: 1
  buildBundles: 1
  cacheBundles: 0
  buildLinux: 1
  assets: []
  lastBuildLinux: 0
"""


def build_modio_asset_yaml(
    mod_name: str, modsettings_guid: str, mod_id: int = 0
) -> str:
    """The `<Mod>_modio.asset` — holds the mod.io ID and cross-references this
    mod's ModBuilderSettings asset by its (freshly-generated) `.asset.meta`
    GUID. `modId` is 0 until the first publish assigns the real one."""
    return f"""%YAML 1.1
%TAG !u! tag:unity3d.com,2011:
--- !u!114 &11400000
MonoBehaviour:
  m_ObjectHideFlags: 0
  m_CorrespondingSourceObject: {{fileID: 0}}
  m_PrefabInstance: {{fileID: 0}}
  m_PrefabAsset: {{fileID: 0}}
  m_GameObject: {{fileID: 0}}
  m_Enabled: 1
  m_EditorHideFlags: 0
  m_Script: {{fileID: 11500000, guid: {MODIO_SCRIPT_GUID}, type: 3}}
  m_Name: {mod_name}_modio
  m_EditorClassIdentifier:
  modId: {mod_id}
  modSettings: {{fileID: 11400000, guid: {modsettings_guid}, type: 2}}
  logo: {{fileID: 0}}
  summary:
"""


def build_steam_asset_yaml(mod_name: str) -> str:
    """The `<Mod>_Steam.asset` — the Workshop counterpart of `_modio.asset`.

    `fileId` is 0 until the first Steam publish assigns the real one, exactly
    as `modId` is above. Scaffolded rather than left to that publish for the
    reason ../docs/publishing.md gives: a file the publish CREATES is easy to
    leave untracked afterwards, and an untracked asset is one `git clean` away
    from taking the id with it — after which the next publish creates a second
    Workshop item indistinguishable from the first. A file already in the repo
    only has a field filled in, which no `git status` can hide.

    `modOwner` and `tags` stay empty because their values are not knowable yet:
    the owner comes back from a live Steam session, and the tags are derived at
    publish time. `modName` is the SDK window's lookup key, so it is the one
    field worth writing now.
    """
    return steam_identity.TEMPLATE.format(
        name=f"{mod_name}_Steam", file_id=0, mod_name=mod_name
    )


# --- .meta builders ---------------------------------------------------------


def build_folder_meta(guid: str) -> str:
    """Folder .meta — `folderAsset: yes` with the DefaultImporter."""
    return f"""fileFormatVersion: 2
guid: {guid}
folderAsset: yes
DefaultImporter:
  externalObjects: {{}}
  userData:
  assetBundleName:
  assetBundleVariant:
"""


def build_script_meta(guid: str) -> str:
    """Minimal C# script .meta — just the GUID carrier. Unity regenerates the
    MonoImporter block on import; the existing mods all use this minimal form."""
    return f"fileFormatVersion: 2\nguid: {guid}\n"


def build_native_asset_meta(guid: str) -> str:
    """ScriptableObject .asset .meta — NativeFormatImporter pointing at the
    MonoBehaviour main object (fileID 11400000).

    Taken from steam_identity rather than spelled out again, because the copy
    that used to live here dropped the trailing space Unity writes after
    `userData:`, `assetBundleName:` and `assetBundleVariant:`. Every scaffolded
    asset therefore carried a `.meta` Unity rewrote on the first import —
    a diff in a brand-new repo, on a file nobody had touched. Verified against
    a Unity-written `.meta` in an existing mod, which has the spaces.
    """
    return steam_identity.META_TEMPLATE.format(guid=guid)


def build_asmdef_meta(guid: str) -> str:
    """Assembly-definition .meta — AssemblyDefinitionImporter."""
    return f"""fileFormatVersion: 2
guid: {guid}
AssemblyDefinitionImporter:
  externalObjects: {{}}
  userData:
  assetBundleName:
  assetBundleVariant:
"""


def build_texture_meta(guid: str) -> str:
    """PNG .meta — the TextureImporter block (captured from a working mod's
    logo.png.meta), with a fresh GUID. Imports the placeholder as a texture so
    `_modio.asset`/the build never see a missing asset."""
    return f"""fileFormatVersion: 2
guid: {guid}
TextureImporter:
  internalIDToNameTable: []
  externalObjects: {{}}
  serializedVersion: 13
  mipmaps:
    mipMapMode: 0
    enableMipMap: 0
    sRGBTexture: 1
    linearTexture: 0
    fadeOut: 0
    borderMipMap: 0
    mipMapsPreserveCoverage: 0
    alphaTestReferenceValue: 0.5
    mipMapFadeDistanceStart: 1
    mipMapFadeDistanceEnd: 3
  bumpmap:
    convertToNormalMap: 0
    externalNormalMap: 0
    heightScale: 0.25
    normalMapFilter: 0
    flipGreenChannel: 0
  isReadable: 1
  streamingMipmaps: 0
  streamingMipmapsPriority: 0
  vTOnly: 0
  ignoreMipmapLimit: 0
  grayScaleToAlpha: 0
  generateCubemap: 6
  cubemapConvolution: 0
  seamlessCubemap: 0
  textureFormat: 1
  maxTextureSize: 2048
  textureSettings:
    serializedVersion: 2
    filterMode: 0
    aniso: 1
    mipBias: 0
    wrapU: 1
    wrapV: 1
    wrapW: 1
  nPOTScale: 0
  lightmap: 0
  compressionQuality: 50
  spriteMode: 2
  spriteExtrude: 1
  spriteMeshType: 0
  alignment: 0
  spritePivot: {{x: 0.5, y: 0.5}}
  spritePixelsToUnits: 16
  spriteBorder: {{x: 0, y: 0, z: 0, w: 0}}
  spriteGenerateFallbackPhysicsShape: 1
  alphaUsage: 1
  alphaIsTransparency: 1
  spriteTessellationDetail: -1
  textureType: 0
  textureShape: 1
  singleChannelComponent: 0
  flipbookRows: 1
  flipbookColumns: 1
  maxTextureSizeSet: 0
  compressionQualitySet: 0
  textureFormatSet: 0
  ignorePngGamma: 0
  applyGammaDecoding: 0
  swizzle: 50462976
  cookieLightType: 0
  platformSettings:
  - serializedVersion: 4
    buildTarget: DefaultTexturePlatform
    maxTextureSize: 2048
    resizeAlgorithm: 0
    textureFormat: -1
    textureCompression: 0
    compressionQuality: 50
    crunchedCompression: 0
    allowsAlphaSplitting: 0
    overridden: 0
    ignorePlatformSupport: 0
    androidETC2FallbackOverride: 0
    forceMaximumCompressionQuality_BC6H_BC7: 0
  spriteSheet:
    serializedVersion: 2
    sprites: []
    outline: []
    customData:
    physicsShape: []
    bones: []
    spriteID: 5e97eb03825dee720800000000000000
    internalID: 0
    vertices: []
    indices:
    edges: []
    weights: []
    secondaryTextures: []
    spriteCustomMetadata:
      entries: []
    nameFileIdTable: {{}}
  mipmapLimitGroupName:
  pSDRemoveMatte: 0
  userData:
  assetBundleName:
  assetBundleVariant:
"""


# --- parametric text files --------------------------------------------------


def build_bootstrap_cs(mod_name: str) -> str:
    """The IMod bootstrap. The loader instantiates this on game start and calls
    the lifecycle methods; Harmony patch classes are auto-discovered, so there
    is no PatchAll() call. The author adds patch + config classes later."""
    return f"""using PugMod;
using UnityEngine;

namespace {mod_name}
{{
    /// <summary>
    /// Mod bootstrap. The Pugstorm mod loader instantiates this class on game
    /// start and calls the IMod lifecycle methods. Harmony patch classes are
    /// auto-discovered by the loader — there is no PatchAll() call.
    /// </summary>
    public sealed class {mod_name}Mod : IMod
    {{
        public void EarlyInit()
        {{
        }}

        public void Init()
        {{
            Debug.Log("[{mod_name}] Mod initialized.");
        }}

        public void ModObjectLoaded(Object obj)
        {{
        }}

        public void Shutdown()
        {{
        }}

        public void Update()
        {{
        }}
    }}
}}
"""


def build_envrc(
    mod_name: str, kebab: str, summary: str, fake_mod_id: int, modio_type: str
) -> str:
    """The mod's environment file. Machine-shared paths (SDK_PATH, UNITY_BIN,
    …) are inherited from the parent core_keeper/.envrc; only the project-
    inherent identity vars live here. Used for both `.envrc` (gitignored) and
    `.envrc.example` (tracked) — the identity is the same in both.

    This file is part of the *publish* contract, not just the build one:
    `CLIPublishHelper` reads `MOD_SUMMARY` and `CK_MODIO_TYPE` from here and
    aborts the publish outright when the latter is missing. The localisation
    pair is left commented out on purpose — unset means "skip localisation",
    while a set `LOC_YAML` pointing at a term-less YAML fails the build."""
    return f"""#!/usr/bin/env bash
# {mod_name} — environment variables.
#
# Machine-level shared values (UNITY_BIN, SDK_PATH, CK_GAME_VERSION,
# MODIO_DEPS_MAP, LOC_TABLE, the ilspycmd PATH entry) are inherited from the
# parent core_keeper/.envrc — define them once there, not here.
#
#   cp .envrc.example .envrc
#   direnv allow                     # then `cd` triggers the chain
#   # or, without direnv:  source .envrc && ../utils/build.sh
#   #   from a worktree:   source .envrc && ../../../utils/build.sh

# --- Inherit shared values from the nearest ancestor core_keeper/.envrc ------
# The manual branch walks up instead of naming a depth, because this file is
# copied verbatim into a worktree under .worktrees/<name>/, which sits one level
# deeper than the mod directory. The SDK_PATH test is what makes the walk safe:
# `source` does not change $PWD, so from a worktree the first *existing* hit
# would be the mod's own .envrc — this same file — whose loop would then restart
# against the same $PWD and never reach the parent. Only the parent defines
# SDK_PATH, so testing content rather than position ends the walk in one place
# regardless of how deep the caller sits. The test matches the ASSIGNMENT, not
# the name: every mod .envrc mentions SDK_PATH in its own header comment, and a
# looser grep therefore selects the mod file, sources it, and recurses.
# direnv needs none of it: source_up_if_exists searches upward on its own.
if command -v source_up_if_exists >/dev/null 2>&1; then
    source_up_if_exists
else
    for _up in ../.envrc ../../.envrc ../../../.envrc ../../../../.envrc; do
        if [ -f "$_up" ] && grep -q '^export SDK_PATH=' "$_up"; then
            # shellcheck disable=SC1090
            source "$_up"; break
        fi
    done
    unset _up
fi

# --- Mod identity (project-inherent — leave as-is) --------------------------

# PascalCase name — drives SDK symlink paths and the build entry point.
export MOD_NAME="{mod_name}"

# kebab-case id, written as `name_id` in the fake mod.io state.json.
export MOD_NAME_ID="{kebab}"

# One-line summary, written into state.json by utils/install-macos.sh.
export MOD_SUMMARY="{summary}"

# Fake mod.io ID — must be DISTINCT per mod.
export FAKE_MOD_ID="{fake_mod_id}"

# Repo root, read by the shared CLIPublishHelper to locate CHANGELOG.md.
export MOD_REPO_ROOT="$PWD"

# mod.io "Type" tags for the listing — PIPE-separated, because the values
# contain spaces. Synchronised (not just added) by the shared
# CLIPublishHelper, so a value dropped here is removed on mod.io. Valid:
# Visual, Audio, Item, NPC, Quality of Life, Overhaul, Language, World,
# Library, Other.
export CK_MODIO_TYPE="{modio_type}"

# Forum tags for the mod's #available-mods thread on the Core Keeper Discord —
# PIPE-separated, because "Misc / Other" contains spaces. Deliberately blank: a
# mod this new has no thread, and the tags belong to one. The channel's current
# tag set lives in utils/ck-discord-tags.json and is read via forum_tags() in
# utils/discord_post.py, which refuses anything else — deliberately not copied
# here, because a copy written into a generated repo can never be corrected and
# the set belongs to a channel somebody else administers. Filling this in is part
# of writing the post.
export CK_DISCORD_TAGS=""

# The mod's thread in #available-mods, once it has one. Empty means no thread
# yet, so the ck-discord-post skill creates a post; set means a new version is
# announced as a comment there. Filled in after the first post, not by hand.
export CK_DISCORD_THREAD=""

# Images and clips for the post, beyond the logo — PIPE-separated, in the order
# they should appear. A relative path becomes an attachment, an http(s) URL
# becomes its own follow-up message (the only route for a clip past Discord's
# upload ceiling). Empty is legitimate here, unlike CK_DISCORD_TAGS: it means
# the mod has nothing to show beyond its logo, which is true of a chat command.
export CK_DISCORD_MEDIA=""

# --- Localisation (read by utils/CLIBuildHelper.cs -> LocalizationGenerator.GenerateFromEnv) ---
# LOC_TABLE (the shared CK language-address table) is inherited from the parent core_keeper/.envrc.
# Wired from the start even for a mod with no text yet: a table holding no terms
# is skipped, so writing the first term is the only step needed later.
export LOC_YAML="$PWD/localization/localization.yaml"
export LOC_OUT="$PWD/unity/$MOD_NAME/Localization/Generated"
"""


def build_gitignore(mod_name: str) -> str:
    """The mod's .gitignore. The Editor-helper sources are symlinked in by
    link.sh and their .meta are Unity-generated; neither belongs in the repo,
    so they are ignored by their mod-name-specific paths."""
    return f"""# macOS
.DS_Store

# Worktrees
.worktrees/

# Editors / IDEs
.idea/
.vscode/
*.swp

# Build artifacts
bin/
obj/
build/
*.dll
*.pdb

# Unity generated
Library/
Temp/
Logs/
UserSettings/
*.csproj
*.sln

# Env / secrets
.env
.envrc
.envrc.local

# Superpowers process artifacts — plans and brainstorming scratch, slop once
# the work is implemented. docs/specs/ and docs/adrs/ stay tracked.
docs/superpowers/

# LocalizationGenerator output (regenerated each build from localization/localization.yaml)
unity/{mod_name}/Localization/Generated/
unity/{mod_name}/Localization/Generated.meta

# Shared editor helpers — symlinked in by utils/link.sh (the .cs are symlinks
# into ../utils, the .meta are Unity-generated locally; no asset references
# them by GUID, so neither belongs in the repo).
unity/{mod_name}/Editor/CLIBuildHelper.cs
unity/{mod_name}/Editor/CLIBuildHelper.cs.meta
unity/{mod_name}/Editor/CLIPublishHelper.cs
unity/{mod_name}/Editor/CLIPublishHelper.cs.meta
unity/{mod_name}/Editor/LocalizationGenerator.cs
unity/{mod_name}/Editor/LocalizationGenerator.cs.meta
"""


def build_steam_description(display_name: str, summary: str) -> str:
    """The Steam Workshop item description.

    Deliberately not derived from modio-description.md: the Workshop renders
    **BBCode**, not Markdown, so a shared source would either ship literal `##`
    and `**` on the Steam page or force modio-description.md itself into BBCode,
    which mod.io does not render. Two small files in two dialects cost less than
    one file that is wrong on one of the two platforms."""
    return f"""[b]{display_name}[/b]

{summary}

[h2]Features[/h2]
[list]
[*] Describe what the mod does.
[/list]
"""


def build_changelog() -> str:
    """A starter CHANGELOG. The publish helper reads the top `## [x.y.z]` as the
    version, so a new mod starts at 0.1.0."""
    return """# Changelog

All notable changes to this mod are documented here.

## [0.1.0] - Unreleased

- Initial scaffold.
"""


def build_localization_yaml(mod_name: str) -> str:
    """The mod's localisation table — inert on purpose: every line a comment.

    The wiring is scaffolded *active* (`LOC_YAML`/`LOC_OUT` in the `.envrc`),
    which is only safe because `LocalizationGenerator` skips a table that holds
    no terms. So this file must contain no authored line: a single uncommented
    namespace header would be content yielding no term, which is exactly the case
    the generator fails on. `test_localization_template_is_inert` guards that.
    """
    return f"""# Localisation table for {mod_name} — namespace at indent 0, term at indent 2,
# its values at indent 4. Every build turns this into TextDataBlock assets; a
# table with no terms is skipped, so the file is inert until the first real
# entry. Uncomment and edit:
#
# {mod_name}-Config:
#   enabled:
#     hint: "Master on/off toggle label."
#     en: "Enabled"
#     de: "Aktiviert"
#
# Leaf keys stay unquoted. The generator rejects a U+2026 ellipsis and a U+2014
# em dash in values: the game's thin font crashes on the first and renders the
# second as a plain hyphen. Write '...' and '-'.
"""


def build_csharpierrc() -> str:
    """The formatting-gate CSharpier config. `printWidth` is deliberately 160,
    not CSharpier's default of 100 — matches every existing mod repo (see the
    parent CLAUDE.md's Formatting gate section). Identical across mods, so
    unparameterized."""
    return """{
    "printWidth": 160
}
"""


def build_csharpierignore() -> str:
    """The file that makes the gate above check anything at all.

    CSharpier searches upward for an ignore file and does not stop at a git
    boundary. A mod repo sits inside `core_keeper/`, whose `.csharpierignore` is
    an allowlist (`/*` plus `!/utils/`) guarding the SDK clone and the sibling
    mods from a full-tree run. Without a local file, a scaffolded mod inherits
    that allowlist and every one of its own sources falls outside it: measured
    inside a git repo, `dotnet csharpier check .` reports `Checked 0 files`
    with no local ignore file and `Checked 1 files` with one. The hook passes
    either way, so the gate looks healthy while checking nothing.

    The `.worktrees/` entry is the content this file would have had anyway --
    sibling worktrees carry their own copies of the sources and their own hook.
    Its presence is the load-bearing part."""
    return """# Required, not optional: CSharpier's ignore-file search walks up past this
# repo into core_keeper/, whose .csharpierignore is an allowlist for utils/
# only. Without this file every source here falls outside that allowlist and
# the gate silently checks zero files.
#
# Sibling worktrees live inside the repo and carry their own copies of the
# sources; formatting them from here would fight the worktree's own hook.
.worktrees/
"""


def build_precommit_config() -> str:
    """The repo's three gates, all at `pre-commit` and `pre-push`, matching
    every existing mod repo.

    `csharpier check` blocks, it does not rewrite. `docs-links` runs the
    parent repo's checker over this repo — a dead relative link or an
    `#anchor` with no matching heading is the quietest documentation defect
    there is, since the file still renders and the link is still blue.
    `docs-wrapping` is its sibling and arrived a year later, not because
    nobody wanted it but because that checker took file arguments and died on
    the `.` this entry passes; a mod repo therefore could not run it, and an
    edit that left a 143-column line in one of them committed unopposed.

    Both of those two find the parent by walking up rather than by spelling
    `..`, and that is the same failure a second time: a literal `..` is the
    parent only when the repo sits directly under it, which it does not in the
    worktree the project requires all work to happen in. The hooks could not
    start there at all, so for a second time these gates were absent from
    exactly the path a defect would be introduced on."""
    return """repos:
    - repo: local
      hooks:
          - id: csharpier
            name: csharpier
            entry: dotnet csharpier check
            language: system
            files: \\.cs$
            stages:
                - pre-commit
                - pre-push

          # Both checkers live in the parent repo, not here: this mod repo sits
          # inside it and already reaches for ../utils/ to build and link. Each
          # takes this repo's root, so the scope is `git ls-files` here.
          #
          # The parent is SEARCHED FOR rather than spelled `..`, because `..` is
          # only the parent when the repo sits directly under it. CLAUDE.md
          # requires the work to happen in a worktree at <mod>/.worktrees/<branch>,
          # where `..` is .worktrees/, so the hook aborted before the checker ran:
          # every documentation commit made from a worktree failed with a spawn
          # error rather than being examined. Loud, not silent — which is what
          # made it survivable, and also what made it look like a gate doing its
          # job. Walking up finds the same directory from either place.
          - id: docs-links
            name: docs links
            entry: bash -c 'd=$PWD; while [ "$d" != / ] && [ ! -e "$d/utils/check_docs_links.py" ]; do d=$(dirname "$d"); done; exec uv run --frozen --project "$d" "$d/utils/check_docs_links.py" .'
            language: system
            pass_filenames: false
            files: \\.md$
            stages:
                - pre-commit
                - pre-push

          - id: docs-wrapping
            name: docs wrapping
            entry: bash -c 'd=$PWD; while [ "$d" != / ] && [ ! -e "$d/utils/check_docs_wrapping.py" ]; do d=$(dirname "$d"); done; exec uv run --frozen --project "$d" "$d/utils/check_docs_wrapping.py" .'
            language: system
            pass_filenames: false
            files: \\.md$
            stages:
                - pre-commit
                - pre-push
"""


def build_dotnet_tools_json() -> str:
    """The pinned CSharpier tool manifest. Lives under `.config/`, not the
    repo root — `dotnet new tool-manifest` writes it to the root under .NET
    10, but the convention here is to move it; `dotnet tool restore` accepts
    either location."""
    return """{
  "version": 1,
  "isRoot": true,
  "tools": {
    "csharpier": {
      "version": "1.3.0",
      "commands": [
        "csharpier"
      ],
      "rollForward": false
    }
  }
}
"""


# --- placeholder PNG --------------------------------------------------------


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def placeholder_png_bytes(size: int = 64) -> bytes:
    """A real, valid solid-colour RGBA PNG to stand in until a real logo is
    dropped in. Built from stdlib (zlib) — no image library dependency."""
    pixel = bytes((40, 40, 40, 255))
    raw = b"".join(b"\x00" + pixel * size for _ in range(size))  # filter byte 0 per row
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)  # 8-bit RGBA
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", zlib.compress(raw, 9))
        + _png_chunk(b"IEND", b"")
    )


# --- live DLL scan ----------------------------------------------------------


def scan_dlls(sdk_path) -> list:
    """The game/SDK DLL basenames for the runtime asmdef's precompiled
    references. Scans `Assets/Plugins/CoreKeeper` and `…/CoreKeeperModSDK`
    recursively — exactly the dirs the wizard scans — so the set stays current
    across game updates. Returns sorted, de-duplicated basenames."""
    sdk = pathlib.Path(sdk_path)
    roots = [
        sdk / "Assets" / "Plugins" / "CoreKeeper",
        sdk / "Assets" / "Plugins" / "CoreKeeperModSDK",
    ]
    names = set()
    for root in roots:
        if root.is_dir():
            names.update(p.name for p in root.rglob("*.dll"))
    return sorted(names)


# --- the full file plan -----------------------------------------------------


def build_plan(
    kebab: str,
    *,
    summary: str,
    dll_names,
    fake_mod_id: int,
    required_on: int,
    modio_type: str,
    corelib: bool = False,
    name: str = None,
    display_name: str = None,
):
    """Assemble the complete (relpath, content) plan for a new mod. Content is
    str for text files and bytes for the PNG. All GUIDs are minted here so the
    one cross-reference — the modio asset pointing at the .asset.meta GUID —
    stays internally consistent."""
    mod_name = name or derive_pascal(kebab)
    display = display_name or derive_title(kebab)
    dependencies = [("CoreLib", 1)] if corelib else None

    # Distinct fresh GUIDs.
    metadata_guid = new_guid()  # .asset internal identity (collision-critical)
    asset_meta_guid = new_guid()  # .asset.meta file GUID (modio cross-refs this)
    moddir_guid = new_guid()
    runtime_asmdef_guid = new_guid()
    bootstrap_cs_guid = new_guid()
    editor_dir_guid = new_guid()
    editor_asmdef_guid = new_guid()
    modio_meta_guid = new_guid()
    steam_meta_guid = new_guid()
    logo_guid = new_guid()

    u = "unity"
    md = f"{u}/{mod_name}"
    ed = f"{md}/Editor"
    envrc = build_envrc(mod_name, kebab, summary, fake_mod_id, modio_type)

    return [
        (".envrc", envrc),
        (".envrc.example", envrc),
        (".gitignore", build_gitignore(mod_name)),
        ("CHANGELOG.md", build_changelog()),
        ("steam-description.txt", build_steam_description(display, summary)),
        ("localization/localization.yaml", build_localization_yaml(mod_name)),
        (".csharpierrc", build_csharpierrc()),
        (".csharpierignore", build_csharpierignore()),
        (".pre-commit-config.yaml", build_precommit_config()),
        (".config/dotnet-tools.json", build_dotnet_tools_json()),
        (
            f"{u}/{mod_name}.asset",
            build_asset_yaml(
                mod_name,
                display,
                metadata_guid,
                dependencies,
                required_on=required_on,
            ),
        ),
        (f"{u}/{mod_name}.asset.meta", build_native_asset_meta(asset_meta_guid)),
        (f"{u}/{mod_name}.meta", build_folder_meta(moddir_guid)),
        (
            f"{md}/{mod_name}.asmdef",
            build_runtime_asmdef(mod_name, dll_names, corelib=corelib),
        ),
        (f"{md}/{mod_name}.asmdef.meta", build_asmdef_meta(runtime_asmdef_guid)),
        # Inside the mod folder, unlike the ModBuilderSettings asset a few lines
        # up and unlike the mod.io one under Editor/. Not a choice made here:
        # steam_identity.asset_path computes this location and every publish
        # addresses the file by it, so a scaffold that guessed differently would
        # be read as "this mod has never been published".
        (f"{md}/{mod_name}_Steam.asset", build_steam_asset_yaml(mod_name)),
        (f"{md}/{mod_name}_Steam.asset.meta", build_native_asset_meta(steam_meta_guid)),
        (f"{md}/{mod_name}Mod.cs", build_bootstrap_cs(mod_name)),
        (f"{md}/{mod_name}Mod.cs.meta", build_script_meta(bootstrap_cs_guid)),
        (f"{md}/Editor.meta", build_folder_meta(editor_dir_guid)),
        (f"{ed}/{mod_name}.Editor.asmdef", build_editor_asmdef(mod_name)),
        (f"{ed}/{mod_name}.Editor.asmdef.meta", build_asmdef_meta(editor_asmdef_guid)),
        (
            f"{ed}/{mod_name}_modio.asset",
            build_modio_asset_yaml(mod_name, asset_meta_guid),
        ),
        (f"{ed}/{mod_name}_modio.asset.meta", build_native_asset_meta(modio_meta_guid)),
        (f"{ed}/logo.png", placeholder_png_bytes()),
        (f"{ed}/logo.png.meta", build_texture_meta(logo_guid)),
    ]


def write_plan(plan, dest_dir) -> None:
    """Write a build_plan() result under *dest_dir*, creating parent dirs.
    str content is written as UTF-8 text, bytes content as binary."""
    dest = pathlib.Path(dest_dir)
    for relpath, content in plan:
        target = dest / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(content, encoding="utf-8")


# --- fs-facing orchestration helpers ----------------------------------------


def scan_existing_fake_mod_ids(mods_dir) -> list:
    """The FAKE_MOD_IDs already in use, read from sibling `*/.envrc.example`."""
    ids = []
    for envrc in pathlib.Path(mods_dir).glob("*/.envrc.example"):
        m = re.search(r'FAKE_MOD_ID="?(\d+)"?', envrc.read_text())
        if m:
            ids.append(int(m.group(1)))
    return ids


def run_git(args, cwd):
    """Run a git command with the ambient git environment scrubbed.

    Inside a git hook, `GIT_DIR` / `GIT_INDEX_FILE` and friends are exported and
    take precedence over *cwd* — so `git ls-files` aimed at a sibling repo
    silently reports the *committing* repo's index instead. Every git call in
    this file means "the repo at this directory", which only holds with those
    variables gone. Found by the parity suite running inside the pre-commit hook.
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    return subprocess.run(
        args, cwd=cwd, capture_output=True, text=True, check=False, env=env
    )


def resolve_mods_dir():
    """The directory the sibling mod repos live in — the **main** checkout.

    This file's grandparent is right in the main clone and wrong in a worktree
    (`.worktrees/<branch>/utils/`), where it would scaffold the new mod into the
    worktree — deleted on cleanup — and, finding no siblings there, hand it a
    FAKE_MOD_ID of 9999999, which `disable-durability` already uses. Working in a
    worktree is the norm here, so the ordinary path must not be the broken one.
    git knows where the main checkout is; without git we are not in a worktree
    either, so the plain grandparent is the correct fallback.
    """
    here = pathlib.Path(__file__).resolve().parent
    # A non-zero exit is the "not a git checkout" signal, hence run_git's
    # check=False.
    proc = run_git(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], here
    )
    if proc.returncode == 0 and proc.stdout.strip():
        return pathlib.Path(proc.stdout.strip()).parent
    return here.parent


def resolve_sdk_path(mods_dir, environ):
    """SDK_PATH from the environment, falling back to parsing the parent
    core_keeper/.envrc. Returns None if neither yields it."""
    if environ.get("SDK_PATH"):
        return environ["SDK_PATH"]
    envrc = pathlib.Path(mods_dir) / ".envrc"
    if envrc.is_file():
        m = re.search(r'SDK_PATH="?([^"\n]+)"?', envrc.read_text())
        if m:
            return m.group(1)
    return None


def _git_init_and_commit(target) -> None:
    for cmd in (
        ["git", "init", "-q"],
        ["git", "add", "-A"],
        ["git", "commit", "-q", "-m", "chore: initial mod scaffold"],
    ):
        subprocess.run(cmd, cwd=target, check=True, capture_output=True, text=True)


def _run_link(target, sdk_path, mod_name) -> None:
    link = pathlib.Path(__file__).resolve().parent / "link.sh"
    env = {**os.environ, "SDK_PATH": str(sdk_path), "MOD_NAME": mod_name}
    subprocess.run([str(link), str(target)], check=True, env=env)


def scaffold(
    kebab,
    summary,
    *,
    mods_dir,
    sdk_path,
    required_on,
    modio_type,
    corelib=False,
    name=None,
    display_name=None,
    dry_run=False,
    finalize=True,
):
    """Top-level orchestration: validate, derive identity, scan DLLs, allocate
    the fake mod.io ID, build the file plan, and (unless dry_run) write it +
    git-init + link into the SDK. Returns a result dict for the caller to
    report. Raises FileExistsError if the target already exists."""
    validate_kebab(kebab)
    modio_types = parse_modio_type(modio_type)
    mod_name = name or derive_pascal(kebab)
    display = display_name or derive_title(kebab)
    target = pathlib.Path(mods_dir) / kebab
    if target.exists():
        raise FileExistsError(f"target already exists: {target}")

    dll_names = scan_dlls(sdk_path)
    fake_id = next_fake_mod_id(scan_existing_fake_mod_ids(mods_dir))
    plan = build_plan(
        kebab,
        summary=summary,
        dll_names=dll_names,
        fake_mod_id=fake_id,
        required_on=required_on,
        modio_type="|".join(modio_types),
        corelib=corelib,
        name=name,
        display_name=display_name,
    )
    result = {
        "mod_name": mod_name,
        "display_name": display,
        "target": target,
        "fake_mod_id": fake_id,
        "required_on": required_on,
        "modio_types": modio_types,
        "dll_count": len(dll_names),
        "plan": plan,
        "dry_run": dry_run,
    }
    if dry_run:
        return result

    write_plan(plan, target)
    if finalize:
        _git_init_and_commit(target)
        _run_link(target, sdk_path, mod_name)
    return result


# --- CLI --------------------------------------------------------------------


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Scaffold a new, buildable Core Keeper mod (no Unity Editor)."
    )
    p.add_argument("kebab", help="kebab-case mod id, e.g. faster-pet-talents")
    p.add_argument(
        "--summary", required=True, help="one-line mod.io summary (required)"
    )
    p.add_argument(
        "--required-on",
        dest="required_on",
        type=int,
        choices=(0, 1, 2, 3),
        required=True,
        help=(
            "who needs the mod: 0=neither, 1=Client, 2=Server, 3=both. Required, "
            "and deliberately without a default — the loader's checks are crossed "
            "(the Server flag makes the CLIENT demand the mod on the server), so "
            "a blanket 3 hard-blocks joining unmodded servers. Ask: does the "
            "SERVER need this mod for the feature to work? 1 for read-only "
            "HUD/UI, 3 for items, recipes, database or server-authoritative "
            "logic, 0 for a mod that must never gate a connection either way "
            "(publishes with no Application Type tag)"
        ),
    )
    p.add_argument(
        "--modio-type",
        dest="modio_type",
        required=True,
        metavar="TYPES",
        help=(
            'pipe-separated mod.io "Type" tags, e.g. "Visual|Quality of Life" '
            "(pipes, because the values contain spaces). Required: the publish "
            "aborts when CK_MODIO_TYPE is unset. Known values: Visual, Audio, "
            "Item, NPC, Quality of Life, Overhaul, Language, World, Library, Other"
        ),
    )
    p.add_argument("--name", help="override the derived PascalCase MOD_NAME")
    p.add_argument(
        "--display-name",
        dest="display_name",
        help="override the derived Title-case displayName",
    )
    p.add_argument(
        "--corelib", action="store_true", help="add a CoreLib loader dependency"
    )
    p.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="print the plan and write nothing",
    )
    return p.parse_args(argv)


def main(argv=None) -> int:
    ns = parse_args(argv)
    mods_dir = resolve_mods_dir()
    sdk_path = resolve_sdk_path(mods_dir, os.environ)
    if not sdk_path:
        print(
            "ERROR: SDK_PATH not set and not found in ../.envrc — "
            "source the env first (see README § Build & install).",
            file=sys.stderr,
        )
        return 1

    try:
        result = scaffold(
            ns.kebab,
            ns.summary,
            mods_dir=mods_dir,
            sdk_path=sdk_path,
            required_on=ns.required_on,
            modio_type=ns.modio_type,
            corelib=ns.corelib,
            name=ns.name,
            display_name=ns.display_name,
            dry_run=ns.dry_run,
        )
    except (ValueError, FileExistsError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    print(f"mod:         {result['mod_name']}  ({result['display_name']})")
    print(f"target:      {result['target']}")
    print(f"fake mod id: {result['fake_mod_id']}")
    required_on = result["required_on"]
    print(f"requiredOn:  {required_on} ({REQUIRED_ON_LABELS[required_on]})")
    print(f"mod.io type: {' | '.join(result['modio_types'])}")
    print(f"game DLLs:   {result['dll_count']} scanned")
    if ns.dry_run:
        print(f"\n[dry-run] {len(result['plan'])} files would be written:")
        for relpath, _ in result["plan"]:
            print(f"  {relpath}")
    else:
        print("\n✓ scaffolded, git-initialised, and linked into the SDK.")
        print(
            f"  next: cd {result['target'].name} && source .envrc && ../utils/build.sh"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
