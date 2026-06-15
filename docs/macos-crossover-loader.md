# macOS / CrossOver — distribution & loader

How a locally developed Core Keeper mod is loaded under CrossOver/Wine, and the loader surfaces for incompatible mods.

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
