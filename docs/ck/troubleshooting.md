# Troubleshooting

Symptom-first index of the ways Core Keeper modding fails without telling you
why — silently disabled scripts, a mod that takes an unrelated mod down with it,
a game that closes at the loading screen, an SDK clone that refuses to compile,
an Editor that hangs, a build that produces nothing. Each entry names what you
observe, then the mechanism, then the fix. Where a symptom has more than one
cause, the cheapest check comes first.

Most in-game diagnosis happens in `Player.log`. Under Wine the file is
**UTF-16**, so `grep` reports "binary file matches" and prints nothing useful —
pipe it through `strings -n 3` first (`iconv` was unreliable on it). The host
path is in [platforms and hosts](platforms.md).

## The mod loads, but its scripts are never compiled

The asset bundle loads. The mod appears in the in-game mod list. And nothing it
does in code happens: no recipe, no HUD, no tab, no patch — **and no error**.

The tell is what is *missing* from `Player.log`:

| Expected line | Meaning when absent |
|---|---|
| `Creating modified script files at …ModLoader\<Mod>` | the loader never staged the sources |
| `Successfully compiled <Mod>` | no compile happened at all |
| `passed code security verification` | the sandbox check never ran |

Alongside that, there is no `…/Temp/Pugstorm/Core Keeper/ModLoader/<Mod>/`
directory while every other mod has one, and deserialising the bundle logs
`referenced script (<Type>) is missing!`.

Two log lines are **not** the cause. `couldn't load …asmdef from asset bundle`
is benign — every mod logs it. `referenced script (<Type>) is missing!` is the
downstream effect of the scripts not existing, not a reason for it.

There is no `CompileFailed` and no `CS####` here. A failing compile is loud; the
causes below are silent, which is exactly what makes them expensive.

### Check first: the mod.io Access Type tag

**A mod.io profile carrying the `Asset` tag has its scripts silently disabled.**
The mod.io loader walks the subscribed profile's `tags` (`ModIOLoader.Init`) and
sets `metadata.disableScripts = true` on `Asset`, with zero log output. The Steam
Workshop loader does the same over `entry.Tags`.

| Profile tag | Effect on the loader |
|---|---|
| `Asset` | `disableScripts = true` — sources are never staged or compiled |
| `Script (Elevated Access)` | normal load, keeps the mod's authored `skipSafetyChecks` |
| anything else, including `Script` or no tag at all | normal sandboxed load; `skipSafetyChecks` forced to false |

**The rule is negative: a scripted mod must not be tagged `Asset`.** Both
loaders compare only against `Asset` and `Script (Elevated Access)`; the
`Script` constant exists but is never compared against, so it is a catalogue
label with no effect on loading. Tag `Script (Elevated Access)` only if the mod
genuinely needs `skipSafetyChecks` (see [the sandbox](sandbox-and-config.md)).
`Asset` is an easy mistake to make by hand at profile creation, because it reads
like the right word for a mod that adds an *item*; it means "ships no code".

**Diagnosis:** compare `modObject.tags` across mods in
`…/Public/mod.io/5289/state.json` — a broken mod shows `…,'Item','Client','Asset'`
where a working one shows `…,'Client','Script'`. If `Player.log` has no
`skipping mod` or `circular dependency` line, the mod survived
`DependencySorter.SortMods` and the tag path is what dropped it.

**Fix:** mod.io website → the mod's profile → Edit → Tags → uncheck `Asset`,
check `Script` → save. Then open the in-game Mods menu once (that is what syncs
tags into `state.json`) and restart. `Asset` is a value the group offers that a
script mod never earns, so anything that sets tags on publish should treat it as
surplus rather than preserve it — see [publishing](publishing.md).

**Trap: opening that menu deletes every local dev install on the machine.** The
sync it triggers is destructive by design. `SyncUsersSubscriptions` **clears**
the local subscription set and rebuilds it from the account's `/me/subscribed`
response, then wakes the mod-management pass, which uninstalls every mod in the
local registry that no user subscribes to (`ShouldThisModBeUninstalled` →
`PerformOperation_Delete`) — installation directory and modfile archive both
gone. A locally installed dev build has a placeholder mod ID that resolves to
nothing in the catalog, so it can never appear in that response and is removed
without a prompt or a dialog. Starting the game, loading a world and playing do
not trigger the sync; the mod browser does. Reinstall each dev build afterwards;
doing so rewrites all three locations a dev install occupies.

### Then: a stale game-version compatibility tag

**This one is not silent — check it first if you have a log.** A published mod
whose profile carries no compatibility tag for the running game version is
refused for mod.io subscribers before it loads at all, and says so twice:

```text
mod <ProfileName> is not compatible with current version
not loading incompatible mod <ModName>
```

The mod is never added, so none of the tells above apply — no bundle, no entry
in the loaded-mod list. Core Keeper's main menu raises the incompatible-mod
dialog offering **Disable** or **Load Anyway**; "Load Anyway" writes the mod's
GUID into `unsupportedModsToLoad`, the force-load allowlist that makes the
loader skip this rejection on the next launch ([the loader's two disable lists](#the-loaders-two-disable-lists-are-opposites),
below).

**This bites only when the first three version components change.**
`ModVersion.IsCompatible` matches `^(\d+)\.(\d+)\.(\d+)` against both the
game version and each tag and compares only those three groups, so `1.2.1.4` and
`1.2.1.5` both reduce to `1.2.1` and a mod tagged for either is compatible with
the other. Most Core Keeper releases are fourth-component patches and need no
re-tagging at all; a move like `1.2.0.x` → `1.2.1.x` does.

**A local dev install can reproduce it.** The install writes the configured
game-version list into its own tags, so it goes through the same filter and
passes because of them — a stale `CK_GAME_VERSION` fails locally just as it
would for a subscriber. What a dev install genuinely does not carry is a type
tag, so it never reproduces the `Asset` failure above; and like any mod without
`Script (Elevated Access)`, it gets `skipSafetyChecks` forced to false.

**Fix:** add the new version tag on the mod.io website; no rebuild is needed if
the code already runs. Keep the publish configuration's game-version list
current so the next publish carries it, and **re-tag every published mod after a
Core Keeper update**, even though they all still work locally.

## `Data block loader already added for key <guid>`

Exactly one such line in `Player.log`, no `CompileFailed`, no `CS####` — and one
mod is missing the entries its asset bundle defines: a recipe that never
appears, an object-database block that never takes effect. The line names the
**GUID, not the mod**, so on its own it does not tell you which mod lost.

**Cause: two mods carry the same `metadata.guid`.** That field lives in the
ModBuilderSettings `.asset` and is written 1:1 into the built
`ModManifest.json`'s `guid` — it is the mod's identity. (The `.asset` file's own
`.meta` GUID is unrelated and is usually unique even when this one is not.) The
loader registers each mod's asset-bundle data-block loader under that GUID
(`ScriptableData.AddDataBlocksLoader(mod.Metadata.guid, …)`), and a registry
that already holds the key refuses the second registration — so the data blocks
that bundle defines are never loaded.

**It is not a load failure.** The rejection is a `LogError` and nothing else:
the losing mod's scripts still compile, its Harmony patches still bind, and its
bundle assets still load. That is why a crafted item can still appear in-game —
CoreLib's entity map is name-keyed and reads the entity from the bundle — while
the recipe that unlocks it does not.

**This is not the cause of the silent-no-scripts symptom above**, although the
two were once conflated. The loader runs the script stage before the bundle
stage, so a mod with a duplicate GUID has already logged its `Successfully
compiled` line by the time the duplicate-key error appears. If you see both
symptoms, you have both problems — fix both.

This happens when a new mod is scaffolded by copying a sibling mod's asset tree
and the GUID is not reset.

**Decisive test:**

```bash
for mf in …/Public/mod.io/5289/mods/*/ModManifest.json; do jq -r .guid "$mf"; done \
  | sort | uniq -d
```

**Fix:** give the *newer* mod's `.asset` a fresh 32-hex `metadata.guid`
(`uuidgen | tr -d -`), rebuild, republish; leave the established mod alone.
After publishing, open the in-game Mods menu once to re-sync the corrected
modfile, then restart — at the price named above: **that visit deletes every
local dev install**, so budget a reinstall of each.

**Two traps while verifying the fix:**

- **The AssetDatabase caches the `.asset` across the symlink.** Editing the
  symlink target is not picked up by a rebuild. A refresh with `ForceUpdate`
  is not enough, and a targeted `ImportAsset` of the mod directory misses it too,
  because the `.asset` is a *sibling* of that directory, not inside it. Force
  re-deserialisation of the ScriptableObject with
  `rm -rf CoreKeeperModSDK/Library/{SourceAssetDB,ArtifactDB,Artifacts}`
  (Editor closed).
- **Read the right manifest.** The publish path builds into a temporary cache
  directory and deletes it — there is no manifest left to inspect, and a a
  validation-only publish run inspects nothing. Only a normal build writes
  `ModManifest.json` into the install output. Verify the GUID there, after a
  fresh build, or you are reading an hours-old file and drawing the wrong
  conclusion.

## `CS0246` on CoreLib types although CoreLib is installed

A mod fails with `CompileFailed` and a batch of `CS0246`/`CS0103` on CoreLib
types, while CoreLib itself is installed, enabled and loads fine. Typically seen
on a *foreign* mod; your own mods are unaffected.

**mod.io has two unrelated dependency concepts, and only one of them matters
here:**

| | Where it lives | What it does |
|---|---|---|
| Platform dependency | mod.io-side, `GET /v1/games/5289/mods/{id}/dependencies` | auto-installs the dependency and shows it in the in-game list |
| Manifest dependency | the `dependencies` array inside the shipped modfile's `ModManifest.json` | **drives the loader's Roslyn compile order** — the topological sort that compiles CoreLib first so its assembly is a metadata reference for dependents |

An author can set the first and forget the second. CoreLib installs and runs,
but the dependent mod is compiled *before* it, so every CoreLib type is
unresolved. Your own mods escape this because the `.asset`'s `dependencies`
block writes `{"modName":"CoreLib","required":true}` into the built manifest —
see [mod anatomy](mod-anatomy.md).

**Diagnosis:**

- The fault surfaces in the game's loader compile step, never in an Editor
  build.
- The `Creating modified script files at …ModLoader\<Mod>` lines are the
  **actual compile order** — and they are not the same as the `loaded mod …`
  order. In a broken setup the dependent's line precedes CoreLib's.
- **Verify at the shipped modfile, not at the source or the local cache.**
  Read-only mod.io REST works with the game's public `gameKey` (in
  `CoreKeeperModSDK/Assets/Resources/mod.io/config.asset`, game ID `5289`); no
  OAuth for reads. Download the modfile via
  `…/mods/{id}/files/{modfile}/download?api_key=…`, confirm it matches the API's
  `filehash.md5`, unzip it, and read its `ModManifest.json`.

**Local workaround for someone else's bug:** back up, then patch the installed
cache manifest at
`…/Public/mod.io/5289/mods/<modId>_<modfile>/ModManifest.json`, changing
`"dependencies": []` to `[{"modName":"CoreLib","required":true}]`. The patch
**survives a game restart** — Core Keeper does not re-verify the modfile hash on
every launch — but is **wiped by any mod.io update of that mod**, because the
update lands in a new `<modId>_<modfile>` directory. CoreLib is modId `3177992`.

The durable fix is the author adding CoreLib to the `.asset` dependencies.

## A previously working mod's Harmony patch suddenly breaks

A mod you did not touch starts throwing — classically a `NullReferenceException`
inside a `[HarmonyPrefix]` dereferencing something that was reliably non-null
before — right after you subscribed to, updated or built *other* mods.

**Cause: mod loading is one shared, all-or-nothing pass.** The loader compiles
every source mod into a single `RoslynCSharp.ScriptDomain` (visible in stack
frames as `PugMod.Loader:LoadScripts (..., RoslynCSharp.ScriptDomain, ...)`), and
a mod that fails to load aborts that pass where it stands: the failing mod is
dropped from the list and every mod sorted after it is not loaded at all this
time round. The ones sorted *before* it are already compiled and already
Harmony-patched — patching happens per mod inside `LoadScripts`, right after the
compile — but the pass returns before the loop that calls `EarlyInit`, so none of
them is initialised.

**It is not compile residue.** Nothing survives a pass: the next one `Reset`s
every mod first — `Shutdown()` on each handler, `UndoHarmonyPatch`, bundles
unloaded — then disposes the domain and builds a new one with
`ScriptDomain.CreateDomain("PugMod")`. What a `CompileFailed` actually changes is
*which* mods are live and *when* the survivors' patches bind: the retry re-does
the whole set at a later point in the game's own initialisation. A prefix that
was safe binding at startup is a NullRef binding mid-initialisation. (The
observation below is verified directly; that the re-bind timing is what breaks
the prefix is the mechanism that fits it, not something proven in isolation.)

**Logical independence between mods is a wrong prior.** In the verified case a
chest-UI mod's `UIManager.Init` prefix started dereferencing a null
`playerInventoryUI` the same launch an unrelated, outdated mod first appeared
with `CompileFailed` (it was built against an older `CoreLib.Util.Extensions`
API). Disabling only that failing mod — touching nothing else — restored the
chest-UI mod.

**Heuristic:** when a previously working Harmony patch NullRefs, do not stop at
the loudest error. Scan `Player.log` for **any** `CompileFailed` earlier in the
same load pass. A failed compile anywhere is not a contained failure — it aborts
the pass every other mod is riding on.

**Bisect** by disabling one mod at a time rather than unsubscribing — see the
two lists below.

### The loader's two disable lists are opposites

| File | Key | Meaning |
|---|---|---|
| `…/Public/mod.io/5289/state.json` | `existingUsers["<userId>"].disabledMods` | *skip this mod* — the loader drops it before the compile step, with no warning dialog |
| `…/LocalLow/Pugstorm/Core Keeper/Steam/<account>/modloader/config.json` | `unsupportedModsToLoad` | *load this incompatible mod anyway* — a force-load override |

`disabledMods` takes mod.io IDs as **strings** (not GUIDs) and the file is
minified JSON — preserve `separators=(",", ":")` when writing it
programmatically. `unsupportedModsToLoad` takes mod **GUIDs**. To get rid of a
stuck incompatible mod cleanly, remove its GUID from `unsupportedModsToLoad`
*and* add its mod.io ID to `disabledMods`.

Both files belong to the loader itself, not to any one host — only the root of
the path above changes with the platform. `unsupportedModsToLoad` is not
save-game state and uses no PlayerPrefs, but it does not survive a game update
either: the loader compares `config.version` against the running version on
startup and clears the whole list on a mismatch, so a mod you confirmed once is
silently dropped again after the next update (see [multiplayer and server](multiplayer-and-server.md)).

### "Loading screen hangs forever" is usually a quit deadlock

Not a slow load. When a `Manager.<Initialize…>` throws — e.g. `Init failed for
UI Manager` — Unity calls `Application.Quit()`, but `ModManager` has registered
a quit-blocking callback that waits on mod.io async operations. Those operations
never complete, because the init crash never let them start, so the quit hangs
forever. What you see is a frozen loading screen.

**The four lines everyone greps for are not the tell — a clean exit logs all
four too.** The block is deliberate: `ModManager`'s handler logs
`waiting for ModIO shutdown`, calls `ModIOUnity.Shutdown(…)` and returns **false
whenever mod.io is initialised**, and `Manager`'s dispatcher reports every
refusal by handler type before giving up on the attempt.

```text
Got quit request
waiting for ModIO shutdown
Exit blocked by ModManager
Quit blocked
```

On a healthy exit the shutdown callback then sets `_pendingQuit`, the next
`ModManager.Update()` calls `Manager.QuitGame()` again, and a **second**
`Got quit request` follows on the very next line — this time unblocked, so
`Running quit handlers` comes right after it and the log runs on through
`CloudSyncUp`, `PlatformManager was destroyed` and the Input-System shutdown
lines.

**The deadlock is that second pair never arriving.** The mod.io shutdown
callback never fires, so no retry is ever scheduled and the log simply stops
after `Quit blocked`. Check what follows those four lines, not that they are
there.

Alongside that, a sibling `UnityCrashHandler64.exe --attach <pid>` process sits
next to `CoreKeeper.exe`. SIGTERM is absorbed by the deadlock; recovery needs
SIGKILL on all of `CoreKeeper.exe`, `UnityCrashHandler64.exe` and
`crashpad_handler.exe`.

## The game window simply closes at the loading screen

A hard, native crash before the main menu — the window disappears, with no
managed exception and no hang. It typically appears right after you changed
assets, which is exactly why it gets blamed on the build.

**Check Steam Cloud before you suspect your mods** — it is one grep, and a Steam
Cloud save conflict has been the cause of exactly this symptom at least once:
verified on a CrossOver/Wine host, where the game crashed at the pre-main-menu
loading screen until cloud sync was switched off. That is one incident on one
host, so treat it as the cheap first check rather than as the identification.
The conflict arises from, for instance, starting the game on a second device or
an interrupted sync.

**Diagnosis in `Player.log`, very early and *before* the mod load:** a
`CloudSyncDown` block with diverging local/cloud timestamps for all save files
(`Admins.json`, `PlayerBans.json`, `worldgenparams/*`, `worldinfos`, `worlds/*`,
`saves/*`, `maps`). That block is the host-independent part — grep for
`CloudSyncDown`.

In the observed case it was followed by 20+ lines of the host failing to write
the conflict backups:

```text
Write failed: Erfolg : '…\cloudconflicts\…pugbackup' (-2147024896)
```

Those write failures are a Wine artifact ([platforms and hosts](platforms.md)),
and the word after `Write failed:` is the Windows locale's name for
`ERROR_SUCCESS` — `Erfolg` because that host runs a German locale. Grep the
`cloudconflicts` path, not the message; on a host that writes the backups
successfully, the `CloudSyncDown` block and the diverging timestamps are all
this entry gives you to go on.

**Why a mod is the wrong suspect once you see that block:**

- A native crash (window closes) is not a managed exception. A mod NRE or
  `CompileFailed` would be logged and the game would keep running.
- The conflict runs *before* the mod load. The mods then load cleanly and
  `Player.log` ends normally with `pooled N modded prefabs` — no crash trace.
  The native crash comes afterwards, at the world-list / main-menu load.
- It reproduces across game and host restarts, and it is orthogonal to the
  game-DLL patches ([platforms and hosts](platforms.md)) — those
  fix directory deletion and save recovery, not the cloud-conflict backup
  writes.

**Fix: disable Steam Cloud globally** (Steam → Settings → Cloud). Core Keeper
frequently **ignores the per-game setting** under the game's properties; only
the global switch reliably makes Steam skip `CloudSyncDown`, after which the
local saves load and the loading screen completes. Resolve the actual conflict
afterwards, deliberately — do not blind-delete save files.

## `Player.log` fills with `GarbageCollector disposing of ComputeBuffer`

A block of these warnings after a session that felt laggy is tempting to read as
the cause of the lag. **Check where in the log they sit before you believe it.**

Normally they bunch in the **last lines of `Player.log`**, immediately after

```text
Input System module state changed to: Shutdown.
```

Both the trailing period and the exact word matter as an anchor: a `Input System
module state changed to: ShutdownInProgress.` line sits two lines earlier, and a
prefix grep matches it too. That position identifies them as the GC's
process-exit cleanup of buffers that were never explicitly `Release()`d — a
shutdown artifact, not a mid-play hitch. A collection that actually ran during
play would spread its warnings through the log rather than cluster them at the
very end. Do not promote them to "the gameplay lag".

**The warning count is not a performance metric.** In one measured case of real
stutter the count stayed **unchanged at 40** with the suspected mod disabled —
while the stutter was gone.

So isolate a suspected render mod the ordinary way: disable it in `state.json`'s
`disabledMods` (the list described above), then judge smoothness directly rather
than by counting warnings.

## Works in singleplayer, not in multiplayer

A Harmony prefix on a DOTS system fires in a local world and never fires on a
dedicated server, with no error and no log line. The cause is Burst bypass
registration being world-scoped and the server's different init ordering — the
mechanism and the fix are in [Harmony and ECS](harmony-and-ecs.md).
Version-compatibility rejections (`Error/BadProtocolVersion`) and the
join-blocking dialog raised by a mod's `requiredOn` flags belong to [multiplayer and the dedicated server](multiplayer-and-server.md).

## A fresh SDK clone will not compile on a macOS Editor host

The first open of a newly cloned `CoreKeeperModSDK` on macOS ends in compilation
errors and the "Enter Safe Mode" prompt, with `CS0246` naming `Steamworks`.
Nothing else in the SDK can be reached until it is resolved — the failure blocks
the SDK from initialising at all.

**It is a platform gate, not a missing Steam installation.** The SDK ships two
Facepunch.Steamworks managed DLLs, each restricted to one Editor platform and
both explicitly off for macOS:

| Plugin | `Editor.OS` | `OSXUniversal.enabled` |
|---|---|---|
| `Facepunch.Steamworks.Win64.dll` | `Windows` | `0` |
| `Facepunch.Steamworks.Posix.dll` | `Linux` | `0` |

So on a macOS Editor neither loads, and the two SDK sources carrying
`using Steamworks;` fail to compile.

**Fix — four single-value YAML edits** in
`Assets/Plugins/CoreKeeperModSDK/Facepunch.Steamworks.Posix.dll.meta`:

| Key | Value |
|---|---|
| `Exclude OSXUniversal` | `0` |
| `OS` | `AnyOS` |
| `enabled` | `1` |
| `CPU` | `AnyCPU` |

Then close Unity and delete `CoreKeeperModSDK/Library/` to force a clean
re-import.

**Enabling the managed DLL is safe although `libsteam_api.dylib` is absent on
macOS.** The runtime mod contains no Steamworks references, so nothing that ships
reaches the missing native library at play time. The edit makes the SDK compile;
it does not make Steam Workshop upload work — the Editor's upload tab would still
fail on macOS for want of that native library.

This is an SDK-level, Editor-only issue: it is inert on Windows and Linux Editor
hosts, unrelated to the Wine/CrossOver game host, and it costs one fix per SDK
clone — a fresh clone reproduces it.

## The Unity Editor hangs at "Initial Asset Database Refresh"

The Editor never gets past the splash after a `-batchmode` build has run against
the same project.

`~/Library/Logs/Unity/Editor.log` shows an infinite retry loop:

```text
Connectivity with IL Post Processor runner cannot be established yet. Retrying.
System.InvalidOperationException: Can't find file /tmp/ilpp.sock-<hash>
```

The IL-Post-Processor subprocess never creates its Unix socket, so the asset-DB
refresh blocks forever. It does **not** self-recover.

**What is established:** a preceding batchmode build is the reliable trigger,
and no `dotnet`/ILPP runner process is running at all — so the socket is missing
because nothing ever started, not because a runner crashed. The
`ilpp.sock-<hash>` name is identical across hung sessions.

**What is inference:** *why* the runner does not start. The batchmode build
leaves the `Library/Bee` and ILPP artifacts in a state the next interactive open
does not accept, and the Hub restart below being decisive points at the
licensing IPC environment rather than at the artifacts alone. Both are
consistent with the evidence; neither is proven.

**This is not a corrupt prefab or script.** If the batchmode build reported
success, it already imported and ILPP-processed the whole project.

**Recovery — both halves are required.** Clearing artifacts alone does not fix
it; it hangs again on reopen. The Editor has no unsaved state while stuck at the
initial refresh, so killing it is safe.

```bash
pkill -9 -f "Unity.*CoreKeeperModSDK"
rm -rf CoreKeeperModSDK/Temp          # lockfile + ILPP state
rm -rf CoreKeeperModSDK/Library/Bee   # ILPP/build cache, rebuilt on next open
rm -f /tmp/ilpp.sock-*
```

Then **quit and restart the Unity Hub** — this is the decisive step, as it
resets the licensing/IPC environment. Reopen the project; the first open does a
one-time fresh ILPP/Bee rebuild and is slower, but should not hang. If it still
hangs, a reboot clears any remaining wedged Unity IPC.

**Prevention: keep the two uses of the shared project apart in time.** The
concurrent direction is already blocked — the Editor's lock aborts a batchmode
run with `Abort trap: 6` and "It looks like another Unity instance is running
with this project open". The unguarded direction is the sequential one: any
batchmode build can leave the *next* interactive open to hang. When someone
opens the Editor to inspect a prefab, pause builds until they are done, and
expect the recovery above if a build ran in between.

## A newly linked mod builds to an empty file list

Bee compiles the mod's DLL correctly (it is there under
`Library/Bee/artifacts/*.dag/<Mod>.dll`), but the build produces a manifest with
`files: []` and neither a `Scripts/` nor a `Bundles/` folder in the install
output.

**Cause:** `ModBuilder.BuildMod`
(`Packages/dev.pugstorm.mod/SDK/Editor/ModBuilder.cs:53`) calls
`AssetDatabase.FindAssets("t:Object", new[] { modDirectory })`. In batchmode
that resolves against `Library/SourceAssetDB` — Unity's persistent asset
database, a SQLite file updated incrementally when the Editor opens, and a
cache separate from Bee and ScriptAssemblies. It does not pick up the children
of a freshly symlinked mod folder. `IsValidFolder` returns true while
`FindAssets` returns zero hits.

**None of these help** (all verified): deleting only `Library/Bee` and
`Library/ScriptAssemblies`; `AssetDatabase.Refresh(ForceUpdate | ForceSynchronousImport)`;
`AssetDatabase.ImportAsset(modPath, ImportRecursive | ForceSynchronousImport)`;
per-file `ImportAsset` calls wrapped in `StartAssetEditing`/`StopAssetEditing`.
Correct `.meta` files (parent-folder `DefaultImporter` + `folderAsset`, asmdef
`AssemblyDefinitionImporter`) are **necessary but not sufficient** — without the
reset, `FindAssets` stays deaf.

**Fix — drop the caches so Unity does a full reindex including symlinks**
(Editor closed):

```bash
rm -rf CoreKeeperModSDK/Library/SourceAssetDB \
       CoreKeeperModSDK/Library/Bee \
       CoreKeeperModSDK/Library/ScriptAssemblies \
       CoreKeeperModSDK/Library/ArtifactDB \
       CoreKeeperModSDK/Library/Artifacts
```

The next build re-imports everything (about 30 s extra, once per newly added
mod). Afterwards the mod is known to SourceAssetDB and normal builds work.

**To confirm before spending an hour on `.meta` files**, add an
`AssetDatabase.FindAssets("t:Object", new[] { settings.modPath })` probe right
before `ModBuilder.BuildMod` and log its `Length`. `0` means the reset is due.

### The same reset for an established mod built from a git worktree

An existing mod is immune to this only when built from the main checkout, where
earlier interactive Editor sessions put it into SourceAssetDB. Build it from a
**git worktree** — where the SDK's `Assets/` symlink points into the worktree
tree — and the AssetDatabase **intermittently misses edits through the
symlink**.

**Trap: the bundle's mtime lies.** It is re-exported fresh on every build, so
the usual "is the bundle newer than my edit?" check gives an all-clear — while
the export happens from the *stale imported* asset. In the observed case a
prefab `localPosition.x` edit never reached the loaded bundle over several
builds, while `localPosition.y` and `DrawMode`/`m_Size` edits to the same
objects in the same session did. It is intermittent, not field- or
block-specific.

The fix is the same cache reset. In a tight worktree calibration loop, clear
the caches **proactively before every build** — a slower reimport beats another
round of "is this stale, or does the value simply not do anything?".

## An edit to a shared editor helper appears to have no effect

You change an editor helper that is shared across several mods (a CLI build or
publish entry point), run it, and the run contradicts the change you just made.

**Two compounding causes:**

1. **The helper compiles into *every* linked mod's `<Mod>.Editor` assembly**,
   because the one shared source file is symlinked into each mod's editor
   folder. So the same
   class exists many times over, and
   `-executeMethod <Namespace>.<Class>.<Method>` runs the **alphabetically
   first** assembly that defines the type — regardless of which mod you are
   building. That is harmless while all copies are identical, which is why it
   only bites right after you edit one.
2. **Unity's AssetDatabase does not detect edits to a symlink *target*.** A
   build re-links only the mod being built, so only that mod's symlinks get a
   fresh mtime and reimport. Every other mod's editor assembly keeps a stale
   compiled copy — and the alphabetically-first pick may well be one of those.
   All the `*.Editor.dll` files can share one mtime and still contain different
   source versions.

**The symptom has three shapes, and two of them look like your code is wrong:**

| What you see | What it actually is |
|---|---|
| Stack-trace `:line` numbers that do not match the current source | stale assembly |
| A newly added log line producing **no output at all** | stale assembly — reads as "the feature does not support this mode" |
| An error message you thought you had **replaced**, sometimes with a log line the new code cannot reach | stale assembly — the most expensive misread available |

A partially-new run is possible too: an edit made minutes earlier appears while
the newest one does not, because only the earlier one made it into the compiled
assembly.

**Fix ladder — both rungs, in order:**

1. **Re-link every mod**, not just the one you are building, so all the symlinks
   get a fresh mtime and the AssetDatabase reimports the sources.
2. **`rm -rf CoreKeeperModSDK/Library/{ScriptAssemblies,Bee}`** with the Editor
   closed, so Unity recompiles every editor assembly from source on the next
   batchmode launch.

Neither rung implies the other, and each has, on its own, failed to pick up a
change: re-linking repairs links but not the compile cache, and dropping
`ScriptAssemblies` alone still ran the old helper when the sources had not been
reimported. It is lighter than the full `Bee`/`SourceAssetDB` nuke above and
targets scripts only.

**Whenever a verification run contradicts a change you just made to a shared
helper, suspect staleness before suspecting the change.** Gate shared-helper
changes behind a validation-only run first, if your tooling has one — a
non-mutating path is a safe compile-and-freshness probe before any real publish.

## Symptoms owned by other chapters

| Symptom | Where |
|---|---|
| `CompileFailed` with `failed code security verification`, illegal namespace/type/member references | [the sandbox](sandbox-and-config.md) |
| Text renders as raw term keys instead of translations | [localisation](localisation.md) |
| A Harmony patch that never binds at all ("Undefined target method"), or binds and never fires | [Harmony and ECS](harmony-and-ecs.md) |
| Loader failures caused by stale `ModLoader/` directories, Roslyn satellite-assembly lookups, or failing save writes on a Wine host | [platforms and hosts](platforms.md) |
| A client refusing to join with `Error/BadProtocolVersion`, or a dialog demanding a mod be disabled before connecting | [multiplayer and the dedicated server](multiplayer-and-server.md) |
