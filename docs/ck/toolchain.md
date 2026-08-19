# Setting up the toolchain

What you need installed before any of the rest of this handbook is reachable,
and then one worked example of a build setup on top of it.

The chapter has two halves and they are not equally binding. **The first is what
the SDK requires** — get one of these wrong and nothing compiles, regardless of
how you organise the rest. **The second is one particular setup, mine.** It is
here because a working example beats an abstract description, not because it is
the way. Every part of it is a choice you can make differently.

## What the SDK requires

### Unity Editor `6000.0.59f2`, exactly

Not "6000.0 or newer". The version is pinned in the SDK's
`ProjectVersion.txt`, and Unity refuses to open a project written by a
different patch release without an upgrade step you do not want here.

**Trap: the SDK's own `README.md` names a patch version one lower.** Trust
`ProjectVersion.txt`, which is what the Editor actually checks.

Install it through Unity Hub with these modules:

| Module | Why |
|---|---|
| **Linux Build Support (Mono)** | the mod build targets it |
| **Windows Build Support (Mono)** | additionally required on macOS |

### The SDK clone, initialised once

Clone Pugstorm's `CoreKeeperModSDK`, open it in that Editor, and run two
wizard steps once: **Create New Mod** and **Update Game Files**. The second
copies the installed game's assemblies into the project — without it your mod
compiles against nothing.

### The Editor locks the project

A `-batchmode` build cannot run while the Editor has the project open; Unity
holds a lock file. This is worth knowing early because the failure looks like a
broken build script rather than a lock.

The same applies in reverse to file edits: while the Editor is open it
reserialises assets on its own schedule, so an external write to a prefab or
`.asset` can be silently overwritten — or overwrite what the Editor was about
to save. Close it before touching those files from outside.

### On macOS, a fresh clone does not compile at all

A newly cloned SDK fails on a macOS Editor with `CS0246: … 'Steamworks'`. The
SDK ships Steamworks DLLs gated to Windows and Linux Editors, and neither loads
on macOS.

The fix is one meta-file setting: enable
`Assets/Plugins/CoreKeeperModSDK/Facepunch.Steamworks.Posix.dll.meta` for
`OS: AnyOS`. It is a one-time change per SDK clone, and it works because the
Posix DLL is a *managed* assembly — once the Editor is allowed to load it, the
`Steamworks` namespace and its types resolve at compile time on macOS like
anywhere else.

Runtime calls into Facepunch.Steamworks would still fail on macOS for want of
`libsteam_api.dylib`, and the Editor's Steam Workshop upload tab is unusable
there — but a mod's own runtime code carries no Steamworks references, so
nothing reaches the missing library at play time. See
[the sandbox chapter](sandbox-and-config.md) for what a mod may reference at
all.

### Where the game's own files live

Two locations matter, and neither is the SDK:

| What | Where |
|---|---|
| the game assemblies a mod binds against | `<install>/CoreKeeper_Data/Managed/` |
| installed mods, saves, logs, mod config | the platform's `LocalLow/Pugstorm/Core Keeper/` tree |

The first is what [reverse engineering](reverse-engineering.md) decompiles; the
second is where [save formats](savegame-formats.md) and a mod's own
[configuration](sandbox-and-config.md) live.

## One working setup — mine

Everything from here down is **a personal arrangement**, not a requirement. It
solves problems that come from maintaining several mods against one shared SDK
clone; a single mod needs much less. Read it as a worked example — and if your
situation differs, the reasoning is more portable than the scripts.

### The problem it solves

The SDK wizard puts a mod's files inside the SDK clone, under `Assets/<Mod>/`.
That is fine until you want the mod in its own git repository: the files then
live in a tree you do not version, one `git clean` or re-clone away from loss.

My arrangement keeps every Editor-generated file — `.cs`, `.asmdef`, the
ModBuilderSettings `.asset`, and all the `.meta` GUID carriers — in the mod's
own repository, in a directory that mirrors the SDK's `Assets/` layout, and
**symlinks that mirror into the SDK clone**. A directory symlink for the mod
folder captures every current and future file the Editor writes, so nothing has
to be wired up by hand.

The symlinks encode absolute paths and therefore dangle after a move or a
worktree switch. The build script re-creates them on every run, which makes
that self-healing rather than a manual repair step.

### Build and install

One shared set of scripts serves every mod: build, symlink refresh, local
install, upload, uninstall. They are mod-agnostic and read a mod's identity
from environment variables it exports itself — mod name, ids, install path,
mod.io type. They `source` nothing on their own and abort on a missing variable
rather than proceeding with a blank, which is the difference between a clear
error and a build that quietly ships something wrong.

A build refreshes the symlinks, runs Unity in batchmode through
`-executeMethod` against a small editor-side helper class, and on macOS places
the result into the local development install so the loader picks it up on the
next launch.

### Machine values in one place

Values that belong to the *machine* rather than to a mod — the Unity binary
path, the SDK path, the game-version list, the decompiler on `PATH` — live once
in a gitignored file at the parent level, with a tracked template beside it.
Each mod's environment file inherits them through direnv's `source_up` and adds
only its own identity.

**Trap: a git worktree breaks the inheritance silently.** A worktree sits two
levels below the mod root, so the fallback that looks for the parent one level
up resolves to a directory that does not exist. The mod's own identity
variables still load, the machine-level ones stay unset, and nothing warns you.
That has already shipped a build whose localisation table came out empty. From
a worktree, source the parent explicitly first.

### A formatting gate that blocks rather than rewrites

Every repository here runs a formatter as a pre-commit *and* pre-push hook, in
checking mode. A rejected commit means running the formatter and retrying —
nothing is ever reformatted behind an edit, which keeps a diff attributable to
the person who made it.

Two details cost me time and are worth passing on. The C# formatter searches
upward for its ignore file and **does not stop at a repository boundary**, so a
mod without its own ignore file inherits the parent's — under which everything
in the mod is out of scope and silently skipped. The hook passes, and checks
nothing. Measured in a repo holding one misformatted file: `Checked 0 files`
without a local ignore file, `Checked 1 files` with one. And `pre-commit
install` refuses to run while `core.hooksPath` is set, even when that path
merely points at the repository's own hooks directory.

### Python tooling pinned by exact version

The shared Python scripts are a `uv` project with a lock file. The image
library is pinned to an exact version deliberately: some scripts generate
binary assets that ship inside a mod, and those are verified by regenerating
them and comparing bytes. PNG output is encoder-dependent, so an unpinned
library would make "the source changed" indistinguishable from "my encoder
differs". The test suite fails outright if the running version is not the
pinned one — which also catches the likelier accident of running it outside
the project environment.

### What this repository documents

The concrete form of all of the above — script names, variable names, the exact
commands, the publish modes and their scopes — is in
[the repository README](../../README.md). This chapter deliberately stops at
the reasoning, so that it stays useful to someone who arranges things
differently.
