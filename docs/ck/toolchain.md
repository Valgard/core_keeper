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
| **Windows Build Support (Mono)** | the target every build produces |
| **Linux Build Support (Mono)** | the second target, built while the mod's `buildLinux` setting is on — it is on by default |

An Editor host needs the module for every platform it is not itself — a Linux
host needs Windows Build Support, a Windows host needs Linux Build Support,
and a macOS host needs **both**: macOS is neither, so there is no target it
builds natively and can skip.

## The SDK clone, initialised once

Clone Pugstorm's `CoreKeeperModSDK`, open it in that Editor, and run two wizard
steps once — **in this order**:

1. **Update Game Files**, which copies the installed game's assemblies into the
   project. They are not in the repository; a fresh clone has none.
2. **Create Mod**, which generates the mod folder and its assembly definition.

**The order is not cosmetic.** Creating the mod freezes its list of precompiled
references from a one-time scan of the assemblies present at that moment, and
nothing re-runs that scan later. Do it first and the list is empty — the mod
compiles against nothing, and no amount of updating game files afterwards
repairs it.

## After a game update: update the SDK, then Update Game Files again

"Once" above means once per clone, not once for good. **Update Game Files is
also the step that installs the SDK's own builds of game assemblies**, and those
are tied to the game build. It reads `Assets/ModSDK/EditorAssemblies.zip` — a
file tracked in the SDK repository and replaced by Pugstorm's "Update SDK for …"
commits — and installs its non-Editor assemblies, builds compiled for the Editor,
in place of the game's copies of the same names, which it then skips; it copies
the remaining game assemblies, and it unpacks the zip's `*.Editor.dll` files
into the project (`PugText.Editor.dll` only when `Pug.Other` was imported). All
of this is `ImporterWindow` in the SDK's importer package. A game update can
therefore need both halves: pull the SDK, so the zip matches the game, and run
Update Game Files, so the project holds what is in it.

Skipping either one shows up in a place that looks unrelated. Measured with an
SDK clone left at its 1.3.0.1 update while the game was on 1.3.0.5: **opening any
prefab crashed the Editor**, with a `MissingMethodException` for
`PugText.RenderEditorPreview` followed by a native crash. The 1.3.0.2 game
assemblies still declare `PugText.RenderEditorPreview(PugText, bool)`; the
1.3.0.4 ones no longer do. The `PugText.Editor.dll` in the SDK's 1.3.0.1 zip calls
it, while the one in the zip of "Update SDK for 1.3.0.3" carries a preview
method of its own. Pulling the SDK and running Update Game Files once more fixed
it.

## Two copies of one package break its GUIDs

Unity requires every asset GUID to be unique in a project. **Adding a source
clone of a package while the installed package is still there** — CoreLib as an
`Assets/` folder beside the `ck.modding.corelib` package, for one — puts two
copies of every `.meta` GUID into the project, and Unity resolves that on its
own by giving one copy new GUIDs. Observed in an SDK clone: 707 `.meta` files in the
CoreLib clone were rewritten, every prefab that referenced CoreLib's
`SupportsCoreLib` by its usual GUID showed a missing script and refused to save,
and the cause looked like an upstream GUID change until the clone's own history
said otherwise. Remove the package before adding the clone. If it has already
happened, remove the package and restore the clone's `.meta` files from its
repository; the prefabs resolve again without being touched.

## On macOS, the Inspector loses edits on components that reference a data block

A field edited in the normal Inspector **does not keep its value** on a
component that has a data-block reference field, with nothing in the Inspector
to say so. The cause is the SDK's `DataBlockRefDrawer` (in
`ScriptableData.Editor.dll`): drawing the field calls
`ScriptableDataEditorUtility.GetCachedDataBlocks`, which sorts the blocks
through `FilePathComparer`, a P/Invoke of `StrCmpLogicalW` in Windows'
`shlwapi.dll` with no platform branch. On macOS that throws a
`DllNotFoundException` — from the sort, so only once the project holds two or
more blocks of the type. The exception and the lost edit were observed; that the
exception ends the Inspector pass before the component's changes are applied is
the reading that connects them. A failed sort is not cached, so it repeats on
every repaint.

The **Debug** Inspector draws the raw serialized fields without that drawer and
keeps edits; it was used to author an item prefab on a macOS Editor this way.
Editing the prefab's YAML with the Editor closed is the other route. Measured on
an SDK at its 1.3.0.5 commit; Linux, which lacks `shlwapi.dll` too, is
untested.

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

These failures belong to getting a toolchain running rather than to any mod, and
each is written up under the symptom you actually see:

| Symptom | Where |
|---|---|
| A fresh SDK clone will not compile on macOS | [Troubleshooting](troubleshooting.md#a-fresh-sdk-clone-will-not-compile-on-a-macos-editor-host) |
| The Editor hangs at "Initial Asset Database Refresh" | [Troubleshooting](troubleshooting.md#the-unity-editor-hangs-at-initial-asset-database-refresh) |
| The Editor crashes as soon as a prefab is opened, after a game update | [Above](#after-a-game-update-update-the-sdk-then-update-game-files-again) — stale SDK Editor assemblies |
| Prefabs show a missing script after a package's source clone was added while the package was still installed | [Above](#two-copies-of-one-package-break-its-guids) — duplicate GUIDs |
| Inspector edits revert on macOS | [Above](#on-macos-the-inspector-loses-edits-on-components-that-reference-a-data-block) — use the Debug Inspector |
