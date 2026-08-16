# Reusable Cattle Box — Design Spec

- **Date:** 2026-06-24
- **Status:** Approved (brainstorming) — pending implementation plan
- **Slug:** reusable-cattle-box

## 1. Purpose & success criterion

A Core Keeper mod that turns the single-use **Cattle Transport Box** into a
**deposit ("Pfand") box**: when a boxed cattle is **released** (placed back
into the world), one empty `CattleCage` is returned to the placing player's
inventory. Net box cost per transport round-trip becomes 0 after the first
craft.

**Success is empirical, in-game** (no unit-test harness exists for the runtime
sandbox): catch a cow (box is consumed) → place the cow at a new location → the
cow spawns **and** an empty box reappears in the inventory. Box count before
first catch == box count after release.

## 2. Names (three-level convention)

| Level | Value |
|-------|-------|
| Repo (kebab) | `reusable-cattle-box` |
| Namespace / asmdef (Pascal) | `ReusableCattleBox` |
| DisplayName (Title) | `Reusable Cattle Box` |

## 3. Verified game mechanic (decompile, game 1.2.1.4)

Source: `~/Projects/checkouts/CoreKeeperDecompile/Pug.Other.decompiled.cs`.

- The empty transport box is `ObjectID.CattleCage`.
- **Capture** — `CageCattle()` @404656, inside `UpdatePlayerStateSystem`
  (`struct ISystem`, Burst-compiled): finds a nearby cattle, calls
  `EntityUtility.DropPetInCage()` @254079 which spawns a `DroppedItem` entity
  carrying the cattle **as a `ObjectType.Creature` item** (with aux-data:
  `NameCD`, `MealsEatenCD`, `BreedToggleCD`), destroys the cattle entity, then
  consumes 1 `CattleCage` via `Create.ConsumeEntityAt(.., destroy:true, ..)`
  @404706. The captured cattle is now a creature **item** the player picks up;
  the empty box is gone.
- **Release** — placing that creature item via `PlaceItem()` (~311388, in the
  equipment-use system, Burst): `entityObjectInfo.objectType == Creature` path
  (@311451) consumes the item with `Create.ConsumeEntityAt(.., destroy:false,
  ..)` @311465, which spawns the cattle back into the world.

**Key correction over the initial assumption:** there is no "filled box" item;
the box is gone after capture and the cattle travels as a creature item.
Therefore "reusable" = *additively re-grant* a `CattleCage` on release, not
*suppress* an existing consume. The data-driven `SpawnsItemsOnUseCD` /
`OpenItemAndSpawnLoot` path (@404518) does **not** fire on placement, so a
pure CoreLib data patch cannot achieve this — a code patch is required.

## 4. Architecture & components

Mirror the `disable-durability` mod (BurstDisabler + Harmony). Two source files:

- **`ReusableCattleBoxMod.cs`** — `IMod` bootstrap. `Init()` calls
  `BurstDisabler.DisableBurstForSystem<TSystem>()` for the equipment-use DOTS
  system whose job invokes `PlaceItem`, so the static helper runs as managed IL
  and Harmony can bind. **Exact system type pinned during planning** by tracing
  the caller of `PlaceItem` (the awk guess `PlayRespawnSequenceClientSystem` is
  unreliable; the real container uses `EquipmentUpdateAspect`).
- **`ReturnBoxOnReleasePatch.cs`** — `[HarmonyPatch]` (auto-discovered by the
  loader). **Postfix** on `PlaceItem`. Gate: the placed item is
  `ObjectType.Creature` **and** `cattleLookup.HasComponent(equipmentPrefab)`.
  Action: append one `InventoryChangeBuffer` entry that adds 1×
  `ObjectID.CattleCage` to the placing player's inventory — **purely additive**;
  the existing `ConsumeEntityAt` is left untouched.

## 5. Data flow

```
Capture (CageCattle, UNCHANGED)
  → box consumed, cattle becomes a Creature item (aux-data preserved)
Release (PlaceItem)
  → cattle spawns + creature item consumed   [vanilla]
  → POSTFIX: detect Creature + CattleCD       [mod]
  → append inventory-add for 1× CattleCage    [mod]
```

## 6. Error handling / edge cases

- Cattle item destroyed/trashed without placing → no box returned (player loses
  box *and* cattle — fair, matches vanilla loss).
- Creative mode → refund is harmless (boxes are free there); no special gate.
- Server authority → inventory change is server-side → `requiredOn: 3`
  (ClientAndServer), per project convention.
- `CattleCage` stacking → handled by the game's inventory-add logic (merge into
  existing stack or new slot).

## 7. Scaffolding (CLI bootstrap from disable-durability)

The "Create New Mod" Editor wizard is bypassed by copying the
`disable-durability` repo structure and renaming:

- Rename every `DisableDurability` → `ReusableCattleBox` (files, dirs, asmdef
  names + references, namespace, `.asset`, `_modio.asset`).
- **Fresh unique GUIDs** in all `.meta` files and the `.asset`
  `metadata.guid` (avoids the `Data block loader already added` collision bug).
- New `.envrc` (`MOD_NAME`, `MOD_NAME_ID`, `FAKE_MOD_ID` ≥ 9999000,
  `MOD_SUMMARY`, `CK_GAME_VERSION`, `MOD_INSTALL_PATH`, `MOD_REPO_ROOT`).
- Editor helpers (`CLIBuildHelper.cs`, `CLIPublishHelper.cs`,
  `LocalizationGenerator.cs`) stay `.meta`-only — symlinked from shared
  `utils/` by `link.sh`.
- First build: run `link.sh`, then reset `Library/SourceAssetDB` (+ Bee /
  ScriptAssemblies / ArtifactDB / Artifacts) before building, per the
  newly-symlinked-mod cache trap.

## 8. Verification

- **Early spike (primary risk):** confirm a Harmony postfix on the static
  `PlaceItem` binds **after** `BurstDisabler` — the helper runs inside a Burst
  job rather than being an `OnUpdate` like `disable-durability`'s patch target.
  Validate with a no-op postfix + log before writing the real logic.
- **Functional smoke test:** build → fake-ID dev install → in-game: catch a
  cow, place it, assert box count restored.

## 9. Distribution

- Publish to mod.io like the sibling mods. Profile type tag **`Script`** (not
  `Asset`, which silently sets `disableScripts`).
- Start version **`1.0.0`** (single, complete feature).
- **Local-first:** fake-ID dev + green smoke test BEFORE the mod.io publish; no
  half-finished profile online.
- CHANGELOG `## [1.0.0]`, player-oriented README, logo via the existing logo
  pipeline.

## 10. Out of scope (YAGNI)

- Option B semantics (box never consumed at capture) — explicitly rejected.
- Configurable refund amount / probability.
- Any change to the capture flow, cattle aux-data, or crafting recipe.
