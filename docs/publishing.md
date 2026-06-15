# mod.io Publishing

How every Core Keeper mod is published to mod.io through the SDK's plugin.

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

### Mod dependencies → mod.io platform dependencies

On publish, `CLIPublishHelper` syncs the `.asset`'s `metadata.dependencies`
list (e.g. `CoreLib`) to the mod's **mod.io platform** dependency list
(`AddDependenciesToMod` / `RemoveDependenciesFromMod`) — a separate concern
from the loader-side `ModManifest.json` dependencies (which stay the loader's
source of truth). The step runs between the profile create/edit and the
modfile upload, so an unresolvable required dependency aborts before anything
is uploaded.

- **modName → ModId resolution.** The `.asset` references a dependency by its
  loader **name** (`CoreLib`); the mod.io API needs a numeric **ModId**. A
  self-populating cache `utils/modio-dependencies.json` (`{modName → modId}`,
  versioned) bridges this; its path is passed via the `.envrc` var
  `MODIO_DEPS_MAP` (set only by mods that declare dependencies). On a cache
  miss the helper runs a `GetMods` search (pagination params are **required** —
  `SetPageIndex`/`SetPageSize`, else error 20201), accepts the ID only on a
  single normalised-name match (case/space-insensitive), and writes it back to
  the cache (allowed even in `--dry-run`).
- **Failure severity follows the `.asset` `required` flag** (which is *not*
  transmitted to mod.io — the API has no per-dependency required attribute):
  an unresolvable **required** dependency aborts the publish; an unresolvable
  **optional** one logs a warning and is skipped.
- **Full sync, not additive:** the helper diffs the resolved target set against
  `GetModDependencies` and both adds missing and removes extra, so the mod.io
  list mirrors the `.asset` exactly. `--dry-run` logs the plan and skips the
  add/remove calls.

> ⚠️ Known build gotcha: the shared `CLIPublishHelper`/`CLIBuildHelper` compile
> into **every** linked mod's `<Mod>.Editor` assembly, so the class exists in
> several assemblies and `-executeMethod` runs the alphabetically-first one
> (`CavelingDiviningRod.Editor`). Because Unity's AssetDatabase does **not**
> detect edits to a symlink *target*, only the currently-built mod's symlinks
> are refreshed per build — the other mods' editor assemblies keep a **stale**
> compiled copy of the shared helper, and `-executeMethod` may run that stale
> copy. After editing a shared helper, re-link **all** mods (run `link.sh` for
> each) so every editor assembly recompiles from the current source before
> relying on a publish/build run.

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
