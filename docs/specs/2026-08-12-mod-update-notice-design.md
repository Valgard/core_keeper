# Mod Update Notice — Design (DRAFT)

- **Date:** 2026-08-12
- **Mod:** working title `mod-update-notice` (new repo) — name still open
- **Status:** **draft.** The display surface is deliberately undecided; see
  § Open decisions. Everything under § Settled mechanics holds regardless of
  which surface wins.

## Problem

Core Keeper never tells you a mod update exists unless you go looking. There
is no badge, no toast, no line in the log — the information is reachable only
by opening the mod menu, which is the one place you have to *decide* to visit.

The cost is not merely a missed patch. On this machine the client and the
dedicated server share a mod set through symlinks into the client's mod.io
cache. When the client pulls an update and the server does not, the join fails
as `Error/BadProtocolVersion`, which reads as "wrong game version" and sends
you debugging the wrong thing. Seeing "3 updates available" *before* loading a
world would head that off.

No existing mod does this. A scan of all 269 public mods in the Core Keeper
mod.io catalogue (name + summary + full description) found nothing that reports
update availability. The closest is **0ModReporter** (modId 3177999, by limoka),
which lists per-mod *load state* — `Ok`, `Disabled`, `Errored`,
`Missing Dependency`, `Not Downloaded`, `Corrupted` — but never compares
versions. It also sits behind a menu of its own, and its only version tag is
`1.0.0.2`.

## What the game already does

All line references are against game **1.2.1.4** as decompiled at
`~/Projects/checkouts/CoreKeeperDecompile/`; they will drift with updates, so
treat them as a starting point for a grep, not as coordinates.

The mod menu is `RadicalMainMenuOption_OpenMods` (`Pug.Other:338577`), which
opens **mod.io's own drop-in UI package** (`modio.UI.dll`, namespace
`ModIOBrowser`) via `Browser.Open()`. Pugstorm embedded that package rather
than reimplementing it, and that embedding is the whole reason the information
is trapped: the update logic lives on the browser's lifecycle, not on a game
service.

The server round-trip that discovers updates is `ModIOUnity.FetchUpdates()`,
and it has exactly **two** callers:

| Caller | Fires when |
|---|---|
| `Browser.Open()` | you open the mod menu, and only if already authenticated |
| `Collection.CheckForUpdates()` | you press "Check for Updates" in the collection panel |

There is no timer and no startup hook. Directly beside the call in
`Browser.Open()` sits `ModIOUnity.EnableModManagement(Mods.ModManagementEvent)`
— the automatic download/install machinery. It, too, is armed by the act of
opening the menu.

The resulting state is then held locally and is readable at any time, with no
callback and no HTTP:

```csharp
SubscribedMod[] mods = ModIOUnity.GetSubscribedMods(out ModIO.Result result);
// SubscribedMod { SubscribedModStatus status; string directory;
//                 ModProfile modProfile; bool enabled; }
```

`SubscribedModStatus` (`modio.UnityPlugin:29014`) carries the needed value
directly:

```
Installed, WaitingToDownload, WaitingToInstall, WaitingToUpdate,
WaitingToUninstall, Downloading, Installing, Uninstalling,
Updating, ProblemOccurred, None
```

**`WaitingToUpdate` is the signal this mod exists to surface.** Nothing has to
be parsed, diffed, or fetched over REST.

## Settled mechanics

These hold for every display option below.

### Reaching the mod.io API from a sandboxed mod

Two independent switches, both already familiar in this family:

1. **`accessesExtraAssemblies: 1`** in the ModBuilderSettings `.asset`. The
   loader adds every assembly loaded at game start as a Roslyn metadata
   reference (`PugMod.Loader:1278`), which is what makes `modio.UnityPlugin`
   visible to mod source. Every sibling mod here already sets it — as does
   CoreLib — alongside `skipSafetyChecks: 0`. **The sandbox does not have to be
   given up for this.**
2. **`modio.UnityPlugin.dll` in the runtime `.asmdef`'s
   `precompiledReferences`.** The wizard puts it only in the *editor* asmdef
   (where `CLIPublishHelper` needs it), so without this the Unity build fails
   with `CS0246` long before the loader is involved. Two switches, two
   different compilers — both are required.

### Triggering the check ourselves

`FetchUpdates(callback)` must be called by this mod, since the game only calls
it from the browser. Preferred trigger: **once when the main menu becomes
active**, not on a repeating timer. Rationale — the value of the information is
"decide before you load a world", a poll adds network traffic for a state that
changes every few days, and a single call keeps the failure surface to one
place. A manual re-check can be added later behind a settings row.

There is a second, cheaper attachment point worth evaluating during
implementation: `Mods.OnModManagementEvent` is a plain multicast delegate
(`RadicalMainMenuOption_OpenMods.Awake` combines its own handler onto it at
`Pug.Other:338594`). Subscribing to it costs no Harmony patch at all. It only
reports management *events*, so it cannot replace the initial `FetchUpdates`,
but it can keep a badge current after one.

### Reading the result

In the `FetchUpdates` callback: call `GetSubscribedMods`, check
`result.Succeeded()`, and count entries where

```csharp
mod.enabled && (mod.status == SubscribedModStatus.WaitingToUpdate
             || mod.status == SubscribedModStatus.Updating)
```

`enabled` matters — a mod you switched off should not nag. Failure is silent by
design: no result means no badge, never an error popup. The user did not ask
for this check and must not be interrupted by its failure.

### `requiredOn`

**`1` (Client).** This is a read-only client-side display; it must never make
joining an unmodded server impossible. Per this family's crossed-flag rule, a
`Server` flag would make the *client* demand the mod on the server — exactly the
hard block this mod is meant to help you avoid.

## Open decisions

### D1 — Display surface (**the open one**)

**A — Badge on the main-menu "Mods" entry.** A count or dot beside the label.

The strongest technical finding for this option: `RadicalMenuOption`
(`Pug.Other:343031`, the base class two levels up) already declares
**`public PugText valueText`** (`:343058`) next to `labelText` (`:343056`).
That is the field CK uses
for the right-hand value on toggle-style options. If it is present and wired on
the Mods entry, a badge needs **no prefab, no new GameObject, no layout work** —
only a string written into an existing text object. That would make the
"heaviest-looking" option the lightest one to build. *Must be verified in the
extracted prefab before committing to this — see U3.*

*Pro:* the only surface where the information can still change what you do;
warns before a world load, which is where the client/server drift bites; no
in-game clutter. *Contra:* invisible to someone who clicks straight through to
"Continue".

**B — One-shot message on entering a world.** A chat or popup line.

*Pro:* cheapest possible build; unmissable; exactly once. *Contra:* arrives at
the moment you can least act on it — you are in the world, and the only remedy
is to leave it again.

**C — Permanent in-game HUD.** The `player-coordinates-hud` pattern.

*Pro:* lowest technical risk; this family has built the part three times.
*Contra:* permanent screen real estate for a fact that changes every few days.
A poor trade.

**Recommendation: A**, with B as a cheap follow-up if A proves too easy to walk
past. Not both in iteration 1.

### D2 — Notify only, or also update?

Recommendation: **notify only.** `EnableModManagement` exists and would let the
mod pull updates itself, but installing behind the player's back changes the
mod set — and on this machine the dedicated server's symlinks are reconciled by
`utils/server.sh relink`, which runs at server start, not when a client-side
download lands. An unattended client-side update is therefore the exact input
that produces the `BadProtocolVersion` mismatch this mod is meant to warn about.
Notifying is the whole job.

### D3 — Name

`mod-update-notice` / `ModUpdateNotice` / "Mod Update Notice" is a working
title, chosen to stay neutral about D1 (`…-badge` would presuppose A). All three
levels must agree per family convention.

### D4 — Settings

Probably one `Enabled` toggle via Mod Settings Menu, matching the siblings; that
adds `ModSettingsMenu` + `CoreLib` as dependencies. Worth asking whether a mod
this small needs a settings row at all — if the answer is no, it ships with zero
dependencies, which is a meaningful simplification.

## Architecture

Small enough to state in a table. Under option A, in namespace
`ModUpdateNotice`:

| Class | Responsibility |
|---|---|
| `ModUpdateNoticeMod : IMod` | Bootstrap. Nothing in `EarlyInit`. |
| `UpdateProbe` | Owns the mod.io conversation: calls `FetchUpdates`, reads `GetSubscribedMods`, exposes an `int PendingCount`. No UI knowledge. |
| `MenuBadge` | Harmony patch on the Mods menu option; writes `PendingCount` into `valueText`. No mod.io knowledge. |
| `ModConfig` | Only if D4 says yes. |

The seam between `UpdateProbe` and the display is the point of the split: D1 is
undecided, and the probe must not have to change when it resolves. Whichever
surface wins consumes the same `PendingCount`.

## Open unknowns

Each is cheap to settle, and none can invalidate the approach — but U1 and U2
should be answered by a throwaway probe in an existing mod *before* the repo is
scaffolded.

1. **Does the Roslyn sandbox admit the ModIO namespaces?** The known ban list
   covers `System.IO.*` and `Manager.saves.*`; ModIO is not on it, and
   `accessesExtraAssemblies` exists precisely to widen this surface. Unverified
   all the same. A single `ModIOUnity.GetSubscribedMods` call added to a sibling
   mod answers it — look for `safetyCheck=True` and the absence of
   `CompileFailed` in `Player.log`.
2. **Does `FetchUpdates` work with no browser ever opened?** The game's own call
   is guarded by `ModIOUnityAsync.IsAuthenticated()`, so an unauthenticated
   session may return a failed `Result` rather than data. If so, the mod
   inherits that limitation honestly: no login, no badge.
3. **Is `valueText` actually present and populated on the Mods entry?** Decides
   whether option A is a one-line write or needs a text object of its own.
   Answerable offline in the AssetRipper extraction of the main-manager prefab
   via `utils/prefab_query.py`.
4. **Does calling `FetchUpdates` outside the browser arm anything else?**
   Specifically whether mod management stays disabled — relevant only because
   D2 says we do not want automatic installs.

## Verification

No offline test is possible; the sandbox, Harmony and the menu exist only in the
running game.

1. `utils/build.sh`, then grep `Player.log` for `error CS`, `CompileFailed` and
   `safetyCheck=True`.
2. **Producing a real test fixture:** publishing a trivial version bump to one
   of this family's own mods creates a genuine `WaitingToUpdate` on a machine
   whose local cache still holds the old modfile. That beats mocking, and it is
   the only way to see the true status value rather than a guessed one.
3. In-game:
   - With an update pending: the count appears, and it matches what the mod menu
     shows when opened.
   - With nothing pending: **no badge at all** — not a `0`.
   - Offline / not logged in to mod.io: no badge, no error dialogue, nothing in
     the log louder than a single informational line.
   - After the update is installed: the badge clears on the next main-menu
     visit.

## Identity

- Repo `mod-update-notice`, namespace `ModUpdateNotice`, DisplayName
  "Mod Update Notice" — all three matching, per family convention.
- Scaffold with `utils/new_mod.py` (see the `new-ck-mod` skill); `--summary`,
  `--required-on` and `--modio-type` are mandatory. Add `--corelib` only if D4
  lands on "yes".
- Fake mod.io dev ID **9999986** — verified free against the `FAKE_MOD_ID`
  values in every sibling `.envrc` (9999987…9999999 are taken).
- `requiredOn: 1`, `skipSafetyChecks: 0`, `accessesExtraAssemblies: 1`.

## Deliverables beyond the scaffold

`utils/new_mod.py` emits the `.asset`, both `.asmdef`s, every `.meta`,
`_modio.asset`, the `IMod` bootstrap, `.envrc`, `.gitignore`, `CHANGELOG.md`,
the formatting gate, a placeholder logo, and the localisation table with its
`LOC_YAML`/`LOC_OUT` wiring already active. Still needed:

- **The `modio.UnityPlugin.dll` reference** in the runtime asmdef — not
  scaffolded, and the build fails without it.
- **The localisation terms**, if D4 adds a settings row. The scaffolded
  `localization/localization.yaml` is deliberately **inert** — every line a
  comment — because the wiring is armed from the start and the generator fails
  on a table that has content but yields no term. So the file exists and the
  build is green either way; what is missing is the first real entry. Leaf keys
  stay unquoted (the generator is a line parser that does not unquote them).
- **`README.md`** and **`modio-description.md`**, both free of build-environment
  detail (no `utils/`, no `.envrc`, no Wine/CrossOver, no fake IDs).
- **A real logo** in the family style (teal/petrol hero object, gold accents,
  golden radial glow, 4-point sparkles, 1024², transparent). Gesture still to be
  invented — something like a gold download arrow or a small "new" spark over a
  stack of cubes, not a reused sibling motif.
- **`CLAUDE.md`** for the new repo.

## Out of scope: comparing versions against a server

Warning about a *server's* mod versions was considered and deliberately split
off into its own mod — see
[`server-mod-version-check`](2026-08-13-server-mod-version-check-design.md).
The motive overlaps, the mechanism does not: that one patches an ECS RPC and
reads the loader API, this one reads the mod.io plugin. Their manifests want
opposite things too — that mod needs `requiredOn: 0` so a diagnostic can never
gate a connection, this one wants `1`.

The division of labour: this mod warns **before** drift exists ("mod.io has a
newer build than you"), the other diagnoses it **after** ("the server's copy
differs from yours").
