# Core Keeper modding — Roadmap

Work that concerns every mod here rather than one of them. A mod's own roadmap
lives in that mod's `docs/roadmap.md`.

Points that are **deliberately cut to stand alone**, not a shopping list for a
release. Each entry records what is already settled and what still has to be
decided, so picking one up does not mean re-deriving the groundwork.

## Workshop subscribers may get every mod refused as incompatible

A player who subscribes to one of these mods on the Steam Workshop may be told
at startup that it does not support the running game version, and be offered
only **Disable** or **Load Anyway** — for every mod here, on every game version,
because nothing in the Workshop pipeline ever states a version.

**Settled, from the decompile (1.3.0.2): the Workshop loader asks the same
question the mod.io loader asks.** Both loaders call
`ModVersion.IsCompatible(Application.version, tags)` and pass the result to
`Integration.AddMod` as `supportsCurrentVersion` — the mod.io one with the
profile's tags (`PugMod.Platform`, `ModIOLoader.Init`), the Workshop one with
the item's `entry.Tags` (`PugMod.Loader`, `SteamWorkshopLoader.InitAsync`).
`IsCompatible` is true only when some tag starts with `x.y.z` matching the
game's first three version components; `AddMod` refuses a `false` unless the
mod's GUID is already in `unsupportedModsToLoad`. That is the same rejection [the handbook describes for a stale mod.io tag](ck/troubleshooting.md#cheaper-if-you-have-a-log-a-stale-game-version-compatibility-tag),
reached by a second route the handbook does not mention.

**Settled: our items carry no such tag.** `utils/steam_bundle.py` sends the
category, application-type and access-type values only; the `tags:` list a
publish writes into `<Mod>_Steam.asset` shows the result, e.g. `Library`,
`Quality of Life`, `Client`, `Script` for Simple Crafting Pool Extender. The
mods concerned are the ones with a Workshop id, found at the time rather than
listed here:

~~~bash
grep -l 'fileId: [1-9]' */unity/*/*_Steam.asset
~~~

**Not yet verified: that it happens in the running game.** Everything above is
read from code, and the author's client has never exercised this path: its
Workshop loader runs and logs `no subscribed workshop items found.`, since the
mods reach it through mod.io and dev installs. Most of them also sit in its
`unsupportedModsToLoad` from earlier "Load Anyway" clicks, so even a Workshop
subscription there would not show the refusal. The test is a Workshop
subscription to a mod whose GUID is not in that list — on this client, one of
the few that are not, or on a clean one. The `Player.log` then says either
`not loading incompatible mod <Name>` or `loaded mod <Name> from steam workshop`.

**To decide, and it depends on a platform fact nobody has checked: whether a
Workshop item can carry a version tag at all.** Core Keeper's Workshop
configuration defines the allowed tag values, and [Steam drops an unknown value without a word](ck/steam-workshop.md#tags-are-sent-flat-and-grouped-by-the-platform).
The handbook says the Workshop has no game-version dimension, but that was
written about what the listing shows, not tested by sending one.

- **If a value such as `1.3.0` is accepted**, the fix is in the pipeline:
  derive the Workshop version tags from `CK_GAME_VERSION` the way
  `CLIPublishHelper` does for mod.io — stand-in rule included, since the
  loader compares only three components — and republish each item. That
  needs a metadata-only Steam path, which `--profile-only` does not have yet;
  without one every item takes a full Workshop update with a change-history
  entry.
- **If no version value is accepted**, nothing on our side can fix it. Then
  the remaining work is reporting it upstream (a loader that demands a tag the
  platform cannot carry), saying so in each `steam-description.txt` so a
  subscriber knows "Load Anyway" is expected, and correcting
  `docs/ck/steam-workshop.md` — which currently records the missing dimension
  without its consequence.

Either way `docs/ck/steam-workshop.md` needs a paragraph on this once the
answer is in, and `docs/ck/troubleshooting.md`'s stale-tag section should name
the Workshop as the second route.
