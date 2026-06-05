# CLAUDE.md — Core Keeper modding (shared)

Parent-level guidance inherited by every Core Keeper mod project under this
directory. Each mod also has its own `CLAUDE.md` with mod-specific detail
(patch targets, classes, build scripts). This file holds **only** what is
true for *all* mods built against Pugstorm's `CoreKeeperModSDK` on this
machine — change it only when an insight is genuinely mod-agnostic.

## Directory layout

- `CoreKeeperModSDK/` — the Pugstorm SDK clone, **shared** by every mod. Its
  own git repo. Mods do not vendor a private SDK copy.
- `<mod-name>/` — one directory per mod, each its own git repo. Currently:
  `disable-durability/` and `faster-talents/`.

A mod keeps **every file the Unity Editor generates for it** — `.cs`
sources, `.asmdef`s, the ModBuilderSettings `.asset`, and all `.meta` GUID
carriers — in a `unity/` directory that mirrors the SDK's `Assets/` tree
1:1. Otherwise those files exist only as untracked files inside the shared
SDK clone — one `git clean` or re-clone away from loss.

`utils/link.sh` symlinks that mirror into `CoreKeeperModSDK/Assets/`: one
**directory** symlink for the mod folder — which captures every current and
future Editor-generated file, so nothing has to be wired up by hand — plus
file symlinks for any Assets-level files beside it. The symlinks encode
absolute paths, so they dangle after a worktree switch or repo move;
`utils/build.sh` re-runs `link.sh` on every build so this self-heals.

## Required setup (per machine / per SDK clone)

- **Unity Editor `6000.0.59f2`** — exact patch version, pinned in the SDK's
  `ProjectVersion.txt` (the SDK `README.md` is one patch behind — do not trust
  it). Install via Unity Hub with **Linux Build Support (Mono)** and, on
  macOS, **Windows Build Support (Mono)**.
- **`CoreKeeperModSDK` clone** — the wizard's "Create New Mod" + "Update Game
  Files" must be run once.
- The Unity Editor **locks the project** — it must be closed during any
  `-batchmode` build.
- **`corekeeper-patch` applied to the installed game's `PugMod.Loader.dll`** —
  required on macOS / CrossOver hosts. Two IL patches: (Patch 1) fixes the
  Wine `Directory.Delete` failure on stale `ModLoader/<ModName>/Scripts/`,
  (Patch 2) forces `CultureInfo.DefaultThreadCurrentUICulture =
  InvariantCulture` so Roslyn doesn't fail compiles by chasing the missing
  `de-DE` satellite assembly. Every Core Keeper update reverts the DLL to
  stock — re-apply after each update. Rationale + canonical commands in
  the `corekeeper-roslyn-locale-bug` memory.

## SDK quirks (apply to every mod)

### macOS Editor — Steamworks compile errors
A fresh SDK clone fails to compile on a macOS Editor host with
`CS0246: ... 'Steamworks'`. The SDK ships Steamworks DLLs gated to Windows/
Linux Editors only; neither loads on macOS. Fix: enable
`Assets/Plugins/CoreKeeperModSDK/Facepunch.Steamworks.Posix.dll.meta` for
`OS: AnyOS`. One-time per SDK clone — see
`disable-durability/docs/research/macos-sdk-steamworks-fix.md`.

### Manifest fields — edit the `.asset`, not `ModManifest.json`
A mod's `ModManifest.json` is **build-generated** from its ModBuilderSettings
`.asset` (`unity/<Mod>/<Mod>.asset`, the `ModMetadata` block: `name`,
`displayName`, `requiredOn`, `dependencies`, …). The build writes the real
manifest (with computed file GUIDs + AssetBundle entries) into the output dir;
the loader reads *that* via `JsonUtility.FromJson<ModMetadata>`. A hand-authored
repo `ModManifest.json` is the **wrong schema** (`name_id`/`version`/
`modDependencies` keys are silently ignored on load) and is read by nothing —
do **not** keep one. So edit manifest fields directly in the `.asset` YAML's
`metadata:` block:
- The SDK mod-settings Editor UI is unreliable for `displayName` (cannot be set
  through the GUI) and `requiredOn` (choosing "Client and Server" writes `-1`
  / "Everything"). Set `displayName:` and `requiredOn: 3` (ClientAndServer)
  directly in the `.asset`.
- Mod dependencies (e.g. CoreLib) live in the `.asset`'s `dependencies:` list
  (`- modName: CoreLib` / `required: 1`) and flow into the built manifest.

The published mod.io listing does **not** read the manifest either: profile name
← `metadata.displayName` (fallback `metadata.name`) — so the human title
"Item Checklist" can differ from the internal identity "ItemChecklist"; summary
← `MOD_SUMMARY` env, version + changelog ← `CHANGELOG.md`, modId ←
`<Mod>_modio.asset`, version tag(s) ← `CK_GAME_VERSION` env — a
**space-separated list** of one or more game versions, each published as its
own compatibility tag (all in `utils/CLIPublishHelper.cs`).

### Runtime asmdef from the wizard
The "Create New Mod" wizard emits the mod's runtime `.asmdef` already
populated with the full game-DLL reference set (`Pug.Other.dll`,
`0Harmony.dll`, `PugMod.SDK.Runtime.dll`, …). Mod code compiles against game
types and Harmony out of the box — no manual reference editing is needed.

## Runtime constraints (apply to every mod's code)

### RoslynCSharp sandbox — no System.IO
Mods ship `Scripts/*.cs` and are compiled at load time inside a default-deny
sandbox. `System.IO.*`, `System.Diagnostics.Process`, reflection-emit and
similar BCL surface fail the compile on first reference (`mod load error:
CompileFailed`). Either avoid those APIs (hardcode what would otherwise live
in a runtime `config.json`) or set `skipSafetyChecks: true` in
`ModManifest.json` to disable the sandbox entirely — acceptable for
personal-use mods, at the cost of whatever the safety checks guarded.

### Burst-compiled systems are not Harmony-patchable
A DOTS system whose `OnUpdate` is Burst-compiled cannot be intercepted by
Harmony. Call `BurstDisabler.DisableBurstForSystem<TSystem>()` in
`IMod.Init()` to move the system off Burst *before* the patch needs to bind.

### IMod lifecycle
`IMod` (namespace `PugMod`) has five methods: `EarlyInit`, `Init`,
`ModObjectLoaded`, `Shutdown`, `Update`. `[HarmonyPatch]` classes are
**auto-discovered** by the loader — no manual `Harmony.PatchAll()` call. The
bootstrap `IMod` class and the patch class are conventionally separate files.

### Editor-only asmdef
`ModBuilder` / `ModBuilderSettings` are editor-only. A combined runtime+editor
asmdef cannot reference an editor-only one, so a CLI build helper (for
`unity -batchmode -executeMethod`) needs its own `*.Editor.asmdef`.

## macOS / CrossOver — distribution & loader

Core Keeper runs under CrossOver here. Two orthogonal concerns:

1. **How a locally developed mod gets loaded at all** — Pugstorm's loader
   only looks at mods that arrive via the mod.io subscription path. A mod
   sitting in a bottle folder with no matching `state.json` subscription is
   simply not seen. The fake-ID install (next section) is the mechanism
   that makes a not-yet-published local mod loadable.
2. **Wine-specific loader bugs** that used to break loading independently
   of how the mod was distributed — the `RemoveDirectoryRecursive` failure
   on stale `ModLoader/<ModName>/Scripts/` (Wine long-path bug) and the
   Roslyn `de-DE` satellite lookup failure. Both are fixed by
   `corekeeper-patch` (see "Required setup" above). They affected
   mod.io-distributed mods just as much as fake-ID ones, on any update
   that left a stale `ModLoader/` folder behind.

The rest of this section documents (1) and the dialog/override surfaces
the loader exposes for incompatible mods.

### Fake-ID dev install — loading a not-yet-published local mod

Populate three locations under the CrossOver bottle, using a fake mod ID
not in mod.io's catalog. Each mod needs its **own** distinct fake ID
(`9999999`, `9999998`, …) or their `mods/<id>_1/` folders collide:
1. `…/mod.io/5289/mods/<fakeid>_1/` — extracted mod files
2. `…/Temp/Pugstorm/Core Keeper/5289/<fakeid>_1.zip` — ZIP cache the loader expects
3. `…/mod.io/5289/state.json` — subscribe the fake ID + a stub `mods` entry

The stub `mods` entry's `modObject` **must** carry a `tags` array containing
the running game's version (e.g. `1.2.1.2`, read from `Game version: X` in
`Player.log`). The loader runs `ModVersion.IsCompatible(gameVersion,
modProfile.tags)`; with no matching tag it flags the mod "not compatible with
current version" and shunts it into the main-menu warning dialog. Real mod.io
mods carry these version tags — the fake install must replicate one.
`install-macos.sh` builds this array from `CK_GAME_VERSION`, which is a
**space-separated list** — set it to multiple versions (e.g.
`"1.2.1.2 1.2.1.4"`) to make one local dev build loadable across several game
builds; a single value is just a one-element list.

`utils/install-macos.sh` writes all three locations and clears
`…/Temp/Pugstorm/Core Keeper/ModLoader/<ModName>/` before launch (defensive
hygiene against the Wine stale-folder issue; with `corekeeper-patch` Patch 1
applied, the cleanup is no longer load-critical but still avoids unrelated
clutter accumulating).

**Do not open the in-game Mods menu** while a fake-ID mod is installed — it
triggers a mod.io API sync that resolves the fake ID against the real catalog,
finds nothing, and deletes the local files + ZIP. Game start, world load and
gameplay are safe; only the mod browser triggers the sync. If the entry is
wiped, re-run the mod's install step to restore all three locations.

Subscribing to a real mod.io mod on its website does **not** install it —
the install happens only when the in-game Mods menu is opened and the
client syncs pending subscription changes. So opening that menu is
sometimes unavoidable; when you do, the same sync wipes **every** fake-ID
mod alongside applying the newly subscribed one. Plan for it as a
two-step: open the menu to let the mod.io change land, then rebuild each
fake-ID mod (`source .envrc && ../utils/build.sh`, which re-runs
`install-macos.sh`) to restore all three locations.

### Incompatible-mod dialog & `unsupportedModsToLoad`

If the loader flags a mod incompatible for any reason, Core Keeper's main
menu shows a warning dialog (`TitleMenuIncompatibleModWarning`) offering
**Disable** or **Load Anyway**. **Load Anyway** force-loads the mod (via
`Loader.LoadUnsupportedMod`) and restarts the game; the choice persists
across launches — a usable fallback when a local mod is wrongly rejected.

The "Load Anyway" choice is stored mod-loader-side in `config.json`:

```
…/LocalLow/Pugstorm/Core Keeper/Steam/<steam-account-id>/modloader/config.json
```

`{"version":"1.2.1","unsupportedModsToLoad":["<mod-guid>", …]}` — the
loader (`PugMod.Loader.dll`, the game's copy, not the SDK's) skips its
`!supportsCurrentVersion` rejection for any mod GUID in
`unsupportedModsToLoad`. The list is **not** save-game state and uses no
PlayerPrefs. On startup `Loader.Init` compares `config.version` against the
running game version (`ModVersion.GetVersion(Application.version)`,
truncated to three parts) and **clears the whole list** on any mismatch — so
a "Load Anyway" decision survives only until the next Core Keeper update,
after which every incompatible mod re-triggers the warning dialog. To reset
manually, drop the GUID from the file (or delete it) while the game is
closed; the loader rewrites `config.json` on exit.

### Disabling a mod (`state.json:disabledMods`)

To exclude a single subscribed mod from loading without unsubscribing on
mod.io, append the mod.io ID (string) to
`existingUsers["<userId>"].disabledMods` in
`…/Public/mod.io/5289/state.json`. The loader skips disabled mods **before
the compile step entirely** — no `TitleMenuIncompatibleModWarning` dialog
appears. Format: mod.io IDs as strings (not GUIDs); the file is minified
JSON, preserve `separators=(',',':')` when editing programmatically.

Do not confuse `disabledMods` with `unsupportedModsToLoad` — they are
opposites. `disabledMods` says "skip this mod"; `unsupportedModsToLoad`
says "load this incompatible mod anyway". To get rid of a stuck
incompatible mod cleanly: remove the GUID from `unsupportedModsToLoad`
*and* add the mod.io ID to `disabledMods`.

For "why a previously-working mod suddenly crashes after a new subscribe"
see the `corekeeper-compile-fail-cascade` memory — Pugstorm's loader
compiles all source mods into one shared `RoslynCSharp.ScriptDomain`, and
one mod's `CompileFailed` can desynchronise an unrelated mod's Harmony
patches. The same memory documents the loading-screen quit-deadlock
symptom (`Exit blocked by ModManager`, requires `SIGKILL`).

### Constants & paths

Core Keeper's mod.io **game ID is `5289`**; the CrossOver bottle is named
**"Core Keeper"**. Full background and upstream-fix candidates:
`disable-durability/docs/research/macos-crossover-wine-workaround.md`.

## Build pattern (shared `utils/`)

All mods build through one shared copy of the build scripts in
`core_keeper/utils/` — `build.sh`, `link.sh`, `install-macos.sh`,
`upload.sh`, `uninstall-macos.sh`. The scripts
are mod-agnostic: each mod supplies its identity through `export`s in its own
`.envrc` (`MOD_NAME`, `MOD_NAME_ID`, `MOD_SUMMARY`, `FAKE_MOD_ID`) alongside
the machine paths (`UNITY_BIN`, `SDK_PATH`, `MOD_INSTALL_PATH`,
`CK_GAME_VERSION`). To build a mod, `source` its `.envrc` and run
`../utils/build.sh` from the mod repo root:

```bash
cd <mod-name>
source .envrc
../utils/build.sh
```

`build.sh` refreshes the SDK symlinks (`link.sh`), runs a Unity batchmode
build via `-executeMethod` (`<MOD_NAME>.Editor.CLIBuildHelper.Build`), then on
macOS auto-runs `install-macos.sh` to place the fresh build into the
fake-ID locations so the loader picks it up on next launch. Each script
resolves the mod repo from its first argument, defaulting to `$PWD`.

To publish a mod to mod.io, `source` its `.envrc` and run
`../utils/upload.sh` from the mod repo root. The script refreshes the SDK
symlinks and runs a Unity batchmode build via
`<MOD_NAME>.Editor.CLIPublishHelper.Publish`, which builds the mod and
drives the mod.io plugin to create/update the mod profile and upload a new
modfile. `upload.sh --dry-run` builds and validates without any writing
mod.io call.

A new mod.io profile is created **hidden**; review it on the website and
switch it to visible manually. The real mod ID is stored in the SDK-native
`<mod-name>/unity/<MOD_NAME>/Editor/<MOD_NAME>_modio.asset` — versioned in
git, so re-runs reuse the profile instead of creating a second one.

`utils/uninstall-macos.sh` is the counterpart to `install-macos.sh`: it
removes a fake-ID local dev install from the CrossOver bottle.

### Shared editor helpers and localisation tooling

The CLI editor helpers (`CLIBuildHelper`, `CLIPublishHelper`) and the
`LocalizationGenerator` now live in `core_keeper/utils/` and are symlinked
into a mod's `unity/<Mod>/Editor/` by `link.sh`, gated behind the per-mod
`.envrc` flag `USE_SHARED_EDITOR_HELPERS=1`. When that flag is set,
`build.sh` / `upload.sh` use the constants
`-executeMethod CoreKeeperModUtils.CLIBuildHelper.Build` /
`...CLIPublishHelper.Publish` rather than the per-mod
`<Mod>.Editor.CLIBuildHelper.Build` path.

**All three mods are migrated.** ItemChecklist was the pilot;
`faster-talents` and `disable-durability` followed. Each sets
`USE_SHARED_EDITOR_HELPERS=1` and adds `MOD_REPO_ROOT="$PWD"` (for the shared
`CLIPublishHelper`'s CHANGELOG lookup); both followers ship no
`localization.yaml`, so the loc generator is a no-op for them. No mod keeps
per-mod `<Mod>.Editor.CLI*Helper` sources anymore.

Also in `utils/`:
- **`ck-language-addresses.json`** — the CK language address→ISO table (13
  runtime languages), captured once via a runtime dump because
  `LanguageDataBlock`s are runtime-only and are not enumerable through the SDK
  editor API at build time. Required by `LocalizationGenerator`.
- **`LocalizationGenerator.cs`** — reads a mod's
  `Localization/localization.yaml` and templates raw `.asset` YAML for each
  language (Option II: raw asset templating). Used by ItemChecklist; the same
  generator can be reused by any mod that adopts the shared-helper pattern.

`core_keeper/` is itself a git repo, but its `.gitignore` tracks only
`utils/`, this `CLAUDE.md`, and `.tool-versions` — the mod repos and the SDK
clone are independent repos and are deliberately ignored so they are not
embedded.

## mod.io publishing (applies to every mod)

Publishing runs through the SDK's own mod.io plugin (`ModIOUnity`), not a
REST client — `utils/upload.sh` invokes a per-mod Editor class
`CLIPublishHelper` (sibling of `CLIBuildHelper`) via `-executeMethod`.

- **One-time login:** open the Pugstorm Mod SDK window, use the "Log in" tab
  (email + security code). The mod.io plugin persists the session;
  batchmode publishes authenticate from it. The session expires after about
  a year — re-login through the window when that happens.
- **Version + changelog:** taken from the mod's `CHANGELOG.md`. The topmost
  `## [x.y.z]` entry is the published version; its body is the modfile
  changelog. There is no version field anywhere in mod source.
- **Async batchmode:** the mod.io calls are asynchronous, so `upload.sh`
  invokes Unity **without `-quit`** and `CLIPublishHelper` calls
  `EditorApplication.Exit` itself; a `timeout` guards a hung run.

### The three mod IDs

Three distinct uses of a "mod.io ID", deliberately kept separate:

- **Publishing** uses the **real** mod ID, stored in
  `unity/<MOD_NAME>/Editor/<MOD_NAME>_modio.asset`.
- **Playing** the published mod uses the **real** ID — written by the game
  client when you subscribe normally in the in-game Mods menu.
- **Local dev builds** use the **fake** `FAKE_MOD_ID` via `install-macos.sh`,
  which is the mechanism by which a not-yet-published mod can be loaded at
  all (Pugstorm's loader only walks the mod.io subscription path); the
  fake ID also keeps the dev build out of the real mod.io catalog sync.

**Dev/Prod coexistence:** never have both the fake-ID dev install and a real
subscription of the same mod active — the loader would load both copies and
double-apply Harmony patches. The mod author runs only the fake-ID dev
install and does not subscribe to their own mod. To test the published
build as an end user, first run `utils/uninstall-macos.sh` to remove the dev
install.

## Conventions

- **Personal-use, non-commercial only** (Pugstorm EULA).
- Documentation files (`CLAUDE.md`, `README.md`, `docs/`) are English; chat
  answers are German.
- Each mod is an independent git repo with its own `CLAUDE.md` for
  mod-specific detail.

> Note: the two `docs/research/` notes referenced above currently live inside
> the `disable-durability/` repo, since that is where they were first written.
> Their content is mod-agnostic — if a second mod needs them, consider
> promoting them to a shared location under this directory.
