# CLAUDE.md — Core Keeper modding (shared)

Parent-level guidance inherited by every Core Keeper mod project under this
directory. Each mod also has its own `CLAUDE.md` with mod-specific detail
(patch targets, classes, build scripts). This file holds **only** what is
true for *all* mods built against Pugstorm's `CoreKeeperModSDK` on this
machine — change it only when an insight is genuinely mod-agnostic.

## Directory layout

- `CoreKeeperModSDK/` — the Pugstorm SDK clone, **shared** by every mod. Its
  own git repo. Mods do not vendor a private SDK copy.
- `<mod-name>/` — one directory per mod, each its own git repo. Currently:
  `disable-durability/`, `faster-talents/`, `faster-pet-talents/`,
  `item-checklist/`, `caveling-divining-rod/`, and
  `simple-crafting-pool-extender/`.

A mod keeps **every file the Unity Editor generates for it** — `.cs`
sources, `.asmdef`s, the ModBuilderSettings `.asset`, and all `.meta` GUID
carriers — in a `unity/` directory that mirrors the SDK's `Assets/` tree
1:1. Otherwise those files exist only as untracked files inside the shared
SDK clone — one `git clean` or re-clone away from loss.

`utils/link.sh` symlinks that mirror into `CoreKeeperModSDK/Assets/`: one
**directory** symlink for the mod folder — which captures every current and
future Editor-generated file, so nothing has to be wired up by hand — plus
file symlinks for any Assets-level files beside it. The symlinks encode
absolute paths, so they dangle after a worktree switch or repo move;
`utils/build.sh` re-runs `link.sh` on every build so this self-heals.

## Required setup (per machine / per SDK clone)

- **Unity Editor `6000.0.59f2`** — exact patch version, pinned in the SDK's
  `ProjectVersion.txt` (the SDK `README.md` is one patch behind — do not trust
  it). Install via Unity Hub with **Linux Build Support (Mono)** and, on
  macOS, **Windows Build Support (Mono)**.
- **`CoreKeeperModSDK` clone** — the wizard's "Create New Mod" + "Update Game
  Files" must be run once.
- The Unity Editor **locks the project** — it must be closed during any
  `-batchmode` build.
- **While the user is actively in the Unity Editor, do NOT edit or write files**
  in the mod or SDK tree — restrict to read-only inspection (`prefab_query.py`,
  `grep`/Read). Concurrent file writes collide with the Editor's own saves /
  reserialization (it may overwrite or be clobbered by the assistant's edit).
  Wait until the user closes the Editor and confirms ("done") before making any
  file mutation.
- **`corekeeper-patch` applied to the installed game's `PugMod.Loader.dll`** —
  required on macOS / CrossOver hosts. Two IL patches: (Patch 1) fixes the
  Wine `Directory.Delete` failure on stale `ModLoader/<ModName>/Scripts/`,
  (Patch 2) forces `CultureInfo.DefaultThreadCurrentUICulture =
  InvariantCulture` so Roslyn doesn't fail compiles by chasing the missing
  `de-DE` satellite assembly. Every Core Keeper update reverts the DLL to
  stock — re-apply after each update. Rationale + canonical commands in
  the `corekeeper-roslyn-locale-bug` memory.

## SDK quirks (apply to every mod)

### macOS Editor — Steamworks compile errors
A fresh SDK clone fails to compile on a macOS Editor host with
`CS0246: ... 'Steamworks'`. The SDK ships Steamworks DLLs gated to Windows/
Linux Editors only; neither loads on macOS. Fix: enable
`Assets/Plugins/CoreKeeperModSDK/Facepunch.Steamworks.Posix.dll.meta` for
`OS: AnyOS`. One-time per SDK clone — see
`disable-durability/docs/research/macos-sdk-steamworks-fix.md`.

### Manifest fields — edit the `.asset`, not `ModManifest.json`
A mod's `ModManifest.json` is **build-generated** from its ModBuilderSettings
`.asset` (`unity/<Mod>/<Mod>.asset`, the `ModMetadata` block: `name`,
`displayName`, `requiredOn`, `dependencies`, …). The build writes the real
manifest (with computed file GUIDs + AssetBundle entries) into the output dir;
the loader reads *that* via `JsonUtility.FromJson<ModMetadata>`. A hand-authored
repo `ModManifest.json` is the **wrong schema** (`name_id`/`version`/
`modDependencies` keys are silently ignored on load) and is read by nothing —
do **not** keep one. So edit manifest fields directly in the `.asset` YAML's
`metadata:` block:
- The SDK mod-settings Editor UI is unreliable for `displayName` (cannot be set
  through the GUI) and `requiredOn` (choosing "Client and Server" writes `-1`
  / "Everything"). Set `displayName:` and `requiredOn: 3` (ClientAndServer)
  directly in the `.asset`.
- Mod dependencies (e.g. CoreLib) live in the `.asset`'s `dependencies:` list
  (`- modName: CoreLib` / `required: 1`) and flow into the built manifest.

The published mod.io listing does **not** read the manifest either: profile name
← `metadata.displayName` (fallback `metadata.name`) — so the human title
"Item Checklist" can differ from the internal identity "ItemChecklist"; summary
← `MOD_SUMMARY` env, version + changelog ← `CHANGELOG.md`, modId ←
`<Mod>_modio.asset`, version tag(s) ← `CK_GAME_VERSION` env — a
**space-separated list** of one or more game versions, each published as its
own compatibility tag (all in `utils/CLIPublishHelper.cs`).

### Runtime asmdef from the wizard
The "Create New Mod" wizard emits the mod's runtime `.asmdef` already
populated with the full game-DLL reference set (`Pug.Other.dll`,
`0Harmony.dll`, `PugMod.SDK.Runtime.dll`, …). Mod code compiles against game
types and Harmony out of the box — no manual reference editing is needed.

## Runtime constraints (apply to every mod's code)

### RoslynCSharp sandbox — no System.IO
Mods ship `Scripts/*.cs` and are compiled at load time inside a default-deny
sandbox. `System.IO.*`, `System.Diagnostics.Process`, reflection-emit and
similar BCL surface fail the compile on first reference (`mod load error:
CompileFailed`). Either avoid those APIs (hardcode what would otherwise live
in a runtime `config.json`) or set `skipSafetyChecks: true` in
`ModManifest.json` to disable the sandbox entirely — acceptable for
personal-use mods, at the cost of whatever the safety checks guarded.

### Burst-compiled systems are not Harmony-patchable
A DOTS system whose `OnUpdate` is Burst-compiled cannot be intercepted by
Harmony. Call `BurstDisabler.DisableBurstForSystem<TSystem>()` in
`IMod.Init()` to move the system off Burst *before* the patch needs to bind.
This works for **both** `SystemBase` (`OnUpdate()`) and `ISystem` structs
(`OnUpdate(ref SystemState)` — the prefix binds with no "Undefined target
method"; verified in `faster-talents`/`faster-pet-talents`). To scale an ECS
value that flows from a (possibly Burst) producer into a Burst-consumed
component/buffer, don't patch the managed producer — Burst callers bypass the
IL patch — but Burst-disable the **consumer** system and pre-inflate the
pending component data in its `OnUpdate` prefix (see the
`reference_ck_xp_grant_architecture` memory).

### IMod lifecycle
`IMod` (namespace `PugMod`) has five methods: `EarlyInit`, `Init`,
`ModObjectLoaded`, `Shutdown`, `Update`. `[HarmonyPatch]` classes are
**auto-discovered** by the loader — no manual `Harmony.PatchAll()` call. The
bootstrap `IMod` class and the patch class are conventionally separate files.

### Editor-only asmdef
`ModBuilder` / `ModBuilderSettings` are editor-only. A combined runtime+editor
asmdef cannot reference an editor-only one, so a CLI build helper (for
`unity -batchmode -executeMethod`) needs its own `*.Editor.asmdef`.

## macOS / CrossOver — distribution & loader

Fake-ID dev install, the incompatible-mod dialog, `state.json`/`config.json`
surfaces, and CrossOver/Wine specifics — see @docs/macos-crossover-loader.md.

## Build pattern (shared `utils/`)

The shared `utils/` build/publish scripts and the `.envrc` inheritance chain
are documented in `README.md` (§ Build & install). Human-facing build/publish
instructions live there.

- **Concurrent build/publish locks the shared SDK project for every session.**
  All mods share one `CoreKeeperModSDK` clone, so any session's batchmode
  build/publish takes the SDK project lock (`UnityLockfile`). If a build aborts
  on a held lock, another session's `build.sh`/`upload.sh` is running — **wait
  for the lock to release (poll), do NOT kill it.** A killed mid-flight
  `CLIPublishHelper.Publish` can leave the mod.io profile/modfile partially
  uploaded; the `timeout 600` wrapper already bounds a genuinely hung run.

## mod.io publishing (applies to every mod)

Publishing flow, dependency sync, and the three mod IDs — see @docs/publishing.md.

## Logo / branding (family style)

Every mod ships a square mod.io profile logo at `unity/<Mod>/Editor/logo.png`,
and they all share one deliberate visual identity — match it for any new mod.

**Shared DNA (all seven existing logos):**
- A single, centred **hero object in teal / petrol-green** with **gold / brass
  accents** and a thick dark outline — hand-painted "sticker" concept-art,
  **not** pixel-art.
- A warm **golden radial glow** behind the subject and scattered **4-point
  sparkles**.
- Square (1:1), 1024².

**Per-mod "gesture":** each logo adds one small gold sub-symbol that hints at
the mod's purpose — reuse arrow-ring (reusable-cattle-box), infinity on crossed
tools (disable-durability), checkmarks + "?" (item-checklist), fanned cards +
"+" (simple-crafting-pool-extender), star + cubes (faster-talents), paw + cube
(faster-pet-talents), crossed rods + orb (caveling-divining-rod). Invent a
fitting gesture for the new mod rather than copying one.

**Generation workflow** — the `generate_images.py` script from the **blogs**
repo's `editorial-workflow` skill (Gemini "Nano Banana Pro"; `GEMINI_API_KEY`
comes from the blogs repo's `.envrc`; run via `uv run`). Three stages produce
the transparent `Editor/logo.png`:

1. **White candidates.** Generate ~4 candidates on a **plain white background**.
   Pass **two polished sibling logos as `-ref`** (palette + style anchors, e.g.
   reusable-cattle-box + caveling-divining-rod) and describe the **form** in the
   prompt. Output lands in `<mod>/sources/logo-white-{N}.jpeg`.
   ```bash
   cd <blogs-repo> && source .envrc        # exports GEMINI_API_KEY
   uv run .claude/skills/editorial-workflow/generate_images.py \
     --article-dir <mod-repo> --name logo-white -ar 1:1 -r 1K -c 4 \
     -ref <siblingA>/Editor/logo.png -ref <siblingB>/Editor/logo.png \
     "<hand-painted CK-sticker prompt: hero object + teal/gold + golden glow + \
       4-point sparkles + plain white background>"
   ```
2. **Black versions — NATIVE, not matted.** For each chosen white candidate,
   re-run with **that white image as `-ref`** and a minimal prompt ("replace the
   white background with pure black #000000; keep everything else unchanged"),
   `--name logo-black --start-index N --count 1` → `logo-black-{N}.jpeg`.
3. **Transparify (local, scriptable).** Run `utils/transparify.py` on the
   matching white + black pair to recover the transparent PNG; copy the chosen
   candidate to `unity/<Mod>/Editor/logo.png`.
   ```bash
   python3 utils/transparify.py \
     -w "<mod>/sources/logo 3 - white background.jpeg" \
     -b "<mod>/sources/logo 3 - black background.jpeg" \
     -o "<mod>/sources/logo 3.png"
   ```
   `utils/transparify.py` is a faithful **1:1 port** of transparify.app's
   client-side algorithm (transparify.app has **no API**): alpha is one minus the
   normalised Euclidean white↔black distance, colour is un-premultiplied (`B/a`)
   above a `0.01` alpha threshold. Validated against transparify.app's own output
   — **alpha bit-identical**, RGB within JPEG-decoder noise. Pure Pillow (no
   numpy); tested in `utils/tests/test_transparify.py`.

**Candidate file naming** (in `<mod>/sources/`, adopted from the sibling mods —
lowercase `logo`, a space before the index, `.jpeg` for the candidates):
- `logo <N> - white background.jpeg` — white candidate N
- `logo <N> - black background.jpeg` — black candidate N
- `logo <N>.png` — that candidate's transparify (transparent) result

`generate_images.py` emits `<name>-<N>.<ext>` (e.g. `logo-white-1.jpeg`);
**rename** to the convention above after generating. The chosen candidate's
`logo <N>.png` is then copied to `unity/<Mod>/Editor/logo.png`.

**Why these choices:**
- **Native black, never matting.** The glow is rendered *against white*, so its
  semi-transparent pixels are already blended with white — mechanically swapping
  the background to black leaves a flat/beige halo (tried, user-rejected).
  Re-rendering on black *natively* produces a correct gold-into-black glow.
- **A white + black *pair* for transparify.** transparify derives the alpha and
  true colour from the per-pixel difference `P_white − P_black`, which only
  works when the **foreground is identical** in both — hence the black pass takes
  the white image as its reference to keep the subject matching (verified: no
  ghosting on the resulting pairs).
- **Two sibling logos as references** keep the new logo inside the family DNA
  (palette, outline weight, glow, sparkle treatment); the prompt carries only
  the new form.

Background / history: the `project_corekeeper_mod_logo_pipeline` memory.

## Conventions

- **Personal-use, non-commercial only** (Pugstorm EULA).
- Documentation files (`CLAUDE.md`, `README.md`, `docs/`) are English; chat
  answers are German.
- Each mod is an independent git repo with its own `CLAUDE.md` for
  mod-specific detail.

> Note: the two `docs/research/` notes referenced above currently live inside
> the `disable-durability/` repo, since that is where they were first written.
> Their content is mod-agnostic — if a second mod needs them, consider
> promoting them to a shared location under this directory.
