# mod.io Publishing

How every Core Keeper mod is published to mod.io through the SDK's plugin.

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

The split follows what a field belongs to. Description and tags describe the
**mod**, so they live on the profile and `--profile-only` can fix them at any
time. A changelog describes a **release**, so mod.io stores it on the modfile —
which is why `--profile-only` cannot reach it and why a wrong release note used
to stay wrong until the next version.

`--changelog-only` therefore does what the plugin cannot: its API offers
`UploadModfile`, which creates a *new* modfile, and no way to edit an existing
one. So this mode reads the active modfile with the public game key, then
`PUT`s the new text with the plugin's own OAuth token, pulled out of the
internal `ModIO.Implementation.UserData` by reflection (editor code, outside
the Roslyn sandbox that forbids reflection in a mod's runtime sources; the
token is never logged or written to disk).

**It refuses unless the live modfile's version equals `CHANGELOG.md`'s topmost
entry.** Without that guard, a repo already sitting on an unreleased entry would
paste those notes onto the previous release. It also exits early when the text
already matches, so re-running costs nothing. Use it to correct a shipped
changelog; use a real release for anything that changes what the mod does.

- **One-time login:** open the Pugstorm Mod SDK window, use the "Log in" tab
  (email + security code). The mod.io plugin persists the session;
  batchmode publishes authenticate from it. The session expires after about
  a year — re-login through the window when that happens.
- **Version + changelog:** taken from the mod's `CHANGELOG.md`. The topmost
  `## [x.y.z]` entry is the published version; its body is the modfile
  changelog. There is no version field anywhere in mod source.
- **Async batchmode:** the mod.io calls are asynchronous, so `upload.sh`
  invokes Unity **without `-quit`** and `CLIPublishHelper` calls
  `EditorApplication.Exit` itself; a `timeout` guards a hung run.

### Mod dependencies → mod.io platform dependencies

On publish, `CLIPublishHelper` syncs the `.asset`'s `metadata.dependencies`
list (e.g. `CoreLib`) to the mod's **mod.io platform** dependency list
(`AddDependenciesToMod` / `RemoveDependenciesFromMod`) — a separate concern
from the loader-side `ModManifest.json` dependencies (which stay the loader's
source of truth). The step runs between the profile create/edit and the
modfile upload, so an unresolvable required dependency aborts before anything
is uploaded.

- **modName → ModId resolution.** The `.asset` references a dependency by its
  loader **name** (`CoreLib`); the mod.io API needs a numeric **ModId**. A
  self-populating cache `utils/modio-dependencies.json` (`{modName → modId}`,
  versioned) bridges this; its path is passed via the `.envrc` var
  `MODIO_DEPS_MAP` (set only by mods that declare dependencies). On a cache
  miss the helper runs a `GetMods` search (pagination params are **required** —
  `SetPageIndex`/`SetPageSize`, else error 20201), accepts the ID only on a
  single normalised-name match (case/space-insensitive), and writes it back to
  the cache (allowed even in `--dry-run`).
- **Failure severity follows the `.asset` `required` flag** (which is *not*
  transmitted to mod.io — the API has no per-dependency required attribute):
  an unresolvable **required** dependency aborts the publish; an unresolvable
  **optional** one logs a warning and is skipped.
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
  hardcoded value list — the game keeps adding `Game Version` values.
- **Configured values are validated before anything is changed.** mod.io accepts
  an unknown tag value and silently drops it, so a typo (`Quality of live`)
  aborts the publish with a message naming the bad value and the group's valid
  values, rather than vanishing.
- **A read failure degrades to additive, never to "remove everything".** If
  `GetTagCategories` or `GetMod` fails (or a group is missing from the live
  taxonomy), the helper logs a warning, adds the desired tags and removes
  nothing.
- The plan is logged per group before acting
  (`Tag sync plan [Type]: +[…] -[…]`); `--dry-run` logs it and stops there.
- `Asset` is never produced — these are script mods — so a hand-set `Asset` tag
  is treated as surplus and removed.

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
  all (Pugstorm's loader only walks the mod.io subscription path); the
  fake ID also keeps the dev build out of the real mod.io catalog sync.

**Dev/Prod coexistence:** never have both the fake-ID dev install and a real
subscription of the same mod active — the loader would load both copies and
double-apply Harmony patches. The mod author runs only the fake-ID dev
install and does not subscribe to their own mod. To test the published
build as an end user, first run `utils/uninstall-macos.sh` to remove the dev
install.
