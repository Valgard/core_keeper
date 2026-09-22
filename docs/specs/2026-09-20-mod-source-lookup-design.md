# Mod Source Lookup — Design

- **Date:** 2026-09-20
- **Tool:** `utils/mod_source.py` (new, shared by every mod)
- **Status:** design, nothing built

## Problem

On 2026-09-19 eight subagents were dispatched to verify claims about CoreLib,
and 19 of 23 dispatches were not told where CoreLib's source lives. Seven fell
back to `find /`, with run times up to 12 h 49 min and roughly 12 % CPU between
them.

A full-filesystem scan is the worst possible fallback on this machine
specifically: several SMB shares are mounted under `/Volumes`, along with a
Time Machine backup volume holding millions of hard-linked entries. `find`
without `-quit` does not stop at the first hit, so even a mod that *is*
installed locally costs a complete traversal — and a mod that is *not*
installed costs the same traversal and finds nothing.

**The repository is not silent about this, and the honest gap is narrower than
it first looks.** [`docs/ck/reverse-engineering.md`](../ck/reverse-engineering.md) carries a section "Every
installed mod is readable source", states outright that the property is not
special to CoreLib, and gives the cache path; [`docs/ck/platforms.md`](../ck/platforms.md) repeats it
in its path table; `utils/server.sh` resolves it executably. What none of them
provides is the step from a **name** to the concrete `<modId>_<modfileId>` —
and that is the whole distance between "the path pattern is documented" and "an
agent can read CoreLib's source without searching for it".

## Acceptance criteria

The tool is finished when each of these holds. They are derived from the
originating request and from the decisions taken while designing; they are
recorded here so the spec is checkable without that conversation.

| # | Criterion |
|---|---|
| AC1 | A query naming an installed mod by **any** of its three names returns its source path, all three names, its mod id and its install state. A query naming a mod that is not installed returns its mod id and the way to obtain it. |
| AC2 | The output is usable in an agent dispatch unchanged: absolute paths, and no identifier the caller had to know beforehand. In particular no invocation requires a `modfileId`. |
| AC3 | The tool lives in `utils/`, runs under `uv run`, passes `ruff format --check`, and has tests under `utils/tests/` that run with `uv run pytest utils/tests`. |
| AC4 | A mod that is not installed can be fetched in one invocation, and its unpacked source is still at the path the output named **after the run finishes**. |
| AC5 | A query naming a mod **and** a file returns that file's full path without walking any directory outside that one mod. |
| AC6 | The mod.io title is a first-class entry point: no query presupposes knowledge of the internal name. |
| AC7 | A fake id declared by one of this workspace's mod repos is reported as an own mod; one declared by none is reported as a temporary foreign parking spot. |
| AC8 | No invocation traverses anything outside the four declared inputs. A mod that cannot be resolved ends in a message, never in a search. |

AC8 is the criterion the tool exists for; AC2 is the one that decides whether
it gets used.

## What was measured

Measured on 2026-09-20 against the live install, not recalled. Cache figures
are live state and will have moved since; they are recorded for the design
conclusions drawn from them, not as current fact.

| | |
|---|---|
| mod.io cache folders | 53 |
| of those, current per `state.json` | 52 |
| leftover folder with no `ModManifest.json` | 1 (`3177992_7710097`, superseded CoreLib) |
| installed mods **disabled** | 19 of 52 |
| installed mods with no `Scripts/` (asset-only) | 1 (`Scenes+`, internally `MoreScenes`) |
| mods in the whole mod.io catalogue for this game | **312** |
| catalogue fetch, full | 0.7–3.2 s, 2.0 MB raw, **~30 KB** reduced |
| sibling repos | 14, of which **13** are mod repos declaring a distinct `FAKE_MOD_ID`; `CoreKeeperModDocs` is not a mod |
| own mods with a fake-id dev build in the cache | **2 of 13** |
| own mods carrying their real `modId` in a tracked asset | **13 of 13** |

Three findings shaped the design more than the rest.

**The cache is live state.** It changed during the design session itself, from
52 folders to 53, because a parallel session side-loaded a mod. Nothing derived
from it may be cached.

**Name resolution has a direction, and the useful direction is the opposite of
the obvious one.** Resolving an *internal* name (`ModManifest.json`'s `name`,
which is what a mod's own code and a `dependencies:` entry use) against the
catalogue succeeds for only 88 % of installed mods, and the remaining 12 % are
not a normalisation problem:

| internal name | is called on mod.io |
|---|---|
| `NameChests` | More Labels |
| `MoreScenes` | Scenes+ |
| `DummyMod` | Beating Dummy |
| `ConveyorTunnelMod` | Conveyor Tunnels |
| `AutoPlant3` | AutoPlant for 1.2.1.5 |
| `FastSmelter1215` | Fast Smelter for 1.2.1.5 |

No string transformation turns `NameChests` into "More Labels". But the name a
person actually knows and types is the mod.io one — and starting from *that*,
every one of these resolves immediately (AC6).

**A fake id is the wrong handle for an own mod.** Only 2 of 13 own mods have a
dev build in the cache at all, while all 13 carry their real `modId` in a
**tracked** asset. See the decision below.

## Decisions

### Search every name space at once, and report what is known

A mod carries three names, and they routinely differ:

| Name space | Source | Example |
|---|---|---|
| internal | `ModManifest.json` → `name` | `NameChests` |
| mod.io title | `state.json` → `modObject.name`, or the catalogue | More Labels |
| slug | `modObject.name_id` | morelabels |

One normalised index over all three yields **368 keys, 10 of them ambiguous
(2.7 %)**, and the ten break down as:

| Cause | Count |
|---|---|
| an artefact of a naive normaliser — **one** key (the empty string) holding three Cyrillic-titled mods | 1 |
| an own mod's dev build beside its own subscription | 2 |
| a foreign mod parked under a fake id beside its catalogue entry | 1 |
| genuine collisions between distinct mods (`AutoFish`, `ToolResizer`, `PouchExpansion`, `ExtendedCraftingRange`, `AutoPlant3`, `test`) | 6 |

The artefact is why normalisation is Unicode casefold plus alphanumeric-only
rather than an `[^a-z0-9]` filter: the filter collapses every non-Latin title
onto one key. Fixing it removes that key and adds the three titles as keys of
their own.

The output reports every name it knows, because the entry name and the needed
name differ: you arrive with "More Labels" and leave needing `NameChests` for a
Harmony patch or a manifest dependency. For a mod that is **not** installed the
internal name is not knowable — it exists only inside a `ModManifest.json` — so
the output says so rather than omitting the line silently.

### Never guess between genuine candidates

On a real ambiguity the tool exits non-zero and prints every candidate with its
id, names and install state. It does not pick the best match.

This follows the position [`docs/publishing.md`](../publishing.md) already takes for Steam
dependencies: a display title is not an identity, and more than one item can
carry the same one, so a name match can silently resolve to the wrong thing.
The failure mode is expensive and quiet — an agent reads a different mod's
source and reports confidently about it. At six genuinely affected keys out of
368, the cost of asking is negligible.

The self-populating half of `utils/modio-dependencies.json` is the model for
the other side: a single unambiguous match is accepted, and a resolution
confirmed by a human is remembered.

### A catalogue-only hit is provisional, and the download settles it

`AutoPlant3` is the case that shows why. Two mods normalise onto that key: the
installed `6163009` via its **internal** name, and `6007069` ("Auto Plant 3")
via its **title and slug**. Because the first is installed, its manifest is
present, the index sees both, and the no-guessing rule fires.

Were it not installed, there would be no internal name in the index, one
apparently unambiguous hit would remain, and the tool would quietly answer with
the wrong mod. The uniqueness depends on what happens to be installed, which is
not a property anything should rest on.

So a hit that comes from the catalogue alone is labelled as provisional, with
the reason (`internal name unknown — it exists only in a manifest`). And since
`--download` fetches exactly the manifest that would settle it, the tool
compares the downloaded `name` against the query afterwards and reports a
mismatch. That turns the one case that would otherwise pass unnoticed into a
message, for the price of one string comparison.

### `state.json` decides which folder is current, never the folder name

The cache keeps superseded folders. `3177992_7710097` and `3177992_7845185`
are both CoreLib; only the second is live. Picking the higher `modfileId` is a
guess that happens to work, and `state.json` answers it outright via
`mods[<modId>].currentModfile.id`. `utils/server.sh` already resolves it this
way and documents the same CoreLib pair as the reason.

### An own mod is identified by its real mod id, not by its fake one

An own mod's source lives in its repository; the cache holds only a built copy.
So the tool has to recognise which mods are ours — and the obvious handle is
the wrong one. `FAKE_MOD_ID` in a repo's `.envrc` identifies only a mod with a
**dev build installed**, which is 2 of 13; it is also gitignored, so it is
absent from a fresh checkout.

The real `modId` in `unity/<Mod>/Editor/<Mod>_modio.asset` is present for all
13 and is **tracked**. That is the identity. `FAKE_MOD_ID` is still read, but
only to recognise the dev-build folder for a secondary line, and its absence
costs that line rather than the classification.

This also dissolves what would otherwise be an ambiguity: an own mod's
subscription and its dev build are two cache entries under one name, and with
both ids mapping to the same repository they are two locations for one mod
rather than two candidates to choose between.

A fake id that **no** repo claims is a foreign mod parked locally for testing —
during the design session `9999986` appeared holding General Mod Config Menu,
placed there by a parallel session. Such an entry is **temporary**
(`utils/install-macos.sh` warns that a mod.io sync deletes fake entries), so it
is reported with that caveat and with the download route named as the durable
alternative. Reporting it as a plain location would hand out a path that stops
existing (AC7).

### Mirror the catalogue, never the cache, and keep both outside the repository

The catalogue is 312 entries and reachable in a second or two; reduced to `id`,
`name`, `name_id` and `modfile` it is about 30 KB. Mirroring it makes lookups
offline once the mirror exists, deterministic, and able to match slug and
substring — none of which the live API offers. Measured against the live
search: `_q=General Mod Config Menu` returns 8 results with the right one
fifth, while `_q=GeneralModConfigMenu` and `_q=generalconfigmenu` both return
nothing, because `_q` matches the title alone.

The cache is the opposite case and is read fresh on every invocation.

Both the mirror and anything `--download` fetches are **derived runtime state
from a foreign service**, not data of this repository, and live outside it
under `CK_MOD_SOURCE_CACHE` (default `~/Library/Caches/ck-mod-source`). Placing
the mirror in `utils/` would have tracked it by default — `.gitignore` excludes
everything with `/*` and re-includes the whole directory with `!/utils/` — so
every refresh would be a committable 30 KB diff that says nothing about the
project. The tracked data files in `utils/` are the opposite kind: curated, and
recording decisions. A resolution a human confirmed belongs there; a mirror of
someone else's catalogue does not.

Cleanup only ever removes this tool's own subdirectories, never the
configured directory wholesale.

### Reuse what `steam_backfill.py` already does, at the right granularity

`utils/steam_backfill.py` reads the read-only game key out of the SDK's mod.io
config asset (`modio_config`) and builds an authenticated download URL
(`download_url`). Both are directly reusable, and both are why the **SDK clone**
is an input of this tool: the catalogue fetch needs that key too.

`download_release` is the partial case, and the spec should not pretend
otherwise: it takes a `Release` dataclass carrying backfill-specific fields, so
what is reused is its body — fetch, verify md5, unpack — rather than its
signature. The md5 check is the part that matters and is kept.

## Design

### Inputs

| Source | Read | Holds |
|---|---|---|
| mod.io cache, `$CK_BOTTLE_PATH/drive_c/users/Public/mod.io/5289/mods/` | every run | folders, `ModManifest.json` per mod |
| `state.json` beside it | every run | current modfile per mod, mod.io title/slug, subscribed and disabled sets |
| sibling mod repos | every run | `<Mod>_modio.asset` → real `modId`; `.envrc` → `FAKE_MOD_ID`; `unity/<Mod>/` source |
| SDK clone, `$SDK_PATH` | when the catalogue is fetched | mod.io server URL, game id, read-only game key |
| catalogue mirror, `$CK_MOD_SOURCE_CACHE/catalogue.json` | every run, refreshed on request | 312 × `id`/`name`/`name_id`/`modfile` |

`CK_BOTTLE_PATH` resolves exactly as `server.sh` does, defaulting through
`CK_BOTTLE_NAME`. `SDK_PATH` is already set by the parent `.envrc`.
`CK_MOD_SOURCE_CACHE` is the one new variable, with a default that works unset;
it is documented in `.envrc.example` like its siblings.

A sibling directory without a `<Mod>_modio.asset` is not a mod repo and is
skipped — `CoreKeeperModDocs` is the standing example.

### Resolution

1. Normalise the query (Unicode casefold, alphanumeric only).
2. Look it up in the union index over internal name, mod.io title and slug,
   built from the cache, `state.json`, the repos and the catalogue mirror.
3. Map every hit to its owning mod: cache entries and repo assets that resolve
   to the same mod id — real or fake — are one mod, not several candidates.
4. One mod → resolve. Several → print candidates, exit non-zero. None → offer
   substring matches as candidates; still none → exit non-zero saying so.
5. Classify: own mod (a repo claims the id) → repository; installed → cache
   folder; fake id no repo claims → cache folder, flagged temporary;
   catalogue only → not installed and **provisional**, offer `--download`.

### Output

Human-readable by default, because its purpose is to be pasted into a dispatch
prompt (AC2). `--json` emits the same facts for programmatic use. Every report
names the mod id, the install state, the source path and each name the tool
could establish — stating explicitly when the internal name is not among them.
An installed mod also gets its `.cs` count, taken from the manifest's file list
rather than from a directory walk.

### File mode

`mod_source.py <mod> <file>` answers with the full path of a single source
file. This is the second half of the original failure: telling an agent the
folder still leaves it to find `ConfigScope.cs` inside — and an agent that
starts searching is the behaviour this tool exists to remove (AC8).

For an installed mod the answer comes from the manifest's own file list, with
no directory traversal at all. For an **own** mod there is no manifest —
`ModManifest.json` is build-generated and no repo contains one — so the answer
comes from walking that mod's `unity/<Mod>/` directory, which is small, local
and bounded. A substring match is enough (`ConfigScope` →
`Scripts/Scripts/Util/Data/ConfigFile/ConfigScope.cs`), with the same
no-guessing rule when several files match.

### Failure modes

| Situation | Behaviour |
|---|---|
| bottle path missing | exit non-zero, name the path and the variable that overrides it |
| catalogue mirror absent | fetch it once, then proceed |
| catalogue fetch fails, or `SDK_PATH` is unset | proceed with cache and repos only, warn that uninstalled mods cannot be resolved |
| mod installed but asset-only (no `Scripts/`) | report as found, state that it ships no source |
| folder without `ModManifest.json` | ignored as superseded, mentioned as a hint when it shares a mod id with the hit |
| a mod repo has no `.envrc` | its dev-build folder is not linked to it; the classification via `<Mod>_modio.asset` is unaffected |
| downloaded manifest's name does not match the query | report the mismatch — this is the provisional-hit check |
| download md5 mismatch | fail loudly, reusing `steam_backfill`'s existing check |

### Making it reachable

A tool nobody reaches for changes nothing, and the original failure was not
that the paths were undocumented — they are — but that nobody thought of them
while dispatching. So the change is not only the tool:

- `CLAUDE.md` gains a short rule: before dispatching an agent at another mod's
  source, resolve the path and **put it in the dispatch**.
- [`docs/ck/reverse-engineering.md`](../ck/reverse-engineering.md) gains a pointer at its path table, which
  names the `<modId>_<modfileId>` pattern but not which numbers belong to which
  name.
- `README.md` gains the usual line among the other `utils/` tools.

### Testing

`utils/tests/test_mod_source.py`, following the house pattern: fixtures build a
synthetic cache tree, `state.json`, repo assets and catalogue in `tmp_path`, so
nothing depends on the live install (AC3). The cases that earn their keep are
the ones the measurements produced — a superseded folder beside the current
one, a name that resolves only via slug, a genuine two-mod collision, an own
mod with and without a dev build, a fake id no repo claims, a sibling directory
that is not a mod repo, an asset-only mod, a catalogue-only hit whose
downloaded manifest disagrees, and a Cyrillic title that must not collapse onto
the empty key.

## Out of scope

- **Anything about which mods the game will load.** `server.sh relink` answers
  that and applies filters (subscribed, enabled, version-compatible) that are
  wrong here: 19 of 52 installed mods are disabled and their source is still a
  perfectly good answer.
- **Searching source content.** This resolves locations; grep does the rest.
- **Decompiled game source.** `~/Projects/checkouts/CoreKeeperDecompile/` is a
  different question with a different answer, and its CoreLib copy is a
  snapshot that can age behind the installed one.
