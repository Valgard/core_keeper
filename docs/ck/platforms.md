# Platforms and hosts

Where Core Keeper actually runs, where it keeps its files, and what breaks on a
host the game was never built for. Most of this chapter matters only if you mod
from macOS — but the file layout section below covers the paths this
handbook names most often, not every path it uses.

## There is no macOS build

Core Keeper ships **Windows and Linux builds only** for the game — measured
2026-09-01 by querying the Steam store API for app `1621690`, which reports
`platforms: {windows: true, mac: false, linux: true}`. On macOS the usual route
runs the Windows build under a Wine-based translation layer — CrossOver, or Wine
directly; it is the route this chapter is about. On Apple Silicon that stacks a
second translation underneath, since the Windows build is x86-64.

This has one consequence that is easy to miss and expensive to rediscover: **a
macOS modder is running the Windows build**, so it is Windows path, registry
and `System.IO` behaviour that applies — filtered through an implementation
that is close but not identical. Most of the failures later in this chapter
live in that gap; one may not, and says so where it appears.

The dedicated server is a different Steam app, `1963720` (see [multiplayer and server](multiplayer-and-server.md)),
and it has no store entry at all, so the store-API check above says nothing
about it. Its own manifest does: **measured** 2026-09-01 via `steamcmd +login
anonymous +app_info_print 1963720` — the same `steamcmd` that installs the
server itself (see [multiplayer and server](multiplayer-and-server.md)) — whose `common.oslist` field lists
`windows,linux` only, and whose only two *own* content depots are tagged windows
and linux. Three more depots are Steam redistributables mounted from app `1007`,
one per OS; the macos one is zero-size, and none of them is game content
(re-queried 2026-10-15 through `api.steamcmd.net`, same result). There is no
macOS build of the dedicated server either. This repository happens to run it
under CrossOver too, in the same bottle as the client, but that is local
practice, not the reason it needs to: the manifest above is.

The Unity Editor, by contrast, runs natively on macOS. Building a mod and
running the game are therefore two different worlds on the same machine, which
is why an SDK problem and a loading problem look nothing alike. The Editor has a
macOS snag of its own — a freshly cloned SDK that refuses to compile — but it is
a plugin import setting rather than anything in this chapter; it lives with the [toolchain requirements](toolchain.md#on-macos-a-fresh-clone-does-not-compile-at-all).

## Where the files live

These locations account for most of the paths this handbook names. Under Wine
they sit inside the bottle's virtual drive, otherwise at the platform's own
equivalent.

| What | Where |
|---|---|
| Game assemblies a mod binds against | `<install>/CoreKeeper_Data/Managed/` — the dedicated server has its own under `CoreKeeperServer_Data/` |
| Mods installed through mod.io, unpacked | `…/Public/mod.io/5289/mods/<modId>_<modfileId>/` |
| Subscriptions and per-user mod state | `…/Public/mod.io/5289/state.json` |
| Side-loaded mods — the dedicated server's usual route | `<install>/CoreKeeper_Data/StreamingAssets/Mods/`, on the server under `CoreKeeperServer_Data/` |
| Client saves, logs, mod config, loader config | `…/LocalLow/Pugstorm/Core Keeper/` — the server's data sits in its own subtree (below), and its stock `Launch.ps1` writes the log to `CoreKeeperServerLog.txt` in the install directory |
| Where the loader extracts a mod's sources to compile them | client: `…/Temp/Pugstorm/Core Keeper/ModLoader/<Mod>/`; server: `…/ModLoader/DedicatedServer/<new GUID>/` |

`5289` is Core Keeper's mod.io game id, from the mod.io settings asset the game
ships, so it is the same on every install. The two mod.io paths are the
plugin's defaults: a `RootLocalStoragePath` in mod.io's `globalsettings.json`
moves the root. The `<modId>_<modfileId>` pair means a published mod's
directory name **changes with every release** — anything that remembers the
path rather than resolving it goes stale on the next update.

The extraction rows differ because the two `PugMod.Loader` builds differ in
exactly that line: the client extracts to a fixed directory per mod
(`PugMod.Loader:Loader:Load:11`), the server to a fresh GUID on every load
(`DedicatedServer/PugMod.Loader:Loader:Load:11`).

The dedicated server keeps its own tree (`…/DedicatedServer/`) beside the
client's — in the server build `StandaloneFilesystem` has two constructors, and
each reads `-datapath` off the command line first and only falls back to that
suffix when the flag is absent
(`DedicatedServer/Pug.Other:StandaloneFilesystem:StandaloneFilesystem(string, PlatformInterface):1-17`;
the second constructor repeats the same read and fallback at
`DedicatedServer/Pug.Other:StandaloneFilesystem:StandaloneFilesystem(string, string, …):3-12`,
then layers a subfolder argument on top) — which is why a server and a client on
one machine do not share a world by default. The client build's constructors
never read `-datapath`; they place the tree under the platform name and account
id instead (`Pug.Other:StandaloneFilesystem:StandaloneFilesystem(string, PlatformInterface):8`).

## What Wine breaks, and how it looks

These are not mod bugs, and none of them names Wine in its error message. All
of them have been observed on CrossOver; each sits in a specific method, which
means each can be patched at the IL level in the installed assemblies.

**Recursive directory deletion fails.** On the client, the loader extracts a
mod's sources to a fixed working directory and deletes what the previous launch
left there first (`PugMod.Loader:Loader:Load:14`); nothing removes that directory after a
load, so every launch after a mod's first reaches the delete. Under Wine that
delete throws where it would succeed on Windows, and nothing catches it on the
way up to the loader's `Update`: the throw ends the whole load pass, after the
pass has already cleared its reload flag (`PugMod.Loader:Loader:Reload:14`), so the failing
mod and every mod after it in load order stay unloaded and nothing retries. It
surfaces as a mod that worked yesterday and does not today. Why the delete
fails on some launches and not on others is **unverified**. On the dedicated
server the same code runs against a fresh GUID directory, so there is nothing
to delete and this path does not arise.

The game's `StandaloneFilesystem.DeleteDirectory` hits the same wall unguarded,
but not on a loader path: the game calls it when it backs up save data after
detecting a new application version (`Pug.Other:PrefsManager:Init:53`, rotating
folders at `Pug.Other:FilesystemManager:BackupFolder:14`), and mods reach it
through `API.ConfigFilesystem`. The mod.io plugin's
`SystemIOWrapper.DeleteDirectory` hits it too but catches the exception and
returns a result code instead of throwing.

**Roslyn chases a satellite assembly that is not there — and this one may not be
Wine's doing.** The load-time compiler formats its diagnostics in the host's UI
language (`diagnostic.GetMessage()` with no culture argument,
`RoslynCSharp.Compiler:CompilationError:CompilationError:5`) — for every
diagnostic it keeps, warnings and infos included, not only errors
(`RoslynCSharp.Compiler:CompilationResult:CreateErrors:7`). On a non-English
host it looks for the matching satellite assembly, fails to find it, and the
compile fails — every source mod whose compile produces such a diagnostic, with
an error that talks about resources rather than about code. The code path to it
is not Wine's: any host with a non-English UI reaches the same `GetMessage()`
call. Whether a native Windows host with a German UI then fails the same way is
**unverified** — .NET normally falls back to the neutral resources when a
satellite is missing, and the lookup itself sits in `Microsoft.CodeAnalysis`,
which is not decompiled here. Forcing the invariant culture before the compiler
runs removes it. The symptom is unmistakable once you know it, and this project
has met it under CrossOver: a machine whose system language is German fails to
compile mods that compile fine elsewhere.

**The first save of a new world can fail to write — and deleting one can fail to
finish.** Observed on 1.2.1.3: under Wine the File API reports failure without
setting an error code, so the exception carries `ERROR_SUCCESS` and the log
reads `Write failed: Erfolg … (-2147024896)`
(`Pug.Other:StandaloneFilesystem:Write(string, string, …):71`). `Write` catches
it, so the caller never learns, and on a first save — no existing file to
replace — nothing reaches the disk: the world is created and then lost. A direct
write as a fallback recovers it. Whether the 1.3 builds still lose a first save
this way is **unverified**. The same failure also breaks
`StandaloneFilesystem.Delete`, which is not a directory deletion at all: it
renames the file to `<path>.pugbackup` via `File.Move`, after deleting any
pre-existing backup — a soft delete of one file, and the generic remove for
every file the filesystem layer deletes, not only worlds. Unlike the two
unguarded directory deletes above, this one is guarded: `Delete` is wrapped in
`try { } catch (IOException)` and logs `Delete failed: …` rather than throwing —
the caller never learns the rename failed, which is why its symptom differs from
the loader's directory-delete failure too: a deleted world that stays in the UI,
rather than a mod that fails to load. The catch is narrower than it looks,
though — `UnauthorizedAccessException` is not an `IOException` and leaves
`Delete`, as does `Rel2Abs`'s `InvalidOperationException` for a path outside the
root. On the main path the save queue's own `catch (Exception)` stops it one
frame up and logs `Exception trying to write <path>: …`
(`Pug.Other:FilesystemManager:WriteHandler:110-112`), so the caller still never
learns. The fix is the same shape as before: a hard delete in place of the
rename.

Two things about patching the installed assemblies are worth knowing before
relying on it:

- **An update reverts every patched assembly it ships, and only those.** The
  patches live in the shipped DLLs, so an update that replaces one restores it
  to stock and its failures return. Until 2026-10-15 this read "every game
  update has reverted them"; the 1.3.0.6 server update replaced `Pug.Other`
  but left the patched `PugMod.Loader` and `modio.UnityPlugin` in place. So
  after an update, check each assembly rather than assuming all are stock or
  all are patched. Treat this as maintenance, not a one-time fix.
- **Each installation needs its own.** The client and the dedicated server are
  separate installations with separate copies of the same-named assemblies —
  and not identical copies: in 1.3.0.6 the server's `Pug.Other` differs from
  the client's by thousands of lines and its `PugMod.Loader` by the extraction
  path, so a patch has to find its target in each build separately. On a
  non-English host, a server missing the Roslyn fix loads its mods and compiles
  none of them — which the client then rejects as a protocol mismatch, not as a
  compile failure. See [multiplayer and server](multiplayer-and-server.md) for why that surfaces as "Game
  version mismatch".

There is also a residual write failure that leaves the files themselves
intact. A client log on this host from 2026-10-12 shows fifteen
`Write failed: Erfolg` lines, every one on a `.pugbackup` path — fourteen for a
character save `saves/<n>.json`, one for a world's `.mapparts.gzip` — while the
target files carry a timestamp from that same session. An earlier case on the
same host hit the client's cloud-conflict backups the same way (see [troubleshooting](troubleshooting.md)).
JSON configuration side files there (`ServerConfig.json`, `Admins.json`,
`prefs.json`) do get their `.pugbackup` written. In the source, all of these go
through the same `Write`, so what decides which files hit the failure is
**unverified**. Until 2026-10-15 this paragraph named `ServerConfig.json` and
its siblings as the files that fail, and said worlds were unaffected; neither
matches the log above.

## Reading logs on a translated host

The client's `Player.log` greps directly under Wine — plain UTF-8 text with no
NUL bytes, confirmed there; the dedicated server's stock launcher writes
`CoreKeeperServerLog.txt` instead, which that check did not cover. How far that
check extends beyond a Wine host is not recorded, and is **unverified**. Its
Windows-side error strings still arrive in the **host system's language**,
though, which produces the memorable case of a write failure whose error text is
the locale's word for success — `ERROR_SUCCESS` rendered as `Erfolg`. Match on
the numeric code, not on the message.

Both processes write two different "loaded mod" lines, and the difference comes
from the loader *stage* rather than from the build — see [multiplayer and server](multiplayer-and-server.md),
which has both forms and the pattern that finds them.
