# Dedicated server — running one in this bottle

**What a dedicated server is and how it behaves** — the Steam app id, why
`-nographics` kills world generation, the crossplay flag, how to stop it without
losing the world, why a mod-set mismatch reports a version error — is in
[`docs/ck/multiplayer-and-server.md`](ck/multiplayer-and-server.md). This file
covers only what is specific to running one *here*: inside the same CrossOver
bottle as the game, sharing one world with the client.

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

The launch flags the script passes — `-batchmode` without `-nographics`, the
port as a command-line argument — are explained in the handbook. One thing is
specific to this host: **the process must be detached.** `cxstart --no-wait`
still keeps it attached to the calling shell, so it dies with the caller; the
script uses `nohup … & disown`.

Under CrossOver the log confirms the graphics device with
`Renderer: AMD Compatibility Mode`.

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

## When it will not take a connection

Every symptom this setup produces — "wrong game version", the crossplay
privilege, a server that exits during world generation, mods listed but inert —
belongs to the game rather than to the bottle, and each is written up under
what you see in
[`docs/ck/multiplayer-and-server.md`](ck/multiplayer-and-server.md) and
[`docs/ck/troubleshooting.md`](ck/troubleshooting.md).

The one thing to check *here* first: `utils/server.sh relink` reconciles the mod
symlinks, and `start` runs it — but a stale set is still the most common local
cause of a mismatch.

## Stopping it

`utils/server.sh stop` sends a Windows `WM_CLOSE` through `taskkill` (no `/F`),
which is the path that runs the quit handlers and rewrites the world; the
handbook explains why a POSIX signal loses the last minutes of play.

One rough edge specific to this host: `Write failed: … .pugbackup
(-2147024896)` for `ServerConfig.json`, `Admins.json` and `PlayerBans.json`
persists even with every game-DLL patch applied. Those files themselves are
written and the world is unaffected — only their backup copies fail.
