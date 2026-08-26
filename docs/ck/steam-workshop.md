# Publishing to the Steam Workshop

Core Keeper gained Steam Workshop support with 1.2. At the time of writing it is
an opt-in beta: both authors and players need to own the game on Steam and join a
Steam group before Workshop items are visible to them at all.

The SDK ships an upload path for it — a tab in the Mod SDK window, built on
Facepunch.Steamworks. This chapter is about how that platform's data model
differs from mod.io's, what the tab does and does not do, and the one prerequisite
that is missing on macOS.

For the loader side — how a subscribed Workshop mod reaches the game, and why a
local build and a subscription of the same mod must not coexist — see [publishing to mod.io](publishing.md),
which covers all three loader platforms.

## One item, not a profile and a modfile

mod.io splits a published mod into a profile (name, description, tags, edited in
place) and modfiles (a build with its version and changelog, immutable once
uploaded). **The Workshop has neither half.** A Workshop item is a single object;
content, title, description, tags, preview and visibility are all fields on it,
and every submit updates whichever of them were set.

Two consequences follow, and both surprise people arriving from mod.io:

- **There is no metadata-only edit that leaves no trace.** Every
  `SubmitItemUpdate` appends an entry to the item's change history, whether or not
  new content came with it. Correcting a description is a visible event.
- **A change note belongs to that entry, not to a version.** It is written at
  submit time and there is no call to edit one afterwards — the same one-way
  property a mod.io changelog has, arrived at from a different direction.

There is also **no Game Version dimension**. mod.io carries compatibility tags per
build; the Workshop has no equivalent, so a mod cannot advertise which game
versions it runs on.

## Tags are sent flat and grouped by the platform

Core Keeper's Workshop configuration defines the tag groups, so an uploader sends
plain values — `Item`, `Quality of Life`, `Client`, `Script` — and the listing
renders them grouped, under localised headings (*Category*, *Application Type*,
*Access Type* in English). Nothing needs prefixing, and the grouping is not
something an uploader controls.

The vocabulary overlaps Core Keeper's mod.io groups closely but not exactly, and
**Steam drops an unknown value without a word**, exactly as mod.io does. Anything
setting tags programmatically should validate before sending, because the platform
will not.

## The preview image is capped at 1 MB

A preview above roughly one megabyte is rejected with `k_EResultLimitExceeded`,
and the upload fails as a whole. This is easy to hit: a 1024² PNG with soft
gradients — a glow, a gradient background — routinely exceeds it, while the same
image at 512² does not.

Downscaling is usually the better remedy than colour reduction. The Workshop
displays previews small (roughly 268² in listings), so resolution above that is
spent where nobody sees it, whereas quantisation shows as banding in exactly the
smooth gradients that made the file large.

Transparency is preserved; the item page composites the image onto its own
background, which is dark.

## What the SDK tab does

The tab lives at
`Packages/dev.pugstorm.mod/SDK/Editor/ModSDKWindow/SteamWorkshopTab.cs`. Reading
it is worth the few minutes, because several of its behaviours are not visible
from the UI.

**Its content folder comes from a UI ring buffer.** The upload target is resolved
as `latestBuildOrInstallPaths.LastOrDefault(x => x.EndsWith(modName))` — a list of
the last five paths, filled only when a mod is built or installed *through the SDK
window*. A build driven any other way leaves it untouched, and the tab then
reports "No built mod found" for a mod that was just built. The match is on the
`metadata.name` suffix, which the folder ModBuilder creates happens to satisfy.

**The Title field is also a display name.** Before uploading, the tab writes that
field into the built `ModManifest.json` as `metadata.displayName`. That field is
`[HideInInspector]` and this tab is the only place in the SDK that writes it —
which is why the Title field is where a human-readable name enters at all.

**The description has a file fallback.** If the description text field is empty,
the tab reads `description.txt` from the mod's asset folder and uploads its
contents. Note that Steam renders **BBCode**, not the Markdown a mod.io
description uses.

**It never writes a change note.** `WithChangeLog` exists in the bundled Facepunch
assembly; the tab does not call it. Uploads therefore produce change-history
entries with no text.

**Its stored File ID is keyed on the display title.** The tab keeps the item's
File ID and tags in a `<Mod>_Steam.asset` next to the mod, writing `modName`
from the *Title* field but looking it up by `metadata.name`. Once the two differ
— which happens the moment a readable title is used — the tab no longer finds
the asset it wrote, and presents an empty File ID field. From that state the
next upload takes the create-new branch rather than the update branch. Reported
upstream as [CoreKeeperModSDK#11](https://github.com/Pugstorm/CoreKeeperModSDK/issues/11).

**A failed upload leaves an item behind and forgets its id.** The tab saves the
File ID only inside `if (result.Success)`; the `else` branch prints the result
code and never reads `result.FileId`. But `SubmitAsync` creates the item first
and uploads afterwards, so anything that fails during the upload leaves a real,
empty item on Steam whose id was written down nowhere — a preview over [the 1 MB cap](#the-preview-image-is-capped-at-1-mb)
is the easy way to reach that state. The next attempt then takes the create-new
branch again and makes a second item. Nothing in the UI mentions the first.

A related trap, and a smaller one than it first looks: that `<Mod>_Steam.asset`
sits inside the mod's asset folder, and **ModBuilder collects what it finds
there**. Scripts, DLLs, `Conf/*.json` and `Localization/*.csv` leave the bundle
by their own routes, and anything under an `Editor` or `CodeGen` directory is
dropped outright — the settings asset is none of those, so it is handed to the
bundle build and its path is written into the plaintext
`.assetbundle.manifest` that ships beside the bundle.

**Its contents do not ship, though.** `SteamWorkshopModSettings` is declared in
an assembly with `"includePlatforms": ["Editor"]`, so the type does not exist in
a player build and Unity writes no object for it. Measured across four built
bundles (two mods × Windows/Linux): the asset is absent from all of them, and so
are the SteamID64 in `modOwner` and the author's absolute `selectedPath`. What
leaks is the project path in the manifest — the mod's own name, which the
listing carries anyway.

A `description.txt` left in the same folder is a different case: a `TextAsset`
exists at runtime, so it is written into the bundle like any other asset.

Reading the bundle to check any of this needs a deserialiser (UnityPy or
similar) — searching it proves nothing either way, because it is compressed.

## Uploading needs a live Steam session

Facepunch initialises against Core Keeper's app ID, so the desktop Steam client
must be running and signed in with an account that **owns** Core Keeper. The game
itself need not be installed.

A Steam account holds one online session at a time. On a host where the game runs
through a translation layer with its own Steam client, bringing the native client
online takes the other one offline — publishing and playing become mutually
exclusive.

## macOS needs a native library the SDK does not ship

On a macOS Editor the tab's *Initialize Steam* button appears to do nothing. The
console holds a swallowed exception: `SteamClient.Init` throws, so the UI refresh
one line below never runs.

```
Failed to initialize Steam for Mod SDK: libsteam_api
```

The SDK bundles the managed Facepunch assemblies and a Windows `steam_api64.dll`,
but no `libsteam_api.dylib`. Supplying one is a one-time step — with a version
trap that costs more time than the missing file itself.

**The newest redistributable does not work.** With a current library the error
merely changes to `SteamAPI_Init`, which Valve removed from the flat API around
Steamworks SDK 1.59. Nor is "one version older" enough: the managed assembly
requests specific interface revisions, and a library offering different ones
initialises but hands back nulls later.

**The bundled `steam_api64.dll` names the target generation.** It shipped with the
same managed assembly, so the interface versions it exports are the ones to match
— currently `SteamUser021` and `SteamUtils010`, alongside the assembly's own
requests for `SteamAPI_SteamUGC_v016` and `SteamAPI_SteamUser_v021`. That
combination is Steamworks SDK **1.55**. Reading it off the DLL survives an SDK
update; a remembered version number does not.

Place the library in the SDK's plugin folder with import settings that enable it
for the Editor on macOS only, and **restart the Editor** — native plugins are
loaded at startup, so dropping the file in while Unity runs changes nothing.

Note this is separate from the meta-file fix that makes a fresh SDK clone
compile on macOS at all, which is written up in [troubleshooting](troubleshooting.md#a-fresh-sdk-clone-will-not-compile-on-a-macos-editor-host). That one makes
the SDK build; this one makes the upload work.
