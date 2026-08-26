# Publishing to mod.io

mod.io is where Core Keeper mods are distributed, and the SDK ships the client
for it. This chapter is about the service's data model and the SDK plugin's
behaviour — the parts that hold whoever presses the button, and that decide what
a mod's listing can and cannot say later.

How you drive a publish is a separate question with many valid answers: the SDK
window, a scripted batchmode run, the website. Nothing here assumes one.

Since 1.2 it is also no longer the only destination: the [Steam Workshop](steam-workshop.md) has its
own data model, its own tag handling and its own limits, and almost nothing
below carries over to it.

## Profile and modfile are different things

A published mod is two layers, and almost every surprise below follows from
which layer a field lives on.

| Layer | Holds | Lifetime |
|---|---|---|
| **Profile** | name, summary, description, logo, tags, dependencies | one per mod, edited in place |
| **Modfile** | the uploaded build, its version, its changelog | one per release, immutable once uploaded |

So a description or a tag can be corrected at any time without shipping
anything. **A changelog cannot** — it belongs to a release, and the API's
`UploadModfile` only ever *creates* a modfile. There is no edit call for one.
Fixing a wrong release note therefore means either a new release or the REST
API directly, which is a different surface from the plugin.

**The mod's own sources carry no version.** Nothing in a `.cs` file, the
assembly definitions or the ModBuilderSettings `.asset` names one; the version
that appears on mod.io is supplied at publish time. Where it comes from is a
matter of convention, and a repository is free to keep it in a changelog file,
a build argument, or a prompt.

**A newly created profile is public unless you ask otherwise.** The plugin
sends `visible = 1` for every profile whose `ModProfileDetails.visible` was not
explicitly set to `false`, so a first publish puts a half-configured listing in
the catalogue for as long as it takes to finish it. Setting `visible = false`
on creation and switching it on the website afterwards is a choice the
publisher makes, not something the platform does for you.

The SDK window is the one route where that choice is already made: its
Register button sets `visible = false` explicitly, so a profile created
through it starts **hidden**, not public — the plugin's own default only
applies to a caller that leaves the field unset.

## Which metadata field becomes what

The listing does not read `ModManifest.json` — and neither does the SDK
window's own publish button. Both read the **ModBuilderSettings `.asset`**,
whose `metadata` block carries the `ModMetadata` field names. Editing the
generated manifest changes nothing.

| `metadata` field in the `.asset` | Becomes |
|---|---|
| `name` | the profile name the SDK window sends — **not** `displayName`, which is `[HideInInspector]` and reaches no publish call at all |
| `dependencies` | the mod.io **platform** dependency list — see below |

`logo` and `summary` do not come from this `.asset` either: the SDK window
keeps them on a separate settings asset of its own, so neither tracks
`metadata.name`.

`requiredOn` and `skipSafetyChecks` do not become mod.io tags through
anything the SDK does — the window makes no mod.io tag call at all; the only
tag picker it ships is a manual one for Steam Workshop, a different target
with its own vocabulary. Whichever `Application Type` or `Access Type` tags a
listing ends up carrying are a **publisher's own convention**, set by hand on
the website or by tooling written for the purpose — never something the
platform or the SDK derives for you.

The consequence worth remembering runs the *other* way, and it is the one
that bites: **at load time the tag is authoritative, not the field.** Both
loaders force `metadata.skipSafetyChecks = false` unless the profile carries
`Script (Elevated Access)`. A mod that ships `skipSafetyChecks: true` and is
published without that tag therefore runs sandboxed at every subscriber,
while its author — who runs a local build that never consults the profile —
cannot reproduce the verification failures they report. The field never
turns into the tag by itself: a publisher who sets `skipSafetyChecks: true`,
publishes through the SDK window, and assumes the `Access Type` tag follows
ships an elevated-access mod **without** the warning that tag exists to
give.

`requiredOn` and what its values mean for joining a server is in [mod anatomy](mod-anatomy.md);
`skipSafetyChecks` and what it buys is in [the sandbox chapter](sandbox.md).

## Tags, and the silence around them

Core Keeper's mod.io game has several tag groups. Four matter to a script mod:
`Game Version`, `Type`, `Application Type`, `Access Type`.

**mod.io accepts an unknown tag value and drops it without a word.** No error,
no warning, no rejected call — a typo such as `Quality of live` simply does not
appear on the listing. Anything that sets tags programmatically should validate
against the live vocabulary first and fail loudly, because the platform will
not.

**The vocabulary is not stable and must be read, never hardcoded.**
`GetTagCategories` returns the groups with their permitted values, and the
`Game Version` group grows with every game patch. It is also *incomplete* by
design: mod.io does not necessarily carry a tag for every build that shipped,
so a mod that runs on a version with no tag simply cannot advertise it.

`Asset` is a value the group offers that a script mod never earns; a listing
that carries it is mis-tagged rather than special.

## Dependencies exist twice, and the two do not know each other

A mod that needs another one — CoreLib, most commonly — declares it in its
ModBuilderSettings `.asset`, which the build writes into `ModManifest.json`.
That is what the **loader** reads at startup.

mod.io keeps its own, separate dependency list on the profile, which is what
the **website and the in-game browser** use to offer "install these too". The
two are set through different calls and can disagree indefinitely; nothing
reconciles them for you.

Two details of the platform list:

- **It is keyed by numeric mod id, not by name.** The manifest refers to
  `CoreLib`; the API wants `3177992`. Resolving one to the other means a
  `GetMods` search — and **that call requires pagination parameters**. Omitting
  `SetPageIndex` / `SetPageSize` fails with error `20201` rather than
  defaulting to a first page.
- **There is no "required" attribute.** The loader-side manifest distinguishes
  a required dependency from an optional one; the mod.io list does not. Whatever
  that distinction means for a publish is a decision made before the call, not
  something the platform stores.

## The plugin, and what it does to a batchmode run

Publishing goes through the SDK's bundled mod.io plugin (`ModIOUnity`), not
through a REST client of your own. Two properties of it shape any automation:

- **The calls are asynchronous.** A Unity run started with `-quit` will exit
  while the upload is still in flight. Automating a publish means letting the
  editor code decide when to terminate, and guarding the run with a timeout so a
  hung call cannot block forever.
- **Authentication is a stored session, not a token you pass.** You log in once
  through the SDK window with an email code; the plugin persists it and
  batchmode runs authenticate from it. The session lasts roughly a year, and its
  expiry looks like an authorisation failure long after anyone remembers logging
  in.

## Never run a dev build and a subscription of the same mod

The loader deduplicates by `metadata.name`: `SortMods` builds a dictionary
keyed on it, last write wins, and returns only the values. A local development
build and a subscription of the same mod share that name, so **exactly one of
them runs and nothing says which**. Which one survives depends on the order the
loader platforms registered.

The hazard is therefore the opposite of doubling: you fix something, relaunch,
and are still testing the other copy. Nothing in the log distinguishes the two.

Before testing a published build the way a player receives it, remove the local
one. The reverse case is the quieter one: subscribing to your own mod for a
quick look leaves it subscribed.

The loader has **three** platforms: a side-loader that scans
`StreamingAssets/Mods` for any directory holding a `ModManifest.json`, the
mod.io loader, and the Steam Workshop loader. `-safemode` disables only the
first two — the Steam Workshop loader is registered unconditionally, even in
safe mode, though it is usually inert there too, since `SteamClient.IsValid`
fails without a live Steam session. Two of the three — the mod.io loader and
the Steam Workshop loader — load from a subscription list; the side-loader is
the one that reads a directory instead — which is why a not-yet-published mod
can be made loadable in more than one way, and why the dedicated server loads
its mods from a directory rather than an account.
