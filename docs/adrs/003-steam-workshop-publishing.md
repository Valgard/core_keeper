# Publish to the Steam Workshop with our own tool, as a second stage after mod.io

## Context and Problem Statement

Core Keeper's Steam Workshop left its closed beta with 1.2, and the mods in this
repository should reach it the way they reach mod.io: from one command, derived
from files that already exist, with nobody retyping metadata a file already
holds.

The SDK ships a Steam Workshop tab that uploads successfully — a reference
upload went through it. The question was whether to drive that tab, or to talk
to Steam ourselves.

## Decision Drivers

- Every published value must come from an existing source of truth. A value
  typed twice is a value that diverges from its mod.io counterpart.
- A Steam failure must never damage a mod.io release, because that release
  cannot be withdrawn once it exists.
- A Workshop item's id must survive every way a run can end. Losing it means the
  next run creates a second, public item that nothing distinguishes from the
  first.

## Considered Options

1. Drive the SDK's Steam Workshop tab
2. A file-based C# script, like `utils/corekeeper-patch.cs`
3. A .NET project binding the SDK's own Facepunch assembly

## Decision Outcome

**Option 3.** `utils/ck-workshop/` is a .NET project that receives a publish
bundle as JSON on stdin and makes the Steamworks calls. `utils/steam_bundle.py`
assembles that bundle from the repository; `utils/upload.sh` runs the two
destinations in sequence.

The split is deliberate: everything derivable and testable lives in Python and
has unit tests, while the half that needs a live Steam session — and cannot be
unit-tested — stays as small as possible.

**Steam runs after mod.io and can never fail it.** A preflight validates
everything the Steam stage needs that does not depend on a finished build, and
runs *before* the mod.io release rather than merely early: once that release
goes out it cannot be undone. A failure there skips Steam and lets mod.io
proceed, ending the run in exit 8 — non-zero, because the invocation asked for
Steam and did not get it, but distinct from 1, because the mod.io release is
published and is not retracted. Once Steam does run, a failure is reported in
the exit code rather than treated as fatal, for the same reason.

**The Workshop id is addressed by path**, in `unity/<Mod>/<Mod>_Steam.asset`,
never by the `modName` field inside it — that field is written from the display
title and looked up by `metadata.name`, so it goes stale by design
([CoreKeeperModSDK#11](https://github.com/Pugstorm/CoreKeeperModSDK/issues/11)).
The tool reports a newly created id the moment it exists, not only on success,
and `upload.sh` persists it regardless of the outcome.

**Everything published is derived.** Tags come from `CK_MODIO_TYPE` and the
manifest, the version and change note from `CHANGELOG.md`, the preview from the
mod's logo. Two values are files of their own: `steam-description.txt`, because
the Workshop renders BBCode where mod.io takes Markdown, and
`utils/steam-dependencies.json`, because a Workshop title is a display name
rather than an identity — several items may share one, so a name search could
resolve to the wrong item. A dependency miss is filled in by hand, once.

### Consequences

- Good: a Steam publish costs the same single command as a mod.io one, and the
  two listings cannot drift apart in the values both carry.
- Good: the failure modes that produce a duplicate public Workshop item are
  closed — a killed run leaves the id in a file rather than losing it.
- Bad: the SDK's own Facepunch assembly must be bound by path, so the build
  depends on `SDK_PATH` and on a native `libsteam_api.dylib` that the SDK does
  not ship on macOS (`utils/fetch_steam_lib.sh` fetches the matching one).
- Bad: publishing requires a live, signed-in Steam client, and an account holds
  one online session at a time — publishing and playing are mutually exclusive.
- Neutral: `--changelog-only` and `--profile-only` have no Steam equivalent and
  skip it. The Workshop has no metadata-only edit that leaves no trace, so both
  would ship a full item update for what was asked to be a text edit on mod.io.

## Pros and Cons of the Options

### Drive the SDK tab

- Bad: it never calls `WithChangeLog`, so every upload leaves an empty change
  note and the published version history stays blank.
- Bad: it resolves its content folder from a five-entry UI ring buffer that only
  the SDK window fills — a build driven any other way leaves it empty.
- Bad: title, description, tags, preview and visibility are UI fields, so
  nothing is derived and everything can diverge from mod.io.
- Bad: it discards a created item's File ID when an upload fails ([#13](https://github.com/Pugstorm/CoreKeeperModSDK/issues/13)) and keeps
  its Editor-only files in the folder ModBuilder collects the mod from ([#14](https://github.com/Pugstorm/CoreKeeperModSDK/issues/14)).

### A file-based C# script

- Good: no project files, matching `utils/corekeeper-patch.cs`.
- Bad: that script works because Mono.Cecil comes from NuGet. Here a *local*
  assembly must be bound, and .NET has no directive for it — `#:reference` does
  not exist.
- Bad: the NuGet `Facepunch.Steamworks` package ships no Posix variant, which is
  what macOS needs, and targets an older Steamworks generation than the SDK
  assembly — it would require a second native library beside the working one.
- Bad: reflection via `Assembly.LoadFrom` was verified to work but moves every
  call to runtime. A probe on the overloaded `WithContent` raised
  `AmbiguousMatchException` — the failure that must not appear mid-publish, when
  the mod.io half has already completed.

## More Information

The raw design spec this distils, including the measurements behind each
rejection, is in the commit that deleted it:

~~~
git show "$(git rev-list -1 HEAD -- docs/specs/2026-08-26-steam-workshop-publishing-design.md)^:docs/specs/2026-08-26-steam-workshop-publishing-design.md"
~~~

How the pipeline is operated is [`docs/publishing.md`](../publishing.md); how the Workshop behaves
as a platform is [`docs/ck/steam-workshop.md`](../ck/steam-workshop.md).
