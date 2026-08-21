# Publishing to mod.io

mod.io is where Core Keeper mods are distributed, and the SDK ships the client
for it. This chapter is about the service's data model and the SDK plugin's
behaviour — the parts that hold whoever presses the button, and that decide what
a mod's listing can and cannot say later.

How you drive a publish is a separate question with many valid answers: the SDK
window, a scripted batchmode run, the website. Nothing here assumes one.

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

**A newly created profile is hidden.** It exists, it can receive files, and
nobody can find it until it is switched visible — deliberately, so a
half-configured listing is not public for the minutes it takes to finish. Expect
one manual step on the website for a mod's first release, and none afterwards.

## Which manifest field becomes what

The listing does not read `ModManifest.json`. Several of its fields do reach
mod.io, but each through a separate call, and two of them arrive as *tags*
rather than as text:

| Manifest field | Becomes |
|---|---|
| `displayName` (fallback: `name`) | the profile name — so the human title may differ from the internal identity |
| `requiredOn` | a tag in the `Application Type` group |
| `skipSafetyChecks` | a tag in the `Access Type` group — `Script` or `Script (Elevated Access)` |
| `dependencies` | the mod.io **platform** dependency list — see below |

The consequence worth remembering: **flipping `skipSafetyChecks` re-categorises
the mod in the catalogue**, not just in the loader. A reader filtering for
sandboxed mods stops seeing it.

`requiredOn` and what its values mean for joining a server is in [mod anatomy](mod-anatomy.md);
`skipSafetyChecks` and what it buys is in [the sandbox chapter](sandbox-and-config.md).

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

A locally installed development build and a real mod.io subscription of the same
mod are **two separate mods** as far as the loader is concerned: two directories,
two manifests, two loads. Its Harmony patches are applied twice, and the
resulting behaviour — doubled effects, a prefix that sees its own output — looks
like a bug in the mod rather than a duplicate installation.

Before testing a published build the way a player receives it, remove the local
one. The reverse case is the quieter one: subscribing to your own mod for a
quick look leaves it subscribed.

How a not-yet-published mod is made loadable at all is a platform question — the
loader only walks the mod.io subscription path — and is covered in [running the game on this platform](platforms.md).
