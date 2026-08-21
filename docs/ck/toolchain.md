# Toolchain requirements

What has to be installed and set up before any of the rest of this handbook is
reachable. Get one of these wrong and nothing compiles, regardless of how you
organise everything else — none of it is a matter of taste.

How you then arrange a mod project around it *is* a matter of taste, and [organising a mod project](organising-a-mod-project.md)
walks through one arrangement in detail.

## Unity Editor `6000.0.59f2`, exactly

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

## The SDK clone, initialised once

Clone Pugstorm's `CoreKeeperModSDK`, open it in that Editor, and run two
wizard steps once: **Create New Mod** and **Update Game Files**. The second
copies the installed game's assemblies into the project — without it your mod
compiles against nothing.

## The Editor locks the project

A `-batchmode` build cannot run while the Editor has the project open; Unity
holds a lock file. This is worth knowing early because the failure looks like a
broken build script rather than a lock.

The same applies in reverse to file edits: while the Editor is open it
reserialises assets on its own schedule, so an external write to a prefab or
`.asset` can be silently overwritten — or overwrite what the Editor was about
to save. Close it before touching those files from outside.

## On macOS, a fresh clone does not compile at all

The first open of a newly cloned SDK on a macOS Editor ends in compilation
errors and the "Enter Safe Mode" prompt, with `CS0246` naming `Steamworks`.
Nothing else in the SDK is reachable until it is resolved.

**This is an Editor problem, not a game-host one.** The Editor runs natively on
macOS; nothing here involves the translation layer the game needs. What blocks
the compile is a gate on the *plugin import settings*: the SDK's Steamworks DLLs
are each restricted to one Editor platform, and both are explicitly off for
macOS. The fix is a handful of values in one `.meta` file plus a clean
re-import, once per SDK clone — [the full procedure is in troubleshooting](troubleshooting.md#a-fresh-sdk-clone-will-not-compile-on-a-macos-editor-host),
including why enabling the managed DLL is safe with no `libsteam_api.dylib`
present.

## When the setup itself misbehaves

Two failures belong to getting a toolchain running rather than to any mod, and
each is written up under the symptom you actually see:

| Symptom | Where |
|---|---|
| A fresh SDK clone will not compile on macOS | [Troubleshooting](troubleshooting.md#a-fresh-sdk-clone-will-not-compile-on-a-macos-editor-host) |
| The Editor hangs at "Initial Asset Database Refresh" | [Troubleshooting](troubleshooting.md#the-unity-editor-hangs-at-initial-asset-database-refresh) |
