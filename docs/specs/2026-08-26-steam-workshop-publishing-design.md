# Steam Workshop publishing

Core Keeper's Steam Workshop left its closed beta with 1.2, and the mods in this
repository should reach it the same way they reach mod.io: from one command, out
of the sources that already exist, without a human retyping metadata that a file
already holds.

The SDK ships a Steam Workshop tab, and it is not a usable base for that. This
spec records what it cannot do, what replaces it, and where every published value
comes from.

## Why not the SDK tab

The tab (`Packages/dev.pugstorm.mod/SDK/Editor/ModSDKWindow/SteamWorkshopTab.cs`)
uploads through Facepunch.Steamworks and works — a reference upload succeeded from
it. Four properties make it the wrong foundation for automation:

- **It never sets a changelog.** `WithChangeLog` exists in the bundled
  Facepunch assembly; the tab does not call it. Every Steam upload therefore
  creates an empty change note, and the version history of a published mod stays
  blank.
- **Its stored identity is keyed on the display title.** `SteamWorkshopModSettings`
  is written from the Title field but looked up by `metadata.name`, so once the two
  differ the tab no longer finds the File ID it wrote — and would create a second
  Workshop item on the next upload. Reported upstream as
  [CoreKeeperModSDK#11](https://github.com/Pugstorm/CoreKeeperModSDK/issues/11).
- **It resolves its content folder through a UI ring buffer.** The upload target
  comes from `latestBuildOrInstallPaths.LastOrDefault(x => x.EndsWith(modName))`,
  a five-entry list that only the SDK window fills. It exists to populate a
  dropdown, not to identify a build.
- **Everything is typed, nothing is derived.** Title, description, tags, preview
  and visibility are UI fields. Each one already has a source of truth in this
  repository, and each one retyped is a chance to diverge from mod.io.

## The tool

A .NET project at `utils/ck-workshop/`, invoked as
`dotnet run --project utils/ck-workshop -- <args>`.

**A project rather than a file-based script**, unlike `utils/corekeeper-patch.cs`.
That script is file-based because Mono.Cecil comes from NuGet; here a *local*
assembly must be bound, and .NET has no directive for that — `#:reference` does
not exist. The remaining options were a NuGet Facepunch package or reflection, and
both were rejected:

- The NuGet package `Facepunch.Steamworks` ships `lib/netstandard2.0/Facepunch.Steamworks.Win64.dll`
  only; there is no Posix variant, which is what macOS needs. It also targets an
  older Steamworks generation (`SteamUGC_v014`, `SteamUser_v020`) than the SDK
  assembly (`SteamUGC_v016`, `SteamUser_v021`), so it would require a second,
  differently-versioned native library alongside the one that already works.
- Reflection with `Assembly.LoadFrom` was verified to work, but moves every call
  to runtime. `WithContent` is overloaded, and a probe using it raised
  `AmbiguousMatchException` — exactly the failure that must not surface during a
  publish, which by then has already completed its mod.io half.

The project therefore carries a `<Reference>` with a `HintPath` onto the SDK's
`Assets/Plugins/CoreKeeperModSDK/Facepunch.Steamworks.Posix.dll`, resolved from
`SDK_PATH`.

## Wiring into `upload.sh`

`utils/upload.sh` gains a second stage: mod.io first, exactly as today, then Steam.
Both read the same sources, which is the point of doing it in one command — one
version, one changelog, one tag set, two destinations.

**A Steam failure does not fail the mod.io publish.** By the time Steam runs, the
mod.io release has happened and cannot be taken back; aborting afterwards would
reverse nothing and only obscure what succeeded. Steam errors are reported loudly
and set the exit code.

Two new flags:

| Flag | Effect |
|---|---|
| `--no-steam` | mod.io only — for mods that are not on the Workshop |
| `--steam-only` | Steam only — so a Steam failure can be retried without cutting another mod.io release |

## Identity

The File ID lives in `unity/<Mod>/<Mod>_Steam.asset`, the file the SDK tab also
uses — but **addressed by its path, never by the `modName` field inside it**. That
sidesteps the upstream defect entirely (the title is irrelevant to us) while
keeping the tab functional, because both sides maintain the same file. A separate
`.envrc` variable was rejected: the tab would keep writing the asset, the tool
would read elsewhere, and the two would eventually name different items.

**A newly created item is uploaded hidden, never public**, mirroring the caution
the mod.io side already applies at first publish. Making a listing visible stays a
deliberate act on the website.

## Where each value comes from

| Field | Source |
|---|---|
| Content | `$MOD_INSTALL_PATH/$MOD_NAME` — the folder ModBuilder produced |
| Title | `metadata.displayName`, falling back to `metadata.name` |
| Description | `<mod-repo>/steam-description.txt` (BBCode) |
| Tags | `CK_MODIO_TYPE` (pipe-separated) plus `requiredOn` and `skipSafetyChecks` |
| Preview | derived from `unity/<Mod>/Editor/logo.png` |
| Changelog | the topmost `## [x.y.z]` entry of `CHANGELOG.md` |
| Visibility | hidden when creating; untouched when updating |

**Tags are sent flat.** Steam assigns them to its own groups — a reference upload
sent `Item`, `Quality of Life`, `Overhaul`, `Client`, `Server`, `Script` and the
listing rendered them under *Kategorie*, *Anwendungstyp* and *Zugriffstyp*. The
mapping already exists on Core Keeper's Workshop configuration; nothing needs
prefixing. Steam drops unknown values silently, exactly as mod.io does, so the
configured values are validated before anything is sent.

There is **no Game Version equivalent** on Steam. `CK_GAME_VERSION` and
`CK_MODIO_VERSION_UNLISTED` have no counterpart here and are not consulted.

### The description is its own file

`steam-description.txt` sits in the mod repository root, beside
`modio-description.md`, and is written in BBCode.

It is deliberately not converted from `modio-description.md`: mod.io renders
Markdown and Steam renders BBCode, and the constructs that differ — tables, nested
lists, fenced code — have no faithful BBCode equivalent. A converter would fail
silently on the live page.

It is equally deliberately **not** placed at `unity/<Mod>/description.txt`, where
the SDK tab would find it as a fallback (`GetDescriptionFromFile`). Everything
under the mod folder is bundled: the manifest of a built mod lists `config.json`,
`<Mod>_Steam.asset` and even `<Mod>.asmdef.wizard-original` among its assets. A
description file there would ship inside the mod, and a symlink would not help
because Unity follows it and imports the target.

### The preview is derived, not authored

Steam rejects a preview image above **1 MB** with `k_EResultLimitExceeded` —
measured, not assumed. Every logo in this repository exceeds it; they are 1024²
PNGs with soft golden glow, which compresses poorly.

The tool derives the preview from `logo.png` by trying successively smaller
lossless sizes — 1024², 896², 768², 640², 512² — and taking the first that fits.
Measured against the current logos, 1024² and 896² never fit and 768² usually
does; 512² is around 360 KB. Only if none of them fits does it fall back to
colour quantisation at the largest size that then fits.

Downscaling comes before quantisation because Steam displays previews small
(roughly 268² in listings), so resolution is spent where it is not seen, while
reduced colour depth shows as banding in the gradients these logos are made of —
visible at full size on a quantised 1024² test render.

Transparency is preserved; Steam composites onto its own background.

## Dependencies

The Workshop has a required-items list, and the SDK tab does not touch it —
`Steamworks.Ugc.Item` exposes `AddDependency` and `RemoveDependency` (over the
native `SteamAPI_ISteamUGC_AddDependency`), and nothing in the tab calls either.
A published Core Keeper mod that needs CoreLib therefore says so on mod.io and
stays silent on Steam, where a subscriber gets no prompt to install it too.

The desired set comes from the same place as the mod.io one: the `.asset`'s
`metadata.dependencies`. As there, the sync is **full rather than additive** —
the resolved set is diffed against what the item currently carries, and surplus
entries are removed, so the Workshop list mirrors the `.asset`.

**Name-to-id resolution follows the mod.io path, with a stricter accept rule.**
The manifest names a dependency (`CoreLib`); Steam wants a published file id.
`Steamworks.Ugc.Query` supports `WhereSearchText`, tag filters (`WithTag`,
`MatchAllTags`) and `RankedByTextSearch`, and each returned `Item` carries
`Title`, `Tags`, `Owner` and `NumSubscriptions` — enough to decide, and enough to
refuse to.

The resolution is a self-populating cache, `utils/steam-dependencies.json`, in
the same `{modName: id}` shape as `utils/modio-dependencies.json`. On a miss it
searches, and **accepts an id only on exactly one candidate whose title matches
the dependency name after normalisation** (case- and space-insensitive) — the
same single-match rule the mod.io helper applies.

What differs is what happens when that rule does not settle it. A Steam title is
free text and a display name, not an identity: several items may share one,
and a dependency may be published under a title that differs from its loader
name. So on zero matches or more than one, the tool **aborts and prints the
candidates** — id, title, owner and subscriber count — rather than picking the
most popular. The operator resolves it once by writing the id into the cache, and
no later run asks again. Guessing here is worse than stopping: a wrong id makes
subscribers install an unrelated mod, and nothing about that failure points back
at the publish.

**A dependency may simply not exist on the Workshop.** It is a young opt-in beta
and carries far fewer mods than mod.io — Pugstorm's own documentation says so.
Severity follows the `.asset`'s `required` flag, exactly as the mod.io path
already does: an unresolvable **required** dependency aborts before anything is
uploaded, an unresolvable optional one warns and is skipped. "Not found" and
"ambiguous" are the same outcome here, and both are reported with what the search
did return.

## Modes

Steam has no profile/modfile split — a Workshop item is one object, and every
`SubmitItemUpdate` leaves an entry in its change history. The existing modes
therefore map asymmetrically:

| Mode | mod.io | Steam |
|---|---|---|
| *(default)* | build, modfile, profile, tags, dependencies | content, title, description, tags, preview, changelog |
| `--profile-only` | description, tags, logo — no release | metadata without `WithContent`; **still produces a change-history entry** [^1] |
| `--changelog-only` | REST `PUT` on the modfile | **skipped** — Steam has no edit for an existing change note |
| `--dry-run` | plans, sends nothing | same |

`--changelog-only` stays a mod.io-only mode by design. A Steam equivalent would
mean an extra empty upload that adds a second history entry in order to correct a
first, which is worse than the error it fixes.

[^1]: Unverified: that `Ugc.Editor` accepts a submit without `WithContent` follows
from its builder shape, but has not been run. If it turns out to require content,
`--profile-only` re-sends the existing build folder instead — the first thing the
implementation should check, because it is cheap to test and changes one branch.

## Prerequisites

- **`libsteam_api.dylib` must be present**, and at the version the SDK's managed
  assembly expects — Steamworks **1.55**. The newest redistributable does not work:
  `SteamAPI_Init` was removed from the flat API around 1.59, and the interface
  accessors the assembly requests (`SteamAPI_SteamUGC_v016`,
  `SteamAPI_SteamUser_v021`) are not in 1.57 either. The SDK's own bundled
  `steam_api64.dll` names the target generation and is the reliable way to
  determine it after an SDK update.
  Because this repository is public, the library is not committed; a setup step
  fetches it from a pinned source and verifies it by checksum.
- **The native Steam client must be running and online**, with an account that
  owns Core Keeper — the game itself need not be installed. On a CrossOver host
  this takes the bottle's Steam session offline: publishing and playing are
  mutually exclusive.
- Unity is **not** required for the upload, only for the build that precedes it.

## Not in scope

- Making a hidden item public. That stays manual and deliberate.
- Cleaning up what ModBuilder puts into the bundle (`<Mod>_Steam.asset` with the
  author's SteamID64, `*.wizard-original`). A real finding, unrelated to publishing.
- A Markdown-to-BBCode converter.
- Picking between ambiguous dependency search results automatically. That stays
  a one-time human decision, recorded in the cache.
