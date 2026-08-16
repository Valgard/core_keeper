# Design: `utils/new_mod.py` — deterministic new-mod scaffold generator

Date: 2026-06-28
Status: approved (brainstorming) — pending user spec review
Scope: shared `core_keeper/utils/` tooling

## Problem

Creating a new Core Keeper mod today means running the SDK's "Create New Mod"
wizard inside the Unity Editor (`ModBuilderWindow.CreateNewMod`). That is slow,
locks the shared SDK project, requires the Editor to be open, and — critically
— produces only a fraction of what a usable mod in this repo needs. The wizard
emits just the `.asset` (ModBuilderSettings), the runtime `.asmdef`, the folder,
and `.meta` GUIDs. (Its template-zip step is a no-op here: `ModTemplate.zip`
does not exist in this SDK clone.) The whole convention layer that
`build.sh`/`upload.sh` depend on — the `Editor/` folder, `_modio.asset`, the
IMod bootstrap, `.envrc`, `CHANGELOG.md` — is hand-grown, not wizard output.

We want a single deterministic command that produces a **fully buildable and
publishable** mod skeleton without opening the Editor.

## Goal

`utils/new_mod.py <kebab-name>` creates a new sibling mod repo under
`core_keeper/<kebab-name>/` that `build.sh` builds and `upload.sh` publishes
with no manual Editor step, matching the three-level naming convention and the
GUID rules that otherwise cause silent failures.

## Non-goals

- **No cloning.** The generator constructs each artifact from data/templates in
  code; it never copies an existing sibling mod and find/replaces.
- **No content/`Data/` mods.** The one wizard step not reproducible in pure
  Python is `ScriptableDataEditorUtility.AddContext` (a compiled-DLL call that
  registers a `Data/` folder context). It is only needed for item/content mods.
  Script mods (Harmony patches) need no `Data/` folder — `faster-pet-talents`
  has none. A future `--data` mode would be a separate extension.
- **No prose docs.** `CLAUDE.md` is left to `/init`; `README.md` and
  `modio-description.md` are omitted (not build/publish-critical, and a generic
  template is dead prose the author replaces immediately).
- **No mod-specific logic.** `ModConfig.cs` and the Harmony patch class are
  omitted; the author writes those during real modding. The IMod bootstrap
  alone builds and loads.

## CLI

```
utils/new_mod.py <kebab-name>
                 --summary "<text>"          # REQUIRED — MOD_SUMMARY / mod.io listing summary
                 [--name <Pascal>]           # override derived PascalCase MOD_NAME
                 [--display-name "<Title>"]   # override derived Title displayName
                 [--corelib]                 # add CoreLib loader dependency
                 [--dry-run]                 # print plan, write nothing
```

`--summary` is mandatory: every published mod needs a one-line summary, so
forcing it at creation time prevents an empty `MOD_SUMMARY` slipping into a
later publish. `argparse` enforces it (`required=True`); a missing `--summary`
aborts with a usage error before anything is written.

- `<kebab-name>` is the single source of identity. Derivation:
  - `MOD_NAME` (Pascal) = each `-`-segment capitalized, joined: `faster-pet-talents` → `FasterPetTalents`
  - `displayName` (Title) = each segment capitalized, space-joined: `Faster Pet Talents`
  - Any `--name` / `--display-name` override replaces its derived value.
- Output dir: `core_keeper/<kebab-name>/` (sibling to existing mods). The script
  resolves the parent dir as its own location's parent (`utils/`'s parent).

## Naming convention (enforced)

Repo (kebab) + Namespace/`MOD_NAME` (Pascal) + `displayName` (Title) must match.
The single-source-derivation makes inconsistency impossible unless an override
is deliberately used.

## Generated file manifest

Two categories. **Computed** = built from data (dynamic GUIDs, live DLL scan) —
this is the wizard logic re-implemented, not a template. **Parametric** = a
short inline f-string with the name substituted.

```
<kebab>/
├── .envrc                  parametric (gitignored; real values so link.sh runs)
├── .envrc.example          parametric (tracked template)
├── .gitignore              parametric (mod name woven into Editor-helper ignores)
├── CHANGELOG.md            parametric (## [0.1.0] – Unreleased)
└── unity/
    ├── <Mod>.asset         computed  (ModBuilderSettings YAML)
    ├── <Mod>.asset.meta    computed  (NativeFormatImporter, mainObjectFileID 11400000)
    ├── <Mod>.meta          computed  (folder meta, folderAsset: yes)
    └── <Mod>/
        ├── <Mod>.asmdef        computed  (14 Unity refs + live-scanned game DLLs)
        ├── <Mod>.asmdef.meta   computed  (AssemblyDefinitionImporter)
        ├── <Mod>Mod.cs         parametric (IMod bootstrap)
        ├── <Mod>Mod.cs.meta    computed  (minimal 2-line guid meta)
        └── Editor/
            ├── Editor.meta                     computed (folder meta)
            ├── <Mod>.Editor.asmdef             parametric (fixed refs, name substituted)
            ├── <Mod>.Editor.asmdef.meta        computed
            ├── <Mod>_modio.asset               computed (modId 0, modSettings cross-ref)
            ├── <Mod>_modio.asset.meta          computed
            ├── logo.png                        computed (embedded placeholder PNG bytes)
            └── logo.png.meta                   computed (TextureImporter block, fresh guid)
```

The three Editor-helper sources (`CLIBuildHelper.cs`, `CLIPublishHelper.cs`,
`LocalizationGenerator.cs`) are **not** generated by the script: `link.sh`
creates them as symlinks into `utils/`, and the Editor generates their `.cs.meta`
on first import. Both the symlinks and their `.meta` are gitignored ("no asset
references them by GUID"), so they are working-tree-only and outside the
script's responsibility — but the generated `.gitignore` must still list them.

Finalization: `git init` + initial commit, then `utils/link.sh <path>` (creates
the SDK symlinks and the Editor-helper `.cs` symlinks into `utils/`).

## GUID strategy (the correctness core)

Every `.meta` `guid` is a fresh `uuid4().hex` (32-hex), **except** these rules:

| Field | Rule | Reason |
|---|---|---|
| every `.meta: guid:` | fresh `uuid4().hex` | Unity asset identity; must be unique |
| `.asset` `m_Script.guid` | **verbatim** `bc43e4983a160e543856e5ba0421c9e1` | binds the SO to the SDK's `ModBuilderSettings` class |
| `_modio.asset` `m_Script.guid` | **verbatim** `d83df2ae64ce1e94f9c006b9d326bf02` | binds to the SDK's modio-settings class |
| `.asset` `metadata.guid` | **fresh, unique** `uuid4().hex` | a collision triggers the loader's "Data block loader already added" crash |
| `_modio.asset` `modSettings.guid` | **internal cross-ref** = the freshly-generated `<Mod>.asset.meta` guid | the modio object points at this mod's ModBuilderSettings asset |

The two verbatim SDK script GUIDs are constants in the script. They are
SDK-clone-stable (every existing mod shares them); if a future SDK update
changes them, the constants are the single edit point.

## Runtime `.asmdef` DLL scan

`precompiledReferences` is **not** a frozen blob. The script scans
`$SDK_PATH/Assets/Plugins/CoreKeeper` and `$SDK_PATH/Assets/Plugins/CoreKeeperModSDK`
recursively for `*.dll`, takes basenames, sorts them — exactly as the wizard
scans `gameAssemblyPath` + `sdkAssemblyPath`. This stays correct across game
updates (new DLLs are picked up automatically). The 14 Unity engine references
(`Unity.Burst`, `Unity.Entities`, … `PugMod.SDK`) are a hardcoded constant list,
matching `ModBuilderWindow.cs:77-90`.

`$SDK_PATH` is read from the parent `core_keeper/.envrc` (the machine-shared
value). The generated mod `.envrc` does **not** redefine it — it inherits via
`source_up_if_exists`, like every existing mod.

## `.envrc` / `.envrc.example`

`.envrc.example` (tracked) mirrors the existing template: inherits the parent
via `source_up_if_exists`, then defines mod identity vars. `.envrc` (gitignored)
is the same with real values filled, so `link.sh` and `build.sh` work
immediately. Identity vars: `MOD_NAME`, `MOD_NAME_ID`, `MOD_SUMMARY` (from the
required `--summary`), `FAKE_MOD_ID`,
`MOD_INSTALL_PATH` (`$HOME/Library/Caches/<kebab>-build/`),
`MOD_REPO_ROOT` (`$PWD`).

## `FAKE_MOD_ID` allocation

Fake mod.io IDs count downward from 9999999. The script scans sibling
`*/.envrc.example` files for `FAKE_MOD_ID=` values and picks `min(found) − 1`
(currently → 9999992). If none found, default 9999999.

## `--corelib`

When set, the `.asset` `metadata.dependencies` list gains
`- modName: CoreLib` / `required: 1`, which flows into the built manifest and is
synced to the mod.io platform dependency list at publish. Default: empty
dependencies.

## Placeholder logo

A small valid PNG embedded as a constant byte blob (decoded and written), paired
with the captured `TextureImporter` `.meta` (fresh guid). Avoids a missing-asset
reference in `_modio.asset`/build. No image library dependency — pure stdlib.

## Error handling / idempotency

- Abort if `core_keeper/<kebab>/` already exists (no overwrite).
- Validate `<kebab-name>` matches `^[a-z0-9]+(-[a-z0-9]+)*$`.
- Require `$SDK_PATH` resolvable (from parent `.envrc` or env) and its
  `Assets/Plugins` present; otherwise fail with a clear message (the DLL scan
  needs it).
- `--dry-run` prints the full file plan and derived values, writes nothing.
- `git init` + `link.sh` run only on a real (non-dry) run; a `link.sh` failure
  is surfaced but the generated files are left in place.

## Dependencies

Python standard library only: `argparse`, `pathlib`, `uuid`, `re`,
`subprocess` (git, link.sh), `base64`/`zlib` (placeholder PNG). No third-party
packages, consistent with the existing `utils/` shell-first tooling.

## Testing

- `--dry-run` snapshot of the planned tree + derived names for a sample kebab
  input.
- A real run into a temp sibling, then `build.sh` against it, asserting the
  build produces a manifest with non-empty `files` (the SourceAssetDB-reset
  caveat for first builds of a newly-linked mod applies — documented separately).
- GUID assertions: all `.meta` guids unique; the two `m_Script` guids verbatim;
  `_modio.asset` `modSettings.guid` equals `<Mod>.asset.meta` guid;
  `metadata.guid` distinct from every sibling mod's.

## Known limitation

`ScriptableDataEditorUtility.AddContext` (the wizard's `Data/`-context
registration) is not replayable in pure Python. Out of scope — script mods do
not need it. Documented so a future `--data` mode knows what it must add (likely
by driving the Editor headless for that one step).
