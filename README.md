# Core Keeper Modding — Build & Publish

Shared build/publish tooling for every Core Keeper mod under this directory.
Project-wide conventions and SDK/runtime details live in `CLAUDE.md`.

## Build & install

All mods build through one shared copy of the build scripts in
`core_keeper/utils/` — `build.sh`, `link.sh`, `install-macos.sh`,
`upload.sh`, `uninstall-macos.sh`. The scripts
are mod-agnostic: each mod supplies its identity through `export`s in its own
`.envrc` (`MOD_NAME`, `MOD_NAME_ID`, `MOD_SUMMARY`, `FAKE_MOD_ID`,
`MOD_INSTALL_PATH`, `CK_MODIO_TYPE`). The scripts read everything from the environment and
never `source` anything themselves; they guard with `set -euo pipefail` +
`: "${VAR:?…}"`, so a missing variable aborts with a clear message.

### `.envrc` inheritance chain (parent → mod)

The machine-level shared values — `UNITY_BIN`, `SDK_PATH`, the
`CK_GAME_VERSION` default, `MODIO_DEPS_MAP`, `LOC_TABLE`, and the `ilspycmd`
PATH entry — live **once** in a gitignored `core_keeper/.envrc` (template:
the tracked `core_keeper/.envrc.example`, allowlisted via `!/.envrc.example`).
Each mod's `.envrc` inherits them and adds only its identity:

```bash
# top of every mod's .envrc
if command -v source_up_if_exists >/dev/null 2>&1; then
    source_up_if_exists          # direnv: walk up to core_keeper/.envrc
elif [ -f ../.envrc ]; then
    source ../.envrc             # manual `source .envrc` fallback
fi
```

Both load paths work: under **direnv** (hooked in the shell) `cd <mod>` loads
the mod `.envrc`, whose `source_up_if_exists` pulls in `core_keeper/.envrc` —
no manual `source` needed (`cd <mod> && ../utils/build.sh`). Without direnv,
the documented `source .envrc && ../utils/build.sh` still works via the
`source ../.envrc` fallback. Paths in `core_keeper/.envrc` must be **absolute**
— `source_up` sources it without changing `$PWD` (which stays the mod dir).
`CK_GAME_VERSION` is kept as one canonical list in `core_keeper/.envrc`; mods
inherit it and do **not** override it (a mod's `.envrc` exporting its own value
after the inherit block would win, but none currently do — keep the list in
sync in the parent `.envrc`). Each new/edited `.envrc` needs one `direnv allow`.

To build a mod, run `../utils/build.sh` from the mod repo root (with direnv
the env is already loaded; otherwise `source .envrc` first):

```bash
cd <mod-name>
source .envrc        # only needed without direnv; direnv auto-loads on cd
../utils/build.sh
```

When building from a **git worktree** (`REPO_ROOT/.worktrees/<branch>`, two
levels below the mod root), the shared scripts are reached via
`../../../utils/build.sh` (three levels up: `<branch>` → `.worktrees` →
`<mod>` → `core_keeper/utils`), not the normal mod-root `../utils/build.sh`.
The environment needs the same three-level correction and gives no warning
when it's missing: the mod `.envrc`'s manual-source fallback only tries
`../.envrc`, which from a worktree resolves to `<mod>/.worktrees/.envrc` and
doesn't exist, so every machine-level variable (`LOC_TABLE`,
`CK_GAME_VERSION`, `MODIO_DEPS_MAP`, …) stays unset while the mod's own
identity variables still load fine. Source the parent directly first, then
the mod's own `.envrc`: `source ../../../.envrc && source .envrc`. A missing
`LOC_TABLE` has already shipped a build whose localisation table came out
empty.

`build.sh` refreshes the SDK symlinks (`link.sh`), runs a Unity batchmode
build via `-executeMethod` (`<MOD_NAME>.Editor.CLIBuildHelper.Build`), then on
macOS auto-runs `install-macos.sh` to place the fresh build into the
fake-ID locations so the loader picks it up on next launch. Each script
resolves the mod repo from its first argument, defaulting to `$PWD`.

To publish a mod to mod.io, `source` its `.envrc` and run
`../utils/upload.sh` from the mod repo root. The script refreshes the SDK
symlinks and runs a Unity batchmode build via
`<MOD_NAME>.Editor.CLIPublishHelper.Publish`, which builds the mod and
drives the mod.io plugin to create/update the mod profile and upload a new
modfile. `upload.sh --dry-run` builds and validates without any writing
mod.io call.

A new mod.io profile is created **hidden**; review it on the website and
switch it to visible manually. The real mod ID is stored in the SDK-native
`<mod-name>/unity/<MOD_NAME>/Editor/<MOD_NAME>_modio.asset` — versioned in
git, so re-runs reuse the profile instead of creating a second one.

`utils/uninstall-macos.sh` is the counterpart to `install-macos.sh`: it
removes a fake-ID local dev install from the CrossOver bottle.

### Shared editor helpers and localisation tooling

The CLI editor helpers (`CLIBuildHelper`, `CLIPublishHelper`) and the
`LocalizationGenerator` live in `core_keeper/utils/` (namespace
`CoreKeeperModUtils`) and are symlinked into a mod's `unity/<Mod>/Editor/` by
`link.sh`. They are the **unconditional** build/publish path for every mod:
`build.sh` / `upload.sh` always invoke
`-executeMethod CoreKeeperModUtils.CLIBuildHelper.Build` /
`...CLIPublishHelper.Publish`.

**Every mod uses the shared helpers.** ItemChecklist was the pilot;
`faster-talents` and `disable-durability` were migrated; `caveling-divining-rod`
(added later) was set up on the pattern from the start. No mod keeps per-mod
`<Mod>.Editor.CLI*Helper` sources. Once the last opt-in mod had migrated the
former flag `USE_SHARED_EDITOR_HELPERS` was removed entirely (its per-mod
fallback path pointed at sources that no longer exist) — the helpers are now
unconditional. Each mod's `.envrc` sets `MOD_REPO_ROOT="$PWD"` (the shared
`CLIPublishHelper` reads it for the CHANGELOG lookup). Every mod except
`simple-crafting-pool-extender` is localised and also sets `LOC_YAML` /
`LOC_OUT` / `LOC_TABLE`; that one ships no `localization.yaml`, so the loc
generator is a no-op for it.

Also in `utils/`:
- **`ck-language-addresses.json`** — the CK language address→ISO table (13
  runtime languages), captured once via a runtime dump because
  `LanguageDataBlock`s are runtime-only and are not enumerable through the SDK
  editor API at build time. Required by `LocalizationGenerator`.
- **`LocalizationGenerator.cs`** — reads a mod's
  `localization/localization.yaml` and templates raw `.asset` YAML for each
  language (Option II: raw asset templating). Used by every localised mod (all
  but `simple-crafting-pool-extender`); ItemChecklist was the pilot.

`core_keeper/` is itself a git repo, but its `.gitignore` is an allowlist: it
tracks only the shared, machine-agnostic files — `utils/`, the docs
(`CLAUDE.md`, `README.md`, the two notes under `docs/`), the tooling config
(`.tool-versions`, `.envrc.example`, `.csharpierrc`, `.csharpierignore`,
`.pre-commit-config.yaml`, `.config/dotnet-tools.json`) and `.claude/skills`.
The mod repos and the SDK clone are independent repos and are deliberately
ignored so they are not embedded. The real `core_keeper/.envrc` (machine
paths) is gitignored; only its `.envrc.example` template is tracked.

## Formatting gate

Every repo here — each mod repo and `core_keeper` itself — runs a
formatting gate as a `pre-commit` **and** `pre-push` hook. It **checks and
blocks**; it never rewrites files behind your back. C# goes through
**CSharpier**, pinned per repo in `.config/dotnet-tools.json` with
`printWidth: 160` in `.csharpierrc`; in `core_keeper` the Python in `utils/`
additionally goes through **`ruff format`**.

`utils/new_mod.py` emits all three gate files (`.csharpierrc`,
`.pre-commit-config.yaml`, `.config/dotnet-tools.json`) as part of its
scaffold, so a freshly created mod repo already carries the gate — only the
one-time tool setup below is still needed.

A fresh clone needs two one-time commands:

```bash
dotnet tool restore                                          # pinned CSharpier
pre-commit install --hook-type pre-commit --hook-type pre-push
```

When a commit is rejected, format and retry — the hook tells you which files
it rejected:

```bash
dotnet csharpier format .        # C#
uvx ruff format .                # Python (core_keeper only)
git add -u && git commit …
```

Both formatters are scoped to the repo they run in. In `core_keeper` that
needs care, because the SDK clone and every mod repo sit inside it as
separate repos: `.csharpierignore` mirrors the `.gitignore` allowlist shape
(`/*` plus `!/utils/`) so a full-tree run cannot reach foreign sources. `ruff`
needs no equivalent, as it honours `.gitignore` itself.
