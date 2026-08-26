# mod.io Publishing — this repository's pipeline

How every Core Keeper mod here is published, and what the tooling does on top
of the platform.

**How mod.io itself behaves** — profile versus modfile, which manifest field
becomes which tag, why unknown tag values vanish, why a changelog cannot be
edited — is in [`docs/ck/publishing.md`](ck/publishing.md). This file assumes that and describes
only what is specific to this repository.

Publishing runs through the SDK's own mod.io plugin (`ModIOUnity`), not a
REST client — `utils/upload.sh` invokes a per-mod Editor class
`CLIPublishHelper` (sibling of `CLIBuildHelper`) via `-executeMethod`. One
narrow exception calls the REST API directly, because the plugin has no
equivalent: `--changelog-only`, below.

### Three modes

A full run builds the mod, uploads a modfile and syncs everything. Two narrower
modes exist because not every correction deserves a release, and each is scoped
to what its target actually is:

| Mode | Touches | Leaves alone |
|---|---|---|
| *(default)* | build + new modfile + profile + tags + dependencies | — |
| `--profile-only` | description, name, summary, logo, tags, dependencies | the build and the modfile — no version change |
| `--changelog-only` | the published modfile's changelog text | everything else — same modfile id, same version |

`--dry-run` combines with all three: it does everything except the writing calls
and logs what it would have sent. `--profile-only` and `--changelog-only` are
mutually exclusive and refuse to run together.

The split follows the platform's own layers: description and tags sit on the
profile, a changelog sits on the modfile. That is why `--profile-only` cannot
reach a release note, and why a wrong one used to stay wrong until the next
version.

`--changelog-only` therefore does what the plugin cannot — the plugin can only
create modfiles, never edit one. This mode reads the active modfile with the
public game key, then `PUT`s the new text with the plugin's own OAuth token,
pulled out of the internal `ModIO.Implementation.UserData` by reflection (editor
code, outside the Roslyn sandbox that forbids reflection in a mod's runtime
sources; the token is never logged or written to disk).

**It refuses unless the live modfile's version equals `CHANGELOG.md`'s topmost
entry.** Without that guard, a repo already sitting on an unreleased entry would
paste those notes onto the previous release. It also exits early when the text
already matches, so re-running costs nothing. Use it to correct a shipped
changelog; use a real release for anything that changes what the mod does.

- **One-time login:** open the Pugstorm Mod SDK window, use the "Log in" tab
  (email + security code). Batchmode publishes authenticate from the persisted
  session.
- **Version + changelog:** taken from the mod's `CHANGELOG.md` — the topmost
  `## [x.y.z]` entry is the published version, its body the modfile changelog.
  That is this repository's convention for a value the mod itself does not
  carry.
- **Async batchmode:** because the plugin's calls are asynchronous, `upload.sh`
  invokes Unity **without `-quit`** and `CLIPublishHelper` calls
  `EditorApplication.Exit` itself; a `timeout` guards a hung run.

### Publishing to the Steam Workshop

`utils/upload.sh` publishes to two destinations from one command. mod.io runs as
described above; Steam publishing — `utils/steam_bundle.py` assembling a publish
bundle, handed as JSON to the `utils/ck-workshop` .NET tool, which makes the
Steamworks calls — runs afterward, against that same build output. How the
Workshop itself behaves as a platform (one item rather than a profile/modfile
split, its tag groups, the preview size limit, the macOS native-library gap) is [`docs/ck/steam-workshop.md`](ck/steam-workshop.md);
this section covers only what this repository's pipeline does with it.

**The Workshop item's id lives in `unity/<MOD_NAME>/<MOD_NAME>_Steam.asset`,
and it must be committed.** `utils/steam_identity.py` reads and writes it by
path, the same way `CLIPublishHelper` reads the mod.io id from
`<MOD_NAME>_modio.asset` — but unlike that file, nothing scaffolds this one,
so it is easy to leave untracked after a publish creates it. Left untracked,
a `git clean` or a fresh checkout drops the id silently; the next publish
then sees no id, treats the mod as never published, and creates a **second**
Workshop item with no way to tell it apart from the first. Commit it once,
right after the first Steam publish, the same way the mod.io asset already
is — **together with the `.meta` beside it**, which the publish writes at the
same time. Unity would otherwise generate that GUID carrier only when someone
next opens the Editor, leaving the repo one file short of the rule that it
holds every one of them. The `.meta` is written only when absent: an existing
GUID is Unity's, and something may already reference it.

**The publish fills that asset in completely, not just its id.** `modOwner`,
`selectedPath` and `tags` are read by the SDK window alone, and a publish is
the moment their current values are known — so the window finds a usable asset
instead of a half-filled one. It also keeps them from rotting: the window's own
`selectedPath` still named the pre-`MOD_INSTALL_PATH` build directory until a
publish corrected it. `modOwner` comes back from `ck-workshop`, since it needs
a live Steam session; the other two are already in the publish bundle. Each is
written only when its value is known, so a run that cannot determine one leaves
what is there rather than blanking it.

Two consequences worth knowing. `modOwner` is the author's SteamID64, and
ModBuilder bundles everything in the mod's asset folder — so it ships inside
every mod. And `modName` is *not* written on later publishes: it is the
window's lookup key, it goes stale by design ([#11](https://github.com/Pugstorm/CoreKeeperModSDK/issues/11)), and overwriting it every
time would fight the window over a value this pipeline has no better answer
for.

**A run killed by a signal leaves that id in a file rather than losing it.**
The step that writes a newly created id into the asset runs after
`ck-workshop` returns, so a signal aimed at `upload.sh` itself — `kill`, a
closed terminal, an outer `timeout` wrapper — can end the run in the window
between Steam creating the item and its id reaching disk, which is the same
duplicate-item hazard as above with no untracked file to blame. The tool's
output therefore goes to its own `mktemp` file *outside* the scratch
directory the EXIT trap removes: a killed run leaves a
`ck-workshop-<MOD_NAME>-result.*` behind in `$TMPDIR`, holding the id if the
kill came after the tool had reported one. A run that gets far enough to
persist removes its own file, and no run can overwrite another's. The two
interrupts that actually occur need none of this: neither `timeout` firing on
a stalled upload nor a terminal Ctrl-C stops `upload.sh`, so the persist step
runs normally in both.

**Copy such an id into `<Mod>_Steam.asset` only while that asset still has
none.** The asset is the authority; the file is one run's notes. Publish the
mod again before recovering the id and that run creates a *second* item and
writes its id into the asset — after which the leftover file names the orphan
while looking exactly like a recovery file, and copying it in would aim every
later publish at the orphan instead of the live item. Two harmless variants
exist and are safe to delete: an empty file, from a kill that landed before
the tool wrote anything, and several files for one mod, from being killed
twice with nothing to order them by.

**Two flags select which destinations run, and they contradict each other.**
`--no-steam` publishes to mod.io only; `--steam-only` skips mod.io and
publishes to Steam alone. `upload.sh` refuses to run with both set.

**A Steam preflight runs before mod.io, and a failure there skips Steam
instead of aborting the run.** `steam_bundle.check_prerequisites` validates
everything the Steam stage needs that does not depend on a finished build:
`MOD_NAME`, the ModBuilderSettings `.asset`, `steam-description.txt`, a
`CHANGELOG.md` whose topmost `## [x.y.z]` entry parses, `Editor/logo.png`, a
recognizable `<Mod>_Steam.asset`, and a Workshop id for every declared
dependency. The built content folder is the one thing it leaves out, because
that cannot exist yet. It runs first, not merely early, for the same reason
the modfile upload itself cannot: once that release goes out it cannot be
undone, so a missing file or an unresolved dependency has to surface while
skipping still costs nothing. On failure it prints why and continues into the
mod.io release with the Steam stage turned off — then ends the run with **exit
8**, so a caller reading only the status still learns that Steam did not go
out. That release is published and is not retracted by the non-zero code; a
code of its own rather than 1 is what says so. `--steam-only` is the one case
with no mod.io release for that skip to protect, so there a failed preflight
aborts the run instead — publishing nothing while reporting success would be
worse than the previous behaviour.

**Steam runs second and can never fail the mod.io publish.** By the time it
starts, the mod.io release has already happened and cannot be undone, so a Steam
failure is reported — and reflected in the exit code — rather than treated as
fatal: aborting at that point would reverse nothing and only hide what had
already succeeded. The preflight above upholds that same invariant at its own,
earlier point in the run, exit code included; it uses a distinct one because
"Steam never started" and "Steam started and failed" are worth telling apart.
`--changelog-only` and `--profile-only` skip Steam outright rather than
attempting an equivalent: the former edits a mod.io modfile's changelog text,
which the Workshop's single-item model has no counterpart for, and the latter
has no metadata-only publish path on the Steam side yet — running it there would
ship a full Workshop update for what was asked to be a text-only mod.io edit.

**The description comes from `steam-description.txt`, and it is BBCode.**
The Workshop renders `[b]`, `[h2]`, `[list][*]…[/list]` — a literal `##` or
`**` from `modio-description.md` would show up unrendered on the item page —
so the two descriptions are separate files in separate dialects rather than
one derived from the other. `new_mod.py` scaffolds a BBCode template for the
same reason.

**The preview image is derived from the mod's logo, not authored by hand.**
`utils/steam_preview.py` downsizes `Editor/logo.png` down a fixed resolution
ladder — and, failing that, quantises it — until it clears the Workshop's
1 MB preview limit, which the golden-glow gradient in every existing logo
routinely exceeds at its native 1024² resolution.

**`utils/steam-dependencies.json` has no automated search step and is filled
by hand on a miss.** `modio-dependencies.json` self-populates: a cache miss
there triggers a `GetMods` name search and accepts the result only on a
single unambiguous match. Steam has nothing equivalent to search on — a
Workshop item's Title is a display name, not an identity, and more than one
item can carry the same one, so a name match could silently resolve to the
wrong item and ship a dependency that installs something else. A miss is
therefore never guessed at: resolving it means finding the item on the
Workshop and adding its numeric file id to the JSON by hand, once — after
that, every later publish reuses it. Severity still follows the `.asset`'s
`required` flag, exactly as it does for mod.io: a required dependency with no
cached id aborts the publish, an optional one is skipped with a warning.

### Mod dependencies → mod.io platform dependencies

On publish, `CLIPublishHelper` syncs the `.asset`'s `metadata.dependencies`
list (e.g. `CoreLib`) to the mod's **mod.io platform** dependency list
(`AddDependenciesToMod` / `RemoveDependenciesFromMod`), which is a different
list from the loader-side one. The step runs between the profile create/edit and the
modfile upload, so an unresolvable required dependency aborts before anything
is uploaded.

- **modName → ModId resolution.** The `.asset` references a dependency by its
  loader **name** (`CoreLib`); the mod.io API needs a numeric **ModId**. A
  self-populating cache `utils/modio-dependencies.json` (`{modName → modId}`,
  versioned) bridges this; its path is passed via the `.envrc` var
  `MODIO_DEPS_MAP` (set only by mods that declare dependencies). On a cache
  miss the helper runs a `GetMods` search, accepts the ID only on a single
  normalised-name match (case/space-insensitive), and writes it back to the
  cache (allowed even in `--dry-run`).
- **Failure severity follows the `.asset` `required` flag**, which the platform
  does not store: an unresolvable **required** dependency aborts the publish;
  an unresolvable **optional** one logs a warning and is skipped.
- **Full sync, not additive:** the helper diffs the resolved target set against
  `GetModDependencies` and both adds missing and removes extra, so the mod.io
  list mirrors the `.asset` exactly. `--dry-run` logs the plan and skips the
  add/remove calls.

### mod.io tags — four synchronised groups

On publish, `CLIPublishHelper` **synchronises** (not merely adds) the mod's tags
in four of Core Keeper's mod.io tag groups. The desired set per group is diffed
against what `GetMod` reports the mod currently carries, and the surplus is
deleted. Tags outside these four groups are never touched.

| Group | Desired set from |
|---|---|
| `Game Version` | `CK_GAME_VERSION` minus `CK_MODIO_VERSION_UNLISTED` — both **space**-separated, one canonical list each in the parent `.envrc` |
| `Type` | `CK_MODIO_TYPE` — **pipe**-separated, because the values contain spaces (`Visual\|Quality of Life`) |
| `Application Type` | derived from the `.asset`'s `metadata.requiredOn` (`Client`=1, `Server`=2, both=3; **0 is valid** and publishes with no tag in this group, for a mod that must never gate a connection — it logs a warning, because 0 is also what an unset field reads as) |
| `Access Type` | derived from `metadata.skipSafetyChecks` (`false` → `Script`, `true` → `Script (Elevated Access)`) |

- **Every version is checked against the shipped builds first.**
  `utils/upload.sh` exports `CK_KNOWN_GAME_VERSIONS` from
  `utils/ck-game-versions.json`, and both `CK_GAME_VERSION` and
  `CK_MODIO_VERSION_UNLISTED` are validated against it before any mod.io call.
  This is repo data, so it works where the live-taxonomy check below cannot:
  when `GetTagCategories` fails, tagging degrades to additive and mod.io drops
  an unknown value without a word. A typo caught here is caught on both paths.

- **`CK_MODIO_VERSION_UNLISTED` is subtracted before anything is sent.**
  mod.io's `Game Version` vocabulary is a *subset* of the builds that shipped —
  `1.2.1.2`, `1.0.0.7` and `1.0.0.12` have Steam patch notes and no tag — so
  `CK_GAME_VERSION` could not name them without tripping the validation below.
  Naming them here drops them from the desired set, which keeps the list
  truthful for everything else that reads it (`utils/discord_post.py` renders
  the Discord post from it) without weakening a guard that exists to catch
  typos. The subtraction has one failure mode of its own, so it is checked
  against the live taxonomy too: **once mod.io offers a build listed here, the
  publish aborts** until the entry is deleted — otherwise the listing would
  quietly advertise one version fewer than the mod supports.

- **Group membership comes from the live API** (`GetTagCategories`), never a
  hardcoded value list.
- **Configured values are validated before anything is changed**, so a typo
  (`Quality of live`) aborts the publish with a message naming the bad value
  and the group's valid values, instead of being dropped in silence.
- **A read failure degrades to additive, never to "remove everything".** If
  `GetTagCategories` or `GetMod` fails (or a group is missing from the live
  taxonomy), the helper logs a warning, adds the desired tags and removes
  nothing.
- The plan is logged per group before acting
  (`Tag sync plan [Type]: +[…] -[…]`); `--dry-run` logs it and stops there.
- A hand-set `Asset` tag is treated as surplus and removed.

> ⚠️ Known build gotcha: the shared `CLIPublishHelper`/`CLIBuildHelper` compile
> into **every** linked mod's `<Mod>.Editor` assembly, so the class exists in
> several assemblies and `-executeMethod` runs whichever assembly name sorts
> first — do not rely on a particular one; adding a mod can change it, and this
> note used to name a mod that no longer sorts first. Because Unity's
> AssetDatabase does **not** detect edits to a symlink *target*, only the
> currently-built mod's symlinks are refreshed per build — the other mods'
> editor assemblies keep a **stale** compiled copy of the shared helper, and
> `-executeMethod` may run that stale copy. After editing a shared helper,
> re-link **all** mods (run `link.sh` for each) so every editor assembly
> recompiles from the current source before relying on a publish/build run.
>
> How to recognise it, because the symptom is misleading: the stack traces name
> a *foreign* mod's path, which looks like the wrong file was used. Check a line
> number instead — a method's position in the trace versus in `utils/`'s current
> source. The symlink content can be perfectly current while the compiled
> assembly is not, and that is the actual failure. Cost when missed: one full
> Unity run that silently does the old thing.

### The three mod IDs

Three distinct uses of a "mod.io ID", deliberately kept separate:

- **Publishing** uses the **real** mod ID, stored in
  `unity/<MOD_NAME>/Editor/<MOD_NAME>_modio.asset`.
- **Playing** the published mod uses the **real** ID — written by the game
  client when you subscribe normally in the in-game Mods menu.
- **Local dev builds** use the **fake** `FAKE_MOD_ID` via `install-macos.sh`,
  which is the mechanism by which a not-yet-published mod can be loaded at
  all through the mod.io path; the loader also has a `StreamingAssets/Mods`
  side-loader and a Steam Workshop loader, so this is one route of three. The
  fake ID also keeps the dev build out of the real mod.io catalog sync.

**Dev/Prod coexistence:** never have both the fake-ID dev install and a real
subscription of the same mod active. The loader deduplicates by name — only one
copy ever runs, and nothing in the log says which ([`docs/ck/publishing.md`](ck/publishing.md#never-run-a-dev-build-and-a-subscription-of-the-same-mod)) — so
the hazard is not double-patching but silently testing the wrong copy: fix
something, relaunch, and the surviving copy may still be the other one. The mod
author runs only the fake-ID dev install and does not subscribe to their own
mod. To test the published build as an end user, run `utils/uninstall-macos.sh`
first.
