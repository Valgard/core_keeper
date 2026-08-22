# Mod anatomy

This chapter describes what a Core Keeper mod consists of, which file is the
real configuration surface, and how the PugMod loader sees it: the `IMod`
lifecycle and its ordering, Harmony auto-discovery, chat commands, the assembly
definitions, the two kinds of dependency, `requiredOn`, and the GUID rules that
matter when you create files by hand. Read it when a mod does not load, a
lifecycle hook fires at the wrong time, or a manifest field does not seem to
take effect.

## What ships, and what the loader reads

A built mod is a directory of payload plus a manifest. Five kinds ship, and only
`Bundles/` is actually an AssetBundle — the other four are copied verbatim by their own
build passes, which remove their hits from the asset list before `BuildAssets` bundles
what remains:

| In the install directory | What it is |
|---|---|
| `Scripts/*.cs` | Your mod's **source**, compiled by Roslyn at load time inside the game process |
| `Bundles/*.assetbundle` | Prefabs, sprites, generated data assets |
| `Libraries/*.dll` | Precompiled assemblies — only loaded when `accessesExtraAssemblies` is set |
| `Conf/*.json` | Configuration, copied as-is by `BuildConf` |
| `Localization/*.csv` | Translation tables, copied as-is by `BuildLocalization` |
| `ModManifest.json` | Build-generated; the loader's entry point into all of the above |

The loader reads `ModManifest.json` with `JsonUtility.FromJson<ModMetadata>` and then
drives everything off the manifest's `files` list: `Load` splits it into the `.dll`,
`.cs` and `.assetbundle` entries and processes each set.

**Trap: a `.cs` file that is not in the manifest does not exist.** It will not be
compiled, and the sandbox compile then fails on the missing type — invisibly to the
Editor build, which compiled the same file happily against the Editor's own assembly.
After adding a source file, check that it reached both the install `Scripts/` directory
and the generated `ModManifest.json`.

Because the SDK's ModBuilder assigns everything under the mod's `modPath` to the
AssetBundle, and Unity imports text files as `TextAsset`s, a stray `.yaml` or `.md`
sitting in the mod folder is baked into the shipped bundle too. Three things keep a file
out: keeping it out of the mod folder, putting it in an `Editor/` or `CodeGen/`
subdirectory of it, or having it claimed by one of the verbatim-copy passes —
`BuildConf` and `BuildLocalization` remove every `.json` under `Conf/` and every `.csv`
under `Localization/` from the bundle's asset list before it is built, exactly as
`BuildScripts` and `BuildLibraries` do for `.cs` and `.dll`. `ModBuilder.BuildAssets`
skips every asset whose path passes through a directory of either name on the way up to
`modPath` — the same `IsInEditorFolder` filter that keeps editor-only `.cs` out of the
shipped `Scripts/` and editor-only DLLs out of the shipped assemblies. That is why a
mod's `Editor/logo.png` and its `Editor/<Mod>_modio.asset` sit inside the mod folder and
still do not ship.

In the repo, a mod is authored as:

```text
Assets/<Mod>.asset          the ModBuilderSettings asset — the configuration surface
Assets/<Mod>/               the mod folder (metadata.modPath) — sources, prefabs, art
Assets/<Mod>/<Mod>.asmdef   the runtime assembly definition
Assets/<Mod>/Editor/        editor-only helpers, with their own asmdef
```

How that source tree becomes an install directory is a build step; one arrangement of it
is in [organising a mod project](organising-a-mod-project.md).

### What the "Create Mod" wizard actually creates

`ModBuilderWindow.CreateNewMod` emits four things inside the project: the
ModBuilderSettings `.asset`, the runtime `.asmdef`, the mod folder, and the `.meta`
GUIDs that go with them. It also registers the mod's `Data/` folder as a scriptable-data
context and marks it for overloading — the one effect that reaches outside the mod's own
files.
Its template-unpacking step is a no-op in this SDK clone — the `ModTemplate.zip` it looks
for is not present.

The one wizard step with no equivalent outside the Editor is
`ScriptableDataEditorUtility.AddContext`, a call into a compiled SDK assembly that
registers the mod's `Data/` folder as a scriptable-data context. **Only an item or content
mod needs that step.** A pure script mod — Harmony patches, UI — has no `Data/` directory,
so everything the wizard would do for it is ordinary file creation.

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
| `displayName` | `string` | Human-facing title. Used for the mod.io profile name (see [publishing](publishing.md)). |
| `skipSafetyChecks` | `bool` | Disables the Roslyn sandbox — see [the load-time sandbox](sandbox.md). |
| `disableScripts` | `bool` | Skips the whole script compile step; the mod ships assets only. |
| `accessesExtraAssemblies` | `bool` | Required to load a shipped `.dll`; also adds every assembly loaded at game start as a metadata reference for the Roslyn compile. |
| `disableHarmonyPatching` | `bool` | Suppresses the automatic Harmony pass over your compiled assembly. |
| `requiredOn` | `[Flags] ModExistsOn` | Which side must have this mod — see below. |
| `files` | `List<ModFile>` | `{path, guid}` per shipped file. **Build-generated; never hand-authored.** |
| `dependencies` | `List<Dependency>` | `{modName, required}` — the load-order dependencies. |

Without `accessesExtraAssemblies`, loading a shipped `.dll` fails with
`Tried to load dll for <name>, but accessesExtraAssemblies not set`.

### There is no mod version at runtime

That table is the whole of `ModMetadata`, and the runtime `LoadedMod` wrapper around it
adds only `ModId`, `Handlers`, `Assets`, `AssetBundles` and `GetFile(string path)`. The
last reads any shipped file from the install directory — a path-traversal guard, then
`File.ReadAllBytes`, both inside the trusted assembly, so it costs nothing against the
sandbox. **No version field exists anywhere in the loader's view of a mod.** A mod that
wants to know which build of itself — or of another mod — is running has to derive it.

The one derivable identifier is the **modfile ID**. Installations live in a directory
named `<modId>_<modfileId>`, and `API.ModLoader.GetDirectory(long modId)`
(`PugMod.SDK.Runtime`) hands you that path as a `string`. Splitting a string needs no
`System.IO`, so the derivation is [sandbox](sandbox.md)-legal. Whether a locally installed development
build yields a parsable ID this way is untested.

**Trap: the GUIDs in `files` are not a version hash.** They are per-asset GUIDs, and the
list only changes when a file is added or removed. A release that changes nothing but C#
source produces an identical set — so `files` used as a version proxy is not merely
approximate, it is silently wrong for exactly the case you most want to detect.

### Fields the SDK's Editor GUI gets wrong

Two of the metadata fields cannot be trusted to the mod-settings inspector:

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

The two `m_Script` values are the same in every mod, so you can check a suspect file
against them directly:

| File | `m_Script.guid` | Binds to |
|---|---|---|
| `<Mod>.asset` | `bc43e4983a160e543856e5ba0421c9e1` | The SDK's `ModBuilderSettings` class |
| `<Mod>_modio.asset` | `d83df2ae64ce1e94f9c006b9d326bf02` | The SDK's mod.io settings class |

They are stable across SDK clones — every mod built against this SDK carries the same
pair — but they are the SDK's own asset GUIDs, so an SDK update can in principle move
them. Treat a mismatch as something to verify, not as proof of corruption.

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

The loader instantiates every **public** `IMod` implementation it finds in your
compiled assembly — the search passes `includeNonPublic: false`, so an `internal`
bootstrap class is skipped silently, with no log line to say your mod did nothing —
so a mod may have more than one handler. Conventionally the bootstrap `IMod` class and the
`[HarmonyPatch]` classes live in separate files.

| Method | When it runs | What is safe here |
|---|---|---|
| `EarlyInit()` | After **all** mods have compiled and loaded, in dependency order — the loader runs a full load pass over the whole sorted list first, then a second pass that calls `EarlyInit` | Resolve your own `LoadedMod` via `API.ModLoader.LoadedMods`; load framework submodules; register keybinds. `API.ConfigFilesystem` is already initialised. |
| `ModObjectLoaded(obj)` | Once per asset loaded from your bundles, right after your `EarlyInit` | Capture and register prefabs by name. This is the only place you see your own loaded assets. |
| `Init()` | On the **first loader `Update` tick** after loading, once per handler | Anything needing a running game loop. The game database is *not* baked yet. |
| `Update()` | Every frame, after `Init` | Hotkey polling, timers. |
| `Shutdown()` | On mod reset/reload, **before** the asset bundles are unloaded and before the Harmony patches are undone | Persist state; drop references to bundle-owned objects. |
| `CanBeUnloaded()` | Polled before a hot reload | Returning `false` (the default) blocks the reload, logging `Mod reload blocked by <type>`. |

### Reaching your own `LoadedMod` and asset bundle

Nothing is handed to you — you look yourself up in the loader's list, matching on your
internal `metadata.name`. The bundle handle that [prefab and sprite loading](prefabs-and-rendering.md)
needs comes off the same object:

```csharp
foreach (var mod in API.ModLoader.LoadedMods)
{
    if (mod.Metadata.name == ModName)
    {
        _bundle = mod.AssetBundles.FirstOrDefault();
        break;
    }
}
```

`EarlyInit` is early enough for this.

### Ordering details that matter

`EarlyInit` and `ModObjectLoaded` are **interleaved per mod**, not run as two global
phases. The loader walks the sorted mod list and, for each mod, calls `EarlyInit` on all
its handlers and then `ModObjectLoaded` for each of its assets — before moving to the next
mod. So your `ModObjectLoaded` runs before a later mod's `EarlyInit`, and a dependency's
`ModObjectLoaded` has already run by the time yours does.

**Against the *game's* own boot code there is no such guarantee.** If a patch of yours
fires from a game initialiser — `TextManager.Init2`, for instance — and needs an asset out
of your bundle, whether that initialiser runs before or after your `ModObjectLoaded` is
not established in either direction. Do not pick a winner. Write a single idempotent
`TryApply()` that checks both preconditions and returns early unless both hold, and call
it from *both* sites: whichever runs second is the one that does the work, and every
further call is a no-op.

`Init` is **not** part of the load pass. The loader calls it from its own `Update`, guarded
by a per-handler "already initialised" flag, and then immediately calls `Update`. That is
why `Init` is the earliest point with a live frame loop — and why it is still too early for
anything that requires the game's object database to be populated.

**On a dedicated server the relative order of `Init` and ECS startup differs from the
client.** That has concrete consequences for Burst-disabling; see [Harmony and ECS](harmony-and-ecs.md).

**Trap: only the first `Init` or `Update` exception is ever logged.** `ModContainer`
wraps four lifecycle methods, but only `Init` and `Update` are ever *dispatched* through
it — `EarlyInit`, `ModObjectLoaded` and `Shutdown` are called on the handler directly.
The two that go through the wrapper have try/catch blocks that share a single
`_hasPrintedException` latch. Once *any* mod throws once from either, every later
exception from every mod is swallowed silently for the rest of the process. A per-frame
`NullReferenceException` in `Update` therefore shows up as one stack trace and then
nothing. `EarlyInit`, `ModObjectLoaded` and `Shutdown` are invoked on a different path —
the load pass and the reset routine call them directly — and always log.

### The world-load anchor

No lifecycle method is late enough to touch the ECS world or the finished object database,
and the obvious "later" candidates are worse than useless: `PugDatabase.UpdateEntityMonos`,
`SaveManager.SetWorldId` and `IMod.Init` itself all throw a `NullReferenceException` whose
message points at nothing.

The anchor that works is a Harmony postfix on `PlayerController.OnOccupied` that starts a
coroutine on the player instance:

```csharp
[HarmonyPatch(typeof(PlayerController), nameof(PlayerController.OnOccupied))]
public static class WorldLoadHook
{
    [HarmonyPostfix]
    public static void Postfix(PlayerController __instance)
    {
        __instance.StartCoroutine(AfterWorldLoad());
    }

    private static IEnumerator AfterWorldLoad()
    {
        yield return new WaitUntil(() => Manager.main != null && Manager.main.player != null);
        // first database or ECS query goes here
    }
}
```

**The `WaitUntil` condition is already true when it is reached — that is the point.** At
`OnOccupied` both `Manager.main` and `Manager.main.player` exist, so this is not a
readiness test; it is a deliberate one-frame settle. Yielding gives the ECS world an update
cycle to bring up its singletons — the localisation sources, the database bank — before
your first query or before `GetObjectName(localize: true)` runs. Read as a guard the line
looks redundant and invites deletion; it is a proxy for "a frame has passed", not a signal,
and removing it produces the worst failure shape there is: correct-looking code that fails
sporadically.

**What this anchor does *not* guarantee is a populated ECS world.** It fires early
enough that a one-shot probe taken here can pin an empty or wrong world for the rest of
the session — see [reading the live ECS world](harmony-and-ecs.md). The yield above buys one update cycle,
which is enough for the managed state this hook is for and not enough to make a world
probe safe. Anything scanning entities needs a re-probe path rather than a single
anchored read.

This is the anchor for *reading* the world and the baked database. It is **not** the
anchor for changing baked data — that has to happen far earlier, from `EarlyInit`; see [database and baking](database-and-baking.md).

## Harmony patches are auto-discovered

You do not call `Harmony.PatchAll()`. After compiling your scripts the loader hands your
whole assembly to its Harmony bootstrap, which discovers the `[HarmonyPatch]` classes
itself. Two metadata fields govern the pass:

- `disableHarmonyPatching` skips it entirely.
- `skipSafetyChecks` selects whether the patch pass runs verified or unverified — the same
  switch that controls the [Roslyn sandbox](sandbox.md).

Failures are logged as `mod <name>: patching failed` and do **not** abort the load, so a
mod whose patches never bound still reports as loaded. On reload the loader undoes your
patches (unless `disableHarmonyPatching` is set) as part of the same reset that calls
`Shutdown`.

Whether a given patch actually *binds* — generated DOTS code, Burst, method signature
matching — is a separate problem, covered in [Harmony and ECS](harmony-and-ecs.md).

## Chat commands

A chat command is a trigger a player types in chat that runs code in your mod. The game
exposes no mod-facing API for *chat* commands. It does ship one for the developer
console — `PugMod.SDK.Runtime`'s `[CommandWithModSupport]`, a subclass of Quantum
Console's `CommandAttribute` and the attribute Pugstorm's own `Pug.Dev` commands carry —
but that is a different surface with a different audience. Chat commands come from
**CoreLib's `CommandModule`**. A mod that offers one therefore takes a hard CoreLib
dependency — which means both the assembly reference and the `.asset` entry, as under [dependencies](#dependencies-two-concepts-only-one-of-which-compiles)
below.

Registration happens in `EarlyInit()`, in three steps:

1. Resolve your own `LoadedMod` (as above), giving you `modInfo.ModId`.
2. Load `CommandModule` — CoreLib submodules are opt-in and must be loaded before use.
3. Call `CommandModule.AddCommands(modInfo.ModId, Name)`, where `Name` is your mod's name.

That one call covers both kinds of command: `AddCommands` reflects over your assembly and
takes every type assignable to either handler interface. A handler whose `GetTriggerNames()`
returns an empty array is dropped with a log warning and nothing else.

**CoreLib does not dispatch commands server-side only.** `CommandCommSystem` is registered
for `ServerSimulation | ClientSimulation`, so a copy of it runs in **both** worlds and
branches on `isServer` into `ServerHandleMessages()` or `ClientHandleMessages()`. Which
branch ends up running your body is decided by the interface you implement:

| Interface | `Execute` signature | Body runs in |
|---|---|---|
| `IServerCommandHandler` | `CommandOutput Execute(string[] parameters, Entity sender)` | the server world |
| `IClientCommandHandler` | `CommandOutput Execute(string[] parameters)` — no `sender` | the client world |

Both inherit `ICommandInfo`, which supplies `GetTriggerNames()` — an array, so one handler
may answer to several triggers — and `GetDescription()`.

**Trap: implementing both interfaces does not get you both.** CoreLib tests
`typeof(IServerCommandHandler).IsAssignableFrom(handlerType)` on the registered type
first and takes the server path whenever that holds, so the client `Execute` is never
called.

**Either way the server sees the command first.** The chat window RPCs the typed line to the
server; the server resolves the trigger and applies its permission check, and only then
either executes a server handler itself or relays the line back for the client to run in
`ClientHandleCommand`. A client command is still refusable by the server — it is client-side
in *where its body runs*, not in how it is dispatched.

### Where a command body runs, and what is allowed there

This is the **server** case. CoreLib's `CommandCommSystem` is itself a
`PugSimulationSystemBase`, and handlers are invoked from its `OnUpdate()`. An
`IServerCommandHandler.Execute` body therefore runs **on the ServerWorld main thread, inside
the ECS frame**. Two consequences:

- **Writing to existing components is fine.** You are on the main thread inside a system
  update — the same position from which [reading and writing the live ECS world](harmony-and-ecs.md)
  is described.
- **Creating or destroying entities is not.** Structural changes from inside a running
  system are the standard ECS prohibition, applied here for the ordinary reason; this
  boundary has not been probed empirically in a command body.

## Assembly definitions

### The runtime asmdef

The SDK's "Create New Mod" wizard emits the runtime `.asmdef` already populated with the
full game-DLL reference set, so mod code compiles against game types and Harmony out of
the box. Its shape:

| Key | Value | Why |
|---|---|---|
| `references` | The `Unity.*` DOTS assemblies (`Unity.Entities`, `Unity.Burst`, `Unity.Collections`, `Unity.Mathematics`, `Unity.NetCode`, `Unity.Physics`, `Unity.Transforms`, …) plus `PugMod.SDK` | Managed assembly references. A hard-coded 14-entry constant list in the wizard — it is not derived from anything. |
| `precompiledReferences` | Every `*.dll` found by recursively scanning `Assets/Plugins/CoreKeeper` and `Assets/Plugins/CoreKeeperModSDK`, reduced to file names in whatever order the directory scan returned — `Pug.Base.dll`, `Pug.Other.dll`, `Pug.ECS.Components.dll`, `Pug.ECS.Authoring.dll`, `ScriptableData.Addressables.dll`, `I2.dll`, `Rewired.dll`, `0Harmony.dll`, the BCL assemblies | The game itself |
| `overrideReferences` | `true` | Required for `precompiledReferences` to be honoured |
| `autoReferenced` | `false` | Keeps the mod assembly out of Unity's default reference graph |

The distinction between the two lists answers a question that comes up after every game
update. `precompiledReferences` is not a constant the SDK maintains, but it is not a live
scan either: the wizard scanned the installed game and SDK assemblies at the moment it
created your mod and froze the result into the asmdef. Nothing re-runs that scan at build
time. So an update that refreshes those DLLs **in place** leaves the list correct and
there is nothing to re-sync — but an update that *adds* an assembly never reaches an
existing mod's asmdef, and neither does anything the original scan missed. That is what
the trap below is about, and why two mods scaffolded at different times against the same
SDK clone carry lists of different lengths.

You normally never edit this list. There are two exceptions.

The first is a **framework dependency**: adding CoreLib or another mod requires *two*
independent edits — the assembly name in `references` (so `using CoreLib;` compiles)
**and** a `dependencies` entry in the `.asset` (so it loads and compiles first). Doing only
one of them is a classic scaffolding defect: either the Editor build fails on an unresolved
namespace, or it succeeds and the mod fails at runtime in the sandbox compile.

The second is a game type whose DLL the scan did not pick up.

**Trap: broad is not exhaustive.** Using a game type directly whose assembly is missing
from `precompiledReferences` fails the Editor compile with `CS0012` — "defined in an
assembly that is not referenced" — for a type that is plainly part of the game. Two that
have come up:

| Type | Lives in | Note |
|---|---|---|
| `SpriteObject` | `PugSprite.dll` | The type's own assembly was missing from the list |
| `GradientMapDataBlock` | `PugSprite.dll` — but its base type `ScriptableDataBlock` is in `ScriptableData.dll` | The asmdef carried `PugSprite.dll` and `ScriptableData.Addressables.dll` but not `ScriptableData.dll`. `CS0012` names the assembly of the **base** type, so the DLL you have to add is not the one the type you used lives in |

Adding the missing DLL to `precompiledReferences` by hand is the sanctioned fix. Unity
assembly definitions have no package manager — hand-editing the list is how they are
maintained, and doing so is not a workaround.

### Using an assembly the game loads but does not expose

Some assemblies are live in the running game without being part of what the SDK wires up
for mods — mod.io's `modio.UnityPlugin` is the case that has come up. Calling into one from
mod source needs **two independent switches, because two different compilers are
involved**:

| Switch | Where | Which compiler it satisfies |
|---|---|---|
| `accessesExtraAssemblies: 1` | The `.asset`'s `metadata` block | The **Roslyn compile at load time**: with it set, the loader adds every assembly loaded at game start as a metadata reference |
| The DLL in `precompiledReferences` | The **runtime** asmdef | The **Unity Editor build**, which happens long before the loader exists |

**Trap: the runtime asmdef may not carry `modio.UnityPlugin.dll`.** The wizard writes
exactly one asmdef — the runtime one — and its `precompiledReferences` is the frozen scan
described above, so whether the DLL is in there at all depends on when the mod was
scaffolded. Where it is missing, the DLL is usually present only in the hand-written
`*.Editor.asmdef` (see the example below), which does nothing for your runtime assembly.
Set only the metadata switch and the Editor build fails with `CS0246` — an unknown-type
error that reads like a loader or sandbox problem and is neither, because neither is
running yet. Check the runtime asmdef and add the DLL there too.

Neither switch requires giving up the sandbox; this works with `skipSafetyChecks: 0`. What
is established here is the two-switch mechanism. Whether a particular foreign assembly's
API is then usable in practice is a separate question per assembly — for
`modio.UnityPlugin` specifically that has not been carried through to a working build.

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

The loader's `DependencySorter.SortMods` does the work:

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

To read the *actual* compile order at runtime, look for the loader's `Creating modified
script files at …ModLoader\<Mod>` lines. They are ordered by compile, unlike the `loaded
mod …` lines. A correctly declared dependent shows its dependency's line first.

For which mods are auto-installed alongside yours, see [publishing](publishing.md).

A mod that silently is not there — the symptom both traps above produce — has its own
symptom-first index: [troubleshooting](troubleshooting.md).

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
| `NetworkClientStartSystem` (`Pug.Other`, decompiled ~124928) | `localMod.required = (requiredOn & ModExistsOn.Server) != 0` | The **Server** flag makes the **client** demand the mod on the server |
| `ModInfoRpcSystem` (`Pug.Other`, decompiled ~125929) | `required = (requiredOn & ModExistsOn.Client) != 0` | The **Client** flag makes the **server** demand it on the client |

A mod without the relevant flag is removed from the check list, but by two different
mechanisms depending on direction: on the server side, `localMods.RemoveAt`
(~124944-124946) drops it outright; on the client side, the server reports `required =
false` for it and the client never adds it to `modsToCheck` in the first place
(~124577-124578). Either way it never interferes with a connection.

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
disable the mod (and restart) or cancel the connection. What exactly a mismatch does to
a join, on either side, is covered in [multiplayer and server](multiplayer-and-server.md); `requiredOn` also feeds a
mod.io catalogue tag, which is described in [publishing](publishing.md).

## The in-game mod menu, and when mod.io is contacted

The mod browser behind the main menu is not Pugstorm's UI.
`RadicalMainMenuOption_OpenMods` (`Pug.Other`, decompiled ~338577) calls `Browser.Open()`
on mod.io's embedded drop-in UI package — `modio.UI.dll`, namespace `ModIOBrowser`.
Pugstorm embedded it rather than rebuilding it, so what you see there is mod.io's
behaviour, not the game's.

That matters for when the game learns that a mod has a new release.
`ModIOUnity.FetchUpdates()` has four callers, all four inside that embedded UI:

| Caller | When |
|---|---|
| `Browser.IsInitialized()` | Opening the mod menu (`Browser.Open()` runs into it) — and only when the session is already authenticated |
| `Authentication.CodeSubmitted(Result)` | After an email-code login succeeds |
| `Authentication.ThirdPartyAuthenticationSubmitted(…)` | After a Steam/portal login succeeds |
| `Collection.CheckForUpdates()` | The "check for updates" button in that same UI |

**There is no timer and no startup hook.** A session that never opens the mod menu and
never authenticates from it never asks mod.io whether anything changed.
`ModIOUnity.EnableModManagement(...)` has four call sites of its own, all in the same UI
and three of them the same members — in `Browser.IsInitialized()` it sits *after* the
authentication branch and therefore runs unconditionally. So the automatic
download-and-install machinery is likewise armed only by going through that UI.

The locally held state, by contrast, is readable at any time with no network traffic:
`ModIOUnity.GetSubscribedMods(out Result)` returns entries of

```csharp
SubscribedMod { SubscribedModStatus status; string directory; ModProfile modProfile; bool enabled; }
```

with the status enum at `modio.UnityPlugin`, decompiled ~29014. Reaching any of this from
mod source is the two-switch case described above under *Using an assembly the game loads
but does not expose*.
