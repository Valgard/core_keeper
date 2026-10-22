# `upload.sh --steam-only` builds its own content — design

Status: APPROVED, 2026-10-22

## What went wrong

On 2026-10-11 a full `upload.sh` for Mod Settings Menu 1.2.2 released to
mod.io, and its Steam stage then failed with exit 3 from `ck-workshop` because
the native macOS Steam client was not running. The Steam half was caught up
afterwards with `upload.sh --steam-only`.

Under `--steam-only` no mod.io build runs, so the file `CK_BUILD_DIR_OUT` names
(`BUILD_DIR_FILE` in `upload.sh`) stays empty and `steam_bundle.build_bundle`
falls back to `MOD_INSTALL_PATH/<Mod>` — the last `build.sh` output on this
machine, from whichever checkout, branch or worktree ran it, with whatever
`MOD_DEV_FLAGS` it was given. That folder held an unreleased v2 build an agent
had made from a rebase worktree the day before. It went to the Workshop
labelled 1.2.2, with 1.2.2's change note. For eleven days Steam players got
`mod ModSettingsMenu load error: CompileFailed`, and every mod that requires MSM
stopped loading with it.

It was found by comparing Steam's `GetPublishedFileDetails.file_size` against
mod.io's `modfile.filesize_uncompressed`: equal for every other mod, 740464
against 116669 for MSM. The item has since been repaired by hand, by uploading
the downloaded 1.2.2 modfile through a hand-set `CK_STEAM_CONTENT`.

A second road leads to the same fallback: after a failed Steam *preflight*,
`upload.sh` prints a recommendation to re-run with `--steam-only`
(`upload.sh:263`). It was not printed on 2026-10-11 — that run's preflight
passed — but it points every future preflight failure the same way.

## The defect, stated once

The **version label** and the **content** come from two unrelated sources. The
label is the topmost `CHANGELOG.md` entry of the checkout `upload.sh` runs in;
the content is whatever was last written to a shared folder that every
`build.sh` run writes to. Nothing ties the two together.

The label half has a flaw of its own: `steam_bundle.parse_changelog` takes the
topmost `## [...]` heading whatever it says, while `CLIPublishHelper` takes the
topmost `## [x.y.z]`. complete-tools opens with `## [Unreleased]`, so today a
publish would label mod.io 1.0.0 and Steam "Unreleased".

Two smaller defects named in the commissioning message ride along:

- **The DOTS codegen check sits in the wrong place.** The `--steam-only` branch
  (`upload.sh:472-474`) always inspects `MOD_INSTALL_PATH/<Mod>`, against the
  compiled assembly of whichever checkout was linked last, even when
  `CK_STEAM_CONTENT` was set from outside and another folder is uploaded.
- **`selectedPath` collects throwaway paths.** The publish writes the uploaded
  content path into `selectedPath` of `unity/<Mod>/<Mod>_Steam.asset`. On the
  normal path that is `CLIPublishHelper`'s `Application.temporaryCachePath/<guid>`,
  which macOS clears at reboot; three mod repos have such paths committed, and a
  fourth carries the SDK window's own `BuiltMods` temp path. The SDK window uses
  this field as its Steam upload folder for every mod whose asset it finds by
  name (`SteamWorkshopTab.cs`, `SelectSteamWorkshopModSettings` overwrites the
  `ModPaths.asset` result), so the value is not cosmetic: seven mods point it at
  `MOD_INSTALL_PATH`, the shared folder of the incident.

## Intent

For the two runs `upload.sh` has — the normal publish and `--steam-only` — what
reaches the Workshop under a version number is built from the checkout that
supplies that version number, in the same run, or is an explicitly named folder
whose size matches what mod.io serves for that version. Under `--steam-only`, a
mismatch with mod.io is caught before the upload; on the normal publish, where
both destinations get one folder, it is reported after it.

Known limit: a mod that is not on mod.io has no reference. For it, a clean
checkout at the wrong commit still goes through; the printed commit is the only
trace.

## Goals

- `--steam-only` can no longer publish a folder that it neither built nor was
  explicitly handed.
- Both `upload.sh` runs compare the Steam content with mod.io's modfile wherever
  mod.io has that version live.
- No `selectedPath` in the mod repos points at a temporary or shared build
  folder, and no publish writes one again.

## Non-goals

- Changing the normal publish beyond: the result check, the duplicate-item
  check in the Steam preflight, the matching changelog parser, the handling of
  an inherited `CK_STEAM_CONTENT`, and `selectedPath`. It already hands its one
  build to both destinations.
- Making mod.io the source of Steam content. A mod may exist on Steam only.
- `steam_backfill.py`; it ships downloaded modfiles by design.
- The SDK window's own lookup flaw: an asset whose `modName` no longer matches
  (disable-durability's reads "Disable Durability") is never found, and the
  window would create a second item from it. That is upstream issue #11.
- Replies to players on Steam.

## Anti-goals

- **Two builds in a normal publish.** mod.io and Steam must keep receiving the
  one build `CLIPublishHelper` makes. (Sven's.)
- **A guard that fires on every correct run.** It gets ignored or switched off.
- **Silent degradation.** No path may fall back to some other content folder,
  or skip a check without saying so.

## Decisions

Made by Sven in the design conversation on 2026-10-22. Where this section adds
detail beyond what he decided, the detail is listed under "The calls I made".

**D1 — `--steam-only` builds.** It runs a Unity batchmode build of the mod from
the checkout it was started in, into a fresh directory, and publishes exactly
that directory. It never reads `MOD_INSTALL_PATH`. It does not download from
mod.io, because a mod need not exist there.

**D2 — One build per normal publish.** Unchanged: `CLIPublishHelper` builds
once and reports the directory through `CK_BUILD_DIR_OUT`; Steam uses it.

**D3 — Uncommitted changes under `unity/` or `localization/` are refused.** In
Sven's words: "`--steam-only` verweigert den Lauf, wenn unter `unity/` oder
`localization/` uncommittete Änderungen liegen."

**D4 — `selectedPath` is cleared.** Every Steam publish through `upload.sh`
writes the field empty, on both runs; the values already committed are cleared
once, as part of this work. Sven chose this over leaving the field alone, whose
cost was that the seven `MOD_INSTALL_PATH` values stay. The accepted cost: the
SDK window's Steam upload button is disabled for these mods
(`SetEnabled(!string.IsNullOrEmpty(_selectedWorkshopPath))` after the asset is
read). Corrects the `selectedPath` part of the paragraph "The publish fills that
asset in completely" in `docs/publishing.md`; `modOwner`, `tags` and the id are
still written.

**D5 — A result guard against mod.io.**

| Run | Check | On mismatch |
|---|---|---|
| normal publish | **after** Steam: Steam `file_size` == mod.io `filesize_uncompressed` of the modfile just published | distinct exit code; nothing can be undone |
| `--steam-only`, mod.io has this version live | **before** the upload: size of the content folder == mod.io `filesize_uncompressed` of that version; then the same check after | refuse before anything is sent |
| `--steam-only`, mod not on mod.io | no comparison, and the run says so | — |

The pre-upload comparison exists only if builds reproduce: a measurement of two
builds of one commit comes first (below). If they differ, it is dropped, as
Sven accepted ("fällt der Vorab-Vergleich weg, statt bei jedem Lauf fälschlich
anzuschlagen").

**D6 — `CK_STEAM_CONTENT` stays as an override, checked.** Under
`--steam-only`, a `CK_STEAM_CONTENT` set from outside replaces the build. It is
announced loudly and accepted **only when the D5 pre-upload comparison can run**
— the mod is on mod.io, that version is live, and the folder's size matches.
Otherwise the run refuses. This is the repair route used on 2026-10-22,
independent of the SDK state; a Steam-only mod has no override.

**D7 — A mod.io mod cannot run ahead of mod.io.** If the mod has a mod.io id
but the topmost `CHANGELOG.md` version is not on mod.io, `--steam-only` refuses.

## Acceptance criteria

Derived from the three defects of the commissioning message and from D1–D7;
each names its source.

1. `upload.sh --steam-only` publishes either its own fresh build of the invoking
   checkout or a `CK_STEAM_CONTENT` folder accepted under D6 — never the
   `MOD_INSTALL_PATH` fallback. (Defect "falscher Inhalt"; D1, D6.)
2. No DOTS codegen check inspects a folder other than the one uploaded; on the
   override path, where none applies, the run prints that it skipped it and
   why. (Defect "DOTS-Codegen-Prüfung am falschen Ort".)
3. No Steam publish through `upload.sh` leaves a path in `selectedPath`, and no
   mod repo keeps one committed. (Defect "`selectedPath`-Nebeneffekt"; D4.)
4. `--steam-only` refuses when `unity/` or `localization/` has uncommitted
   changes, on the build path and the override path alike. (D3.)
5. A normal publish still builds exactly once for mod.io and Steam. (D2.)
6. The result guard behaves as the D5 table says, for all three rows, including
   the measurement-dependent rule below the table. (D5.)
7. An outside `CK_STEAM_CONTENT` under `--steam-only` is announced, and refused
   unless the pre-upload comparison can run and holds. (D6.)
8. `--steam-only` refuses for a mod with a mod.io id whose topmost
   `CHANGELOG.md` version is not on mod.io. (D7.)
9. `docs/publishing.md` (Steam section, `--steam-only`) and the comments in
   `upload.sh` and `steam_bundle.py` describe the new behaviour; tests in
   `utils/tests` cover it and pass (`uv run pytest utils/tests`); the review
   gate `/pr-review-toolkit:review-pr` over the branch diff runs before merge
   or PR. (Commissioning message, "Rahmen".)

## What the result guard does and does not show

Equal size is the measure the two platforms already agree on — for all 16 mods
Steam's `file_size` equals mod.io's `filesize_uncompressed` today — and the
incident's sizes differed sixfold. It is strong evidence of the same build, not
proof: two different builds can share a size.

On the normal path both destinations receive one folder, so the post-upload
comparison shows delivery — Steam holds what mod.io holds — and nothing about
whether that build was right. A wrong but consistent build (the dev-flag case
under "Seen on the way") passes it. Under `--steam-only` the pre-upload
comparison is the check against the incident's class of error: a checkout, or
an override folder, that does not match the release it is labelled as.

## The calls I made

Sven did not decide these; they are mine and open to correction.

- **What D3 counts.** Untracked files count: `link.sh` symlinks the whole
  `unity/<Mod>/` directory, and ModBuilder collects shippable files by folder,
  not by git status. Ignored files do not: under `unity/` they are the `link.sh`
  helper symlinks and their `.meta` files, `.DS_Store`, and in some mods the
  generated localisation. Several mods track their generated localisation
  instead (mod-settings-menu, faster-talents, auto-rail-bridges); the build
  rewrites it, and history shows the rewrite byte-identical, so D3 stays clean
  there. A mod that opts into `MOD_DEV_FLAGS` tracks
  `Generated/DevFlags.generated.cs`, so a dev build leaves it modified and D3
  stops it.
- **D3 also covers `CHANGELOG.md`**, an extension of Sven's rule: the file
  supplies the version label, and an uncommitted entry would make the printed
  commit misstate what the run published. In git terms:
  `git status --porcelain -- unity localization CHANGELOG.md` must be empty.
- **D3 runs before the build**, so a refusal costs seconds, not a Unity run.
- **No exemption for the identity assets the pipeline writes itself**
  (`<Mod>_modio.asset`, `<Mod>_Steam.asset`). After a first release they have
  to be committed before `--steam-only`, which the repository asks for anyway;
  the refusal names the file.
- **One changelog rule for both platforms.** `steam_bundle` adopts
  `CLIPublishHelper`'s `## [x.y.z]` rule, so an `[Unreleased]` heading is
  skipped on Steam as it is on mod.io. Under `--steam-only`, a non-empty
  `[Unreleased]` section above the topmost version is refused: it says the
  checkout carries changes past the release it would be labelled as.
- **The run prints the commit it builds from** (short hash, branch or
  "detached", repo path). It refuses nothing by itself.
- **The ids are checked against `main`.** Release tags commonly predate the
  commits that record the ids — 8 of 16 mods' latest tags carry no Workshop id.
  So when the checkout's `<Mod>_Steam.asset` or `<Mod>_modio.asset` has no id
  while the mod repo's `main` has one, the Steam stage refuses: a missing
  Workshop id would create a second item, a missing mod.io id would make the
  mod look "not on mod.io" and skip D5 and D7. On the normal publish this lives
  in the Steam preflight, so it skips Steam with exit 8 and leaves the mod.io
  release alone.
- **"Not on mod.io" is decided from the repository**, after the check above:
  `<Mod>_modio.asset` has no or a zero `modId`. With an id, mod.io is read; if
  it cannot be read, `--steam-only` refuses (fail closed) and says why.
- **mod.io is read with the authenticated session, inside Unity**, so a first
  release whose profile is still hidden reads as present. Under `--steam-only`
  this means a Unity run even with the override, which then reads but does not
  build. On the normal publish, `CLIPublishHelper` reports the size of the
  modfile it just uploaded, the way it reports the build folder. The builder
  verifies that an authenticated read sees a hidden profile; if not, a hidden
  profile is refused with a message to make it visible first — never treated as
  "not on mod.io".
- **"Live" means the version of the mod's current modfile.** Under
  `--steam-only`, a topmost `CHANGELOG.md` version that is not the live one is
  refused: absent from mod.io is D7, and present but superseded means the
  checkout is behind mod.io.
- **Steam is read so that a new hidden item is visible too** — through the
  Steam session (`ck-workshop`), if the public Web API cannot see hidden items.
  The size is read before the submit as well; afterwards the run re-reads for a
  bounded time until it differs from the old one. Still the old size (and the
  old differs from the expected), or unreadable: "the comparison could not be
  made". A new size that differs from the expected: a mismatch.
- **The DOTS check.** The bash `check_dots_codegen.py` call in the
  `--steam-only` branch is removed. On the build path, `DotsCodegen.Check`
  inside the shared build step checks the folder that is uploaded, after
  `link.sh` has pointed the SDK at this checkout. On the override path there is
  none, and the run says so: the compiled assembly belongs to the last-linked
  checkout, not to the override folder. What the override folder carries is
  what mod.io serves for that version — the check passed it only if that
  modfile was published after the check existed (2026-10-07; 4 of 16 live
  modfiles are newer).
- **The `MOD_INSTALL_PATH` fallback in `steam_bundle.build_bundle` is removed**,
  in the same change as D1 and D6 — until those land, `--steam-only` depends on
  it. Afterwards both production callers set `CK_STEAM_CONTENT` (`upload.sh`,
  `steam_backfill`), and `build_bundle` raises when it is missing.
- **The override may not point into `MOD_INSTALL_PATH`.** That folder is never a
  source, whatever its size.
- **An inherited `CK_STEAM_CONTENT`.** Under `--steam-only`, any outside value
  is treated as the D6 override — announced and checked — whether it was meant
  or left over from a repair session. On the normal publish, `upload.sh` unsets
  it at the start and says so; the Steam stage uses only the folder
  `CLIPublishHelper` reports, and the mod.io release is not affected.
- **When same-toolchain builds reproduce but an older release does not** (a
  rebuild after an SDK or game-asset update), the pre-upload comparison stays,
  and its refusal names the toolchain change as the likely cause and points to
  the override (D6).
- **Exit codes.** `upload.sh`'s own new refusals before anything is sent exit 1.
  Of `ck-workshop`'s codes, 2–4 are refusals before anything is sent and 5–6
  failures; all pass through as today. After the upload, two new codes mean
  "Steam's content does not match mod.io" and "the comparison could not be
  made". `upload.sh` and `ck-workshop` share one code space, and
  `ck-workshop`'s header names 10 as its own next code, so the builder
  allocates past it and updates both headers. A mismatch outranks 0, 7, 9 and
  130 (a killed `tee`, after which the upload may well have completed — so the
  check still runs); nothing masks 2–6 or 124.
- **`--dry-run` under `--steam-only`** runs D3, the changelog and id checks,
  then builds (or takes the override), then D7 and the pre-upload comparison,
  and hands the bundle to `ck-workshop --dry-run`. No post-upload check:
  nothing was sent.
- **The printed recommendation at `upload.sh:263` stays**, since
  `--steam-only` no longer leads into the fallback.
- **The measurements are recorded** in `docs/build-environment.md`; whether a
  mod build reproduces is knowledge other work will want.

## Measurements

**First, before the pre-upload comparison is built: two builds of one commit.**
Build one mod twice from the same commit, with the build steps this design
uses (including the `touch` that forces a recompile), into fresh folders, and
compare total size; byte identity is recorded as information. Equal: the
comparison is built. Different: it is dropped (D5). The leftover folders in
`Application.temporaryCachePath` are suggestive but do not settle it: complete-
tools built twice three minutes apart and map-markers-enhanced in groups of two
or three are byte-identical within each group, but which commit each came from
is not recorded. Two map-markers-enhanced groups built while 2cf81c7 was the
newest commit differ: the first lacks `Scripts/Generated/`, built before the
recompile `touch` existed. So "same toolchain" includes forcing the recompile.
macOS clears these folders at reboot.

**Settled already: the local measure.** For MSM 1.2.2, mod.io's
`filesize_uncompressed`, Steam's `file_size` and the byte total of the folder
it was published from are all 116669; Steam's `file_size` also equals the
folder total for map-markers-enhanced (130860) and complete-tools (235285). So
"size of the content folder" in D5 is the sum of its file sizes.

**Second, informing only the refusal's wording:** a rebuild from a release tag
that predates the SDK update of 2026-10-08 (sign-labels 1.0.0 or
map-markers-enhanced 2.0.0) against that release's modfile, by total size.

## Constraints

- The `--steam-only` build runs the same steps as the publish build, as shared
  code rather than a copy: `link.sh` (so the SDK symlink points at this
  checkout — the incident's build came from another worktree's link), the
  `touch` of the mod's `.cs` files for DOTS codegen,
  `LocalizationGenerator.GenerateFromEnv`, a fresh directory under
  `Application.temporaryCachePath`, `DotsCodegen.Check`, and the unhooking of
  the SDK window's queued `OpenWindow`.
- After changing `CLIPublishHelper`, every mod is re-linked before a real run
  (the stale editor assembly note in `docs/publishing.md`).
- `--steam-only` needs `UNITY_BIN` again, with or without the override;
  `MOD_SUMMARY` stays mod.io-only.
- The SDK project lock is an operator rule: a held lock is waited for, never
  broken. No polling code is asked for.
- "Steam never fails the mod.io release" stays true; every new check on the
  normal path runs in the Steam preflight or after mod.io.
- `ruff`, CSharpier and the documentation gates pass.
- Clearing the committed `selectedPath` values touches the mod repos: one
  commit each, pushed to both remotes, and only while the Unity Editor is
  closed.

## Tests to expect

- D3 on the build path and the override path: clean, modified, untracked,
  ignored-only, and a dirty `CHANGELOG.md`.
- The changelog rule: `[Unreleased]` skipped by `parse_changelog`; a non-empty
  `[Unreleased]` refused under `--steam-only`.
- D4: `steam_result` writes `selectedPath` empty; the fixtures in
  `test_steam_result.py` and `test_steam_identity.py` that expect a path change
  with it.
- The fallback removal: `test_steam_bundle.py` builds most of its environments
  without `CK_STEAM_CONTENT` (29 calls through an `_env` fixture), and one test
  asserts the fallback; these move to a reported folder, and a test asserts the
  raise.
- D5–D7, the id checks against `main`, and the override rules as a testable
  Python decision helper (as `steam_result.py` was for the persist step): equal,
  unequal, unreadable, hidden, not on mod.io, version absent, version
  superseded, override with and without a mod.io reference, override inside
  `MOD_INSTALL_PATH`, either id missing in the checkout but present on `main`,
  and the post-upload re-read (unchanged, changed to expected, changed to
  something else).
- The exit-code mapping, including the precedence rules above.

## Documentation to change in the same work

- `docs/publishing.md`: the Steam section's `--steam-only` description, the
  override, the `selectedPath` paragraph (D4), the exit-code table, and the
  result guard with what it does and does not show.
- `docs/build-environment.md` around line 117 (`--steam-only` no longer
  publishes the last local build), plus the measurements.
- `README.md` around line 119, if its wording still implies the shared build
  output under `--steam-only`.
- Comments and messages: `upload.sh` header, ~180, ~263, ~458-478;
  `steam_bundle.py` ~430-448 and `parse_changelog`; `steam_result.py` and
  `steam_identity.py` where they describe `selectedPath`; `ck-workshop`'s
  exit-code header.

## Seen on the way, out of scope

- `CLIPublishHelper` does not run `GenerateDevFlags`. A normal publish after a
  dev build with `MOD_DEV_FLAGS` set ships the modified `DevFlags.generated.cs`
  unless an ordinary build ran in between; neither D3 (`--steam-only` only) nor
  the result guard (a delivery check) catches it there. Worth its own change.
- `CLIPublishHelper` never removes its temporary build folders; macOS does, at
  reboot.

## Left to the builder

- Whether the build-only path and the authenticated mod.io read live in a mode
  of `CLIPublishHelper.Publish` or a sibling entry point sharing its build
  method.
- Which modfile counts when one version was uploaded twice.
- The bounded re-read before Steam's `file_size` reflects a submit — its length
  is unmeasured.
- The concrete numbers of the two new exit codes.
