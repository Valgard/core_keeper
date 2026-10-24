# Let `--steam-only` build what it publishes, and hold every Steam publish against mod.io

## Context and Problem Statement

`utils/upload.sh --steam-only` exists to catch a mod up on the Steam Workshop
after its mod.io release — when the Steam stage of a normal publish failed, or
when a mod that has been on mod.io for a while goes to Steam for the first
time. It ran no build of its own: it uploaded whatever `build.sh` had last left
in `MOD_INSTALL_PATH`, and labelled it with the topmost `CHANGELOG.md` version
of the checkout it was started in. Nothing tied the two together.

On 2026-10-11 that put an unreleased Mod Settings Menu build, made from another
worktree the day before, on the Workshop as 1.2.2. Steam players got
`CompileFailed` for eleven days, and every mod that requires Mod Settings Menu
stopped loading with it. A Workshop change history cannot be corrected through
any API — only by hand in the browser, one entry at a time — so a wrong upload
stays in the record unless someone edits it out.

Two smaller faults rode along: the DOTS codegen check of that branch inspected
the shared folder rather than what was uploaded, and every publish wrote the
uploaded folder into `selectedPath` of `<Mod>_Steam.asset` — a field the SDK
window's own Steam button uploads from, which ended up naming either a
temporary directory or the shared folder itself.

## Decision Drivers

- The content and the version label have to come from one place, in one run.
- A mod need not exist on mod.io; a Steam-only mod must still be publishable.
- A normal publish keeps building exactly once for both destinations.
- A wrong upload has to be caught before it is sent wherever that is possible,
  and reported right after it where it is not.
- A guard that fires on correct runs gets ignored; one that passes silently is
  how the incident happened. A check fails closed, and where one deliberately
  only warns, it says so.

## Considered Options

1. Download mod.io's modfile for the version and publish exactly that
2. Keep publishing the local build, but check where it came from (a stamp
   written by `build.sh`, or the release tag)
3. Build in the run itself, from the checkout that supplies the version, and
   compare the result with mod.io wherever mod.io holds that version

## Decision Outcome

**Option 3.** `--steam-only` runs the publish build through its own Unity
entry point, `CLIPublishHelper.PublishSteamOnly`, and never reads
`MOD_INSTALL_PATH` as a source. A separate entry point rather than a mode
switch, because the helper is compiled into every mod's editor assembly and a
stale copy would ignore a switch and run a full mod.io release; it lacks the
new method and fails instead.

Before anything is sent, the run refuses when the checkout is not the release it
would be published as — uncommitted changes under `unity/`, `localization/` or
to `CHANGELOG.md`, notes under `## [Unreleased]`, a Workshop or mod.io id that
the mod repo's `main` records but the checkout lacks or records differently —
and, for a mod on mod.io, when its version is not the one mod.io serves or the
build's byte total differs from mod.io's `filesize_uncompressed`. A hand-set
`CK_STEAM_CONTENT` remains as the repair route for a release the current
toolchain no longer rebuilds, accepted only when that same comparison runs and
holds, and never from inside `MOD_INSTALL_PATH`.

After every Steam publish — normal or `--steam-only` — the item's size from the
Steam Web API is compared with mod.io's; a mismatch exits 11, a comparison that
could not be made exits 12. A checkout that lacks the mod.io id `main` records,
or records a different one, stops every run before mod.io, because the publish
helper would otherwise create or update another mod.io profile. Both platforms
read the version with one rule, `## [x.y.z]`, and every publish writes
`selectedPath` empty.

### Consequences

- Good: for a mod on mod.io, a rebuild whose byte total differs from the release
  is refused before the upload — equal size is strong evidence of the same
  build, not proof.
- Good: the normal publish gains a delivery check (Steam holds what mod.io
  holds) without a second build.
- Good: the SDK window can no longer upload the shared folder through a stale
  `selectedPath`.
- Bad: `--steam-only` costs a Unity run and the SDK project lock, even with the
  override, which still reads mod.io through the owner's session.
- Bad: a mod not on mod.io has no reference; a clean checkout at the wrong
  commit still goes through, and the printed commit is the only trace.
- Bad: the id checks need `main`. When it cannot be asked — no `main` branch, a
  git failure or timeout — they only warn, and a checkout whose ids are missing
  or different is not stopped. A missing mod.io id then means no comparison
  under `--steam-only` and a second mod.io profile on a normal publish; a
  missing Workshop id means a second Workshop item on either run — as before
  this change.
- Bad: the first Steam publish of a new mod is expected to end in 12 — a new
  item is hidden, and whether the public Web API reports a hidden item's size
  is unverified.
- Neutral: the size comparison rests on a measured property — a rebuild of a
  checkout identical to a release in every path that ships was byte-identical to
  that release's published folder for one mod, and for a second mod rebuilt
  after an SDK update its byte total still matched mod.io's. A toolchain change
  that breaks it shows up as a refused rebuild, with the override as the repair.
- Neutral: the size comes from the Web API's `file_size` because the session's
  UGC query reported 0 for an item whose content is a folder — measured on one
  item.

## Pros and Cons of the Options

### Download mod.io's modfile

- Good: Steam would carry mod.io's bytes exactly.
- Bad: it assumes every mod is on mod.io, which is not a rule of this
  repository.

### Keep the local build and check its provenance

- Good: no Unity run.
- Bad: the release tag is set by hand after a publish, so nothing ties it to a
  build; and `MOD_INSTALL_PATH` takes whatever any `build.sh` run writes,
  including dev builds with test fixtures.

### Build in the run and compare with mod.io

- Good: works with and without mod.io, and for a mod on it catches the
  incident's case — a build whose size differs from the release it is labelled
  as.
- Bad: costs a build per `--steam-only`, and depends on builds reproducing.

## More Information

The raw design spec this distils is in the commit that deleted it:

~~~
git show "$(git rev-list -1 HEAD -- docs/specs/2026-10-22-steam-only-own-build-design.md)^:docs/specs/2026-10-22-steam-only-own-build-design.md"
~~~

It records the incident in detail and the decisions as they were taken, in the
form they reached after two rounds of review.

How the pipeline behaves day to day — the refusals, the override, the exit codes
— is [`docs/publishing.md`](../publishing.md#publishing-to-the-steam-workshop); the reproducibility measurement is [`docs/build-environment.md`](../build-environment.md#a-mod-build-reproduces-byte-for-byte);
what the Workshop reports as an item's size is [`docs/ck/steam-workshop.md`](../ck/steam-workshop.md).
