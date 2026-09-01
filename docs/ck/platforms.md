# Platforms and hosts

Where Core Keeper actually runs, where it keeps its files, and what breaks on a
host the game was never built for. Most of this chapter matters only if you mod
from macOS — but the file layout in the next section covers the paths this
handbook names most often, not every path it uses.

## There is no macOS build

Core Keeper ships **Windows and Linux depots only** for the game — measured
2026-09-01 by querying the Steam store API for app `1621690`, which reports
`platforms: {windows: true, mac: false, linux: true}`. On macOS it runs as the
Windows build under a Wine-based translation layer — CrossOver, or Wine
directly. On Apple Silicon that stacks a second translation underneath, since
the Windows build is x86-64.

This has one consequence that is easy to miss and expensive to rediscover: **a
macOS modder is running the Windows build**, so it is Windows path, registry
and `System.IO` behaviour that applies — filtered through an implementation
that is close but not identical. Most of the failures later in this chapter
live in that gap; one does not, and says so where it appears.

The dedicated server is a different Steam app, `1963720` (see [multiplayer and server](multiplayer-and-server.md)),
and it has no store entry at all, so the same check says nothing about it. What
is actually known is narrower: this repository runs the dedicated server under
CrossOver too, in the same bottle as the client — evidence that it needs the
same translation layer, not a platform-support guarantee from Valve.

The Unity Editor, by contrast, runs natively on macOS. Building a mod and
running the game are therefore two different worlds on the same machine, which
is why an SDK problem and a loading problem look nothing alike. The Editor has a
macOS snag of its own — a freshly cloned SDK that refuses to compile — but it is
a plugin import setting rather than anything in this chapter; it lives with the [toolchain requirements](toolchain.md#on-macos-a-fresh-clone-does-not-compile-at-all).

## Where the files live

Five locations account for nearly every path this handbook names. Under Wine
they sit inside the bottle's virtual drive, otherwise at the platform's own
equivalent.

| What | Where |
|---|---|
| Game assemblies a mod binds against | `<install>/CoreKeeper_Data/Managed/` — the dedicated server has its own under `CoreKeeperServer_Data/` |
| Installed mods, unpacked | `…/Public/mod.io/5289/mods/<modId>_<modfileId>/` |
| Subscriptions and per-user mod state | `…/Public/mod.io/5289/state.json` |
| Saves, logs, mod config, loader config | `…/LocalLow/Pugstorm/Core Keeper/` |
| Where the loader extracts a mod's sources to compile them | `…/Temp/Pugstorm/Core Keeper/ModLoader/<Mod>/` |

`5289` is Core Keeper's mod.io game id and is the same everywhere. The
`<modId>_<modfileId>` pair means a mod's directory name **changes with every
release** — anything that remembers the path rather than resolving it goes stale
on the next update.

The dedicated server keeps its own tree (`…/DedicatedServer/`) beside the
client's — its filesystem constructor reads `-datapath` off the command line
first and only falls back to that suffix when the flag is absent
(`DedicatedServer/Pug.Other:430199`) — which is why a server and a client on
one machine do not share a world by default.

## What Wine breaks, and how it looks

These are not mod bugs, and none of them names Wine in its error message. All
of them have been observed on CrossOver; each sits in a specific method, which
means each can be patched at the IL level in the installed assemblies.

**Directory deletion fails on paths the loader must clear.** The loader
extracts a mod's sources to a working directory and deletes the previous
contents first. Under Wine that delete throws where it would succeed on
Windows, and the mod does not load. It surfaces as a mod that worked yesterday
and does not today, typically after an update left a stale `ModLoader/<Mod>/`
directory behind. Two code paths hit the same wall unguarded — the loader's own
delete and the game's `StandaloneFilesystem.DeleteDirectory`; the mod.io
plugin's `SystemIOWrapper.DeleteDirectory` hits it too but catches the
exception and returns a result code instead of throwing.

**Roslyn chases a satellite assembly that is not there — and this one is not
Wine's doing.** The load-time compiler formats its diagnostics in the host's UI
language (`diagnostic.GetMessage()` with no culture argument,
`RoslynCSharp.Compiler:581`). On a non-English host it looks for the matching
satellite assembly, fails to find it, and the compile fails — *every* source
mod, with an error that talks about resources rather than about code. Nothing
in that mechanism is Wine's: a native Windows host with a German UI would take
the same path. Forcing the invariant culture before the compiler runs removes
it. The symptom is unmistakable once you know it, and this project has met it
under CrossOver: a machine whose system language is German or French fails to
compile mods that compile fine elsewhere.

**The first save of a new world can fail to write — and deleting one can fail
to finish.** The write path reports success and produces nothing, so the world
is created and then lost; a direct write as a fallback recovers it. The same
File-API-lies-about-success failure also breaks `StandaloneFilesystem.Delete`,
which is not a directory deletion at all: it renames the file to
`<path>.pugbackup` via `File.Move`, after deleting any pre-existing backup — a
soft delete of one file. Its symptom differs from a directory-delete failure
too — a deleted world that stays in the UI, rather than a mod that fails to
load — and so does the fix: a hard delete in place of the rename.

Two things about patching the installed assemblies are worth knowing before
relying on it:

- **So far, every game update has reverted them.** The patches live in the
  shipped DLLs, so an update replaces them with stock and the failures return.
  Treat this as maintenance, not a one-time fix.
- **Each installation needs its own.** The client and the dedicated server are
  separate installations with separate copies of the same assemblies. A server
  missing the Roslyn fix loads its mods and compiles none of them — which the
  client then rejects as a protocol mismatch, not as a compile failure. See [multiplayer and server](multiplayer-and-server.md)
  for why that surfaces as "Game version mismatch".

There is also a residual write failure for JSON side files — on the server for
its own config files (`ServerConfig.json` and friends), on the client for
cloud-conflict backups — whose `.pugbackup` copies fail to write. The files
themselves are written and worlds are unaffected.

## Reading logs on a translated host

`Player.log` greps directly under Wine — plain UTF-8 text with no NUL bytes,
confirmed there. How far that check extends beyond a Wine host is not
recorded, and is **unverified**. Its Windows-side error strings still arrive
in the **host system's language**, though, which produces the memorable case
of a write failure whose error text is the locale's word for success —
`ERROR_SUCCESS` rendered as `Erfolg`. Match on the numeric code, not on the
message.

Both processes write two different "loaded mod" lines, and the difference comes
from the loader *stage* rather than from the build — see [multiplayer and server](multiplayer-and-server.md),
which has both forms and the pattern that finds them.
