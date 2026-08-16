# Mod anatomy

This chapter describes what a Core Keeper mod consists of, which file is the real
configuration surface, and how the PugMod loader sees it: the `IMod` lifecycle and its
ordering, Harmony auto-discovery, the assembly definitions, the two kinds of dependency,
`requiredOn`, and the GUID rules that matter when you create files by hand. Read it when
a mod does not load, a lifecycle hook fires at the wrong time, or a manifest field does
not seem to take effect.

## What ships, and what the loader reads

A built mod is a directory containing exactly three kinds of payload plus a manifest:

| In the install directory | What it is |
|---|---|
| `Scripts/*.cs` | Your mod's **source**, compiled by Roslyn at load time inside the game process |
| `Bundles/*.assetbundle` | Prefabs, sprites, generated data assets |
| `*.dll` | Precompiled assemblies — only loaded when `accessesExtraAssemblies` is set |
| `ModManifest.json` | Build-generated; the loader's entry point into all of the above |

The loader reads `ModManifest.json` with `JsonUtility.FromJson<ModMetadata>` and then
drives everything off the manifest's `files` list: `Load` splits it into the `.dll`,
`.cs` and `.assetbundle` entries and processes each set.

**Trap: a `.cs` file that is not in the manifest does not exist.** It will not be
compiled, and the sandbox compile then fails on the missing type — invisibly to the
Editor build, which compiled the same file happily against the Editor's own assembly.
After adding a source file, check that it reached both the install `Scripts/` directory
and the generated `ModManifest.json`.

Because the SDK's ModBuilder assigns **every** file under the mod's `modPath` to the
AssetBundle, and Unity imports text files as `TextAsset`s, any `.yaml`/`.md`/`.json`
sitting in the mod folder is baked into the shipped bundle too. The only way to keep a
file out of the bundle is to keep it out of the mod folder.

In the repo, a mod is authored as:

```text
Assets/<Mod>.asset          the ModBuilderSettings asset — the configuration surface
Assets/<Mod>/               the mod folder (metadata.modPath) — sources, prefabs, art
Assets/<Mod>/<Mod>.asmdef   the runtime assembly definition
Assets/<Mod>/Editor/        editor-only helpers, with their own asmdef
```

How that source tree becomes an install directory is the build workflow — see
[the repo README](../../README.md).

## The ModBuilderSettings `.asset` is the configuration surface

`ModBuilderSettings` is a plain `ScriptableObject` holding one `ModMetadata metadata`
struct plus build switches (`modPath`, `forceReimport`, `buildBundles`, `cacheBundles`,
`buildLinux`). At build time the SDK copies that struct, clears and refills its `files`
list with one `{path, guid}` entry per output file, serialises the result with
`JsonUtility.ToJson`, and writes it to `<install>/ModManifest.json`.

So the shipped manifest *is* the `.asset`'s metadata, plus a computed file list. Every
manifest field is edited in the `.asset`.

**Trap: a hand-authored `ModManifest.json` in the repo is read by nothing.** It is not
an input to the build (which regenerates the file wholesale), and it is not the schema
the loader deserialises — keys like `name_id`, `version` or `modDependencies` are
silently ignored by `JsonUtility.FromJson<ModMetadata>`. A stale repo copy will look
authoritative for months and change nothing. Delete it; edit the `.asset`.

### `ModMetadata` fields

| Field | Type | Meaning |
|---|---|---|
| `guid` | `string` | Per-mod identity for the loader (see below). Auto-generated when the asset is created. |
| `name` | `string` | Internal identity. Drives the namespace, the asmdef name, the `ModLoader` temp directory, and the string other mods depend on. |
| `displayName` | `string` | Human-facing title. Used for the mod.io profile name (see [publishing](../publishing.md)). |
| `skipSafetyChecks` | `bool` | Disables the Roslyn sandbox — see [sandbox and config](sandbox-and-config.md). |
| `disableScripts` | `bool` | Skips the whole script compile step; the mod ships assets only. |
| `accessesExtraAssemblies` | `bool` | Required to load a shipped `.dll`; also adds every assembly loaded at game start as a metadata reference for the Roslyn compile. |
| `disableHarmonyPatching` | `bool` | Suppresses the automatic Harmony pass over your compiled assembly. |
| `requiredOn` | `[Flags] ModExistsOn` | Which side must have this mod — see below. |
| `files` | `List<ModFile>` | `{path, guid}` per shipped file. **Build-generated; never hand-authored.** |
| `dependencies` | `List<Dependency>` | `{modName, required}` — the load-order dependencies. |

Without `accessesExtraAssemblies`, loading a shipped `.dll` fails with
`Tried to load dll for <name>, but accessesExtraAssemblies not set`.

### Fields the SDK's Editor GUI gets wrong

Two of these cannot be trusted to the mod-settings inspector:

- **`displayName` is `[HideInInspector]`.** The field is real and is read at build and
  publish time, but the GUI does not draw it. Set it in the `.asset` YAML.
- **`requiredOn` "Client and Server" writes `-1`** ("Everything") rather than `3`. Since
  it is a `[Flags]` enum, `-1` has every bit set, including bits that do not exist. Set
  the numeric value in the YAML.

The relevant block looks like this:

```yaml
  metadata:
    guid: dbe54e8c2157416da620d7bab003d548
    name: ItemChecklist
    displayName: Item Checklist
    skipSafetyChecks: 0
    disableScripts: 0
    accessesExtraAssemblies: 1
    disableHarmonyPatching: 0
    requiredOn: 1
    files: []
    dependencies:
    - modName: CoreLib
      required: 1
  modPath: Assets/ItemChecklist
```

`files: []` in the repo asset is correct and expected — the build fills it.

### `name` versus `displayName`

`metadata.name` is identity, not presentation. It is the key other mods write into their
`dependencies`, the key the dependency sorter builds its graph on, and the directory name
under `Application.temporaryCachePath/ModLoader/`. Renaming it for cosmetic reasons breaks
every dependent mod's manifest entry. Put the pretty title in `displayName` instead — the
internal identity `ItemChecklist` and the shown title `Item Checklist` are allowed to
differ, and normally should.

## The two GUIDs, and the rules for hand-created files

Two unrelated things are called "guid" in a mod, and confusing them produces failures that
look nothing alike.

| GUID | Where | Rule |
|---|---|---|
| Per-asset `.meta` `guid:` | Every `.meta` file Unity generates | Must be unique per asset. When copying a tree by hand, remap each one to a fresh value with a **global** find-replace across all copied files, so internal cross-references stay consistent. |
| `metadata.guid` | Inside the ModBuilderSettings `.asset`, in the `metadata:` block | Not a `.meta` GUID. Regenerate it separately when copying a mod. |
| `m_Script: {guid: …}` on the SDK's own assets | The ModBuilderSettings / Data / `_modio` assets | **Leave untouched.** These point at shared SDK classes, not at your files. |

The `.asset`'s own `.meta` GUID is referenced by the `_modio.asset`'s `modSettings` field,
which is why remapping has to be a global replace rather than per-file edits.

**Trap: a duplicated `metadata.guid` breaks asset loading, not identity.** The loader
registers each mod's asset-bundle data-block loader under that GUID
(`ScriptableData.AddDataBlocksLoader(mod.Metadata.guid, …)`), so a second mod carrying the
same value produces `Data block loader already added for key <guid>`. This is the usual
outcome of scaffolding a new mod by copying a sibling and remapping only the `.meta`
files.

## The `IMod` lifecycle

`IMod` lives in namespace `PugMod` and has five methods plus one defaulted:

```csharp
public interface IMod
{
    void EarlyInit();
    void Init();
    void Shutdown();
    void ModObjectLoaded(UnityEngine.Object obj);
    bool CanBeUnloaded() => false;
    void Update();
}
```

The loader instantiates every `IMod` implementation it finds in your compiled assembly,
so a mod may have more than one handler. Conventionally the bootstrap `IMod` class and the
`[HarmonyPatch]` classes live in separate files.

| Method | When it runs | What is safe here |
|---|---|---|
| `EarlyInit()` | Immediately after your mod's assemblies are loaded, in dependency order | Resolve your own `LoadedMod` via `API.ModLoader.LoadedMods`; load framework submodules; register keybinds. `API.ConfigFilesystem` is already initialised. |
| `ModObjectLoaded(obj)` | Once per asset loaded from your bundles, right after your `EarlyInit` | Capture and register prefabs by name. This is the only place you see your own loaded assets. |
| `Init()` | On the **first loader `Update` tick** after loading, once per handler | Anything needing a running game loop. The game database is *not* baked yet. |
| `Update()` | Every frame, after `Init` | Hotkey polling, timers. |
| `Shutdown()` | On mod reset/reload, **before** the asset bundles are unloaded and before the Harmony patches are undone | Persist state; drop references to bundle-owned objects. |
| `CanBeUnloaded()` | Polled before a hot reload | Returning `false` (the default) blocks the reload, logging `Mod reload blocked by <type>`. |

### Ordering details that matter

`EarlyInit` and `ModObjectLoaded` are **interleaved per mod**, not run as two global
phases. The loader walks the sorted mod list and, for each mod, calls `EarlyInit` on all
its handlers and then `ModObjectLoaded` for each of its assets — before moving to the next
mod. So your `ModObjectLoaded` runs before a later mod's `EarlyInit`, and a dependency's
`ModObjectLoaded` has already run by the time yours does.

`Init` is **not** part of the load pass. The loader calls it from its own `Update`, guarded
by a per-handler "already initialised" flag, and then immediately calls `Update`. That is
why `Init` is the earliest point with a live frame loop — and why it is still too early for
anything that requires the game's object database to be populated.

**On a dedicated server the relative order of `Init` and ECS startup differs from the
client.** That has concrete consequences for Burst-disabling; see
[Harmony and ECS](harmony-and-ecs.md).

**Trap: only the first lifecycle exception is ever logged.** The loader wraps `Init`,
`Update`, `Shutdown` and the post-load `ModObjectLoaded` in try/catch blocks that share a
single `_hasPrintedException` latch. Once *any* mod throws once from *any* of those, every
later exception from every mod is swallowed silently for the rest of the process. A
per-frame `NullReferenceException` in `Update` therefore shows up as one stack trace and
then nothing. `EarlyInit` and the load-time `ModObjectLoaded` calls sit outside that latch
and always log.

## Harmony patches are auto-discovered

You do not call `Harmony.PatchAll()`. After compiling your scripts the loader hands your
whole assembly to its Harmony bootstrap, which discovers the `[HarmonyPatch]` classes
itself. Two metadata fields govern the pass:

- `disableHarmonyPatching` skips it entirely.
- `skipSafetyChecks` selects whether the patch pass runs verified or unverified — the same
  switch that controls the [Roslyn sandbox](sandbox-and-config.md).

Failures are logged as `mod <name>: patching failed` and do **not** abort the load, so a
mod whose patches never bound still reports as loaded. On reload the loader undoes your
patches (unless `disableHarmonyPatching` is set) as part of the same reset that calls
`Shutdown`.

Whether a given patch actually *binds* — generated DOTS code, Burst, method signature
matching — is a separate problem, covered in [Harmony and ECS](harmony-and-ecs.md).

## Assembly definitions

### The runtime asmdef

The SDK's "Create New Mod" wizard emits the runtime `.asmdef` already populated with the
full game-DLL reference set, so mod code compiles against game types and Harmony out of
the box. Its shape:

| Key | Value | Why |
|---|---|---|
| `references` | The `Unity.*` DOTS assemblies (`Unity.Entities`, `Unity.Burst`, `Unity.Collections`, `Unity.Mathematics`, `Unity.NetCode`, `Unity.Physics`, `Unity.Transforms`, …) plus `PugMod.SDK` | Managed assembly references |
| `precompiledReferences` | The shipped game DLLs, exhaustively — `Pug.Base.dll`, `Pug.Other.dll`, `Pug.ECS.Components.dll`, `Pug.ECS.Authoring.dll`, `ScriptableData.dll`, `I2.dll`, `Rewired.dll`, `0Harmony.dll`, and the BCL assemblies | The game itself |
| `overrideReferences` | `true` | Required for `precompiledReferences` to be honoured |
| `autoReferenced` | `false` | Keeps the mod assembly out of Unity's default reference graph |

You normally never edit this list. The exception is a **framework dependency**: adding
CoreLib or another mod requires *two* independent edits — the assembly name in
`references` (so `using CoreLib;` compiles) **and** a `dependencies` entry in the `.asset`
(so it loads and compiles first). Doing only one of them is a classic scaffolding defect:
either the Editor build fails on an unresolved namespace, or it succeeds and the mod fails
at runtime in the sandbox compile.

### Why an editor helper needs its own `*.Editor.asmdef`

`ModBuilder` and `ModBuilderSettings` are editor-only types, living in an editor-only
assembly. A combined runtime+editor asmdef cannot reference an editor-only one, so any
build/publish helper you drive with `unity -batchmode -executeMethod` must sit in its own
assembly:

```json
{
    "name": "<Mod>.Editor",
    "references": ["<Mod>", "ModSDK.Editor", "PugMod.SDK"],
    "includePlatforms": ["Editor"],
    "overrideReferences": true,
    "precompiledReferences": ["modio.UnityPlugin.dll"],
    "autoReferenced": false
}
```

`includePlatforms: ["Editor"]` is what makes it editor-only; `ModSDK.Editor` is what gives
it `ModBuilder`.

## Dependencies: two concepts, only one of which compiles

| | Manifest dependency | Platform dependency |
|---|---|---|
| Declared in | The `.asset`'s `dependencies` list → the generated `ModManifest.json` | The mod.io listing |
| Read by | The PugMod loader | mod.io |
| Effect | **Compile order** — a topological sort so the dependency's assembly exists as a metadata reference when your scripts compile | **Auto-install** — subscribers receive the dependency and it appears in the in-game mod list |

They are independent, and setting only the platform one produces a contradiction that
looks impossible: CoreLib is installed, visibly loaded, and your mod still fails with
`CS0246`/`CS0103` on every CoreLib type. The reason is that your mod was compiled *before*
CoreLib, so CoreLib's assembly was not yet among the metadata references.

The loader's `ModSorter.SortMods` does the work:

1. It indexes every mod by `metadata.name`.
2. It scans the mod list backwards; a mod with a **required** dependency whose name is not
   in the index is dropped, logging
   `skipping mod <name> because of missing dependency: <dep>`.
3. It builds a dependency graph from the surviving `dependencies` entries and
   depth-first-visits it, producing the load and compile order. A cycle logs
   `<name> has circular dependency` and is broken rather than resolved.

**Trap: a missing required dependency drops your mod with no in-game feedback.** That
warning line is the only signal — there is no dialogue and no error toast. To the player,
the mod simply is not there: no UI, no hotkey, nothing to click. If you ship a hard
dependency, document that symptom.

**Trap: at most one mod is dropped per pass.** The removal loop `break`s as soon as it
removes a mod, so a second mod with a missing required dependency is neither warned about
nor removed in that pass — it stays in the load list and fails later at the compile step
instead.

To read the *actual* compile order at runtime, look for the loader's
`Creating modified script files at …ModLoader\<Mod>` lines. They are ordered by compile,
unlike the `loaded mod …` lines. A correctly declared dependent shows its dependency's
line first.

For which mods are auto-installed alongside yours, see [publishing](../publishing.md).

## `requiredOn` and its crossed checks

`ModMetadata.requiredOn` is a `[Flags]` enum in `PugMod.SDK`:

| Value | Member | Meaning |
|---|---|---|
| `0` | `None` | Enforce nothing in either direction |
| `1` | `Client` | |
| `2` | `Server` | |
| `3` | `ClientAndServer` | |

**The checks are crossed**, which is the part that is easy to get backwards:

| Check site | Test | Effect |
|---|---|---|
| `NetworkClientStartSystem` (`Pug.Other`, decompiled ~124928) | `requiredOn & ModExistsOn.Server` | The **Server** flag makes the **client** demand the mod on the server |
| `ModInfoRpcSystem` (`Pug.Other`, decompiled ~125929) | `requiredOn & ModExistsOn.Client` | The **Client** flag makes the **server** demand it on the client |

A mod without the relevant flag is removed from the check list entirely and never
interferes with a connection.

### Choosing a value

The question to ask is: **does the server need this mod for it to work?**

| Pick | For |
|---|---|
| `1` (Client) | Read-only HUD and UI mods. They must not block joining unmodded servers. |
| `2` (Server) | Mods with no client side at all — world, spawn or simulation changes with no UI. |
| `3` | Both sides genuinely need it: new items, recipe or database changes, server-authoritative inventory or progression logic, or a framework whose consumers may run server-side. |
| `0` | Enforcement *and* side-of-execution are both honestly "either" — e.g. a pure diagnostic that must never gate a connection in either direction. This is a legitimate loader value; CoreLib itself ships it. |

**Do not default to `3`.** An over-broad value is a hard block, not a hint: joining a
server that lacks a `Server`-flagged mod raises a dialogue whose only options are to
disable the mod (and restart) or cancel the connection. What exactly a mismatch does to a
join, on either side, is covered in
[multiplayer and server](multiplayer-and-server.md); `requiredOn` also feeds a mod.io
catalogue tag, which is described in [publishing](../publishing.md).
