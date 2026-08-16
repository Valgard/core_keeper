# Auto Rail Bridges — Design

- **Date:** 2026-08-08
- **Mod:** `auto-rail-bridges` (new repo)
- **Status:** design settled, pending implementation

## Problem

A rail (`ObjectID.Rail = 6550`, `Pug.Base:3357`) cannot be placed on any tile
the game does not consider walkable. Laying a rail line across a pit therefore
means interrupting the line, switching to a bridge, placing it, switching back,
and placing the rail — once per tile. Over a wide chasm that is dozens of
manual tool switches for a result the player already committed to when they
started drawing the line.

The mod collapses that into one action: placing a rail on a tile that cannot
carry it places a bridge from the player's inventory first, then the rail.

### The game already does exactly this for walls

`PlaceObjectSlot.GetTileTypeToPlace` (`Pug.Other:295561`) substitutes a tile
the player did not ask for:

```csharp
if (objectToPlaceInfo.tileType == PugTilemap.TileType.wall
    && !tileAccessor.HasType(worldPosition, PugTilemap.TileType.ground)
    && !tileAccessor.HasType(worldPosition, PugTilemap.TileType.bridge)
    && PugDatabase.TryGetTileItemInfo(PugTilemap.TileType.ground, …).objectID != ObjectID.None)
{
    return PugTilemap.TileType.ground;   // place ground *instead*, then the wall
}
```

Placing a wall on a tile with neither ground nor bridge silently lays ground
first. This mod is the same idea with rail→bridge instead of wall→ground, which
is why it should feel native rather than bolted on.

### Why the rail is refused today

`PlacementHandler.ShouldCheckPlaceObjectOnTile` (`Pug.Other:295735`) gates the
non-walkable tile types behind per-item flags:

```csharp
bool flag3 = placementCD.canPlaceOnWater  && tileData.tileType == TileType.water && tileData.tileset != 3;
bool flag4 = placementCD.canBePlacedOnLava && tileData.tileType == TileType.water && tileData.tileset == 3;
bool flag5 = placementCD.canPlaceOnPit    && tileData.tileType == TileType.pit;
```

Those flags come from the equipped item's `ObjectPropertiesCD` in
`PlacementHandler.Activate` (`Pug.Other:296019-296036`) — `canPlaceOnPit` from
`Has(-1827158511)`, `canPlaceOnWater` from `Has(-1324171664)`,
`canBePlacedOnLava` from `Has(-1535225238)`.

**Which objects carry those properties is not derivable from the decompile** —
`Activate` shows what each hash *does*, not who *has* it. That bridges carry
them and rails do not is inferred from in-game behaviour, not from source. The
tile layer rules below are the part that *is* provable.

### What the tile layer rules do prove

`TileType.GetNeededTile` (`Pug.Base:18111`) is the authority on what may sit on
what, and it is checked again when the tile buffer is applied:

| Tile | Requires (any of) |
|---|---|
| `rail` (with `wall`, `floor`, `fence`, `rug`, …) | `ground`, `bridge` |
| `bridge` | `pit`, `water` |

`GetInvalidTile` (`Pug.Base:18155`) adds the mirror pair: `bridge` is invalid
where `ground` is present, and `ground` is invalid where `bridge` is.

Two consequences for this design:

1. **The ordering requirement is proven, not assumed.** A `rail` whose tile has
   neither `ground` nor `bridge` is rejected at apply time, so the bridge must
   be applied first.
2. **`ground || bridge` — not `IsWalkableTile()` — is the correct test** for
   "does this tile already carry the rail". `IsWalkableTile` also accepts
   `floor`, `rug`, `litFloor`, `looseFlooring` and `rail` itself, which is a
   wider set than the engine checks here.

Bridges being defined over `pit` **and** `water` also settles the water half of
the borrowed-scope question at tile level (lava is `water` with `tileset == 3`,
so it is covered here too — but whether the *placement* check permits it still
depends on the item's `canBePlacedOnLava` property).

`TileType.bridge` **is** walkable (`Pug.Base:17781`, `IsWalkableTile` lists both
`bridge` and `rail`), so a rail on top of a bridge is already vanilla-legal. The
two-step sequence needs no special casing — only the ordering.

## Decisions

| Question | Decision |
|---|---|
| Bridge source | **player inventory only** — no chests |
| Trigger scope | **wherever the game lets the player build a bridge** — not a hardcoded tile list |
| Order of bridge types | **fixed default in v1**; configurable in v1.1 |
| Config surface | Mod Settings Menu consumer API (`enabled` toggle) |
| Approach | **borrow the bridge's placement flags**, let vanilla decide |
| `requiredOn` | `3` (ClientAndServer) |
| Rail teardown | bridge stays — two independent tiles, deliberately no rollback |

> ## ⚠️ SUPERSEDED IN PART — read this first (2026-08-08, after implementation)
>
> **The central mechanism below is wrong.** Verified in-game: bridges do **not**
> carry `canPlaceOnPit` / `canPlaceOnWater` / `canBePlacedOnLava`. Those flags read
> `False` on a real `WoodBridge` — on the database prefab *and* in `PlacementCD`
> while it is equipped. "Borrowing the bridge's flags" therefore borrows nothing,
> and **Hook 1 never worked**; because its guard gated Hooks 2 and 3, those were
> unreachable dead code.
>
> The real permission route is a second, independent branch in
> `ShouldCheckPlaceObjectOnTile` (`Pug.Other:295775`):
> `ObjectCanBePlacedOnObject(<ObjectID the target tile maps to>, …,
> canBePlacedOnObjects)`. That list lives on the **prefab** under property hash
> **`-789473209`** (the two list hashes are passed *crossed* at `:295631`).
> Measured: `WoodBridge = [Water, Pit, Lava]`, `Rail = [ConveyorBelt,
> ElectricalDoor]`.
>
> **What ships instead:** a bake-time prefix on
> `PugDatabasePostConverter.PostConvert` adds `Pit` and `Water` to Rail's list
> (`RailPlacementPropertyPatch`). Permission must exist *before* placement runs —
> `PlaceItem` returns at `:311322` when `canPlaceObject` is false, so no hook can
> justify a placement after the fact. Hook 2 remains the gate: no bridge carried,
> no placement.
>
> Everything below about Hooks 2 and 3, the double-debit protection, the
> `optionalTargetObjectID` guard and the tile ordering is **still accurate and
> shipping**. Only the permission mechanism changed. Full account:
> `.superpowers/sdd/2026-08-08-auto-rail-bridges/progress.md`.

### Scope is borrowed, not enumerated

The mod does **not** test for `pit`, `water` or `lava`. It copies the chosen
bridge prefab's placement flags onto the held rail and lets the vanilla check
decide. Wherever a bridge may be built, the rail may be too.

This matters for two reasons. First, whether bridges are allowed over water or
lava is **not derivable from the decompiled code** — the flags are three
independent properties in the baked database, and `canPlaceOnPit` does not
imply the others. Borrowing sidesteps the question entirely. Second, a game
update that adds a bridge type or a new bridgeable tile is inherited for free.

### Default order: ascending `ObjectID`

The nine bridge types (`Pug.Base:2755-2799`):

| ObjectID | Name |
|---|---|
| 4703 | `WoodBridge` |
| 4707 | `StoneBridge` |
| 4712 | `ScarletBridge` |
| 4717 | `CoralBridge` |
| 4721 | `GalaxiteBridge` |
| 4724 | `GlassBridge` |
| 4729 | `GleamWoodBridge` |
| 4773 | `MetalGrateBridge` |
| 4802 | `ExcavationBridge` |

Consumed in that order: the first type the player actually carries wins, so a
valuable bridge is only touched once every cheaper one is gone. Pugstorm
assigns IDs as content ships, so the sequence roughly tracks biome progression
and therefore roughly tracks scarcity — "roughly" being the honest word:
`GlassBridge` and `MetalGrateBridge` are probably later in this list than their
material cost warrants. Material costs live in the baked database and were not
verifiable from the decompile.

No type is excluded. Exclusion would produce the worst failure mode of an
unconfigurable v1 — a player carrying only higher-tier bridges would see the
mod do nothing and have no way to find out why.

## Architecture

### Why three hooks and not one

The obvious shape — one prefix on `PlaceObjectSlot.PlaceItem` that lays the
bridge and debits the item — is wrong, because **`PlaceItem` runs more often
than a placement actually happens.** It protects itself *inside* the method:

| Guard | Location |
|---|---|
| `if (!valueRW.canPlaceObject) return;` | `Pug.Other:311322` |
| `CanPlaceItem` → `tilePlacementTimer` (0.65 s) | called at `Pug.Other:311332`; declared at `:311533`, timer logic `:311538-311555` |
| `timeSincePlaced.isRunning && … < 1f && pos == positionLastPlacedAt` | `Pug.Other:311337` |
| `PlayerController.CanConsumeEntityInSlot` | `Pug.Other:311350` |
| creative / `ObjectType.PlaceablePrefab` check | `Pug.Other:311354` |

A prefix runs **before all of them**. Debiting a bridge there loses one item per
discarded input tick.

`EntityUtility.AddTile` (`Pug.Other:311379`), immediately followed by vanilla's
own `ConsumeEntityAt`, is the **first point past every one of those guards** —
which is the property this design needs.

It is *not* the point at which a tile becomes real: `AddTile`
(`Pug.Other:256440`) only appends to `TileUpdateBuffer`, and validity is
re-evaluated later when the buffer is applied. That distinction matters for the
failure mode (below), not for the guard argument. Hence a sandwich:

### The three hooks

**Hook 1 — `PlacementHandler.UpdatePlaceablePosition` prefix**
(`Pug.Other:295381`)

1. Equipped item is `ObjectID.Rail`? Otherwise return.
2. Scan the player's inventory for the first bridge in **priority order** — the
   order wins, not the slot index. The read needs no extra plumbing: the hook
   already receives `LookupEquipmentUpdateData`, which carries
   `BufferLookup<ContainedObjectsBuffer> containedObjectsBufferLookup`
   (`Pug.Other:419083`); `UpdateJob.Execute` reads it for
   `equipmentUpdateAspect.entity` in exactly this way (`:419886`).
3. Bridge found → set the bridge prefab's placement flags on `PlacementCD`
   (`canPlaceOnPit`, `canPlaceOnWater`, `canBePlacedOnLava`,
   `canBePlacedOnLowColliders`).
4. **No bridge → clear those same four flags.**

Step 4 is not symmetry for its own sake: it makes the hook's output a function
of the current inventory alone, never of the state it was entered with.

**Corrected 2026-08-08.** An earlier draft justified this by claiming vanilla
only re-initialises the flags on an equipment change —
`PlacementHandler.Activate` is called from
`SelectedEquipmentChangeSystem.EquippedSlotChangeJob` (`Pug.Other:427117`, call
at `:427333`), and the name was read as the cadence. It is not:
`SelectedEquipmentChangeSystem.OnUpdate` schedules that job **unconditionally
every tick** (`:428254-428257`, no `SetChangedVersionFilter`), and the
`Activate` call sits *outside* the equip-change branch above it. Vanilla does
reset the flags per tick.

The clear stays, on the stronger footing: a hook must not depend on another
system's cadence, nor on the relative order in which the two run. Idempotence
that rests on an assumption about foreign scheduling is not idempotence.

Owning all four flags makes Hook 1 **idempotent** and independent of how often
`Activate` runs. It is safe because the hook only engages while `ObjectID.Rail`
is held, and a rail never carries these properties itself — so there is nothing
of vanilla's to destroy.

Vanilla then computes `bestPositionToPlaceAt` and `canPlaceObject` as usual, so
the placement indicator turns green **only** when a bridge is genuinely
available.

This is the hook, not `PlacementHandler.Activate`, for a hard reason: `Activate`
takes `(ref PlacementCD, Entity placementPrefab, ComponentLookup<ObjectPropertiesCD>,
ComponentLookup<TileCD>, ComponentLookup<PseudoTileCD>)` — **no player entity**,
therefore no inventory access, therefore no way to condition the flags on
actually owning a bridge. `UpdatePlaceablePosition` receives the whole
`EquipmentUpdateAspect`.

**Hook 2 — `PlaceObjectSlot.PlaceItem` prefix** (`Pug.Other:311319`)

Decides, but does not act:

- Not a rail, or the target tile already has `ground` **or** `bridge`
  (`tileAccessor.HasType(pos.ToInt2(), …)` for both) → return `true`, vanilla
  proceeds untouched. This mirrors exactly what `ApplyAdd` will check for the
  rail; `IsWalkableTile()` would be a wider set than the engine uses.
- Substrate missing **and** a bridge available → record `(player entity, slot
  index, bridge ObjectID, target position)` in a `[ThreadStatic]` pending field.
  Consume nothing. Return `true`.
- Substrate missing and **no** bridge → return `false`, aborting `PlaceItem`
  entirely. Nothing placed, nothing consumed.

That last branch is load-bearing. Without it a stale `canPlaceObject` could let
vanilla lay a rail over an unbridged pit.

**Hook 3 — `EntityUtility.AddTile` prefix**

Vanilla calls it as
`AddTile(entityObjectInfo.tileset, tileTypeToPlace, new int2(pos.x, pos.z), isCreative, tileUpdateBuffer)`,
so the prefix can identify the rail placement from its own arguments.

Executes what Hook 2 promised. If a pending record matches this call
(`tileType == TileType.rail` at the recorded position):

1. `AddTile(bridgeTileset, TileType.bridge, pos, isCreative, tileUpdateBuffer)`
   — into the *same* buffer, *before* the rail.
2. `InventoryChangeBuffer` ← `Create.ConsumeEntityAt(playerEntity, slotIndex, 1,
   destroy: true, dontConsume: godMode, position, variation,
   **optionalTargetObjectID: bridgeID**)`.
   `ConsumeEntityAt(Entity inventory, int index, …)` (`Pug.Other:407732`) takes
   any inventory entity, so the player's own is straightforward.

   **`optionalTargetObjectID` is mandatory here, not optional.**
   `InventoryUtility.ConsumeEntityAt` (`Pug.Other:409859`) compares the slot's
   `objectID` against it **only when it is set**:

   ```csharp
   if (optionalTargetObjectID != ObjectID.None
       && …containedObjectsBufferLookup[inventory][index].objectID != optionalTargetObjectID)
       return false;
   ```

   Left at `None`, the recorded bridge ID would be dead weight and a queued
   inventory operation that changes that slot before the request is processed
   would make the mod consume whatever is now there. With it set, a mismatch
   makes the consume fail instead — the bridge tile is then placed without a
   debit (a free bridge), which is the acceptable direction for this failure.
3. Clear the pending record.

`bridgeTileset` comes from `PugDatabase.GetEntityObjectInfo(bridgeID).tileset` —
the same source vanilla uses one line later for the rail.

A **`PlaceItem` postfix** clears the pending record on every other path, so a
vanilla early-return between Hook 2 and Hook 3 cannot leak state into the next
tick.

### Why writing the bridge first is correct

Both tiles go into one `TileUpdateBuffer`, bridge first. The buffer is then
**reversed twice** on its way into the world, which restores the original order:

- `UpdateSubMapCommon.FilterUpdates` (`Pug.Other:240546`) walks the buffer
  backwards (`for (int num = tileUpdates.Length - 1; num >= 0; num--)`) while
  building `addList`
- `ApplyAdd` (`Pug.Other:241602`) walks `addList` backwards as well

So the bridge, written first, is applied first — which is exactly what
`GetNeededTile(rail)` requires. A single reversal anywhere in that chain would
invert this; it is worth re-checking after a game update.

All three hooks additionally run in the **same tick** of the same
`UpdateEquipment` call, so no player input can change the inventory between
them.

### The one genuine failure mode

Because the debit is queued at `AddTile` time but validity is judged at apply
time, a bridge can be charged for a tile that is then rejected. The consequence
is bounded: `ApplyAdd` does not silently swallow a rejected tile, it drops the
corresponding item into the world via `EntityUtility.DropNewEntity`
(`Pug.Other:241659`). The player has to pick it up rather than losing it.

For this mod the case should be unreachable anyway — Hook 1 only turns the
cursor green where vanilla's own placement check passed, which tests the same
tile state `ApplyAdd` re-tests. It is listed because "unreachable by
construction" is a claim to verify in-game, not to assume.

### Files

| File | Purpose |
|---|---|
| `AutoRailBridgesMod.cs` | `IMod` bootstrap; registers the settings section |
| `ModConfig.cs` | `enabled` toggle + the priority list (root namespace, per family convention) |
| `BridgeSelector.cs` | inventory scan in priority order via `LookupEquipmentUpdateData.containedObjectsBufferLookup` (`Pug.Other:419083`, used the same way in `UpdateJob.Execute` at `:419886`); shared by Hook 1 and Hook 2 |
| `PlacementPatch.cs` | Hook 1 |
| `PlaceItemPatch.cs` | Hooks 2, 3 and the clearing postfix |

Every `in`/`ref` parameter needs `argumentVariations` in its `[HarmonyPatch]`
attribute, or Harmony fails to bind with "Undefined target method".

## Error handling

| Case | Behaviour |
|---|---|
| No bridge in inventory | Hook 1 **clears** the four borrowed flags → cursor stays red → identical to vanilla. No custom feedback; vanilla gives none either |
| Last bridge just spent | same path: the next Hook 1 pass clears the flags, so the cursor goes red again without waiting for an equipment change |
| Substrate missing, bridge unexpectedly unavailable | Hook 2 aborts `PlaceItem` — nothing placed, nothing consumed |
| Creative / god mode | as vanilla: `AddTile(…, isCreative, …)`, debit suppressed via `dontConsume: godMode` |
| `enabled = false` | all three hooks return immediately; behaviour bit-identical to vanilla |
| Rail torn down later | bridge remains — two independent tiles |
| Multiplayer | `requiredOn: 3` ensures both sides have the mod installed, and both write through the same buffers vanilla uses for the rail itself. That the prefixes execute identically on a dedicated server, a host client and a predicted remote client is **not** established — see open unknown 3 |

## Not in this iteration

- **Configurable order** — fixed default; needs a string/list declaration in the
  Mod Settings Menu consumer API, which does not exist yet (see below)
- **Bridges from nearby chests** — no vanilla precedent in CK for consuming from
  remote containers; multiplayer race conditions and no UI feedback
- **Objects other than rails** (conveyor belts, fabricators)
- **Teardown symmetry** — removing the rail does not remove the bridge

### The v1.1 dependency, stated precisely

`SectionBuilder` (`mod-settings-menu/unity/ModSettingsMenu/Settings/SectionBuilder.cs`)
exposes `Toggle`, `Slider`, `Choice<T>`, `Stepper`, `Hint`, `SortOptions`,
`RequiresRestart` — no free-string declaration. `Choice<T>` binds a
`ConfigEntry<string>` but constrains it with
`new AcceptableValueList<string>(tokens)` (line 100), so an arbitrary order
string cannot pass through it.

`SettingKind.List` exists but is produced **only** by `ForeignConfigDiscovery`
for foreign CoreLib entries, never by the consumer API — stated explicitly in
`docs/specs/2026-07-28-list-widget-editing-design.md` §2. That spec's §5 also
lists **reordering tokens** as a non-goal.

So v1.1 needs, in Mod Settings Menu and not here: a declaration path for a
free string (rendering as `SettingKind.Info` would already make it visible,
`List` makes it editable), and ideally a reorder affordance — because for this
use case moving an entry up is the operation that matters, not retyping nine
names.

## Open unknowns

1. **Is `EntityUtility.AddTile` reachable by Harmony?** It is also called from
   Burst systems. The call from `PlaceItem` is managed, so the patch should
   bind, but this is unverified.
   **Fallback:** replicate the three vanilla guards (`tilePlacementTimer`, the
   `timeSincePlaced` duplicate check, `CanConsumeEntityInSlot`) inside the
   `PlaceItem` prefix and act there. Functionally equivalent, but it duplicates
   vanilla logic — hence a fallback, not the plan.
2. **Is `PlacementHandler.UpdatePlaceablePosition` reachable?** It is called
   from the same `UpdateEquipment` context as `PlaceObjectSlot.PlaceItem`
   (`Pug.Other:311305` vs `:311319`), which `reusable-cattle-box` already
   patches successfully without `BurstDisabler`. Strong indication, not proof.
3. **Do the hooks execute identically across all multiplayer topologies?**
   `EquipmentSystemGroup` (`Pug.Other:418855`) runs in both the server and the
   client simulation world, `EquipmentUpdateSystem.UpdateJob` is a **scheduled
   job**, and the borrowed `PlacementCD` flags are **not `GhostField`s**
   (`Pug.ECS.Components:4297-4314`) — they are local-only state. `requiredOn: 3`
   guarantees the mod is *installed* on both sides; it does not prove the
   prefixes run in the same order on a dedicated server, a host client and a
   predicted remote client. Must be verified on a real multiplayer session
   before the mod is described as multiplayer-safe.
4. **Which objects carry `canPlaceOnPit` / `canPlaceOnWater` /
   `canBePlacedOnLava`?** Not in the decompile — these live in the baked
   database. That rails lack them and bridges carry them is inferred from
   behaviour. The tile-layer half (`rail` needs `ground || bridge`, `bridge`
   needs `pit || water`) *is* proven (`Pug.Base:18111`). Verification test 5
   settles the water case empirically; lava depends on a fourth property no
   cited source confirms for any bridge.
5. ~~**Is fake mod.io ID `9999989` free?**~~ **Resolved 2026-08-08: it is not.**
   The block below `9999990` had already been entered by an **eleventh** mod,
   `refill-ore-boulders`, which is absent from the parent `CLAUDE.md` roster.
   This mod uses **`9999988`**. The lesson stands for the next mod: derive the
   next free ID from the `.envrc` files on disk, never from a `CLAUDE.md` list.

## Verification

No automated tests in this family — verification is a manual in-game pass.
Tests 4-7 each prove one design claim rather than checking routine behaviour.

1. Options → Mod Settings shows "Auto Rail Bridges" with `enabled`
2. Rail + wood bridges, one click on a pit tile → bridge **and** rail placed,
   **exactly one** wood bridge debited
3. No bridge carried → cursor stays red, nothing consumed
4. **Spend the very last bridge, keep the rail equipped, keep aiming at a pit →
   the cursor must go red immediately, without switching items.** This is the
   test of Hook 1's idempotence; a merely additive hook leaves the borrowed flag
   set until the next `PlacementHandler.Activate`
5. **Hold the button and drag across a multi-tile chasm → exactly one bridge
   per tile.** This is the test of the sandwich; a prefix-side debit would
   over-charge here
6. **Same over water.** The tile rules say `bridge` needs `pit || water`
   (`Pug.Base:18149`), so this should work — it verifies that the *placement*
   property agrees with the *tile* rule
7. **Two players, one host: place rails over a chasm from the non-host client.**
   Verifies open unknown 3 — that the prefixes behave the same in the predicted
   client path as on the server
8. Wood **and** stone carried → stone is untouched until the wood runs out
9. `enabled = false` → behaviour identical to vanilla
10. Check `build.log` / `Player.log` for `Undefined target method` — the tell for
    missing `argumentVariations`

## Identity

| | |
|---|---|
| Repo | `auto-rail-bridges` |
| Namespace | `AutoRailBridges` |
| displayName | `Auto Rail Bridges` |
| `requiredOn` | `3` (ClientAndServer) — writes tiles *and* inventory |
| Dependencies | CoreLib, ModSettingsMenu |
| Fake mod.io ID | `9999989` (to be confirmed, see open unknowns) |

`requiredOn: 3` is about *installation*, not about correctness — the runtime
multiplayer behaviour is open unknown 3. It follows the family pattern: the mods with server-relevant
effects (`reusable-cattle-box`, `rebalance-key-crafting`) use `3`; the
display-only ones (`item-checklist`, `player-coordinates-hud`) use `1`.

## Deliverables beyond the scaffold

- Square mod.io logo at `unity/AutoRailBridges/Editor/logo.png` in the family
  style, gesture: a rail segment crossing a gap on a gold bridge span
- `localization.yaml` (EN/DE) for the settings section
- `README.md`, `CHANGELOG.md`, `CLAUDE.md`, `modio-description.md`
- An ADR for the three-hook sandwich — the decision worth preserving is *why*
  the commit point is `AddTile` and not the `PlaceItem` prefix
