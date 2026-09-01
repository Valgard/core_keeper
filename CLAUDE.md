# CLAUDE.md — Core Keeper modding (shared)

Parent-level guidance inherited by every Core Keeper mod project under this
directory. Each mod also has its own `CLAUDE.md` with mod-specific detail
(patch targets, classes, build scripts). This file holds **only** what is
true for *all* mods built against Pugstorm's `CoreKeeperModSDK` on this
machine — change it only when an insight is genuinely mod-agnostic.

**Game and SDK reference — `docs/ck/`.** Deliberately NOT an `@`-reference: it
is many times the size of this file and most sessions need none of it. Open
`docs/ck/index.md` when a question is about the game rather than about this repo
— it routes by symptom and by task, so one read usually lands on the right
chapter. Triggers: getting a build to run at all — Unity version, modules,
wizard steps, the project lock, the macOS Steamworks fix (`toolchain.md`); the
load-time sandbox and `CompileFailed`; Harmony or ECS patching that binds but
never fires; the object database and bake-time edits; UI, prefabs, sprites,
fonts; world geometry, tiles, placement, creatures; multiplayer and
dedicated-server differences; localisation; save file formats; decompiling and
asset extraction.

The split: **this file holds the working rules for this repo** (setup,
conventions, what must stay in step with what), **the handbook holds the game
knowledge**. Check the handbook before investigating game behaviour from
scratch: it records what has already been ruled out, so it either answers the
question or sharpens it.

**But it is a witness, not a judge.** Every chapter was written out of what
developing one particular mod turned up, and what the sentence states is the
generalisation drawn from that one case — which can hold only there, be wrong,
be incomplete because the contradicting case never came up, or be inverted.
Nothing in the text marks which. So take a passage as the strongest available
hypothesis, and verify it against the decompile or the running game before a
design decision, an "it cannot be done" verdict, or anything published rests on
it. When the game contradicts a chapter, the game wins and the chapter is
corrected in the same pass. The handbook stands to the game as a memory stands
to reality: worth consulting first, never quoted as proof.

## Directory layout

- `CoreKeeperModSDK/` — the Pugstorm SDK clone, **shared** by every mod. Its
  own git repo. Mods do not vendor a private SDK copy.
- `<mod-name>/` — one directory per mod, each its own git repo. **Do not keep
  a list of them here or a count anywhere** — both go stale silently, and did.
  Enumerate them at the moment you need them:
  ```bash
  find . -maxdepth 2 -name .git -not -path "./.git*" \
    | sed 's|^\./||; s|/\.git$||' | grep -v "^CoreKeeperModSDK$" | sort
  ```

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

**The SDK-level requirements are in `docs/ck/toolchain.md`** — the exact Unity
patch version and why the SDK's own README misstates it, the build modules, the
one-time wizard steps, the project lock, and the macOS Steamworks meta-file fix.
Read it rather than reproducing it here; what follows is what this file adds.

- **While the user is actively in the Unity Editor, do NOT edit or write files**
  in the mod or SDK tree — restrict to read-only inspection (`prefab_query.py`,
  `grep`/Read). Concurrent file writes collide with the Editor's own saves /
  reserialization (it may overwrite or be clobbered by the assistant's edit).
  Wait until the user closes the Editor and confirms ("done") before making any
  file mutation.
- **`corekeeper-patch` applied to the installed game DLLs** — required on
  macOS / CrossOver hosts. Six IL patches across three DLLs. In
  `PugMod.Loader.dll`: (Patch 1) fixes the Wine `Directory.Delete` failure on
  stale `ModLoader/<ModName>/Scripts/`, (Patch 2) forces
  `CultureInfo.DefaultThreadCurrentUICulture = InvariantCulture` so Roslyn
  doesn't fail compiles by chasing the missing `de-DE` satellite assembly. In
  `Pug.Other.dll`: (Patch 3) a direct-write fallback for the Wine initial-save
  regression, (Patches 4–5) rewrite `StandaloneFilesystem.DeleteDirectory` /
  `Delete` to a Wine-safe iterate-and-delete. In `modio.UnityPlugin.dll`:
  (Patch 6) the same delete rewrite for `SystemIOWrapper.DeleteDirectory`.
  Every Core Keeper update reverts all three DLLs to stock — re-apply after
  each update. The patcher lives at `utils/corekeeper-patch.cs` (a .NET
  file-based script; `~/local/bin/corekeeper-patch` is a symlink onto it). It
  takes the **game directory** and resolves `<game>/*_Data/Managed` itself —
  `corekeeper-patch analyze|apply "<…>/steamapps/common/Core Keeper"` — so the
  same invocation works for any build. Apply it to **each installation
  separately**: the Dedicated Server (`CoreKeeperServer_Data`) needs all six
  patches too, and without Patch 2 its mods load but never compile, which the
  client then rejects as `Error/BadProtocolVersion` ("Game version mismatch").
  Rationale + canonical commands in the `corekeeper-roslyn-locale-bug` memory.

## SDK quirks (apply to every mod)

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
  / "Everything"). Set both directly in the `.asset` YAML.
- **`requiredOn` is a `[Flags]` enum — pick it per mod, do NOT default to `3`.**
  `ModExistsOn { None = 0, Client = 1, Server = 2, ClientAndServer = 3 }`
  (`PugMod.SDK`). The checks are **crossed**, which is the counter-intuitive part:
  the **Server** flag makes the *client* demand the mod on the server
  (`NetworkClientStartSystem`, Pug.Other ~124928), and the **Client** flag makes
  the *server* demand it on the client (`ModInfoRpcSystem`, ~125929).
  - The cost of an over-broad value is real: joining a server that lacks a
    `Server`-flagged mod raises `Menu/ModMissingServerDialogue` offering only
    "disable the mod (+ restart)" or "cancel the connection" (~124940-124978) —
    a hard block, not a warning. With a side-loaded mod (`modId <= 0`, negated by
    the loader's own side-loader as `ModId = -Mathf.Abs(metadata.name.GetHashCode())`
    — a fake-ID dev build carries a positive id and is not this case) the
    disable option is not even offered. A mod without the flag is dropped from
    the check list entirely (`localMods.RemoveAt`) and never interferes.
  - **The question to ask: does the SERVER need this mod for it to work?**
    `1` (Client) for read-only HUD/UI mods — they must not block joining unmodded
    servers. `2` (Server) for a mod with no client side at all (world/spawn/
    simulation changes with no UI; none of this family's mods are like that yet).
    `3` only when both sides genuinely need it: new items, recipe or database
    changes, server-authoritative inventory/XP logic, or a framework whose
    consumers may run server-side.
  - Corrected on 2026-08-06 for `player-coordinates-hud`, `item-checklist` and
    `simple-crafting-pool-extender`, which had inherited a blanket `3` from an
    earlier version of this very bullet and were needlessly blocking joins.
- Mod dependencies (e.g. CoreLib) live in the `.asset`'s `dependencies:` list
  (`- modName: CoreLib` / `required: 1`) and flow into the built manifest.

The published mod.io listing does **not** read the manifest either: profile name
← `metadata.displayName` (fallback `metadata.name`) — so the human title
"Item Checklist" can differ from the internal identity "ItemChecklist"; summary
← `MOD_SUMMARY` env, version + changelog ← `CHANGELOG.md`, modId ←
`<Mod>_modio.asset`, version tag(s) ← `CK_GAME_VERSION` env minus
`CK_MODIO_VERSION_UNLISTED` — both **space-separated lists**, the first naming
every build the mod runs on and the second the ones mod.io has no tag for, so
what remains is published one compatibility tag each (all in
`utils/CLIPublishHelper.cs`; see @docs/publishing.md for why the subtraction
exists and when it aborts the publish).

### Runtime asmdef from the wizard
**Run "Update Game Files" BEFORE "Create Mod".** Creating the mod freezes its
precompiled-reference list from a one-time scan of the assemblies present at
that moment, and nothing re-runs that scan; the assemblies arrive with Update
Game Files and are not in the SDK repository. In the right order the wizard
emits the mod's runtime `.asmdef` already populated with the full game-DLL
reference set (`Pug.Other.dll`, `0Harmony.dll`, `PugMod.SDK.Runtime.dll`, …).
Mod code compiles against game types and Harmony out of the box — no manual
reference editing is needed.

## Runtime constraints (apply to every mod's code)

### RoslynCSharp sandbox — no System.IO
Mods ship `Scripts/*.cs` and are compiled at load time inside a **default-allow**
sandbox with explicit deny lists — seven namespaces (`System.IO.*`,
`System.Diagnostics.*`, `System.Net.*`, `System.Runtime.InteropServices.*`,
`System.Reflection.*`, `RoslynCSharp.*`, `Pug.Platform.*`), sixteen types
(`System.AppDomain` plus fifteen `HarmonyLib.*` including `AccessTools` and
`Traverse`), seven assemblies and two members. The complete list is data, not
folklore: `Resources/Assets/Resources/RoslynCSharpSettings.asset` in the
decompile. A violation fails the compile on first reference (`mod load error:
CompileFailed`).

**This does not mean a mod cannot have a runtime config** — the sandbox
inspects references in the mod's *own* source, so a call into an
already-loaded trusted assembly costs nothing. Three ways out, in order of
preference:

- **`API.ConfigFilesystem`** (`PugMod`) — the loader's own file API, and the
  right answer for anything a `config.json` would hold. `FileExists`, `Read` /
  `Write` (both `byte[]`), `CreateDirectory`, rooted at
  `…/LocalLow/Pugstorm/Core Keeper/<platform>/<user-id>/mods/<ModName>/` and
  initialised before any mod's `EarlyInit`. No dependency, sandbox-clean.
  Used by `mod-settings-menu`'s `ConfigStore` — and by CoreLib, which is
  itself a sandboxed source mod (`skipSafetyChecks: false`) with zero
  `System.IO` references.
- **CoreLib's `ConfigFile`** — typed entries, defaults,
  `AcceptableValueRange`, a TOML-ish `.cfg` on disk. Same
  `API.ConfigFilesystem` underneath, at the cost of a hard CoreLib dependency.
- **`skipSafetyChecks: true`** in the ModBuilderSettings `.asset` — disables
  the sandbox entirely and unlocks raw `System.IO`. A last resort for what the
  first two cannot express; it also flips the derived mod.io `Access Type`
  tag.

### Burst-compiled systems are not Harmony-patchable
A DOTS system whose `OnUpdate` is Burst-compiled cannot be intercepted by
Harmony. Call `BurstDisabler.DisableBurstForSystem<TSystem>()` in `IMod.Init()`
to move the system off Burst *before* the patch needs to bind — or
`DisableBurstForSystemAndJobs<TSystem>()` when the actual patch target sits
inside a job the system schedules rather than in `OnUpdate` itself, since the
plain variant leaves that job Bursted (`docs/ck/harmony-and-ecs.md` has the
mechanism and a documented false shortcut for telling the two apart). Every system this
repo's mods disable Burst for is an **`ISystem` struct** (`OnUpdate(ref
SystemState)` — the prefix binds with no "Undefined target method"; verified in
`faster-talents`/`faster-pet-talents`). A managed `SystemBase` takes a
**completely different path** inside the SDK — `DisableBurstForSystemInternal`
returns early into `PatchManagedSystem`, which toggles Burst around the system's
own lifecycle methods and never touches the per-world registry — so none of the
AddWorld/dedicated-server reasoning below applies to it. There is no
`SystemBase` precedent here; an earlier version of this bullet claimed one, and
the mod it named patches an `ISystem` struct. Details in
`docs/ck/harmony-and-ecs.md`. To scale an ECS value that flows from a (possibly
Burst) producer into a Burst-consumed component/buffer, don't patch the managed
producer — Burst callers bypass the IL patch — but Burst-disable the
**consumer** system and pre-inflate the pending component data in its `OnUpdate`
prefix (see the `reference_ck_xp_grant_architecture` memory).

**On a dedicated server that call alone is a silent no-op** — no error, no log
line, the prefix simply never fires, so the mod works whenever a player hosts —
singleplayer *and* host-based multiplayer, since that process creates its own
ServerWorld after `Init()` — and does nothing on a dedicated server. ("Not in
multiplayer" is the wrong scope and stood here until 2026-08-24;
`docs/ck/harmony-and-ecs.md` has the evidence.) `DisableBurstForSystem` only
*registers* the type; the bypass is armed per world by `BurstDisabler.AddWorld`,
whose sole caller is `ECSManager.StartEcs` and which **snapshots** the types
registered so far. A dedicated server runs `IMod.Init()` *after* `StartEcs` (the
client runs it before), so the snapshot is taken while the registration is still
missing. Follow every `DisableBurstForSystem*` call with:

```csharp
foreach (var world in World.All)   // using Unity.Entities;
    BurstDisabler.AddWorld(world);
```

`World.All` passes the Roslyn sandbox, and the registry is a `HashSet`, so the
pass is a no-op in the client ordering. Moving the call to `EarlyInit()` instead
does **not** work — `TypeManager` is not initialised that early and
`DisableBurstForSystem` throws `NullReferenceException`. To prove the patch is
live server-side, log from the **static constructor** of the `[HarmonyPatch]`
class and read the server log *after* a session with a player connected — an
idle dedicated server sits at `timescale = 0` and never simulates. Background:
the `reference_ck_burstdisabler_dedicated_server` memory.

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

Read `docs/macos-crossover-loader.md` for the **fake-ID dev install** — the
three locations it writes and why the in-game Mods menu wipes them. What a
Wine host breaks is `docs/ck/platforms.md`; the loader's two disable lists
(`unsupportedModsToLoad`, `disabledMods`) and the incompatible-mod dialogue are
`docs/ck/troubleshooting.md`.

Read `docs/dedicated-server.md` before starting, stopping or debugging the local
dedicated server — it runs in the same bottle and shares one world with the
client via directory symlinks. How a server behaves, and why a mod-set mismatch
surfaces as "Game version mismatch", is `docs/ck/multiplayer-and-server.md`. The
helper is `utils/server.sh start|stop|status|log|relink`. The mod symlinks drift
four ways — a release mints a new `<fileId>`, a mod is switched off or
unsubscribed, a mod is added or moves between mod.io and a dev build, or one ends
up linked twice — so `relink` reconciles the whole directory against what is
installed and switched on (mod.io cache minus `disabledMods`, the loader's own two
filters), adding, re-pointing and removing links; `start` runs it first. When
the target set is unreadable it changes nothing: the symlinks are the sole record
of the mod set.

## Build pattern (shared `utils/`)

The shared `utils/` build/publish scripts and the `.envrc` inheritance chain
are documented in `README.md` (§ Build & install) — script names, variables, the
exact commands. `docs/ck/toolchain.md` carries the same arrangement's *reasoning*,
framed as one setup among possible ones.

**When a build misbehaves rather than merely fails, read [`docs/build-environment.md`](docs/build-environment.md)
before investigating.** It covers what goes wrong with this arrangement on this
machine: a build that **hangs** is almost always Unity waiting on an IL Post
Processor runner that never started — diagnosable in three numbers (≈0 % CPU, an
`ilpp.sock-*` that exists, and no runner process alive), and fixed by clearing
`Temp` + `Library/Bee` **and restarting Unity Hub**, which is the step that
actually does it (24-minute hang → 75 seconds, measured). It also records that
`Access token is unavailable` appears in *successful* builds and is therefore no
diagnosis, why the log needs `tee` to survive at all, and where the Unity Hub
CLI does and does not help — it wraps batchmode rather than replacing it, so it
would not have prevented any of this.

- **Concurrent build/publish locks the shared SDK project for every session.**
  All mods share one `CoreKeeperModSDK` clone, so any session's batchmode
  build/publish takes the SDK project lock (`UnityLockfile`). If a build aborts
  on a held lock, another session's `build.sh`/`upload.sh` is running — **wait
  for the lock to release (poll), do NOT kill it.** A killed mid-flight
  `CLIPublishHelper.Publish` can leave the mod.io profile/modfile partially
  uploaded; the `timeout 600` wrapper already bounds a genuinely hung run.

## New mods — keep `utils/new_mod.py` in step

`utils/new_mod.py` is the only path to a new mod repo (the `new-ck-mod` skill
documents the invocation), which makes it a standing liability: **when a
convention lands in every mod repo, it belongs in `new_mod.py` in the same
change.** A lagging scaffold produces a repo that looks finished and fails later
— three drifts did exactly that, found 2026-08-12: no `CK_MODIO_TYPE`, so
`CLIPublishHelper` aborted the publish; `requiredOn` hardcoded to `3` against
this file's own rule (and never even passed through); and `--corelib` writing the
loader dependency without the assembly reference, so `using CoreLib;` would not
compile. Its own unit suite was green throughout — it can only check the
generator against itself.

The guard is `utils/tests/test_new_mod_parity.py`, part of the normal suite
(`uv run pytest utils/tests`). One rule: **whatever every mod repo has, the
generator must produce.** So it needs no list of conventions to keep current, and
anything only some mods adopt stays their business. It compares each file at the
level the repos actually agree on — verbatim, contained block, JSON value,
pattern lines — because byte-identity across all of them is not true, and it
skips loudly in a checkout without the mod repos.

Localisation is wired from the start — `LOC_YAML`/`LOC_OUT` in the generated
`.envrc`, an all-comment `localization/localization.yaml`, the two `.gitignore`
entries. That is only safe because `LocalizationGenerator` tells an **empty**
table (skip generation, and clear what an earlier run wrote, or emptying a table
would keep shipping stale assets) from one that **has content but yields no
term** (fail — a term is a `Leaf:` at indent 2, so namespace headers alone define
nothing, and those terms would render as raw keys in game). A missing file stays
fatal: `LOC_YAML` pointing at nothing is a contradiction, and a silent skip there
would ship text that quietly fell back to raw keys. Consequence for a new mod:
the first localisation step is writing a term, not wiring anything — and the
scaffolded template must stay fully commented, which
`test_localization_template_is_inert` enforces.

Deliberately **not** scaffolded: `README.md`, `modio-description.md`,
`discord-post.md` and `CLAUDE.md` — a static template would be dead prose; they
are authored from the mod's real purpose right afterwards. That is the guard's
one hand-kept exception list. `CK_DISCORD_TAGS` *is* scaffolded, but empty: the
variable is universal, its value belongs to a forum thread that does not exist
yet, and `utils/discord_post.py` refuses to render while it is blank.

`CK_DISCORD_THREAD` and `CK_DISCORD_MEDIA` are scaffolded empty too, but for
a different reason — and the difference matters, because all three look
alike. An empty `CK_DISCORD_TAGS` is an omission the renderer refuses; an
empty `CK_DISCORD_THREAD` states that no thread exists yet, and an empty
`CK_DISCORD_MEDIA` that the mod has nothing to show beyond its logo, which
is the honest answer for a chat command. Same syntax, opposite semantics for
the empty value; the `.envrc.example` comments have to say which is which.

## Formatting gate (every repo)

Every repo under this directory — each mod repo and `core_keeper` itself —
carries the same CSharpier gate. `README.md` (§ Formatting gate) holds the
human-facing setup; what matters when editing code here:

- **The gate blocks, it does not rewrite.** `.pre-commit-config.yaml` runs
  `dotnet csharpier check` over staged `.cs` at `pre-commit` **and** `pre-push`,
  so a rejected commit needs `dotnet csharpier format .` and a retry — nothing
  is ever reformatted behind an edit. `core_keeper` adds `ruff format --check`
  for the Python in `utils/`.
- **`printWidth: 160`** in each repo's `.csharpierrc` — deliberate, not a
  leftover. Do not "correct" it to the CSharpier default of 100.
- **The formatting diff is not printWidth-driven.** CSharpier also splits
  single-line `if (x) y;`, collapses column-aligned trailing comments to a
  single space, and moves binary operators to the start of the continuation
  line. Above ~140 it increasingly *joins* deliberately wrapped constructs. For
  a line that must keep its shape, use `// csharpier-ignore`.
- **`pre-commit install` refuses to run while `core.hooksPath` is set**
  ("Cowardly refusing to install hooks"), even when that path merely points at
  the repo's own `.git/hooks`. Two mod repos had it set that way; the fix is
  `git config --unset-all core.hooksPath`.
- **`dotnet new tool-manifest` writes `dotnet-tools.json` into the repo root**
  under .NET 10, not into `.config/`. Move it to `.config/dotnet-tools.json`;
  `dotnet tool restore` accepts either location.
- **Never run a formatter from `core_keeper/` without its ignore file.** The SDK
  clone (~2,900 foreign `.cs`) and every mod repo sit inside it as separate
  repos, so a bare `csharpier format .` would rewrite them all. The parent's
  `.csharpierignore` is an allowlist (`/*` + `!/utils/`) for exactly that
  reason; `ruff` needs no counterpart because it honours `.gitignore`.
- **A staged `.md` also runs the documentation link gate** — in `core_keeper`
  *and in every mod repo* (`utils/check_docs_links.py`, `pre-commit` +
  `pre-push`): a dead relative link, an `#anchor` with no matching heading, or
  a `docs/ck/` chapter that `docs/ck/index.md` does not link blocks the
  commit. Practical consequence: **renaming a heading in `docs/ck/` breaks
  every link into it**, and the gate will say so — fix the links in the same
  commit. A mod repo has no checker of its own: its hook runs the parent's
  over the mod repo's own root, the same way its build reaches for
  `../utils/build.sh`. One rule bends for it — the duplicate-anchor check
  skips `CHANGELOG.md`, because Keep a Changelog repeats `### Added` once per
  release, which is the format and not a defect.
- **A staged `.md` runs the wrapping gate as well**
  (`utils/check_docs_wrapping.py`, the same two stages): a paragraph whose line
  breaks no longer fit the width that file is written at blocks the commit.
  There is no number to write to — it takes each file's width from that file's
  own median, because the handbook is not uniform. Practical consequence: **an
  `Edit` into the middle of a paragraph leaves exactly this defect**, a replaced
  line ending short or long while the rest of the paragraph keeps its old
  breaks. Run `uv run utils/check_docs_wrapping.py --fix <file>` after such an
  edit rather than discovering it when the commit is rejected. Frozen on
  purpose: `docs/specs/`, because reformatting a spec edits a record of what was
  decided, and the `ck-docs-review` skill's fixtures and scoring keys, which are
  the two halves of one calibration instrument.
- **The wrapping gate runs in every mod repo too, since 2026-09-01.** For a long
  while it did not, while this file claimed it did, and the mod repos went
  unchecked — which is how an edit left a 143-column line in
  `mod-settings-menu/docs/roadmap.md` and reached a commit unopposed. The reason
  was not neglect: the script took file arguments and died on the `.` a mod
  repo's hook passes, where its sibling has always taken a root. Wiring it in
  cost a rewrap of about 700 lines across twelve repos first, because of the
  next bullet.
- **Both gates check the whole repository, not the staged files.** Each hook is
  configured `pass_filenames: false` and a staged `.md` merely triggers it — so
  a defect anywhere blocks a commit that touches documentation nowhere near it.
  Deliberate for the link gate, whose targets cross files; the consequence for
  wrapping is that a backlog is never latent, which is why one had to be cleared
  before the hook could go in anywhere.
- **`--fix` repeats itself, because fixing a file changes the width it is
  measured against.** Each pass takes that width from the lines it finds on
  entry, and then rewrites them — rewrapping long paragraphs adds a short tail
  to each, so a file measured at 88 can come out measured at 80, with lines the
  pass was right to leave alone. One pass therefore used to leave work behind
  while reporting success, and a repo committed clean was rejected by the gate it
  had just installed. Fix mode now loops until nothing moves, and reports a
  non-zero exit if it runs out of passes — which would mean the fixer and the
  checker disagree, not that one more turn was needed.
- `pre-commit` itself is pinned once in the parent `.tool-versions`; asdf
  resolves it for the mod subdirectories by walking up.
- **`utils/new_mod.py` scaffolds the gate too.** A freshly generated mod repo
  already carries `.csharpierrc`, `.pre-commit-config.yaml`, and
  `.config/dotnet-tools.json` from its first commit — there is no separate
  step to add them by hand.

## mod.io publishing (applies to every mod)

Read `docs/publishing.md` before publishing or re-tagging anything on mod.io:
the publish modes, how dependencies and tags are synchronised here, and which of
the three mod IDs is which. How mod.io itself behaves — profile versus modfile,
which manifest field becomes which tag — is `docs/ck/publishing.md`.

## Logo / branding (family style)

Every mod ships a square mod.io profile logo at `unity/<Mod>/Editor/logo.png`,
and they all share one deliberate visual identity — match it for any new mod.

**Shared DNA (every existing logo):**
- A single, centred **hero object in teal / petrol-green** with **gold / brass
  accents** and a thick dark outline — hand-painted "sticker" concept-art,
  **not** pixel-art.
- A warm **golden radial glow** behind the subject and scattered **4-point
  sparkles**.
- Square (1:1), 1024².

**Per-mod "gesture":** each logo adds one small gold sub-symbol that hints at
the mod's purpose. Examples for calibration, **not** an inventory of every mod
— that is the kind of list that goes stale silently, and this one already had;
each mod's own `CLAUDE.md` describes its logo. Reuse arrow-ring
(reusable-cattle-box), infinity on crossed tools (disable-durability),
checkmarks + "?" (item-checklist), fanned cards + "+"
(simple-crafting-pool-extender), star + cubes (faster-talents), paw + cube
(faster-pet-talents), crossed rods + orb (caveling-divining-rod), gear +
toggle-slider (mod-settings-menu), ornate gemmed key (rebalance-key-crafting),
type-case tray with glowing gold characters (complete-tiny-font). Invent a
fitting gesture for the new mod rather than copying one.

**Generation workflow** — the global `image-generation` skill
(`~/.claude/skills/image-generation/`, Gemini "Nano Banana Pro"). Both of its
scripts are PEP-723 `uv` scripts that resolve their own dependencies, so `uv run
<script>` is all they need; `GEMINI_API_KEY` comes from the environment, so
there is no `source` step. The skill documents the generic white → black →
transparify pipeline; below is only what is CK-specific about it. Three stages
produce the transparent `Editor/logo.png`:

1. **White candidates.** Generate ~4 candidates on a **plain white background**.
   Pass **two polished sibling logos as `-ref`** (palette + style anchors, e.g.
   reusable-cattle-box + caveling-divining-rod) and describe the **form** in the
   prompt. Output lands in `<mod>/sources/logo-white-{N}.jpeg`.
   ```bash
   uv run ~/.claude/skills/image-generation/generate_images.py \
     --out-dir <mod-repo>/sources --name logo-white -ar 1:1 -r 1K -c 4 \
     -ref <siblingA>/Editor/logo.png -ref <siblingB>/Editor/logo.png \
     "<hand-painted CK-sticker prompt: hero object + teal/gold + golden glow + \
       4-point sparkles + plain white background>"
   ```
2. **Black versions — NATIVE, not matted.** For each chosen white candidate,
   re-run with **that white image as `-ref`** and a minimal prompt ("replace the
   white background with pure black #000000; keep everything else unchanged"),
   `--name logo-black --start-index N --count 1` → `logo-black-{N}.jpeg`.
3. **Transparify (local, scriptable).** Run the skill's `transparify.py` on the
   matching white + black pair to recover the transparent PNG; copy the chosen
   candidate to `unity/<Mod>/Editor/logo.png`.
   ```bash
   uv run ~/.claude/skills/image-generation/transparify.py \
     -w "<mod>/sources/logo 3 - white background.jpeg" \
     -b "<mod>/sources/logo 3 - black background.jpeg" \
     -o "<mod>/sources/logo 3.png"
   ```
   A faithful **1:1 port** of transparify.app's client-side algorithm
   (transparify.app has **no API**), validated against its own output — **alpha
   bit-identical**, RGB within JPEG-decoder noise. The math and its rationale live
   in the skill; it used to sit in this repo as `utils/transparify.py`.

**Candidate file naming** (in `<mod>/sources/`, adopted from the sibling mods —
lowercase `logo`, a space before the index, `.jpeg` for the candidates):
- `logo <N> - white background.jpeg` — white candidate N
- `logo <N> - black background.jpeg` — black candidate N
- `logo <N>.png` — that candidate's transparify (transparent) result

`generate_images.py` emits `<name>-<N>.<ext>` (e.g. `logo-white-1.jpeg`);
**rename** to the convention above after generating. The chosen candidate's
`logo <N>.png` is then copied to `unity/<Mod>/Editor/logo.png`.

**Why these choices:**
- **Native black, never matting**, and **a white + black *pair* for transparify**
  are properties of the pipeline itself — the skill explains both. Recorded here
  because it was learned here: mechanically swapping the white background to black
  leaves a flat/beige halo (tried, user-rejected) instead of a correct
  gold-into-black glow, and the reference-chained pairs show no ghosting.
- **Two sibling logos as references** keep the new logo inside the family DNA
  (palette, outline weight, glow, sparkle treatment); the prompt carries only
  the new form.

Background / history: the `project_corekeeper_mod_logo_pipeline` memory.

## Sprite sheets

A mod's in-game sprites come from a `.pixaki` master in its `sources/`, cut by
`utils/pixaki_to_sheet.py` against a sibling `<name>.json` sprite definition
into `unity/<Mod>/Art/UI/<name>.png` plus its `.meta`. The `.png` is generated —
never hand-edit it, re-cut instead. `utils/pixaki_inspect.py` prints any layer
of a master as a character grid with its palette, which is how a stray pixel or
a forgotten working-background layer is caught before it ships; the format
itself is @docs/pixaki-format.md.

**Pin both halves of a prefab's sprite reference in the sprite definition.**
A prefab points at a sprite with `{fileID, guid}`, and the generator derives
each from something that changes without anyone meaning to: the sheet **`guid`**
from the output path, and each sprite's **`internalID`** from its layer name. So
cutting the same master from a worktree, or renaming a layer, silently orphans
the reference — and a dead reference shows up as an empty patch of UI, not as an
error. `"guid"` and `"internalIds"` in the `.json` remove both hazards; the
generator validates the pins before writing anything.

**Exclude the layers that must not ship** — extracted vanilla art kept as visual
reference, alternative drafts, and the opaque backdrop layer that makes pale
pixels visible while drawing. Exclusion is by name in the `.json` rather than by
hiding the layer in Pixaki, because a working background gets toggled constantly
while drawing and *will* eventually be saved visible.

## Conventions

- **Personal-use, non-commercial only** (Pugstorm EULA).
- Documentation files (`CLAUDE.md`, `README.md`, `docs/`) are English; chat
  answers are German.
- Each mod is an independent git repo with its own `CLAUDE.md` for
  mod-specific detail.

> Note: some mod-agnostic research notes still live under `disable-durability/docs/research/`,
> since that is where they were first written. **A note that two mods depend on is
> not a mod's note** — promote it to `docs/` here as soon as a second mod needs it,
> the way `docs/pixaki-format.md` was promoted out of `item-checklist` once the
> shared `utils/pixaki_*` tools gave it a second consumer.
