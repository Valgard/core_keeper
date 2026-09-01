# Answer Key — Planted Errors, Corpus (SCORING ONLY)

⚠️ **This document is for scoring only.** It must never be given to a lane during a baseline or verification run. A lane that is handed the answers is not measuring anything. Destroy this file or withhold it from every agent that reviews the fixture.

Fixture: `../fixtures/corpus-diff.md`. Same instrument as `planted-errors.md`
and `planted-errors-2.md`, aimed at a different evidence source: these four
errors are grounded in the **mod corpus** — the mod repositories in this
workspace and the third-party mods installed on this machine. Two of them —
the counter-case and the enumeration — have no decompile-side evidence at all,
because neither is a claim about the game. The other two do, and are corpus
errors anyway: what makes each wrong is a mod this workspace contains, and the
decompile only confirms it afterwards.

**Where the paths are rooted.** Mod-repository paths are relative to
`/Users/valgard/Projects/private/core_keeper/` (the grandparent of this
worktree, which sits in `core_keeper/.worktrees/<name>/` — the mod
repositories are `core_keeper`'s contents, not its siblings), and decompile
paths to `~/Projects/checkouts/CoreKeeperDecompile/`. A bare `<id>_<fileId>/` prefix
names an installed third-party mod, under:

```
~/Library/Application Support/CrossOver/Bottles/Core Keeper/drive_c/users/Public/mod.io/5289/mods/
```

⚠️ **Searching the mod repositories needs `command grep`.** The
`core_keeper` directory's `.gitignore` is `/*`, and the in-session `grep` shim
honours it, so a root-relative search returns nothing at all and says nothing
about why. Every line number below was taken with `command grep -rn` or
`command sed -n`; re-check them the same way.

---

## The four errors

Established on 2026-09-01 by reading the corpus directly, then planted. Five
mod repositories call `BurstDisabler` — `disable-durability`, `faster-talents`,
`faster-pet-talents`, `auto-rail-bridges` and `reusable-cattle-box` — and all
five follow the call with the `AddWorld` pass. Re-run that enumeration before
scoring — a mod added since then changes what row 4 is worth, and a mod
removed could retire it entirely.

| Sentence | Class | Evidence |
|---|---|---|
| "A method that only ever runs inside a job the system schedules cannot be patched from a mod at all: the job body executes after the gate has closed again, so the patch binds cleanly and never fires." | Counter-case | `reusable-cattle-box/unity/ReusableCattleBox/ReturnBoxOnReleasePatch.cs:46-52` — a `[HarmonyPostfix]` on `PlaceObjectSlot.PlaceItem`, which is exactly such a method: its only call site is inside `EquipmentUpdateSystem`'s nested `UpdateJob` (`Pug.Other.decompiled.cs:419770` declares the job, `:419767` carries its `[BurstCompile]`, `:419874` its `Execute`, `:419899` the call). The mod reaches it with `DisableBurstForSystemAndJobs<EquipmentUpdateSystem>()` (`ReusableCattleBoxMod.cs:57`), and its own comment at `:26-32` records the same call chain. `auto-rail-bridges` patches into the same job (`PlaceItemPatch.cs:68`, `:98`) and records the in-game measurement at `AutoRailBridgesMod.cs:46-49`: with the plain variant no hook fired, with `AndJobs` every hook fires. Both mods are published and installed (`6161722_8124036`, `6295455_8079988`) |
| "`FasterPetTalents` needs none of it. `PetHandlerSystem` is a managed `SystemBase` rather than an unmanaged `ISystem`, so `DisableBurstForSystemInternal` hands it to `PatchManagedSystem` …" | False claim about a workspace mod | `Pug.Other.decompiled.cs:138748` — `public struct PetHandlerSystem : ISystem, ISystemStartStop, ISystemCompilerGenerated`. It is an unmanaged `ISystem` struct, so `DisableBurstForSystemInternal`'s managed branch (`PugMod.SDK.Runtime.decompiled.cs:810-820`) is never taken for it. The mod also does the opposite of what the sentence says: `faster-pet-talents/unity/FasterPetTalents/FasterPetTalentsMod.cs:23` registers the system and `:34-35` runs the `AddWorld` pass, with a comment at `:25-33` explaining why it is needed. This is the error the parent `CLAUDE.md` itself carried — an earlier revision claimed a `SystemBase` precedent and named a mod that patches an `ISystem` struct |
| "That two shipped mods rely on it is evidence enough that the loader arms each world as it creates it, and that the extra pass is defensive rather than load-bearing." | Precedent as rule | The two observations it rests on are true and were verified — `5088296_8112340/Scripts/Scripts/Main.cs:38` and `3400322_7742541/Scripts/Scripts/PlacementPlusMod.cs:202`, with `command grep -rn AddWorld` finding nothing anywhere in either mod — but an omission in a shipped mod is a fact about its author, never a fact about the loader, and neither mod's dedicated-server behaviour is observable from its source at all. What the loader does contradicts the inference: `PugMod.SDK.Runtime.decompiled.cs:846-860` — `AddWorld` arms only the system types registered by the moment it is called (`:848`) — and its sole call site in the game is `Pug.Other.decompiled.cs:2675`, inside `StartEcs` (`:2632`), which on a dedicated server runs before `IMod.Init()`. `auto-rail-bridges/unity/AutoRailBridges/AutoRailBridgesMod.cs:52-59` records the corpus's own opposite finding for this very system, and `reusable-cattle-box/unity/ReusableCattleBox/ReusableCattleBoxMod.cs:95-105` explains why the client ordering hides it |
| "Four mods here carry that pass — `DisableDurability`, `FasterTalents`, `AutoRailBridges` and `ReusableCattleBox`" | Stale enumeration | Five do. The list omits `faster-pet-talents`, whose pass is at `faster-pet-talents/unity/FasterPetTalents/FasterPetTalentsMod.cs:34-35`, following its `DisableBurstForSystem<PetHandlerSystem>()` at `:23`. The other four are `disable-durability/unity/DisableDurability/DisableDurabilityMod.cs:38-39`, `faster-talents/unity/FasterTalents/FasterTalentsMod.cs:34-35`, `auto-rail-bridges/unity/AutoRailBridges/AutoRailBridgesMod.cs:60-61` and `reusable-cattle-box/unity/ReusableCattleBox/ReusableCattleBoxMod.cs:84-90`. The count is what makes it scorable: the parent `CLAUDE.md` forbids stored mod counts precisely because they go stale without anyone touching the sentence |

Rows 2 and 4 both concern `faster-pet-talents` and are deliberately consistent
with each other inside the fixture — the false `SystemBase` story is what
explains the mod's absence from the list. That is the shape a stale
enumeration actually takes in prose, and it means a lane can find one without
the other. Score them separately.

## What must stay true in the fixture

Everything else `corpus-diff.md` adds is accurate and should draw
`NO OBJECTION`. These are what separate a lane that reads the corpus from one
that objects to every sentence naming a mod:

- "`DisableBurstForSystem<T>()` registers a system type so the SDK's gate on
  `WorldUnmanagedImpl.UpdateSystem` can flip Burst off around that system's
  update" — `PugMod.SDK.Runtime.decompiled.cs:822` and `:833` on the unmanaged
  path; the gate is the Harmony patch declared at `:960`.
- "`DisableBurstForSystemAndJobs<T>()` registers the same type and additionally
  installs a postfix on `OnUpdate` that completes the system's outstanding
  dependency" — `:783-786` passes `addCompleteDependencyPatch: true`, `:867`
  reaches `CreateCompleteDependencyPatch` (`:924-941`), whose postfix calls
  `state.Dependency.Complete()` (`:947`).
- "Every mod in this family that touches `BurstDisabler` makes both calls from
  `Init()`; none of them attempts it from `EarlyInit()`" — all five bootstraps
  place both calls inside `Init()`: `DisableDurabilityMod.cs:22-39`,
  `FasterTalentsMod.cs:22-35`, `FasterPetTalentsMod.cs:21-35`,
  `AutoRailBridgesMod.cs:41-61`, `ReusableCattleBoxMod.cs:19-106`. Each
  bootstrap's `EarlyInit()` is either empty or registers settings only.
- "`ReusableCattleBox` goes one step further and counts how many worlds the
  pass actually reached, because `AddWorld` returns nothing and logs nothing" —
  `ReusableCattleBoxMod.cs:82-90` counts, `:77-81` gives the reason, and
  `PugMod.SDK.Runtime.decompiled.cs:846-860` shows a `void` body with no
  logging on any path.
- "`SceneBuilder` calls the plain variant for `DungeonApplySpawnedObjectsSystem`
  and never calls `AddWorld` at all, and `PlacementPlus` does the same for
  `EquipmentUpdateSystem` with the `AndJobs` variant" — `Main.cs:38`,
  `PlacementPlusMod.cs:202`, and no `AddWorld` in either mod. Only the
  inference drawn from this pair is planted, not the pair itself: naming a
  third-party mod is not the error.
- "every mod named above ships with `skipSafetyChecks` off" — line 19 of each
  of `disable-durability/unity/DisableDurability.asset`,
  `faster-talents/unity/FasterTalents.asset`,
  `faster-pet-talents/unity/FasterPetTalents.asset`,
  `auto-rail-bridges/unity/AutoRailBridges.asset` and
  `reusable-cattle-box/unity/ReusableCattleBox.asset` reads
  `skipSafetyChecks: 0`; `3400322_7742541/ModManifest.json` and
  `5088296_8112340/ModManifest.json` both carry `"skipSafetyChecks": false`.

## One calibration round (recorded 2026-09-01)

The following scores are what one calibration round measured against this
fixture. They are a record of that round, not a property of the lane —
a re-run, especially after the fixture or the lane definition changes, could
score differently and would supersede this entry rather than average with it.

**Baseline — two independent general-purpose reviewers, sonnet tier,** each
dispatched with the fixture only: no error classes named, no answer key, and
the corpus context supplied by hand in the prompt (the mod-repository
enumeration command, the mod.io cache path, and the `command grep` caveat
above). Run 1 found 4 of 4 planted errors, 0 false positives on the true
sentences. Run 2, a fresh reviewer given the identical prompt, also found 4
of 4 with 0 false positives, and went further than run 1: it cited the
handbook's own `docs/ck/harmony-and-ecs.md` against two of the errors on its
own initiative.

**Lane — `ckdocs-corpus-checker`, same model tier,** dispatched with the
standard dispatch envelope only (the diff, the full file, the decompile
paths, the out-of-bounds clause) and **none** of the hand-written corpus
context the baseline runs received. It also found 4 of 4 planted errors with
0 false positives. It reached the corpus using its own enumeration command
and filled the `reached the files` field substantively — 9 hits across 7 mod
repositories, noted explicitly as "not empty" — and it ran in a session
where the `.gitignore`-honouring `grep` shim described above was active,
i.e. under the condition where a root-relative search genuinely returns
nothing.

**Equal scores do not mean the lane adds nothing.** The baseline reviewers
were handed the corpus context by a human and happened to run while the
shim was inert; the lane was given none of that context and ran with the
filter active. What the equality establishes is that the lane definition
carries the context a human otherwise has to supply by hand — that is the
claim this round tested, and it is a claim that could have failed.

**One fact from the same round that nearly went the other way.** The lane's
enumeration command is prefixed with `cd` into the repository root before
enumerating. The version without that prefix — which is what an earlier
draft of the lane specified — produces zero output when run from a
worktree, and a worktree is a realistic dispatch context. Had that version
been copied in unchanged, the lane would have found no mods at all and
reported corpus-silence on every assertion, with nothing in its output
distinguishing that from a genuinely silent corpus.
