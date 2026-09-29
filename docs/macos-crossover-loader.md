# macOS / CrossOver — this machine's dev install

How a not-yet-published mod is made loadable on this host.

**What a Wine-based host breaks and why** — the failing directory delete, the
Roslyn satellite lookup, the lost first save — is in [`docs/ck/platforms.md`](ck/platforms.md).
All of it is fixed here by `corekeeper-patch` (see `CLAUDE.md`, "Required
setup"), and none of it is specific to how a mod was distributed.

**The loader's two disable lists** — `unsupportedModsToLoad` and `disabledMods`,
what each does and how to clear a stuck mod — are in [`docs/ck/troubleshooting.md`](ck/troubleshooting.md).

What remains here is the fake-ID install: Pugstorm's loader only looks at mods
that arrive via the mod.io subscription path, so a mod sitting in a bottle
folder with no matching `state.json` entry is not seen *by that loader*. The
fake ID is what makes a local build visible to it. (The loader has two further
platforms — a `StreamingAssets/Mods` side-loader, which is how the dedicated
server gets its mods, and Steam Workshop.)

For a quick throwaway question rather than a real dev install, the side-loader
is cheaper than any of this: it [accepts a hand-written manifest](ck/mod-anatomy.md#the-side-loader-accepts-a-hand-written-manifest)
with no build behind it at all.

## Fake-ID dev install — loading a not-yet-published local mod

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

**Do not open the in-game Mods screen** while a fake-ID mod is installed. Since
CK 1.3, merely opening it syncs the subscription list with mod.io, and the fake
ID, which no real subscription contains, drops out of `subscribedMods` in
`state.json`. The mod is then no longer loaded, although its files and ZIP are
still on disk. Pressing **Mod.io** in that screen goes further and deletes the
installation directory and the `mods` entry in `state.json` as well; only the ZIP
survives. Game start and world load are safe.
Either way, re-run the mod's install step to restore all three locations.
Mechanism and measurement: [`docs/ck/mod-anatomy.md`](ck/mod-anatomy.md#the-in-game-mod-menu-and-when-modio-is-contacted).

Subscribing to a real mod.io mod on its website does **not** install it — the
download happens only once **Mod.io** is pressed in the in-game Mods screen, which
enables mod.io's install machinery for the session. So that visit is sometimes
unavoidable; when you make it, it unregisters and deletes **every** fake-ID mod
alongside installing the newly subscribed one. Plan for it as a two-step: open
the Mods screen and press Mod.io to let the change land, then rebuild each fake-ID
mod (`source .envrc && ../utils/build.sh`, which re-runs `install-macos.sh`) to
restore all three locations.

## Constants & paths

The CrossOver bottle is named **"Core Keeper"**; the mod.io game id `5289` that
appears in every path is the game's, not this machine's. Full background and
upstream-fix candidates:
`disable-durability/docs/research/macos-crossover-wine-workaround.md`.
