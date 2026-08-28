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

- **A submit that changes the content is a visible event**, so shipping a build
  is never a quiet edit. A submit that changes *nothing* is the opposite: it
  reports success and appends nothing at all, discarding the change note with
  it. Measured twice on one item — the same content folder submitted again
  returned `Success = true` and left the history at three entries; pointing at a
  different build and submitting again produced the fourth. It is the same
  effect an older probe saw when it submitted a note with no content, which had
  been recorded here as an open question about *missing* content; the rule is
  about *unchanged* content, and having no content is one way to be unchanged.
  **`Success = true` is therefore not evidence that an entry exists** — which
  matters to anything that records what it has published, and to anyone
  intending to correct a note by re-submitting it.
- **A change note belongs to that entry, not to a version.** It is written at
  submit time, and no API can go back and change it — see below, because that
  sentence is easy to over-read.

## A history entry has no version, and no title but the one you write

There is no `SetItemVersion` anywhere in `ISteamUGC`, and `SubmitItemUpdate`
takes exactly one argument: the change note. `SetItemTitle` names the *item*, so
using it per submit would rename the mod. A published entry therefore shows
`Update: <date>` and the note, and nothing else — several entries submitted in
one session are indistinguishable by their headers, because the date is all
they have.

**The note is BBCode, like the description — not Markdown.** Measured against a
live item with both in one note:

| Written | Rendered |
|---|---|
| `[h2]0.9.2 — a headline[/h2]` | a real heading |
| `[h3]…[/h3]` | a subheading under it |
| `[b]`, `[i]` | bold, italic |
| `[list][*]…[/list]` | a bullet list |
| `[olist][*]…[/olist]` | a numbered list |
| `[url=https://…]text[/url]` | a link, with Steam's own `[domain]` appended after it |
| `[code]…[/code]` | a code box — **block-level, full width** |
| `### heading`, `**bold**`, `` `code` `` | shown literally, character for character |

So an `[h2]` first line is the only way to give an entry a heading of its own,
and a version number belongs there if the history is meant to be readable.

Two things follow for anything converting Markdown to a change note. `[code]`
is a *block*: mapping inline `` `identifier` `` onto it splits the sentence
around it, so inline code has no BBCode equivalent and is best left as the
backticks it already is — they render literally, but literal backticks still
delimit the identifier, which is what they were there for. And a note written
in Markdown does not degrade gracefully: `###` and `**` appear as themselves,
which is worse than plain prose would have been.

There is also **no Game Version dimension**. mod.io carries compatibility tags per
build; the Workshop has no equivalent, so a mod cannot advertise which game
versions it runs on.

## The change history is append-only to every API, and editable in the browser

The distinction matters and is easy to collapse into "immutable", which is
wrong. **In the web UI an author can edit a change note and delete a history
entry.** No programmatic path can do either. Checked three ways:

- **`ISteamUGC`** — the whole surface of the bundled assembly is 84 calls. The
  only ones that touch an item's history are `SubmitItemUpdate`, which appends,
  and `DeleteItem`, which removes the entire item. Nothing names an individual
  entry; `ChangeNote` exists solely as a field on the editor for the entry
  being created. (`Revision` appears in the assembly only for controller
  bindings.)
- **`steamcmd`** — four workshop commands: `workshop_status`,
  `workshop_download_item`, `workshop_create_legacy_item`,
  `workshop_build_item`. The last takes a VDF whose keys are `appid`,
  `publishedfileid`, `contentfolder`, `previewfile`, `visibility`, `title`,
  `description`, `changenote`, `language`, `tags` — `changenote` being the new
  entry's. It is an uploader over the same `ISteamUGC` calls, so it could not
  exceed them.
- **Steam's public Web API** — `GetSupportedAPIList` offers only reads for
  Workshop content (`GetPublishedFileDetails`, `GetCollectionDetails`,
  `GetUserVoteSummary`). `IPublishedFileService`'s writing methods are
  publisher-key gated, and a publisher key belongs to the app's owner rather
  than to a mod author.

So a mistake in a published history is repairable, but only by hand, one entry
at a time. Anything that writes many entries should therefore be rehearsed
against a throwaway item first — not because a mistake is permanent, but
because correcting N of them is N visits to a web form.

One caveat on `steamcmd` in particular: it needs a TTY for its first-run
bootstrap. Given `</dev/null` it stops after its start banner and sits until
killed, so it is not usable from a script here even though it works fine from
an interactive shell.

## An item can carry publisher-side state, and it is the right place for it

`SetItemMetadata` gives every item a free-form string that only the publisher
reads — `Editor.WithMetaData(string)` writes it, and a query returns it as
`Item.Metadata`. The read buffer is 32,768 bytes, though Valve documents the
limit as 5,000.

**A query only fills it when asked**: `Query.All.WithFileId(id).WithMetadata(true)`.
Without that flag the field is `null`, and code that reads `null` as "nothing
recorded yet" would be wrong for every item that has something recorded.

Why it is worth knowing: it removes the need for a local state file when a
process spans several submits. A file can disagree with reality — the upload
succeeds, the file write does not — whereas metadata travels in the same
`SubmitItemUpdate` as the content it describes, and survives a fresh checkout
or a different machine. (The Workshop *id* still has to live locally, because
it is needed before the first submit exists to carry anything.)

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
Reported upstream as [CoreKeeperModSDK#13](https://github.com/Pugstorm/CoreKeeperModSDK/issues/13).

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

A `description.txt` left in the same folder is the opposite case, and the tab
asks for it there — `GetDescriptionFromFile` reads the description from
`modBuilderSettings.modPath` when the description field is empty. A `TextAsset`
does exist at runtime, so it is written into the bundle like any other asset:
measured with a marked file, it comes back out of both the Windows and the
Linux bundle as a `TextAsset` named `description`, contents intact. The type
decides, not the folder.

Both files — the settings asset the tab writes there, and the `description.txt`
it asks for there — are reported upstream as [CoreKeeperModSDK#14](https://github.com/Pugstorm/CoreKeeperModSDK/issues/14).

Reading the bundle to check any of this needs a deserialiser (UnityPy or
similar) — searching it proves nothing either way, because it is compressed.

## Reading an item's dependencies: which query answers, and which lies

A Workshop item's dependencies are its **children**. Two Facepunch calls appear
to offer them and only one does, which matters to anything that syncs a
dependency list rather than only adding to it — removing what an item should no
longer carry requires knowing what it carries now.

**`Item.GetAsync(id)` never returns them.** It comes back with `Children ==
null` for an item that demonstrably has children, because it asks only for
`WithLongDescription`. Measured against a live item, not inferred from the
signature.

**`Query.All.WithFileId(id).WithChildren(true)` does return them, populated.**
Measured against seven live Core Keeper items, each of which carries exactly one
child:

| Item | Child |
|---|---|
| PlacementPlus, ChatCommands, Quick Replace, Quick Potion, Master Experience, DummyMod | `3673516180` (CoreLib) |
| Scenes+ | `3674611197` |

**A bulk `Query.All` page is not usable for this, or for anything else about an
item's content.** Its entries are placeholders: across 162 items every one came
back with an empty `title`, `owner` of 0, no tags and no children. A `null`
there measures how complete the response is, not what the item holds — so an
absent value proves nothing at all.

That trap is easy to walk into, because the placeholder page answers without
erroring. The control that exposes it costs two minutes: print `title` and
`owner` beside whatever is being read. An empty title next to a null field says
the response is empty, not the item.

One more way to probe this wrongly: CoreLib is the item nearly everything else
points **at**. Reading *it* to find out whether children come back populated
asks the wrong item — what is needed is one that **has** a dependency, not one
that **is** one.

## Attaching a child twice reports failure

`AddDependency` returns **false** for a child the item already carries. The
value is the same one a genuine failure returns, and nothing distinguishes
them — measured on a live item, then reproduced by calling it a second time
against a child known to be attached.

So a sync that adds unconditionally is wrong from the second submit to the same
item onward: it grades the wanted state as a failed attach. Read the item's
children first and skip what is already there. The removal half of a full sync
needs that same list anyway, so reading it once costs nothing and keeps both
halves deciding from one answer.

## Steam does prompt subscribers to install required items

Subscribing to an item that carries children opens a dialogue — *Additional
required content* — listing them by title, with buttons to subscribe to one or
to all. The item page also shows them in its own sidebar box. Neither needs
anything in the description.

Worth stating because the opposite is easy to believe while it is still true:
before an item has children, no prompt appears and no box is rendered, so a
description that tells players to subscribe to the dependencies by hand looks
correct. It stops being correct the moment the dependencies are actually
attached — and the description does not stop saying it.

## A missing item does not come back as an empty result

Querying an id that is not a Workshop item returns `ResultCount == 1`, not 0 —
with an entry whose `Result` is `FileNotFound`, an `Owner` of 0 and an empty
title. Measured with three ids, two of them non-existent; all three returned a
count of 1.

So a `ResultCount == 0` check never detects a missing item. The entry's own
`Result` is the only thing that does, and code that skips that check goes on to
act on a `FileNotFound` entry as though it were real.

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
