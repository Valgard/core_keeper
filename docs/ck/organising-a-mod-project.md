# Organising a mod project

One way to lay out a Core Keeper mod so that it stays in version control, builds
reproducibly, and does not collide with the next mod you write. **It is an
example, not a requirement** — every choice here can be made differently, and it
solves problems that come from maintaining several mods against one shared SDK
clone, so a single mod needs much less of it. What is worth carrying over is the
reasoning, not the shape.

The requirements it builds on are in [toolchain requirements](toolchain.md).

## The problem it solves

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

## Build and install

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

## Machine values in one place

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

## A formatting gate that blocks rather than rewrites

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

## Python tooling pinned by exact version

The shared Python scripts are a `uv` project with a lock file. The image
library is pinned to an exact version deliberately: some scripts generate
binary assets that ship inside a mod, and those are verified by regenerating
them and comparing bytes. PNG output is encoder-dependent, so an unpinned
library would make "the source changed" indistinguishable from "my encoder
differs". The test suite fails outright if the running version is not the
pinned one — which also catches the likelier accident of running it outside
the project environment.

## What this chapter leaves out

Script names, variable names and exact commands belong to whichever
repository implements an arrangement like this one, and are worth little to
anyone who arranges it differently. This chapter stops at the reasoning for
that reason — the shape of a problem outlives any particular solution to it.

## When this arrangement misbehaves

Both failures below are consequences of building through symlinks rather than
from files the Editor owns, so they only occur under an arrangement like this
one:

| Symptom | Where |
|---|---|
| A newly linked mod builds to an empty file list | [Troubleshooting](troubleshooting.md#a-newly-linked-mod-builds-to-an-empty-file-list) |
| An edit to a shared editor helper appears to have no effect | [Troubleshooting](troubleshooting.md#an-edit-to-a-shared-editor-helper-appears-to-have-no-effect) |

