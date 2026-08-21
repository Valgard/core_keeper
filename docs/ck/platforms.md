# Platforms and hosts

Where Core Keeper actually runs, where it keeps its files, and what breaks on a
host the game was never built for. Most of this chapter matters only if you mod
from macOS — but the file layout at the end is what every chapter means when it
names a path.

## There is no macOS build

Core Keeper ships **Windows and Linux depots only**, for the game and for the
dedicated server alike, and nothing suggests that will change. On macOS it runs
as the Windows build under a Wine-based translation layer — CrossOver, or Wine
directly. On Apple Silicon that stacks a second translation underneath, since
the Windows build is x86-64.

This has one consequence that is easy to miss and expensive to rediscover: **a
macOS modder is running the Windows build**, so every Windows path, registry
quirk and `System.IO` behaviour applies — filtered through an implementation
that is close but not identical. The failures later in this chapter all live in
that gap.

The Unity Editor, by contrast, runs natively on macOS. Building a mod and
running the game are therefore two different worlds on the same machine, which
is why an SDK problem and a loading problem look nothing alike. The Editor has a
macOS snag of its own — a freshly cloned SDK that refuses to compile — but it is
a plugin import setting rather than anything in this chapter; it lives with the [toolchain requirements](toolchain.md#on-macos-a-fresh-clone-does-not-compile-at-all).

## Where the files live

Four locations matter, and every chapter that names a path means one of them.
Under Wine they sit inside the bottle's virtual drive, otherwise at the
platform's own equivalent.

| What | Where |
|---|---|
| Game assemblies a mod binds against | `<install>/CoreKeeper_Data/Managed/` |
| Installed mods, unpacked | `…/Public/mod.io/5289/mods/<modId>_<modfileId>/` |
| Subscriptions and per-user mod state | `…/Public/mod.io/5289/state.json` |
| Saves, logs, mod config, loader config | `…/LocalLow/Pugstorm/Core Keeper/` |

`5289` is Core Keeper's mod.io game id and is the same everywhere. The
`<modId>_<modfileId>` pair means a mod's directory name **changes with every
release** — anything that remembers the path rather than resolving it goes stale
on the next update.

The dedicated server keeps its own tree (`…/DedicatedServer/`) beside the
client's, which is why a server and a client on one machine do not share a world
by default.

## What Wine breaks, and how it looks

These are not mod bugs, and none of them names Wine in its error message. All
of them have been observed on CrossOver; each sits in a specific method, which
means each can be patched at the IL level in the installed assemblies.

**Directory deletion fails on paths the loader must clear.** The loader
extracts a mod's sources to a working directory and deletes the previous
contents first. Under Wine that delete throws where it would succeed on
Windows, and the mod does not load. It surfaces as a mod that worked yesterday
and does not today, typically after an update left a stale `ModLoader/<Mod>/`
directory behind. Several code paths hit the same wall — the loader's own
delete, the game's `StandaloneFilesystem.DeleteDirectory` and `Delete`, and the
mod.io plugin's `SystemIOWrapper.DeleteDirectory`.

**Roslyn chases a satellite assembly that is not there.** The load-time
compiler formats its diagnostics in the host's UI language. On a non-English
host it looks for the matching satellite assembly, fails to find it, and the
compile fails — *every* source mod, with an error that talks about resources
rather than about code. Forcing the invariant culture before the compiler runs
removes it. The symptom is unmistakable once you know it: a machine whose
system language is German or French fails to compile mods that compile fine
elsewhere.

**The first save of a new world can fail to write.** The write path reports
success and produces nothing, so the world is created and then lost. A direct
write as a fallback recovers it.

Two things about patching the installed assemblies are worth knowing before
relying on it:

- **Every game update reverts them.** The patches live in the shipped DLLs, so
  an update replaces them with stock and the failures return. This is
  maintenance, not a one-time fix.
- **Each installation needs its own.** The client and the dedicated server are
  separate installations with separate copies of the same assemblies. A server
  missing the Roslyn fix loads its mods and compiles none of them — which the
  client then rejects as a protocol mismatch, not as a compile failure. See
  [multiplayer and server](multiplayer-and-server.md) for why that surfaces as
  "wrong game version".

There is also a residual write failure for the server's own JSON side files
(`ServerConfig.json` and friends) whose `.pugbackup` copies fail to write. The
files themselves are written and worlds are unaffected.

## Reading logs on a translated host

`Player.log` is written as **UTF-16** under Wine, so `grep` reports "binary file
matches" and prints nothing useful; decode it first. Its Windows-side error
strings also arrive in the **host system's language**, which produces the
memorable case of a write failure whose error text is the locale's word for
success — `ERROR_SUCCESS` rendered as `Erfolg`. Match on the numeric code, not
on the message.

Server and client also disagree on how they announce a loaded mod, so no single
pattern finds both; [multiplayer and server](multiplayer-and-server.md) has the
two forms.
