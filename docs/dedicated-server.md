# Dedicated server (macOS / CrossOver)

Core Keeper's dedicated server is Steam app **1963720**, free and installable
with `login anonymous`. It ships for Windows and Linux only — there is no macOS
build, and none is coming, because the game itself has no Mac build either. On
macOS it therefore runs as the Windows build **inside the same CrossOver bottle
as the game**.

This is worth having for mod work: it is the only way to exercise the
server-authoritative half of a mod (`requiredOn` behaviour, CoreLib server
commands, world-mutating logic) without a second machine.

## Running it

Install it through the bottle's Steam client, or with SteamCMD:

```
steamcmd +login anonymous +app_update 1963720 +quit
```

Then use the helper:

```bash
utils/server.sh start     # launch, wait for GameInfo.txt, print the join string
utils/server.sh status    # running? plus GameID, IP, port, password
utils/server.sh stop      # terminate
utils/server.sh log       # follow CoreKeeperServerLog.txt
```

Configuration comes from the environment (see `.envrc.example`):
`CK_SERVER_WORLD`, `CK_SERVER_PORT`, `CK_SERVER_PASSWORD`,
`CK_SERVER_MAXPLAYERS`, `CK_SERVER_PLATFORM`, plus the shared `CK_BOTTLE_*`
variables the install scripts already use.

Three things about the launch are non-obvious and are baked into the script:

- **`-batchmode` yes, `-nographics` never.** Part of the procedural world
  generation runs on the GPU, so the server needs a graphics device even when
  headless. Under CrossOver the log confirms it with
  `Renderer: AMD Compatibility Mode`; on a Linux host this is the role `xvfb`
  plus the Mesa drivers play.
- **`-port` only works as a command-line argument** — setting it in
  `ServerConfig.json` has no effect. With a port the server accepts direct
  connections; without one it is reachable only through the Steam relay by its
  Game ID.
- **The process must be detached.** `cxstart --no-wait` still keeps it attached
  to the calling shell, so it dies with the caller; the script uses
  `nohup … & disown`.

A cold start with a full mod set takes minutes — every mod's scripts go through
Roslyn and the world is brotli-decompressed on load.

## Sharing one world with the client

The server's data path is `<bottle>/…/LocalLow/Pugstorm/Core Keeper/DedicatedServer/`,
separate from the client's `…/Core Keeper/Steam/<steamId>/`. Copying a world
across creates two copies that drift apart. **Directory symlinks** keep it as
one world:

```
DedicatedServer/worlds          ->  Steam/<steamId>/worlds
DedicatedServer/worldinfos      ->  Steam/<steamId>/worldinfos
DedicatedServer/worldgenparams  ->  Steam/<steamId>/worldgenparams
DedicatedServer/servermaps      ->  Steam/<steamId>/servermaps
```

Verified to work in both directions — the server writes through the symlink into
the client's world file.

- **Directory symlinks, not file symlinks.** Saves are written with a
  `.pugbackup` rotation; anything that deletes and recreates a file would
  replace a file symlink with a real file, and the two copies would silently
  diverge again.
- **Server → client, not the reverse.** This keeps every symlink out of the
  Steam Cloud-synced client directory, where a sync could otherwise overwrite it
  with a plain file.
- **Never run both at once.** The scheme relies on sequential use: stop the
  server before hosting the same world locally.
- **`saves/<n>.json` are characters, not worlds** — `characterGuid`, `skills`,
  `inventory`, `discoveredObjects`. Together with `maps/<n>/` they stay
  client-side; a player brings their character to the server.

## Mirroring the mods

Installed mods live unpacked in `<bottle>/drive_c/users/Public/mod.io/5289/mods/<modId>_<fileId>/`.
Symlink them into the server:

```
CoreKeeperServer_Data/StreamingAssets/Mods/<name_id>  ->  …/mod.io/5289/mods/<modId>_<fileId>
```

Folder names are free — the loader reads each `ModManifest.json` — so `relink`
names them after the mod.io slug (`modObject.name_id`): unique, filesystem-safe
and readable, unlike `mod_<id>`. Note that a mod can carry three different names:
`morelabels` (slug), `More Labels` (mod.io profile, what you see in game) and
`NameChests` (`metadata.name`, the identity the server hashes its `ModId` from). Symlinks are
the right tool here (mod.io is the only writer, the server only reads); copies
would go stale on the next mod update, which immediately breaks the join.

**The symlinks drift, and in four different ways** — all of them quiet, because
the loader gates on `File.Exists(ModManifest.json)` and skips a broken link
without a word:

| Drift | What happens |
|---|---|
| A mod is updated | mod.io mints a new `<modId>_<fileId>` folder; the link points at a superseded one — the server either drops the mod or keeps running the *old* version, which looks like a fixed bug coming back |
| A mod is switched off in the game, or unsubscribed | the client skips it, the server keeps loading it |
| A mod is newly subscribed, or moves between mod.io and a dev build | no link exists at all — and a dev build changes the `modId` itself, so the old link cannot even be repaired |
| The same mod ends up linked twice | both are fed to the loader; `SortMods` keeps whichever comes last |

`utils/server.sh relink` reconciles all four in one pass, and `start` runs it
first, so a normal start is already correct:

```
  + BoatTurbo: mod_6265625 -> 6265625_8033551        added
  ~ AutoPlant3: mod_6163009 -> 6163009_7887057       re-pointed
  - mod_3400322 (not loaded by the client)           removed
  - zweitlink (duplicate of mod_6198932)             removed
```

The target set mirrors what `PugMod.Platform` does on a normal client start,
read from the same structured data the game keeps in `state.json`:

| Step | Source |
|---|---|
| walk the subscriptions | `existingUsers[*].subscribedMods` |
| drop what is switched off | `existingUsers[*].disabledMods` |
| drop what is not installed | `mods[id].currentModfile.id` → folder must exist with a manifest |
| drop version-incompatible mods | `mods[id].modObject.tags` vs. the game version, unless the guid sits in `unsupportedModsToLoad` |

The folder comes from `currentModfile.id`, not from guessing at the cache — the
cache keeps superseded folders around (CoreLib had `3177992_7845185` next to
`_7710097`), and "highest number wins" is a guess where `state.json` has the
answer. `metadata.name` and `guid` still come from each `ModManifest.json`:
`state.json` only carries the mod.io *profile* name, which differs
(`Mod Settings Menu` vs. `ModSettingsMenu`), and the manifest name is the identity
the server goes by. Verified against a live client run: the derivation produced
exactly the 33 mods the game had loaded.

Version comparison follows `ModVersion`, which looks at the **first three**
components only — a game on `1.2.1.5` accepts a `1.2.1.0` tag. Nothing in the
client is written; all of this is read-only.

If the target set cannot be determined — unreadable `state.json`, empty cache —
`relink` changes **nothing** and says so. These symlinks are the only record of
the server's mod selection; there is no second list to restore from.

Two enabled mod folders can also claim the same `metadata.name` — the identity
the server goes by, since `ModId` is hashed from it and `SortMods` keys on it.
Only one of them can run, so `relink` reports the collision and names its pick.

**A shared `guid` does not prove they are the same mod.** A fork inherits the
guid along with the manifest, so two different authors can ship the same name
*and* the same guid — `Auto Plant 3` (`6007069`) and `AutoPlant for 1.2.1.5`
(`6163009`) are exactly that. It is still worth reporting, because the data-block
loader keys on the guid and would clash on top of the name collision.

## Client and server must match

A mismatch surfaces in the client as **"wrong game version"**, which is
misleading — the underlying error is `Error/BadProtocolVersion`. Unity NetCode
generates its ghost serializers at build time and validates
`NetworkProtocolVersion` plus the ghost collection hash on connect; anything that
changes the ECS component set changes that hash. Diagnose in `Player.log`: a long
run of `ComponentHash[N]` lines followed by
`Client disconnected because Error/BadProtocolVersion`.

Three things have to line up:

1. **The same mods**, mirrored as above.
2. **`corekeeper-patch` applied to the server install too.** Without Patch 2 the
   mods load but Roslyn fails on the missing `de-DE` satellite assembly, so none
   of them compile — same hash mismatch, one step later. The patcher takes the
   game directory, so run it once per installation.
3. **Mods the client rejects as incompatible.** Only the client checks version
   compatibility — it reads the mod.io tags and skips a mod that does not match,
   unless its GUID sits in `modloader/config.json` → `unsupportedModsToLoad`
   (what the "load anyway" dialog writes). The server's directory scan passes
   `supportsCurrentVersion: true` **hardcoded** (`PugMod.Loader` ~2172), so it
   loads everything present, tags be damned.

   The asymmetry runs one way: a mod the client drops but the server loads is a
   set mismatch. Either confirm it in the client's dialog or unlink it on the
   server. Copying `unsupportedModsToLoad` to the server does nothing — the gate
   it feeds (`!supportsCurrentVersion && !contains(guid)`) can never fire there.
   Note the loader clears that list on every game-version change, so a mod you
   confirmed once is silently dropped by the client after the next update.

## Troubleshooting

| Symptom | Cause |
|---|---|
| "wrong game version" | `Error/BadProtocolVersion` — see the section above |
| "missing the crossplay privilege" | Server offers crossplay; start it with `-allowonlyplatform Steam` so client and server share a platform and the check is skipped |
| Server exits during world generation | `-nographics` was passed, or the host has no usable graphics device |
| Mods listed but inert | Scripts did not compile — check the log for `CompileFailed` or the `de-DE` satellite assembly |

## Stopping it without losing progress

`utils/server.sh stop` sends a Windows `WM_CLOSE` through `taskkill` (no `/F`),
which is what Unity turns into a quit request. The chain is visible in the log:

```
Got quit request
Exit blocked by ECSManager     <- the manager holding the world defers the quit
Quit blocked
Got quit request
Running quit handlers          <- Deinit() on every manager, then PID.txt is removed
```

A POSIX signal (`pkill`, SIGTERM) bypasses all of it — the process disappears and
only the last autosave survives. This is also why Pugstorm's own `Launch.ps1`
uses `taskkill`. Verified: a graceful stop rewrote the world file, an earlier
SIGTERM stop did not.

Two independent signals tell the paths apart:

- `Running quit handlers` in the log — only present on the graceful path.
- A leftover `PID.txt` next to the executable. It is written at startup and
  removed *only* by the quit handler, so its presence means the previous run was
  cut short. A stale one is also read back on the next start as "a server is
  already running".

Autosave runs every 60 s (`AutoSaveInterval`, disableable with
`-disableautosave`), so even a hard kill costs at most a minute.

One known rough edge: `Write failed: … .pugbackup (-2147024896)` for
`ServerConfig.json`, `Admins.json` and `PlayerBans.json` persists even with all
six patches applied. Those files themselves are written and the world is
unaffected — only the backup copies fail.

## Log formats differ

The server logs `loaded mod <Name> at <path>`, the client logs
`Loading mod with ID <modId>`. There is no single grep pattern for both — a
detail that costs time when comparing the two sides.
