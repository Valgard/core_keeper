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
CoreKeeperServer_Data/StreamingAssets/Mods/<any-name>  ->  …/mod.io/5289/mods/<modId>_<fileId>
```

Folder names are free — the loader reads each `ModManifest.json`. Symlinks are
the right tool here (mod.io is the only writer, the server only reads); copies
would go stale on the next mod update, which immediately breaks the join.

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
3. **`modloader/config.json` → `unsupportedModsToLoad`.** This list holds the mod
   GUIDs you once confirmed through the "load anyway" dialog. The server can
   never populate it: `Loader.LoadUnsupportedMod` is only reachable from that
   dialog, and `-batchmode` has no UI. Copy the client's list over. The loader
   clears it on every game-version change, so after each Core Keeper update
   confirm in the client again and re-copy.

## Troubleshooting

| Symptom | Cause |
|---|---|
| "wrong game version" | `Error/BadProtocolVersion` — see the section above |
| "missing the crossplay privilege" | Server offers crossplay; start it with `-allowonlyplatform Steam` so client and server share a platform and the check is skipped |
| Server exits during world generation | `-nographics` was passed, or the host has no usable graphics device |
| Mods listed but inert | Scripts did not compile — check the log for `CompileFailed` or the `de-DE` satellite assembly |

Two known rough edges:

- `Write failed: … .pugbackup (-2147024896)` for `ServerConfig.json` and
  `Admins.json` persists even with all six patches applied. The files themselves
  are written; only the backup copy fails.
- `utils/server.sh stop` terminates the process without triggering a final save,
  so the last autosave is what survives.

## Log formats differ

The server logs `loaded mod <Name> at <path>`, the client logs
`Loading mod with ID <modId>`. There is no single grep pattern for both — a
detail that costs time when comparing the two sides.
