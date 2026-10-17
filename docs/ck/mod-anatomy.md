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
| `Libraries/*.dll` | Precompiled assemblies — a mod that ships one without `accessesExtraAssemblies` fails to load as a whole; none of them gets the automatic Harmony pass |
| `Conf/*.json` | Configuration, copied as-is by `BuildConf` |
| `Localization/*.csv` | Translation tables, copied as-is by `BuildLocalization` |
| `ModManifest.json` | Build-generated; the loader's entry point into all of the above |

The loader reads `ModManifest.json` with `JsonUtility.FromJson<ModMetadata>` and then
drives everything off the manifest's `files` list: `Load` splits it into the `.dll`,
`.cs` and `.assetbundle` entries and processes each set. One file is read without being
listed: beside each bundle the build also writes a JSON `<bundle>.manifest`, and the loader
opens it by naming convention whenever it exists (`PugMod.Loader:Loader:LoadBundle:50-61`)
— [what it changes](#reaching-your-own-loadedmod-and-asset-bundle) is below.

**Trap: a `.cs` file that is not in the manifest does not exist.** It will not be
compiled, and the sandbox compile then fails on the missing type — invisibly to the
Editor build, which compiled the same file happily against the Editor's own assembly.
After adding a source file, check that it reached both the install `Scripts/` directory
and the generated `ModManifest.json`.

Because the SDK's ModBuilder assigns almost everything under the mod's `modPath` to the
AssetBundle, and Unity imports text files as `TextAsset`s, a stray `.yaml` or `.md`
sitting in the mod folder is baked into the shipped bundle too. The collection step
itself drops directories, `.unity` scenes and every asset whose main type is one of the
SDK's three settings classes — `ModBuilderSettings`, the mod.io settings and the Steam
Workshop settings — wherever they sit (`ModBuilder.BuildMod` and
`IsExcludedSettingsAsset` in the SDK's `ModBuilder.cs`). Beyond those, three things keep
a file out: keeping it out of the mod folder, putting it in an `Editor/` or `CodeGen/`
subdirectory of it, or having it claimed by one of the verbatim-copy passes —
`BuildConf` and `BuildLocalization` remove every `.json` under `Conf/` and every `.csv`
under `Localization/` from the bundle's asset list before it is built, exactly as
`BuildScripts` and `BuildLibraries` do for `.cs` and `.dll`. `ModBuilder.BuildAssets`
skips every asset whose path passes through a directory of either name on the way up to
`modPath` — the same `IsInEditorFolder` filter that keeps editor-only `.cs` out of the
shipped `Scripts/` and editor-only DLLs out of the shipped assemblies. That is why a
mod's `Editor/logo.png` sits inside the mod folder and still does not ship; its
`Editor/<Mod>_modio.asset` would stay out by its type alone.

The "Create Mod" wizard lays a mod out like this in the SDK project:

```text
Assets/<Mod>/               the mod folder (metadata.modPath) — sources, prefabs, art
Assets/<Mod>/<Mod>.asset    the ModBuilderSettings asset — the configuration surface
Assets/<Mod>/<Mod>.asmdef   the runtime assembly definition
Assets/<Mod>/Data/          the scriptable-data context folder (below)
```

The settings asset can equally sit beside the folder as `Assets/<Mod>.asset` — every mod
in this family keeps it there, and CoreLib keeps it in a `Metadata/` folder of its own —
because the type filter above keeps it out of the bundle either way. An `Editor/`
subfolder with its own asmdef is not the wizard's; it is added by hand
([below](#why-an-editor-helper-needs-its-own-editorasmdef)).

How that source tree becomes an install directory is a build step; one arrangement of it
is in [organising a mod project](organising-a-mod-project.md).

### What the "Create Mod" wizard actually creates

`ModBuilderWindow.CreateNewMod` emits four things inside the project: the
ModBuilderSettings `.asset`, the runtime `.asmdef`, the mod folder, and the `.meta`
GUIDs that go with them. It sets `accessesExtraAssemblies` from the importer's
`includeAllAssemblies` switch, so a wizard-made mod normally starts with that flag on. Its
template-unpacking step is a no-op in this SDK clone — the `ModTemplate.zip` it looks for
is not present.

It also calls `ScriptableDataEditorUtility.AddContext` on the mod's `Data/` folder — for
every mod, unconditionally — which registers that folder as a scriptable-data context,
marks it for overloading, and leaves a context asset in it. That call goes into a
compiled SDK assembly and is the one step with no equivalent outside the Editor. **Only
an item or content mod needs its result**: a pure script mod — Harmony patches, UI —
carries a `Data/` folder when the wizard made it (faster-talents does) but adds nothing
to it beyond that context asset, so a script mod created by hand can skip the step, and
everything else the wizard does is ordinary file creation.

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
| `name` | `string` | Internal identity. Drives the asmdef name, the client's `ModLoader` temp directory, and the string other mods depend on; the namespace follows it by convention only. |
| `displayName` | `string` | Human-facing title. Used for the mod.io profile name (see [publishing](publishing.md)). |
| `skipSafetyChecks` | `bool` | Disables the Roslyn sandbox — see [the load-time sandbox](sandbox.md). Honoured as written only for a side-loaded mod: the mod.io and Steam loaders force it off unless the listing carries the `Script (Elevated Access)` tag ([the tag table](troubleshooting.md)). |
| `disableScripts` | `bool` | Skips the whole script step — compiling the sources, loading shipped DLLs, finding `IMod` handlers; the mod ships assets only. The platform loaders force it on for a listing tagged `Asset`. |
| `accessesExtraAssemblies` | `bool` | Required to load a shipped `.dll` — without it the whole mod fails to load; also adds every assembly loaded at game start as a metadata reference for the Roslyn compile. |
| `disableHarmonyPatching` | `bool` | Suppresses the automatic Harmony pass over your compiled assembly. |
| `requiredOn` | `[Flags] ModExistsOn` | Which side must have this mod — see below. |
| `files` | `List<ModFile>` | `{path, guid}` per shipped file. **Build-generated for a mod built through the SDK — the build recomputes it, and editing it there is still wrong.** |
| `dependencies` | `List<Dependency>` | `{modName, required}` — the load-order dependencies; a missing `required` one also stops the mod from loading at all ([below](#dependencies-two-concepts-only-one-of-which-compiles)). |

("Never hand-authored" is the wrong scope and stood here until 2026-09-03: a mod loaded
through [the side-loader](#the-side-loader-accepts-a-hand-written-manifest) below writes this whole list by hand, along with the rest of the
manifest — nothing in the loader requires a build to have produced it.)

Without `accessesExtraAssemblies`, loading a shipped `.dll` fails with
`Tried to load dll for <name>, but accessesExtraAssemblies not set`, and the load of the
whole mod ends there with `InvalidAccess` — its scripts are not compiled either
(`PugMod.Loader:Loader:LoadDll:4-8`).

### There is no mod version at runtime

That table is the whole of `ModMetadata`, and the runtime `LoadedMod` wrapper around it
adds only `ModId`, `Handlers`, `Assets`, `AssetBundles` and `GetFile(string path)`. The
last reads any shipped file from the install directory — a prefix check of the resolved
path against that directory, then `File.ReadAllBytes`, both inside the trusted assembly,
so it costs nothing against the sandbox. See [persistence](persistence.md#reading-a-file-your-mod-ships) for using it to read a shipped
`Conf/` payload — what follows here is its other use, deriving a version proxy instead.
**No version field exists anywhere in the loader's view of a mod.** A mod that wants to
know which build of itself — or of another mod — is running has to derive it.

The one derivable identifier is the **modfile ID**, and only for a mod installed through
mod.io. mod.io installs a mod into a directory named `<modId>_<modfileId>`, and
`API.ModLoader.GetDirectory(long modId)` (`PugMod.SDK.Runtime`) hands you that path as a
`string`; a Steam Workshop mod lives in Steam's content directory and a side-loaded one in
any directory under `StreamingAssets/Mods`, neither carrying a modfile ID — and a dedicated
server has only the side-loader. Splitting a string needs no `System.IO`, so the
derivation is [sandbox](sandbox.md)-legal. Whether a locally installed development build
yields a parsable ID this way is **unverified**.

**Trap: the GUIDs in `files` are not a version hash.** They are per-asset GUIDs, and the
list only changes when a file is added, removed or moved. A release that changes nothing but C#
source produces an identical set — so `files` used as a version proxy is not merely
approximate, it is silently wrong for exactly the case you most want to detect.

### Fields the SDK's Editor GUI gets wrong

Two of the metadata fields cannot be trusted to the mod-settings inspector:

- **`displayName` is `[HideInInspector]`.** The field is real and is read at build and
  publish time, but the GUI does not draw it. Set it in the `.asset` YAML.
- **`requiredOn` "Client and Server" was observed to write `-1`** ("Everything") rather
  than `3` — Unity's own flags-enum field does that; the SDK's sources have no custom
  drawer for it. Since it is a `[Flags]` enum, `-1` has every bit set, including
  bits that do not exist. Both runtime checks test single bits, so `-1` behaves like `3`
  there; the value is still wrong on its face and misleads every later reader of the
  YAML. Set the numeric value.

The relevant block looks like this (item-checklist's, with two of its three
dependencies left out):

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
`dependencies`, the key the dependency sorter builds its graph on, and on the client the
directory name under `Application.temporaryCachePath/ModLoader/` (a dedicated server
compiles into `ModLoader/DedicatedServer/<random GUID>` instead,
`DedicatedServer/PugMod.Loader:Loader:Load:11`). Renaming it for cosmetic reasons breaks every
dependent mod's manifest entry. Put the pretty title in `displayName` instead — the
internal identity `ItemChecklist` and the shown title `Item Checklist` are allowed to
differ, and normally should.

## The side-loader accepts a hand-written manifest

Everything above is the SDK build pipeline. The loader has a second path in
that needs none of it — and on a dedicated server, which registers no mod.io or Steam
loader, the only path in (`DedicatedServer/Pug.Other:Manager:EarlyInit:70-74`):
`SideLoader.Update()` (`PugMod.Loader:SideLoader:Update:1-61`) scans
`Application.streamingAssetsPath + "/Mods"` for directories, and for each one
holding a `ModManifest.json` reads it with `JsonUtility.FromJson<ModMetadata>`,
then calls `Integration.Instance.AddMod(metadata, <directory>, ModId,
supportsCurrentVersion: true)`. The id it assigns is
`-Mathf.Abs(metadata.name.GetHashCode())` — negative, which is what makes a
side-loaded mod recognisable as one in [multiplayer and server](multiplayer-and-server.md).
The same method also holds logic to re-read a directory whose manifest's write time
changed and to drop a mod whose manifest disappeared, but in 1.3.0.6 it runs only once,
from `SideLoader.Init` (`PugMod.Loader:SideLoader:Init:4`): the game keeps its mod
platforms in a list it fills and initialises and never updates, in either build. So a
side-loaded mod that changes takes effect at the next launch.

From there the ordinary load path runs, same as for a built mod: the loader reads each
`.cs` entry of `metadata.files` relative to the mod directory, source-gen-patches the
texts, writes them into a temp tree — `ModLoader/<name>/` on the client,
`ModLoader/DedicatedServer/<random GUID>/` on a dedicated server — and compiles them
with [the sandbox](sandbox.md) active unless `skipSafetyChecks` is set
(`PugMod.Loader:Loader:LoadScripts:28-61`). So an unlisted source file is never opened —
the one file the loader opens unlisted is a bundle's `.manifest` beside it — and a
listed `.cs` is all a code mod needs. **`files`'s "build-generated" above describes the
SDK pipeline, not a requirement of the loader** — `SideLoader` never touches
`ModBuilder`, and a manifest it accepts is nothing a person cannot type by hand:
`StreamingAssets/Mods/<any directory>/ModManifest.json` naming one `Scripts/*.cs` file
is a complete, loadable mod. Verify field names against [`ModMetadata`](#modmetadata-fields) rather than
guessing them, and pick a `guid` that does not collide with an installed mod's — a
collision breaks asset loading, [as below](#the-two-guids-and-the-rules-for-hand-created-files).

**Which is what makes a throwaway probe cheap: a directory, not a build.** No
Unity, no AssetBundle, no mod.io identity, no `.envrc` chain. Two properties
decide how such a probe round is designed:

- **The sandbox verdict is per assembly, and one mod compiles to one assembly.** Several
  small probes in one launch give several independent verdicts, where one probe with
  several references gives a single verdict over all of them. The compile-failure
  message reports counts and no names (see [what is banned](sandbox.md#what-is-banned)), which is why isolating one
  question per mod is what makes the answer attributable at all.
- **A reference in code that never runs still counts.** Verification reads
  the compiled IL, so a probe can put its reference in a method nobody calls
  and learn whether it is allowed without executing anything.

**Measured 2026-09-03, game version `1.2.1.5-8be0`:** eight hand-written
manifests, loaded, compiled and sandbox-verified this way, with no Unity
build behind any of them.

## The two GUIDs, and the rules for hand-created files

Two unrelated things are called "guid" in a mod, and confusing them produces failures that
look nothing alike.

| GUID | Where | Rule |
|---|---|---|
| Per-asset `.meta` `guid:` | Every `.meta` file Unity generates | Must be unique per asset. When copying a tree by hand, remap each one to a fresh value with a **global** find-replace across all copied files, so internal cross-references stay consistent. |
| `metadata.guid` | Inside the ModBuilderSettings `.asset`, in the `metadata:` block | Not a `.meta` GUID. Regenerate it separately when copying a mod. |
| `m_Script: {guid: …}` on the SDK's own assets | The ModBuilderSettings / Data / `_modio` assets | **Leave untouched when copying a mod.** These point at shared classes, not at your files — the settings assets at SDK classes, the Data asset at `ScriptableData.dll` as the SDK ships it. |

The `.asset`'s own `.meta` GUID is referenced by the `_modio.asset`'s `modSettings` field,
which is why remapping has to be a global replace rather than per-file edits.

The two `m_Script` values are the same in every mod, so you can check a suspect file
against them directly:

| File | `m_Script.guid` | Binds to |
|---|---|---|
| `<Mod>.asset` | `bc43e4983a160e543856e5ba0421c9e1` | The SDK's `ModBuilderSettings` class |
| `<Mod>_modio.asset` | `d83df2ae64ce1e94f9c006b9d326bf02` | The SDK's mod.io settings class |

Every mod in this family carries that same pair, but they are the SDK's own asset GUIDs,
so an SDK update can move them. These two have not moved so far; the third `m_Script` in
the row above has. The Data asset binds `ScriptableData.dll`, whose `.meta` the SDK
tracks, and the SDK update for 1.3 ("Update SDK for 1.3.0.1") changed that GUID from
`d00b036db31ed324f99d4111c393f019` to `e853a5af7d19630282ad0af7b5dabadc` — after which
four mods here had their Data assets repointed. So treat a mismatch as something to
verify against the current SDK, not as proof of corruption.

**An assembly GUID that changes under a prefab empties the screen rather than
raising an error.** After the 1.3 update, the `Pug.Other.dll` in this machine's SDK
clone carried a different asset GUID than before. A prefab authored against the
previous one names the old GUID in every `m_Script` that binds a vanilla UI
component, so each of those resolves to nothing: the prefab still instantiates,
its own hierarchy survives, and the components are simply absent. Nothing is
logged. Measured 2026-09-23 on Mod Settings Menu 1.x, whose menu prefab carried 23
such references.

Where that GUID comes from is less settled than the symptom. Unlike
`ScriptableData.dll`'s, the SDK does not track `Pug.Other.dll.meta`: Update Game Files
copies the DLL out of the installed game and writes a `.meta` only when none exists,
taken from `Assets/ModSDK/Data/MetaFiles.zip` — and that archive, unchanged since the
SDK's 1.0.0.0 update, still prescribes the *old* GUID. The clone's current `.meta` was
created from it and rewritten in place later. Whether the new GUID is the 1.3 update's
doing or something local to this clone — Unity regenerating it, as it does for [a duplicated GUID](toolchain.md#two-copies-of-one-package-break-its-guids)
— remains **unverified**, and with it whether a prefab authored in one SDK clone
resolves in another.

This is the row above one level out. Those entries are `m_Script` on the *SDK's*
assets; a prefab's `m_Script` binds a *game* assembly, whose `.meta` the SDK
generates rather than ships. The `fileID` beside it is unaffected, because it
identifies the class within the assembly and the classes did not move — so the
repair is a GUID substitution and nothing else, which is also how to check it: a
correct fix touches no line that is not one of the two GUIDs.

Finding it needs no suspicion about a particular file. Collect every GUID the mod
*references* and subtract every GUID that any `.meta` under the SDK's `Assets`,
its `Packages` or the mod itself *defines*; what remains points at nothing. Three
things produce false positives, and all three did here: `Packages/` holds the
SDK's own classes and is easy to leave out of the subtraction; `metadata.guid` in
the ModBuilderSettings `.asset` matches a naive `guid:` pattern although it is an
identity field and not a reference at all; and Unity's built-in
`0000000000000000f000000000000000` is a marker rather than an asset.

Run the same sweep over a tree that already works on the new version, and the
difference between the two results is what changed between them. A GUID that is
unresolved in both is something else. The generated localisation assets are the
case in point: most mods here carry `ScriptableData.dll`'s current GUID in them,
but faster-pet-talents and player-coordinates-hud still carry its pre-1.3 one,
which nothing in the SDK tree defines any more — and the next paragraph shows
such a stale reference working in a bundle built before the change.

**A bundle built before the update is a separate question from a build made
after it, and in both cases measured the old bundle loaded and was used.** On
2026-09-27 the published Faster Pet Talents 1.1.1 modfile, built on 2026-08-10
against 1.2.1.x, rendered its generated setting terms correctly — in German — on
a 1.3.0.2 client. `Localization.csv` had been deleted beforehand and no dev build
of the mod was loaded, so the text can only have come from that bundle. Those
term assets were authored against the GUID `ScriptableData.dll` carried before
1.3, which 1.3 also moved and no `.meta` in the updated SDK defines any more — so
a stale assembly GUID broke nothing in a bundle that was already built. The sweep
above checks what an Editor can resolve when it builds, and says nothing about a
bundle built before the update.

The second case holds no data block at all. The published Complete Tiny Font 1.0.1
modfile, built on 2026-08-12 against 1.2.1.x, carries two assets its code uses — one
`Sprite` texture and one `TextAsset`, both fetched by path with `AssetBundle.LoadAsset`
— beside an entry for the mod's own `.asmdef`, for which the bundle holds no object. On
2026-09-28 a 1.3.0.2 client loaded it from the subscription — `Loading mod with ID`
named the real mod id, and no dev build of the mod was installed — and both assets
loaded: the mod's own log line reported a 257×144 texture, the size its glyph rects are
laid out for, and a filled kerning table, which that code writes only when the
`TextAsset` is exactly 384 × 384 bytes. Those two values are what the line takes from
the bundle — its glyph and row counts come from a table compiled into the code — so it
proves the load, the dimensions and the length, not every pixel. What it had to get past
first was the version gate, not the bundle: its profile carried no 1.3 tag, so it loaded
only because it had been force-loaded once ([a stale game-version compatibility tag](troubleshooting.md#cheaper-if-you-have-a-log-a-stale-game-version-compatibility-tag)). The
code is no part of this evidence either way: the modfile ships source, not a compiled
assembly, and the loader compiles it against the running game at every load.

What this does not cover: both measurements were taken on a client, and a dedicated
server was not tried; neither bundle holds a prefab, and the screen the localisation
terms appeared on is another mod's prefab, rebuilt for 1.3. Data blocks of other types,
some of them defined in `Pug.Other`, were not tested. Unity stayed at `6000.0.59f2`
across this update, so neither was a change of engine version. Whether a pre-update
*prefab* bundle survives remains **unverified**: Mod Settings Menu's 1.2.0 changelog
reports that 1.3 left its screen empty, but not whether that was the published 1.1.0
bundle, nor whether the GUID or 1.3's rewritten `LinearLayout` caused it. The reverse
direction — a bundle built after the update, on a client still running the previous
version — remains **unverified**.

**Trap: a duplicated `metadata.guid` breaks asset loading first, and identity with it.**
The loader registers each mod's asset-bundle data-block loader under that GUID
(`ScriptableData.AddDataBlocksLoader(mod.Metadata.guid, …)`), so a second mod carrying
the same value produces `Data block loader already added for key <guid>` — and the
registration returns there, so that mod's data blocks are never registered
(`ScriptableData:ScriptableData:AddDataBlocksLoader:5-8`). It is the visible half. The
same value is also an identity key elsewhere: the connection-time mod check counts a
server mod as present on a matching id **or** a matching guid
(`Pug.Other:NetworkClientStartSystem_33002849_LambdaJob_0_Job:OriginalLambdaBody:12`),
and the loader's preferred load order is keyed on it
(`PugMod.Loader:DependencySorter:SortMods:57-61`), so two mods sharing one are partly
treated as one. A duplicate is the usual outcome of scaffolding a new mod by copying a
sibling and remapping only the `.meta` files.

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
| `ModObjectLoaded(obj)` | Once per asset loaded from your bundles, right after your `EarlyInit` | Capture and register prefabs by name. It is the only per-asset callback; the same objects are also listed in your `LoadedMod.Assets` ([below](#reaching-your-own-loadedmod-and-asset-bundle)). |
| `Init()` | On the **first loader `Update` tick** after loading, once per handler — at startup every mod's `Init` before any mod's `Update`; a reloaded mod would get it again later | Anything needing a running game loop. At startup, as measured on 1.3.0.6, the startup conversion has run and the per-world ones have not — see [the order of conversions](database-and-baking.md#trap-a-config-value-the-bake-reads-must-be-bound-in-earlyinit). |
| `Update()` | Every frame, after `Init` | Hotkey polling, timers. |
| `Shutdown()` | From the loader's reset, **before** the asset bundles are unloaded and before the Harmony patches are undone — on a reload, on a mod's removal, and on a mod whose load failed after its handlers were created (so possibly without any `EarlyInit`). **Not at game quit** | Drop references to bundle-owned objects. Do not rely on it to persist state: write as you go. |
| `CanBeUnloaded()` | Polled before a reload, for every handler of every mod | Returning `false` (the default) blocks the reload — for all mods, since a reload resets them all — logging `Mod reload blocked by <type>`. |

**In 1.3.0.6 nothing triggers a reload after startup.** The reload flag is set only when
a mod is added or removed (`PugMod.Loader:Loader:Add:15`,
`PugMod.Loader:Loader:Remove:27`); mods are added only by the platform loaders' one-time
`Init`, and removed only by the side-loader's update, which runs once at startup
([above](#the-side-loader-accepts-a-hand-written-manifest)). The game's mod-facing API (`API.ModLoader`) offers no reload either. So the
reload rows describe a code path that exists, and `Shutdown` in practice runs only for a
failed load.

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

`EarlyInit` is early enough for this. Two equivalent forms are in use: the game's own
`API.ModLoader.GetMod(name)` runs exactly this loop and returns the first match or
`null`, and matching on `mod.Handlers.Contains(this)` from inside your `IMod` needs no
name at all — the more common form in the mods here, this family's and third-party ones
alike.

**What `LoadedMod.Assets` holds depends on the bundle's `.manifest`.** When a bundle
ships with its `.manifest` beside it, as the SDK's build output does, the loader reads
the asset names from it and calls `LoadAsset(name)` once per entry
(`PugMod.Loader:Loader:LoadBundle:50-61`), and that list is what `Assets` exposes
(`PugMod.Loader:Loader:Reload:96`). `LoadAsset` returns the named asset's main object
only, so a sliced sprite sheet contributes its `Texture2D` and none of its sprites —
measured with a probe mod on 1.3.0.2: one asset, no sprite. A bundle without a manifest
goes through `LoadAllAssets()` instead (`PugMod.Loader:Loader:LoadBundle:67`), which
includes sub-assets such as those sprites, and that case is not hypothetical: six
installed third-party mods ship their bundles without one. Either way the sprites are in
the bundle: reach them through the bundle handle above, or reference them from an asset
that ships in the bundle — a prefab or a data block — which is how a map-marker icon
block carries a sprite sheet's slices.

### Reaching another mod without a dependency

The same list answers questions about other mods, and nothing in it is limited
to your own entry. What one mod can reach of another without declaring it:

- **Whether it is there.** The load pass adds a mod to `LoadedMods` only after its
  `Load` succeeded, and records a failure in a separate not-loaded list instead
  (`PugMod.Loader:Loader:Reload:62-91`); a mod the sorter dropped before that — a
  missing required dependency, or the earlier of two mods with the same name, which the
  sorter's name index silently replaces with the later one
  (`PugMod.Loader:DependencySorter:SortMods:3-10`) — is in neither. The pass runs over
  every mod before the first `EarlyInit` (`PugMod.Loader:Loader:Reload:109`), so
  matching another mod's `metadata.name` is reliable from `EarlyInit` on, and that name
  becomes an interface the moment a second mod matches on it. Being listed means
  compiled and loaded, not working: an exception in its `EarlyInit` is logged and the
  mod stays.
- **Its content.** `Assets` and `AssetBundles` on its `LoadedMod` are its loaded
  objects, and `GetFile` reads its install directory exactly as on your own; see [reading a file your mod ships](persistence.md#reading-a-file-your-mod-ships).
- **The files it writes through the API.** `API.ConfigFilesystem` is rooted at the
  shared `mods/` folder, so another mod's folder is one path segment away, for reading
  and writing alike ([persistence](persistence.md#1-apiconfigfilesystem--the-default-answer)), and `API.Config` takes the mod's name as a plain
  parameter. A file written past the API — `System.IO` under `skipSafetyChecks` — is
  outside this.
- **Its code, narrowly.** `Handlers` holds its live `IMod` objects, so its lifecycle
  methods can be called, and `API.ModLoader`'s `ApplyHarmonyPatches` /
  `UnloadHarmonyPatches` take any mod's id. Its own types are another matter: a call
  needs a compile-time reference, and `API.Reflection` admits an assembly by name prefix
  only ([the permission gate](sandbox.md#reaching-a-private-member-resolving-it-is-only-half-the-job)), which a mod's assembly — named after its `metadata.name` —
  passes only if that name happens to begin with one of the admitted prefixes. What does
  work is a call through a type both sides compile against: CoreLib lists its consumers'
  types with `API.Reflection.GetTypes`, instantiates them and calls them through its own
  interfaces — which takes a dependency in one direction, theirs on it. That call takes
  a mod id and ignores it: it returns the types of every assembly of every loaded mod
  (`Pug.Other:ModAPIReflection:GetTypes:1-18`), so a caller that wants one mod's types
  filters them itself. With none in either direction two mods share data rather than
  calls, and the file API reports no change: the side that reads polls, and
  `GetFileTime` is the cheap check.

### Ordering details that matter

`EarlyInit` and `ModObjectLoaded` are **interleaved per mod**, not run as two global
phases. The loader walks the sorted mod list and, for each mod, calls `EarlyInit` on all
its handlers and then `ModObjectLoaded` for each of its assets — before moving to the next
mod. So your `ModObjectLoaded` runs before a later mod's `EarlyInit`, and a dependency's
`ModObjectLoaded` has already run by the time yours does.

**Against the *game's* own boot code there is no such guarantee.** If a patch of yours
fires from a game initialiser — `TextManager.Init2`, for instance — and needs an asset out
of your bundle, whether that initialiser runs before or after your `ModObjectLoaded` remains
**unverified** in either direction. Do not pick a winner. Write a single idempotent
`TryApply()` that checks both preconditions and returns early unless both hold, and call
it from *both* sites: whichever runs second is the one that does the work, and every
further call is a no-op.

`Init` is **not** part of the load pass. The loader calls it from its own `Update`,
guarded by a per-handler "already initialised" flag, and then immediately calls `Update`
— the `Init` loop covers every handler first (`PugMod.Loader:Loader:Update:3`,
`PugMod.Loader:Loader:Update:4`), so at startup a mod's first `Update` sees what every other mod
did in its `Init`. That is why `Init` is the earliest point with a live frame loop. It
comes after the startup conversion and before the per-world ones (measured on 1.3.0.6,
client and dedicated server — on the client an observation, not something the code
enforces; on the server the code does, see below), so the managed `PugDatabase`
catalogue and `API.Authoring.ObjectProperties` exist by then, and a world's converted
database does not.

**On a dedicated server `Init` runs at a different point of ECS startup than on the
client.** Since 1.3 the server's `StartEcs` calls the loader's `Update` itself, after
the ServerWorld exists and before the conversion whose callback arms the Burst bypass
(`DedicatedServer/Pug.Other:ECSManager:StartEcs:38`); the client reaches `Init` from its
frame loop, before any world. Through 1.2 the server ran `Init` only after that
callback, which made `BurstDisabler` registrations from `Init` a silent no-op there — a
consequence 1.3 removed. The evidence, and why the `AddWorld` pass stays anyway, is in [Harmony and ECS](harmony-and-ecs.md).

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
and the obvious "later" candidates are worse than useless: world work attempted from
`IMod.Init`, or from patches on `PugDatabase.UpdateEntityMonos` or `SaveManager.SetWorldId`,
was observed to throw a `NullReferenceException` whose message points at nothing.

On a client — singleplayer or a host — the anchor that works is a Harmony postfix on the
player's spawn method that starts a coroutine on the player instance. **Since 1.3 that
method is `OnSpawn`**, a `protected override` on `PlayerController`
(`Pug.Other:PlayerController:OnSpawn:1`), which is why it is named by string. Through
1.2 it was `OnOccupied` (1.2.1.5: `PlayerController.OnOccupied` in `Pug.Other`); 1.3
moved the spawn logic out of it, and `PlayerController` no longer declares `OnOccupied`
at all:

```csharp
[HarmonyPatch(typeof(PlayerController), "OnSpawn")]
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
the local player's `OnSpawn` both `Manager.main` and `Manager.main.player` exist, so
this is not a readiness test; it is a deliberate one-frame settle. In practice — this is
observed, not read off the code — yielding gives the ECS world an update cycle to bring
up its singletons — the localisation sources, the database bank — before your first
query or before `GetObjectName(localize: true)` runs. Read as a guard the line looks
redundant and invites deletion; it is a proxy for "a frame has passed", not a signal,
and removing it produces the worst failure shape there is: correct-looking code that
fails sporadically.

**Filter on `__instance.isLocal`.** The postfix fires for every player that spawns, remote
ones included, and `Manager.main.player` is assigned only inside `if (isLocal)`
(`Pug.Other:PlayerController:OnSpawn:77`).

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
itself. Only the assembly compiled from your `Scripts/` gets this pass — a shipped
`Libraries/*.dll` does not. Two metadata fields govern the pass:

- `disableHarmonyPatching` skips it entirely.
- `skipSafetyChecks` selects whether the patch pass runs verified or unverified — the same
  switch that controls the [Roslyn sandbox](sandbox.md).

Failures are logged and do **not** abort the load, so a mod whose patches never bound
still reports as loaded. Two lines, two different causes: `mod <name>: patching failed`
is the safety check rejecting the assembly, while `failed to patch mod <name>, got
exception` — followed by the exception itself — is Harmony throwing
(`PugMod.Loader:Loader:HarmonyPatchAssembly:5-14`). On reload the loader undoes your
patches (unless `disableHarmonyPatching` is set) as part of the same reset that calls
`Shutdown`.

**A throw does not cost you one patch, it costs the rest of the pass.** The loader hands
the whole assembly to `Harmony.PatchAll`
(`PugMod.Loader:HarmonyBootstrap:Patch(string, Assembly, …):51`), which walks
`assembly.GetTypes()` and calls `PatchClassProcessor.Patch()` on each type with nothing
catching in between (`0Harmony:2148-2154`, `0Harmony:3999-4003`). A target that cannot
be resolved makes `PatchWithAttributes` throw `ArgumentException: Undefined target
method for patch method …` (`0Harmony:3242`), and `Patch()` catches it only to run
`[HarmonyCleanup]` before rethrowing it wrapped as a `HarmonyException`
(`0Harmony:3169-3174`, `0Harmony:3371`) — a cleanup method receives the exception by
reference and could suppress it, but a class without one rethrows. The enumeration ends
there: classes already processed stay patched, the rest are never reached — and
`GetTypes()` guarantees no order, so *which* ones made it is not something the source
tells you. The symptom is a half-patched game, not one missing feature.

**That is what makes a string-named target a bet on the whole mod.** A member named by
string — private or, like `OnSpawn` above, protected — resolves to nothing after a rename
in a game update, which is precisely the throw above.

**`nameof` does not protect you either, when an override is dropped.**
`[HarmonyPatch(typeof(X), nameof(X.Y))]` catches a renamed or removed member, because that
fails to compile. It does not catch `X` ceasing to override a base method: `nameof(X.Y)`
still compiles through the inherited member, but the attribute form resolves the target
with `AccessTools.DeclaredMethod` (`0Harmony:1366`), which looks only at what `X` itself
declares. The 1.3 update did exactly this to `PlayerController.OnOccupied` — the Editor
build stayed green, and every attribute patch on it without a `[HarmonyPrepare]` guard
fails at load with the throw above. `caveling-divining-rod`'s did, observed at load;
`item-checklist` carried a patch of the same unguarded shape.

**The guard is a `[HarmonyPrepare]` that probes for the member and returns `false`**,
skipping that one class cleanly: Harmony runs it before resolving any target
(`0Harmony:3145-3157`), so a class that opts out never reaches the throw. The usual
probe is unavailable in a sandboxed mod — `AccessTools.Method` and `System.Reflection`
are both denied ([what is banned](sandbox.md#what-is-banned)) — but the SDK's checked lookup is legal:
`GetMembersChecked()`, [as under resolving a private member](sandbox.md#reaching-a-private-member-resolving-it-is-only-half-the-job), filtered on
`GetNameChecked()` **and** on `GetDeclaringTypeChecked() == typeof(X)`. The second test
is not optional. `GetMembersChecked()` returns inherited members too
(`PugMod.SDK.Runtime:ModAPIExtensions:GetMembersChecked:1-10`), and in exactly the case
above the base class `PoolableSimple` still declares `OnOccupied` — a name-only probe
finds it, returns `true`, and the declared-only lookup throws anyway. Opting out costs
that one feature; not opting out costs everything else the assembly patches.

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

That one call covers both kinds of command: `AddCommands` takes every type assignable to
either handler interface. It asks the game for them with
`API.Reflection.GetTypes(modId)`, which [ignores the id](#reaching-another-mod-without-a-dependency) — so the scan covers every loaded
mod's assembly, not only yours, and registers whatever handlers it finds under the name
you passed. A handler whose `GetTriggerNames()` returns an empty array is dropped with a
log warning and nothing else.

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
- **Creating and destroying entities through `EntityManager` is possible too.** Handlers
  run after the system's own `Entities.ForEach(…).Run()` and its command-buffer playback,
  outside any iteration, and CoreLib itself creates its reply RPC entities from this very
  call, every time it answers a command (`SendMessage` in its `CommandCommSystem.cs`).
  Such a change is a sync point: do not hold component arrays or lookups across one.
  ("Creating or destroying entities is not" stood here until 2026-10-17, as the standard
  in-iteration prohibition applied to a position that is not inside an iteration.)

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
namespace, or it succeeds and the mod compiles at load time only when the framework
happens to load before it — which nothing guarantees ([below](#dependencies-two-concepts-only-one-of-which-compiles)).

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

Neither switch requires giving up the sandbox; this works with `skipSafetyChecks: 0`.
What is established here is the two-switch mechanism. Whether a particular foreign
assembly's API is then usable in practice is a separate question per assembly. For
`modio.UnityPlugin` it is **unverified**: no mod here has been carried through to a
working build, but the published third-party mod ItemBrowser ships a sandboxed call to
`ModIOUnity.GetSubscribedMods` (`skipSafetyChecks: false`, `accessesExtraAssemblies:
true`, in `ItemBrowserPackage/Scripts/Utilities/ModUtility.cs`). It has not been run on
this machine — it is disabled there — so whether that call compiles in the sandbox and
returns data is the open question, and ItemBrowser is the place to settle it.

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
| Effect | **Compile order** — a topological sort so the dependency's assembly exists as a metadata reference when your scripts compile; a missing `required` one drops the mod | **Auto-install** — subscribers receive the dependency and it appears in the in-game mod list; the game itself subscribes to missing ones when the mod.io browser closes ([below](#the-in-game-mod-menu-and-when-modio-is-contacted)) |

They are independent, and setting only the platform one produces a contradiction that
looks impossible: CoreLib is installed, visibly loaded, and your mod still fails with
`CS0246`/`CS0103` on every CoreLib type. The reason is that your mod was compiled *before*
CoreLib, so CoreLib's assembly was not yet among the metadata references.

**Every mod loaded earlier is a reference, not only the declared ones.**
`LoadScripts` hands the compiler the assemblies of every mod in the load list
(`PugMod.Loader:Loader:LoadScripts:5-7`), and only those already loaded have any.
Two consequences, read from the loader rather than measured. A mod that uses
another mod's types without declaring it compiles exactly when the other one is
loaded first, and with no dependency between them that order is not the mod's
to choose: the sorter ranks unrelated mods by the loader's `preferredLoadOrder`
list and otherwise keeps the order it found them in
(`PugMod.Loader:Loader:Reload:56`). A dependency with `required: 0` is the
controlled form — the sorter orders by every declared dependency that is
present, required or not (`PugMod.Loader:DependencySorter:SortMods:38-43`) — but
it orders only; the types still have to exist, so the mod fails to compile
whenever the other one is missing. And a type two mods both define, such as a
helper copied into each, is visible to every mod compiled after them; code meant
to be duplicated across mods belongs in `internal` types, or at least in a
namespace of each mod's own.

The loader's `DependencySorter.SortMods` does the work:

1. It indexes every mod by `metadata.name`.
2. It scans the mod list backwards; every mod with a **required** dependency whose name
   is not in the index is dropped, logging `skipping mod <name> because of missing
   dependency: <dep>`, and the scan repeats until a pass drops nothing, so a mod whose
   dependency was itself just dropped goes too.
3. It builds a dependency graph from the surviving `dependencies` entries and
   depth-first-visits it, producing the load and compile order. A cycle logs
   `<name> has circular dependency` and is broken rather than resolved.

**Trap: a missing required dependency drops your mod with no in-game feedback.** That
warning line is the only signal — there is no dialogue and no error toast. To the player,
the mod simply is not there: no UI, no hotkey, nothing to click. If you ship a hard
dependency, document that symptom.

**Through 1.2.1.5, at most one mod was dropped per pass.** The removal loop left with
`break` as soon as it removed a mod and did not repeat, so a second mod with a missing
required dependency was neither warned about nor removed — it stayed in the load list
and failed later at the compile step instead. Since 1.3 the loop runs to the end and
repeats (`PugMod.Loader:DependencySorter:SortMods:11-34`); this section described the
old loop as current until 2026-10-08.

To read the *actual* compile order on a client, look for the loader's `Creating modified
script files at …ModLoader\<Mod>` lines. They are ordered by compile, unlike the `loaded
mod …` lines. A correctly declared dependent shows its dependency's line first. On a
dedicated server the same line names a random GUID instead of the mod; there the
`Successfully compiled <name>` line that follows each one carries the name, in the same
order.

For which mods are auto-installed alongside yours, see [publishing](publishing.md).

A mod that silently is not there — the symptom the trap above produces — has its own
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
| `NetworkClientStartSystem` (`Pug.Other:NetworkClientStartSystem:OnUpdate:25`) | `localMod.required = (requiredOn & ModExistsOn.Server) != 0` | The **Server** flag makes the **client** demand the mod on the server |
| `ModInfoRpcSystem` (`Pug.Other:ModInfoRpcSystem:OnCreate:14`) | `required = (requiredOn & ModExistsOn.Client) != 0` | The **Client** flag makes the **server** require it of the client — the server advertises the flag, the joining client enforces it |

A mod without the relevant flag is removed from the check list, but by two different
mechanisms depending on direction: in the `Server` direction, `localMods.RemoveAt`
(`Pug.Other:NetworkClientStartSystem:OnUpdate:41-43`) drops it outright; in the `Client`
direction, the server reports `required = false` for it and the client never adds it to
`modsToCheck` in the first place
(`Pug.Other:NetworkClientStartSystem_33002849_LambdaJob_0_Job:OriginalLambdaBody:18-20`).
Either way it never interferes with a connection.

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
disable the mod (and restart) or cancel the connection — and for a side-loaded mod
(`modId <= 0`) a different dialogue offering only the cancel. What exactly a mismatch does to
a join, on either side, is covered in [multiplayer and server](multiplayer-and-server.md); `requiredOn` also feeds a
mod.io catalogue tag, which is described in [publishing](publishing.md).

## The in-game mod menu, and when mod.io is contacted

In the 1.3 builds the Mods entry in the main menu opens a screen of Pugstorm's own,
`ModListMenu` (`Pug.Other:ModListMenu:1`): the installed mods from all sources in load
order — plus pending, failed and mod.io-disabled ones — with reorder controls and one
button per source. In 1.2.1.5 the same entry, `RadicalMainMenuOption_OpenMods`, went
from its confirmation popup straight to `Browser.Open()`, with no list in between; older
notes that say "the Mods menu" mean the mod.io browser. The source buttons are
**Mod.io** and **Local**, plus **Steam** on Steam builds only
(`Pug.Other:ModListMenu:SetupSlots:28`). Their `OnActivated` switch
(`Pug.Other:ModSourceMenuOption:OnActivated:4`) sends **Mod.io** to
`RadicalMainMenuOption_OpenMods.OpenModUI`
(`Pug.Other:RadicalMainMenuOption_OpenMods:OpenModUI:1`), which calls `Browser.Open()`
on mod.io's embedded drop-in UI package — `modio.UI.dll`, namespace `ModIOBrowser` — and,
when the browser closes, subscribes the account to every missing mod.io dependency of
its enabled subscriptions (`SubToDependencies`, which the class also runs on every
mod-management event).
**Steam** opens the Workshop page (in the Steam overlay when it is enabled), **Local**
the local mods folder. Pugstorm embedded mod.io's browser rather than rebuilding it, so
what you see behind that button is mod.io's behaviour, not the game's.

That matters for when the game learns that a mod has a new release.
`ModIOUnity.FetchUpdates()` has five callers — four inside that embedded UI, and one
that is the list screen itself:

| Caller | When |
|---|---|
| `ModListMenu.Activate()` (`Pug.Other:ModListMenu:Activate:14`) | **Every time the Mods screen opens**, before any button is pressed — and only when the session is already authenticated |
| `Browser.IsInitialized()` | Pressing **Mod.io** (`Browser.Open()` runs into it) — and only when the session is already authenticated |
| `Authentication.CodeSubmitted(Result)` | After an email-code login succeeds |
| `Authentication.ThirdPartyAuthenticationSubmitted(…)` | After a Steam/portal login succeeds |
| `Collection.CheckForUpdates()` | The "check for updates" button in that same UI |

**There is no timer and no startup hook.** A session that never opens the Mods screen
never asks mod.io whether anything changed. It can still contact mod.io for other
reasons: joining a server that requires a mod this client lacks looks the mod up and,
on consent, subscribes to it — neither of which fetches updates.

**Syncing and installing are two separate steps, and the list screen does only the
first.** `FetchUpdates` first sends any unsubscriptions queued while offline, then
rebuilds the local subscription set from the account's subscriptions
(`SyncUsersSubscriptions` **clears** it first,
`modio.UnityPlugin:ModCollectionManager:SyncUsersSubscriptions:8`), refreshes each
subscribed mod's cached profile — tags included — and saves the registry. Downloading,
installing and uninstalling are the mod-management pass, which it wakes but which does
nothing unless it has been enabled (`modio.UnityPlugin:ModManagement:WakeUp:3`).
`ModIOUnity.EnableModManagement(...)` has four call sites, all in the embedded UI and
three of them the members above; in `Browser.IsInitialized()` it sits *after* the
authentication branch, so the call is always made — but it sets the flag only for an
authenticated session
(`modio.UnityPlugin:ModIOUnityImplementation:EnableModManagement:3`). So apart from
`state.json` itself, the list screen writes and deletes no mod files until **Mod.io**
has been pressed, logged in, in that session. From then on the flag stays set until a
logout in the browser or quitting the game (`DisableModManagement`, reached from
`RemoveUserData` and `ShutdownOperations`, and from the management loop itself once the
plugin is no longer initialised), so every later visit to the list screen in that
session runs the full pass as well — that half is read from the code, not measured.

When the pass runs, it uninstalls a mod the account no longer subscribes to — the
installation directory, then its `mods` entry in `state.json`
(`modio.UnityPlugin:ModManagement:GetNextModManagementJob:49`) — and installs a missing
subscribed one or replaces it when a newer modfile exists; an up-to-date mod whose
directory exists is left as it is, contents unchecked.

Measured on 1.3.0.3 with a fake-ID dev install present (a placeholder mod id that no
subscription can contain): fresh launch, open the Mods screen, close it without
pressing anything, quit. The id was gone from `subscribedMods` in `state.json`, while
its `mods` entry, its installation directory and its modfile archive were all still
there. The mod.io loader (`ModIOLoader`) loads only subscribed mods, so from the code the
next launch would not load it; the side-loader and the Steam Workshop loader are not
subscription-bound.

The locally held state, by contrast, is readable at any time with no network traffic:
`ModIOUnity.GetSubscribedMods(out Result)` returns entries of

```csharp
SubscribedMod { SubscribedModStatus status; string directory; ModProfile modProfile; bool enabled; }
```

with the status enum at `modio.UnityPlugin:SubscribedModStatus:1`. Reaching any of this from
mod source is the two-switch case described above under *Using an assembly the game loads
but does not expose*.
