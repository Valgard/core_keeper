# PugDatabase and bake-time data

Core Keeper's object catalog — every item, placeable, creature and recipe — is
authored in the Unity project as `ObjectInfo` data and *baked* into immutable
ECS blobs at world-conversion time. This chapter covers how to read that catalog
at runtime (`PugDatabase`), how to change a vanilla object's baked values before
they freeze, how a new item becomes craftable at a vanilla station or drops from
a vanilla loot table, and the data conventions around it: naming objects in the
enums, variations and paint, item level and sell value, display names for
foreign-mod items, and the fileIDs that let a mod's prefab YAML reference game
components and sprites.

## Changing a vanilla object's baked data

**The authoring converters run twice: once at boot, and again per ECS world.**
`ECSManager` finds every converter in the assembly, enqueues the whole
`pugDatabase.prefabList`, and converts it immediately at startup; then
`ECSManager.ConvertAuthoringData` reconverts the same prefab list per world,
from `StartEcs`, for both the server and client worlds.
`PugDatabasePostConverter` — the hook this chapter recommends below — is
registered into that same pipeline, and its post-converters run only after the
converters have. What is actually immutable is the *result*: once a conversion
builds it, the values you want to change (recipe ingredient amounts, craft
time, sell value) live in a `BlobArray`, and each conversion rebuilds that
blob fresh from the authoring `ObjectInfo` objects.

Two supported hooks reach *conversion*: the SDK's `API.Authoring
.OnObjectTypeAdded`, which hands you each entity as it is converted, and
CoreLib's `[EntityModification]` / `[PrefabModification]` attributes, which
dispatch through it. Both operate on the ECS components of an already-converted
entity — which is the right level for adding or replacing a component, and the
wrong one for the authoring values that get copied into the blob.

> **The example below is 1.2 code.** 1.3 removed `DatabaseConversionUtility`
> and `ObjectInfo.prefabInfos`, so it no longer compiles: the loader reports
> `CompileFailed` with `CS0103: The name 'DatabaseConversionUtility' does not
> exist`. `PostConvert` itself now reads the prefabs from
> `ScriptableData.GetDataBlocks<EntityAuthoringDataBlock>()` (`Pug.Other:3718`),
> so that is the list a 1.3 prefix would walk; `rebalance-key-crafting` and
> `auto-rail-bridges` carry such prefixes, unreleased, and neither has been
> seen running — **unverified**. The runtime station lookup further down has both forms.

For those — recipe ingredient amounts, craft time, sell value — the window
where the data is still mutable is
`PugDatabasePostConverter.PostConvert(GameObject authoring)` — the method that
walks the authoring prefab list and copies each value into the blob. Harmony-
**prefix** it, mutate the authoring `ObjectInfo` objects, and let the original
run: the bake then copies your values.

```csharp
[HarmonyPatch(typeof(PugDatabasePostConverter), nameof(PugDatabasePostConverter.PostConvert))]
static class ScaleRecipeCosts
{
    // PostConvert re-fires per world conversion over PERSISTENT ObjectInfo
    // instances — without this guard the edit compounds on every world load.
    static readonly HashSet<ObjectInfo> Done = new HashSet<ObjectInfo>();

    static bool Prefix(GameObject authoring)
    {
        if (!authoring.TryGetComponent<PugDatabaseAuthoring>(out var db))
            return true;

        foreach (var prefab in DatabaseConversionUtility.GetPrefabList(db))
        {
            var info = prefab.ObjectInfo;
            if (info == null || !Done.Add(info))
                continue;

            var required = info.requiredObjectsToCraft;
            for (int i = 0; i < required.Count; i++)
            {
                var req = required[i];          // never name the element type
                int scaled = req.amount / 4;
                req.amount = scaled < 1 ? 1 : scaled;
                                                // no write-back: the element is
                                                // a class, so this mutated it
            }
        }

        return true;   // always let the original bake run
    }
}
```

Four things about this pattern are load-bearing:

- **`PostConvert` is managed, not Burst.** It manipulates `List`, `GameObject`,
  `BlobBuilder` and `EntityManager`, so the prefix binds normally — **no
  `BurstDisabler` call is needed**. See [Harmony and ECS](harmony-and-ecs.md) for how patch binding
  works and when Burst *does* get in the way.
- **The bake is a straight copy**, e.g.
  `blob.amount = objectInfo.requiredObjectsToCraft[j].amount`. Whatever you
  leave in the list is what ships into the blob — you are not fighting a
  transform.
- **Idempotency is your problem.** `PostConvert` fires once per world
  conversion, over `ObjectInfo` instances that persist across those
  conversions. A `static HashSet<ObjectInfo>` (or an equivalent one-shot guard)
  is mandatory; without it, a ×0.25 recipe scaler quarters the cost again on
  every world load.
- **None of these types needs a `using`.** `PugDatabaseAuthoring`,
  `DatabaseConversionUtility` and `ObjectInfo` are in the global namespace;
  `PrefabData` is a struct nested inside `DatabaseConversionUtility`, so spelled
  out it is `DatabaseConversionUtility.PrefabData` — which is exactly what `var`
  in the loop above saves you from writing.

### Trap: `CraftingObject` is ambiguous — use `var`

The name `CraftingObject` is taken twice, by two unrelated types that identify an
item in two different ways:

| How you spell it | Where it is declared | Shape |
|---|---|---|
| `CraftingObject` | a **class**, global namespace (`Pug.Base:4709`) | `{ ObjectID objectID; int amount; }` |
| `InventoryItemAuthoring.CraftingObject` | a **struct** nested inside `InventoryItemAuthoring` (`Pug.ECS.Authoring:2896`) | `{ string objectName; int amount; }` |

Only the first is global, so a bare `CraftingObject` resolves to it and the
compiler never has to choose between the two — there is no `CS0104` to trip over
here. The ambiguity is the reader's: the bare name does not say which of the two
you are holding, and they disagree about the one thing that matters, how the
item is named.

Iterate with `var` and never write the type name. Where you must name the nested
one — in a method signature, say, where `var` is not available — qualify it in
full; that is what CK's own bake code does (`foreach
(InventoryItemAuthoring.CraftingObject item in …)`, `Pug.ECS.Authoring:3031`),
and CoreLib too. Reading the element into a `var` local, mutating it, and
assigning back through the list indexer (as above) is the shape that works for
both — and is not optional for the nested struct, where the local is a copy.

### Trap: a config value the bake reads must be bound in `EarlyInit`

There are two kinds of conversion, and `Init` falls between them. Measured on
1.3.0.6 in a client log and a dedicated-server log of the same mod set, the order
is identical on both sides:

1. `EarlyInit`, every mod.
2. **The startup conversion**, in `ECSManager.Init`: it registers the
   post-converters, `PugDatabasePostConverter` among them (`Pug.Other:3115`),
   and converts the server authoring prefab once (`Pug.Other:2550`,
   `Pug.Other:2553`, `Pug.Other:2554`). A `PostConvert` prefix fires here — its
   log lines come before `PugDatabase initialized` and before any mod's `Init`.
3. `Init`, every mod, then `Update` — in the same loader call (below).
4. **The per-world conversions**, from `ECSManager.StartEcs`: on a client when a
   world is entered, on a dedicated server when it starts its world. The server's
   `StartEcs` runs the loader's update before it converts
   (`DedicatedServer/Pug.Other:2785`), so a mod not yet initialised is
   initialised there first. Through 1.2 a dedicated server ran `Init` *after*
   `StartEcs`; [Harmony and ECS](harmony-and-ecs.md#the-dedicated-server-trap) has that measurement.

This section used to put the world conversions before `Init` as well, which no
1.3 log shows. What it concluded still holds, because `PostConvert` already runs
in step 2: a value your prefix consumes *during* the conversion must be read and
bound in `EarlyInit`.

Bound in `Init`, the startup bake has already run and copied the **hard-coded
default** instead — and the idempotency guard that `PostConvert` needs anyway
then freezes that default in place, so the world conversions copy it too.
Restarting does not repair it: the ordering is the same every session, so a
one-line timing mistake becomes a permanent one.

**The loader calls every mod's `Init` before any mod's `Update`.** Its update is
`_modHandlers.Call.Init()` followed by `_modHandlers.Call.Update()`
(`PugMod.Loader:1216`, `PugMod.Loader:1217`), and the first loops over every
handler not yet initialised (`PugMod.Loader:844`). The order of `Init` between
two mods that do not depend on each other is not yours to choose, but the first
`Update` comes after all of them. So an edit to a list that other mods also edit
from `Init` — a station's `canCraftObjects`, for one — belongs in the first
`Update` if it has to see their entries: that is still before the world
conversion that bakes the list. Measured in Complete Tools on 1.3.0.6, whose
first `Update` found Caveling Divining Rod's Iron Workbench entry, written in
that mod's `Init`, on client and dedicated server alike.

`API.ConfigFilesystem` is initialised before any mod's `EarlyInit`, so reading
configuration that early does work — see [storing configuration and state](persistence.md).
The lifecycle itself is in [Mod anatomy](mod-anatomy.md).

| A value that is… | Read it in | Tell the player |
|---|---|---|
| read live at runtime | `Init` | takes effect immediately |
| consumed by the bake | `EarlyInit` | requires a restart |

### Why bake time and not the craft path

The obvious alternative — patching the runtime craft — is closed to a plain
Harmony patch. The path is `InventoryUpdateSystem` → `ProcessCraftingJob` →
`InventoryUtility.Craft`, and it is **Burst-compiled twice over**:
`InventoryUpdateSystem` is a `[BurstCompile] ISystem` (`Pug.Other:427456`), and
the work sits in the separately `[BurstCompile]`d `IJob` it schedules
(`ProcessCraftingJob`, `Pug.Other:427823`; scheduled at `Pug.Other:428180`, calling
`InventoryUtility.Craft` at `Pug.Other:427876`).

**The distinction that matters is which `BurstDisabler` call.**
`DisableBurstForSystem<InventoryUpdateSystem>()` does not reach it — that takes
the *system's* `OnUpdate` off Burst and leaves the job it schedules to run its
own Burst-compiled form. A nested job needs `DisableBurstForSystemAndJobs<T>()`
(`PugMod.SDK.Runtime:709`), which additionally completes the system's job
dependency inside the un-Bursted window. That variant is verified to make
patches fire on another `ISystem` whose work sits in a nested `[BurstCompile]`
job, but whether it does the same for the craft path is **unverified** — see [Harmony and ECS](harmony-and-ecs.md)
for how it works and what it costs.

Bake time remains the seam this chapter recommends: one edit at conversion time,
against a per-craft patch on a hot simulation path that has to be taken off Burst
to exist at all.

## Adding an item and making it craftable

**A new item needs no CoreLib.** It is a prefab authored in the Editor carrying
`ObjectAuthoring` + `InventoryItemAuthoring`. Its own craft materials sit on
`InventoryItemAuthoring.requiredObjectsToCraft`, a `List<CraftingObject>` whose
elements are `{ objectName: string, amount: int }`. CoreLib is needed for UI,
not for the item.

**Since 1.3 the prefab also needs an `EntityAuthoringDataBlock`, or the item
is missing from the database.** `PugDatabasePostConverter` builds the database
bank from `ScriptableData.GetDataBlocks<EntityAuthoringDataBlock>()` and nothing
else (`Pug.Other:3718`); through 1.2 the prefab list also took in the loader's
`Manager.mod.ExtraAuthoring`, which is why a 1.2 mod needed no block.

What a missing block looks like was measured in `caveling-divining-rod` on
1.3.0.2, with CoreLib's `EntityModule` loaded: the rod still resolved to an
`ObjectID` — which path assigned it is not traced; any converted
`ObjectAuthoring` prefab gets one, whether a block or another prefab pulled it
into the conversion ([below](#where-a-modded-items-objectid-comes-from)) — so its Iron Workbench recipe resolved
(`moddedObjectID` goes through `API.Authoring.GetObjectID`,
`Pug.ECS.Conversion:1765`) and an extra crafting window opened, because that
test only asks for a non-`None` ID (`Pug.Other:339027`, the check at
`Pug.Other:339061`). The slot inside it stayed empty, because drawing one asks
the bank (`PugDatabase.HasObject`, `Pug.Other:430819`), and nothing could be
crafted. No error was logged.

**Most 1.3 item mods ship the block as an asset.** StoragePlus, ChestsGalore,
DoubleChest, Extra Pouches and MoreScenes all carry `EntityAuthoringDataBlock`
assets in their bundles; ChestsGalore's pre-1.3 build carried none. The
alternative, which `caveling-divining-rod` uses and CoreLib uses for the
workbenches it generates, is to create the block at runtime:

```csharp
public void EarlyInit()
{
    var mod = API.ModLoader.LoadedMods.FirstOrDefault(m => m.Handlers.Contains(this));
    var authoring = mod.Assets.OfType<GameObject>()
        .Select(go => go.GetComponent<ObjectAuthoring>())
        .First(a => a != null && a.objectName == "MyItem");

    var block = API.DataBlocks.CreateRuntimeInstance<EntityAuthoringDataBlock>(mod.ModId);
    block.prefab = authoring.gameObject;
    block.name = "MyItem";
    authoring.authoringRef = block;
}
```

- **It has to be `EarlyInit`.** Runtime blocks are refused once ScriptableData
  has started loading — the loader throws and says so (`PugMod.Loader:2288`).
- **Take the prefab from `LoadedMod.Assets`.** In `caveling-divining-rod`,
  `AssetBundle.LoadAsset<GameObject>("<prefab name>")` returned null in game
  for a prefab that `Assets` contained; why is **unverified**.
- `First` throws when the prefab is missing, and the loader prints only the
  first exception any mod throws from a lifecycle call, so a real mod should
  test and log instead — as `caveling-divining-rod` does.
- The authored asset is untried in this repository.

**The two ways of naming an item in recipe data are asymmetric** — this is the
part that catches people:

| Data | Keyed by |
|---|---|
| an item's own ingredient list (`InventoryItemAuthoring.requiredObjectsToCraft`) | **string** — `objectName` |
| a station's craftable list (`CraftingAuthoring.canCraftObjects`) | **`ObjectID`**, with a string fallback |

The element type of `requiredObjectsToCraft` is the ambiguous `CraftingObject`
from the trap above — write `var`, never the type name. It resolves to the
declaration nested inside `InventoryItemAuthoring`: the string-keyed
`{ objectName, amount }` **struct**, not the `objectID`-keyed `Pug.Base` class
that `ObjectInfo.requiredObjectsToCraft` uses. Because it is a struct, mutating
the `var` copy and assigning it back through the list indexer is not optional
here.

### Where a modded item's `ObjectID` comes from

**During play, a modded item's `ObjectID` is a counter value handed out by the
first entity conversion of the process, in the order the conversion queue
reaches the prefab.** Nothing derives it from the name, and no ID table is
exchanged or reconciled between processes — the IDs themselves cross the
network all the time, in ghost snapshots and in the craft request below. Traced
on build `1.3.0.5-cb48`, client and dedicated server alike:

1. `API.Authoring.GetObjectID(name)` is a dictionary lookup and nothing else
   (`Pug.Other:410222`); a name that is not in it returns `ObjectID.None`.
2. The lookup is written during conversion, first value wins: by
   `ObjectConverter` for every converted `ObjectAuthoring` prefab
   (`Pug.ECS.Conversion:3572`), and by `EntityMonoBehaviourDataConverter` with
   the vanilla prefab's own enum value (`Pug.ECS.Conversion:5818`).
3. The index a prefab converts under is its *preferred* index if it has one,
   otherwise the next value of a counter (`PugConversion:1044`,
   `PugConversion:1046`). Every converted object without a preferred index takes
   a value, item or not. An `ObjectAuthoring` prefers the ID its `objectName`
   already resolves to (`Pug.ECS.Authoring:2992`, `Pug.ECS.Authoring:2983`) — so
   on the first conversion a modded item has none and takes the counter, and
   every later conversion reuses that value. The counter starts above the
   highest vanilla `ObjectID`, at no less than 32768 (`PugConversion:712`,
   `Pug.Other:2607`).
4. The first conversion is `ECSManager.Init`, which converts the server
   authoring prefab once at startup (`Pug.Other:2553`). Its
   `PugDatabaseConverter` enqueues the prefab of every `EntityAuthoringDataBlock`,
   **sorted by the block's address** (`Pug.Other:3640`, `Pug.Other:3643`; the
   comparison is the address GUID, `ScriptableData:1808`). A prefab can also
   enter the queue because a converted prefab references it — a
   `PugPrefabBufferAuthoring` list does that (`Pug.ECS.Conversion:3507`) — and
   then it gets an ID with no block of its own. The loader's
   `RegisterAuthoringGameObject` (`Pug.Other:279067`) only lists a prefab in
   `ExtraAuthoring`. Startup enqueues only the server authoring prefab
   (`Pug.Other:2553`) and hands that list, after the conversion, to
   `PugDatabase.UpdateEntityMonos` (`Pug.Other:2555`), which reads the
   prefabs' `ObjectInfo` rather than converting them; no other use of the list
   in the decompile enqueues it. That is the likeliest reading
   of the blockless rod above, which resolved to an ID all the same; which
   reference pulled it in is not traced.
5. `API.DataBlocks.CreateRuntimeInstance<T>(modId)` — the call this chapter's
   example uses, and CoreLib uses for its generated workbenches — gives the
   block a fresh `Guid.NewGuid()` (`PugMod.Loader:2236`, `ScriptableData:71`),
   on every launch, the same machine included.

So a runtime block created that way lands at a random place in the sort, in each
process separately, and the counter values it and every other modded prefab
receive follow from that place. A host's client and server worlds share one
process and one lookup, so a host always agrees with itself. **A second process
— a dedicated server, or a player joining someone else's game — may give the
same item a different `ObjectID`**, and several items registered this way may
come out in a different order on each side. The dedicated-server decompile runs
the identical path (`DedicatedServer/Pug.Other:2542`,
`DedicatedServer/Pug.Other:3617`, `DedicatedServer/PugMod.Loader:2236`). Nothing
at connect time would notice: the connect request carries a hash over the ghost
collection (`Pug.Other:2599`), not the ID table. This is read from the code; the
mismatch has not been observed in game.

**Saves are the exception, and the strongest sign that the game treats these
IDs as unstable.** Both save paths translate modded IDs back by name on load. A
world save keeps the name of every ID, and `DefaultConvertSystem` renumbers
every ID from 32767 up through that name (`Pug.Other:176409`,
`Pug.Other:176415`, `Pug.Other:176425`). A character save stores
`inventoryObjectNames` beside the IDs (`Pug.Other:381160`), and loading
re-resolves each modded slot with `API.Authoring.GetObjectID`
(`Pug.Other:133539`, `Pug.Other:133541`). Neither runs during play: crafting,
synced entities and the UI all use the raw ID.

**A stable address is not a stable `ObjectID`.** Two ways to the first, neither
measured: ship the block as an asset, whose address is serialised with it, or
call the overload that takes an address, `CreateRuntimeInstance<T>(modId,
address)` — the loader then derives the block's address from a SHA-256 of the
mod's manifest GUID and the given address (`PugMod.Loader:2262`,
`PugMod.Loader:2295`), the same on every machine for one build of the mod. What
the overload's `m_overload` side effect does is [below](#scriptabledata-blocks-addresses-and-order). Either way, the IDs are
only as stable as everything else that consumes the counter: another mod's
random-address block still sorts among yours — CoreLib creates one for every
workbench it generates — and a mod installed on only one side shifts every value
after its own.

### The recipe entry: `CraftingAuthoring.CraftableObject`

A station's craftable list is `CraftingAuthoring.canCraftObjects`, declared
`public List<CraftableObject>`. `CraftableObject` is a struct **nested inside
`CraftingAuthoring`**, not a top-level type — reference it accordingly.

Beside `objectID`, `moddedObjectID`, `amount`, `entityAmountToConsume` and
`craftingConsumesEntityAmount` — the `[ShowIf]` gate for `entityAmountToConsume`
— the struct carries `allowCraftingNone`, `craftingTime`, `hasPrerequisites`
and a nested `Prerequisites` struct.

**`Prerequisites` gates a recipe on game progress.** It keys off the presence or
absence of content bundles and off individual boss kills — fields such as
`birdBossKilled`, `octopusBossKilled`, `scarabBossKilled` and
`hydraBossNatureKilled`.

**Trap: `moddedObjectID` is only read while `objectID` is `ObjectID.None`.** The
string field carries `[ShowIf("objectID", ObjectID.None)]`, so a modded recipe
entry must leave `objectID` unset. A `[ShowIf]`-gated field looks optional; for
a modded item it *is* the mechanism.

**A `None` slot is a layout gap, not a free slot.** Vanilla `canCraftObjects`
lists carry `ObjectID.None` placeholders, and the idiom other mods follow
overwrites the first of them instead of appending. What a placeholder actually
does follows from how the station window is drawn, below: it pads a group out to
the six-slot boundary, so the next group begins in a window of its own. An item
written into one appears in the group that gap pads.

**Trap: `CraftingAuthoring.OnValidate` silently discards `moddedObjectID`.** Any
entry with `amount <= 0` is rewritten to a fresh `CraftableObject` that keeps
only `objectID`, forces `amount = 1`, and re-derives
`craftingConsumesEntityAmount` from the station's `craftingType` (true for
`CraftingType.Cattle`) — the string id is gone, with no error and nothing in the
console. This is Editor-only and does not affect the runtime injection
below, but it destroys a hand-written modded entry in a prefab. Give every
modded entry an `amount` of at least 1.

### Injecting a craftable into a vanilla station at runtime

There is a runtime path that bypasses the bake entirely, and **CoreLib is not
involved in it**: find the station's authoring prefab, and mutate its authoring
list. 1.3 removed `DatabaseConversionUtility` and `ObjectInfo.prefabInfos`, so
the way to the prefab depends on the game version. (Extra Pouches reaches the
same list through `API.Authoring.OnObjectTypeAdded` instead, which hands over
each authoring object as it converts and is the same on 1.2 and 1.3.)

| Step | Since 1.3 | Through 1.2 |
|---|---|---|
| 1 | `ScriptableData.GetDataBlocks<EntityAuthoringDataBlock>()` | `DatabaseConversionUtility.GetPrefabList(Manager.ecs.pugDatabase)` |
| 2 | the block whose `prefab`'s `IEntityMonoBehaviourData.ObjectInfo.objectID` is the station | the `DatabaseConversionUtility.PrefabData` whose `ObjectInfo.objectID` is the station |
| 3 | `block.prefab` | `ObjectInfo.prefabInfos[0].ecsPrefab` |
| 4 | its `CraftingAuthoring.canCraftObjects` | its `CraftingAuthoring.canCraftObjects` |

`ScriptableData.GetDataBlocks` lives in `ScriptableData.dll`, which an asmdef
created before 1.3 may not reference — `ScriptableData.Addressables.dll`
is a different assembly and does not resolve the type. Both columns are
verified in game in single-player, the first by `caveling-divining-rod` on
1.3.0.2; neither has been measured on a dedicated server.

**Now established, from the conversion pipeline above:** conversion reconverts
the whole prefab list per world, rebuilding the blob from the authoring data
on each pass — so a `canCraftObjects` list mutated from `Init` is read by the
next per-world conversion, not lost to it. Whether it also needs the same
re-entrancy guard a `PostConvert` prefix needs remains open.

### A craft carries the `ObjectID`; the server checks materials

Clicking a recipe sends the item's `ObjectID`, not a slot or a name: the station
window calls `CraftItem(player, objectID, …)` (`Pug.Other:334113`), which queues
a craft action built from that ID (`Pug.Other:305187`). The crafting job runs on
the server, and on the client as predicted crafting (`Pug.Other:427908`). It
drops a craft from a non-admin on a read-only (guest-mode) world
(`Pug.Other:427851`), then hands the ID to `InventoryUtility.Craft`
(`Pug.Other:427876`; dedicated server `DedicatedServer/Pug.Other:423184`), whose
gate is `InventoryUtility.CanCraft` (`Pug.Other:430203`): for a cooking pot its
two ingredients, for a station that consumes its own stack
(`craftingConsumesEntityAmount`) only that stack's amount, and otherwise the
output slot, the material tag and the materials the requested ID's recipe lists.
**None of these asks whether the station offers the item.** Read from the code,
not tried in game: a recipe the station's list does not carry would still be
crafted when the ID arrives, and an ID that means a different item on the server
would craft that item, at that item's cost. Which is why [where the ID comes from](#where-a-modded-items-objectid-comes-from)
matters in multiplayer.

### How a station window lays out the list: six slots, three windows

A station drawn by `SimpleCraftingUIContainer` (`Pug.Other:338979`) cuts its
recipes into windows of six slots — `MAX_RECIPES_PER_UI = 6`
(`Pug.Other:338981`). `ShowCraftingUI` walks the list in six-slot ranges and
opens a window only for a range holding at least one non-`None` entry
(`Pug.Other:339027`); an empty range is skipped and the windows after it close
up. So the list index decides which range an entry falls into, not which
on-screen position it ends up in.

**The metal workbenches show their own list as one category among several.**
From Copper to Solarite, each workbench names every lower-tier workbench in
`CraftingAuthoring.includeCraftedObjectsFromBuildings` — Copper names Wood,
Solarite names Wood through Galaxite. The conversion appends those lists to the
station's own (`Pug.ECS.Conversion:1690`) and records one
`IncludedCraftingBuildingsBuffer` entry per list, the station's own first
(`Pug.ECS.Conversion:1707`). `CraftingBuilding.OnSpawn` turns those into
category ranges (`Pug.Other:318136`), and `ShowCraftingUI` then walks only the
active category, counting its six-slot ranges from the category's own start.
The Wood workbench and the Relucite Smithing Table include nothing and show one
list. Two consequences:

- An entry added to a lower workbench's list also appears in that workbench's
  category on every higher one — the authoring list is shared, and each
  category's length is read from it at conversion.
- The six-slot arithmetic below applies per category, so for a metal workbench
  "slot 18" means the 19th entry of its *own* list, not of the merged buffer.

**Vanilla has three windows per view.** The container's window list is
serialized with three entries (`simpleCraftingUIs` in `Global Objects (Main
Manager).prefab`). A fourth range with at least one recipe in it logs `Not
enough SimpleCraftingUIs in SimpleCraftingUIContainer to show all recipes`
(`Pug.Other:339031`) and its entries never render — the recipe exists, it just
has nowhere to appear. On 1.3.0.5 the own list of every metal workbench from
Copper to Solarite already holds 18 entries, so on those an appended recipe
needs a fourth window.

**The vanilla lists use the windows as groups.** On those workbenches the first
window holds tools and gear and the second further stations, up to Galaxite
including the next tier's workbench; the third is mostly walls, floors and other
building pieces, though Copper's and Tin's also hold decoration and stations.
The Galaxite and Solarite benches leave the unused tail of their first and
second windows as `None`. So an appended entry lands in whatever range its
index falls into, and overwriting a gap moves an item into the group the gap
belongs to.

**Window titles are a separate per-station list, and a missing one warns every
frame.** `CraftingBuilding.buildingSpecificUISettings` names each window per
station (`CraftingUISettings.titles`), falling back to `defaultUISettings` for a
station it does not list. For a window index past the end of the titles, the
window shows the default title and logs `Missing title for crafting UI window
index …` (`Pug.Other:370852`) — from `Update` (`Pug.Other:370819`), so once per
frame while the station is open. A mod that adds a window should add its title
too.

A fourth window needs more `SimpleCraftingUI` instances in the container. This
workspace's `simple-crafting-pool-extender` adds them: a postfix on
`SimpleCraftingUIContainer.Awake` clones the last entry up to a fixed ceiling of
five windows, and a second postfix on `CraftingCategoryNavigationUI.LateUpdate`
positions the navigation widget, whose offset vanilla hardcodes for one to three
windows only. DoubleChest carries a window patch of its own. A mod whose recipe
needs a fourth window depends on one of them.

The idiom of overwriting the first `None` — Extra Pouches and DoubleChest both
use it — falls back to appending once no `None` is left, and both test only
`objectID == ObjectID.None`, so either would also overwrite another mod's entry
that names its item through `moddedObjectID`.

## Adding an item to a vanilla loot table

Loot tables are baked like recipes. `LootTableConverter.Convert` builds the
loot blob from `Manager.mod.LootTable` in play mode
(`Pug.ECS.Conversion:2551`), so a mod edits that list before the conversion
runs. CoreLib's `LootDropModule` does exactly this, applied once per process by
a prefix on `LootTableConverter.Convert`. `AddNewDrop(LootTableID,
DropTableInfo)` and `EditDrop` take the item by name and resolve it through
`API.Authoring.GetObjectID` at that point, which suits a modded item whose
`ObjectID` is assigned at load; `RemoveDrop` takes an `ObjectID`.

**The two lists in a table are rolled differently, and only one of them
tolerates an appended entry.**

| List | Rolled by | An appended entry |
|---|---|---|
| `lootInfos` (random drops) | `weight`, summed over the list at roll time (`Pug.Other:326339`) | is weighed in correctly |
| `guaranteedLootInfos` | `accumulatedDropChance`, precomputed (`Pug.Other:326289`) | is not reached |

`accumulatedDropChance` is computed by `LootTableBank.InitLoot`
(`Pug.Base:17334`) from `OnAfterDeserialize` (`Pug.Base:17292`), which the
game calls when it loads the table (`Pug.Mods:714`, from `Pug.Other:279189`) —
before CoreLib's edit, which runs at conversion. So a `LootInfo` appended
afterwards keeps its default of 0, while the existing entries' accumulated
values already run up to 1 over a roll drawn from `[0, 1)`: the appended entry
is never reached, whatever value it is given. CoreLib's `AddDrops` appends every
added drop to both lists, skipping one already present, and computes no
`accumulatedDropChance`. For an ordinary random drop the guaranteed copy is
therefore inert and the random copy works; a drop meant to be guaranteed would,
by the same reading, never arrive. This is source reading only and
**unverified** in game.

**A weight is not a percentage.** The `editorVisualDropChance` shown beside
each entry in the asset is derived from the weight, the list's total weight
and the table's average unique-drop count, so the weight that yields a target
chance depends on the table it is added to.

## ScriptableData blocks: addresses and order

`EntityAuthoringDataBlock` above is one of many `ScriptableDataBlock` types;
map-marker icons, text and skins are others. What follows holds for all of
them, and matters as soon as anything stores a reference to a block.

**A block's identity is its address.** `DataBlockAddress` is a `Guid` overlaid
on two `long`s, `m_low` at offset 0 and `m_high` at offset 8
(`ScriptableData:34-45`). A block asset stores those two fields, so writing
one by hand means taking the GUID's .NET byte layout — the byte order Python's
`uuid.UUID(...).bytes_le` produces — and reading bytes 0–7 and 8–15 each as a
signed little-endian 64-bit integer. Verified on 1.3.0.2: five assets written
that way registered under exactly the intended addresses. A saved reference —
a map marker's icon, for one ([world and mechanics](world-and-mechanics.md#since-13-a-user-markers-icon-is-a-data-block)) — holds this
address and nothing else.

**A runtime block created without an address gets a new one on every launch.**
`CreateRuntimeInstance<T>(modId)` passes `DataBlockAddress.NewAddress()`
(`PugMod.Loader:2236`), which is `Guid.NewGuid()` (`ScriptableData:71`). So no
saved reference can name such a block by its address: in a probe mod on 1.3.0.2,
markers placed with a runtime icon lost it at the next restart — observed,
without a recorded test. That concerns references by address only. An item built
on a runtime block survives a restart in a save because the save does not trust
its `ObjectID`: world and character saves carry each modded item's name and are
renumbered by name on load ([how a modded item gets its ID](#where-a-modded-items-objectid-comes-from)), which is how
CoreLib's and caveling-divining-rod's runtime blocks persist. The overload
taking an address is stable — the block's address is a SHA-256 over the mod's
GUID and the given address (`PugMod.Loader:2295`) — but it also records the
given address as the block's `m_overload` (`PugMod.Loader:2263`), declaring it
an overload of the block at that address. What that does depends on whether such
a block exists. If one does, `ScriptableData.Initialize` resolves the given
address to the runtime block (`ScriptableData:1341-1345`) and leaves the
original out of every runtime list (`ScriptableData:1361-1363`): the call
replaces it. If none does, the runtime block registers under its own hashed
address only (`ScriptableData:1327-1330`). Both cases are read from the code and
untried in game. A shipped asset avoids the question: it registers under the
`m_address` it carries.

**Within one loader, blocks are sorted by address.** Every loader's set is
sorted as it loads (`ScriptableData:1238` async, `ScriptableData:1264` sync),
and `ScriptableDataBlock.CompareTo` compares addresses (`ScriptableData:1808`).
`Initialize` then walks the loaders in registration order
(`ScriptableData:1284`) and appends each set to the typed lists
(`AddDataBlocksToRuntimeLists`, `ScriptableData:1350`). So a mod that wants the
blocks it ships as assets in a particular order gives them ascending addresses.
That does not carry over to runtime blocks: they sit in a runtime loader of
their own (`PugMod.Loader:2207`), and one created with an address is stored
under the hash above, so its position does not follow the address it was given.
Keeping the first hex digit of each at `0`–`7` sidesteps a question not checked
here: whether the GUID's first 32-bit field compares signed or unsigned on the
game's runtime.

**Across loaders, the order observed is not the one the code suggests.** The
addressables loader, which holds the game's own blocks, registers at
`AfterAssembliesLoaded` (`ScriptableData.Addressables:237`), before any mod is
loaded. Yet in one run on 1.3.0.2 the log listed every mod loader before it,
and the map-marker dialog showed a mod's icons in front of the game's. That was
observed without a recorded test: map-markers-enhanced's `docs/manual-tests.md`
("Icon order and scrolling") records only the order after that mod moved its
icons. The decompile does not explain it. Treat it as an observation, not as a
rule, and do not build on either order.

**`TryGetDataBlocks<T>` hands out the live typed list.** The `IReadOnlyList<T>`
it returns is the `List<T>` the registry itself keeps (`ScriptableData:1430`,
created at `ScriptableData:1375`), so a caller that casts it back to `List<T>`
can reorder it in place — and every later reader sees the new order until the
next ScriptableData load. That load's `Reset` empties the registry's
dictionaries (`ScriptableData:1180-1186`), not the lists they held, and the
rebuild creates a new list per type (`ScriptableData:1375`) in sorted order; the
reordered list is left behind rather than emptied, so a caller still holding it
keeps seeing the old order, while one that asks again gets the new list.
Reordering this generic typed list leaves runtime IDs alone: they come from a
separate untyped list and lookup (`ScriptableData:1383-1384`, read at
`ScriptableData:1446` and `ScriptableData:1490`), and lookup by address uses a
dictionary of its own (`ScriptableData:1526`). The non-generic
`TryGetDataBlocks(Type, …)` is a different matter: it hands out that untyped
list itself, just as live (`ScriptableData:1417-1421`), so reordering it would
change which block a runtime ID resolves to (`ScriptableData:1495`) while the
lookup keeps the old indices. Verified on 1.3.0.2: a Harmony prefix that moved a
mod's map-marker icons to the end of the generic list, before the dialog read
it, put them behind the game's icons (map-markers-enhanced,
`docs/manual-tests.md`, "Icon order and scrolling"). This is an implementation
detail; a later version could hand out a copy.

## Naming objects: `ObjectID`, `ObjectType` and class names

**Constant names are not derivable.** `ObjectID.IronWorkBench` capitalises the
B. Neither the in-game name nor the spelling of a sibling constant tells you how
a given constant is written — read it out of the enum instead of reconstructing
it. A wrong constant is at least a compile error, so this one fails loudly.

**Trap: the same identifier exists in unrelated enums.** `ObjectID.Slime` is
`1630`; `AreaLevel.Slime` is `0`. A grep hit proves the name exists, not that
you found the enum you meant — and picking the wrong enum fails *silently*,
which makes it the more expensive of the two mistakes.

**Trap: one identifier, three different things.** `DiggingSpot` resolves to a
`LootTableID` enum value (`50`), an `ObjectID` enum value (`5530`) **and** an
`EntityMonoBehaviour` class, with numerically unrelated values. (`ObjectType`
has no `DiggingSpot` member at all — which is its own reminder that "the enum I
expected" is a guess until read.) Confirm which of the three a search hit
belongs to before using its number.

**Biome variants split one logical object over several ObjectIDs.** Digging
spots occupy `5532`–`5536` for five biome variants beside the generic `5530`,
while CK's own checks (`objectID == ObjectID.DiggingSpot`, all three of them:
`Pug.Other:306891`, `Pug.Other:307309` and `Pug.Other:322506`, and in the server
build `DedicatedServer/Pug.Other:302705`, `DedicatedServer/Pug.Other:303123` and
`DedicatedServer/Pug.Other:318309`) test only the generic one. Filtering on a single
`ObjectID` then produces a mod that works in one biome and not in another —
which reads like a bug everywhere except at the filter. Biome variants are
common but not universal, so the rule is: **check the enum neighbourhood before
filtering on one ObjectID.**

## `PugDatabase.objectsByType` and the `(objectID, variation)` key

At runtime the catalog is `PugDatabase.objectsByType`, a
`Dictionary<ObjectDataCD, ObjectInfo>`. The key is **not** just the objectID:
`ObjectDataCD.Equals`/`GetHashCode` (in `Pug.ECS.Components`) include the
`variation` field, so the dictionary is keyed on the pair `(objectID,
variation)`.

That makes dictionary membership a genuine discriminator:

| Key state | Meaning |
|---|---|
| `(id, v)` present in `objectsByType` | **DB-authored** variation — it exists in the baked catalog |
| `(id, v)` absent | **Runtime-assigned** variation — created during play (cattle colours and similar), never authored |

**Trap: you cannot probe for a variation's existence via the getters.**
`PugDatabase.GetObjectInfo(id, v)` and `TryGetObjectInfo` **fall back to
variation 0** for an unauthored variation. They never return null for a valid
objectID, so "call it until it fails" does not enumerate a colour set — the only
"does this variation exist" signal is a direct lookup in `objectsByType`.

**Non-zero variations are common, and mixed.** An in-game sweep on 1.2.1.4
found roughly 600 DB-authored non-zero keys spread over 204 objectIDs (about
395 of the entries being `PlaceablePrefab`). They are not all cosmetic: the set
mixes paintable decor with pure state-junk — chest open/closed states (driven
by `variationToToggleTo` / `variationIsDynamic`) and seed growth stages. Any
catalog that enumerates variations needs a filter, not an assumption.

**Two fields look like a variation count and are not.**
`RandomObjectEnabler.variations` and `Pug.Sprite.SpriteAsset.staticVariantCount`
are appearance-randomisation mechanisms for sprites and GameObjects; neither
ever sets `ObjectDataCD.variation`, so both are irrelevant to discovering which
variations an object has. Do not re-chase them as a variant-count source — the
real palette source for cattle is the `PossibleChildVariation[]` property below.

### Trap: `ObjectDataCD.amount` is not a stack size everywhere

The struct's `amount` field is double-purposed. For **equipment**,
`amount` carries **durability**, not a stack count — a break check reads
`objectData.amount <= 0` immediately after a durability reduction. Counting a
full-durability tool as a stack of 50 is a real, shipped bug class.

This is verified for the equipment/durability case; establish which meaning
applies to the objects you enumerate before reading the field.

**On an object that shows a world label, `amount` is the label's visibility
state** — and still the drop count, which is where the two meanings collide.
`WorldLabel` hides the label at `0`, shows it at `1` only while the object is
the player's current interactable, and always otherwise (`Pug.Other:321349`,
`Pug.Other:321353`); the Hover check compares against the object's first
`InteractableObject` found with `GetComponentInChildren`, so one on a child
counts. The sign window's toggle writes it through the `SetWorldLabelVisibility`
RPC, whose server handler sets `amount` on whatever entity it is handed, with no
type check (`Pug.Other:415525`) — and drops it, like the text RPC, from a player
without admin rights on a guest-mode world (`Pug.Other:415251`; see [multiplayer and server](multiplayer-and-server.md#who-is-allowed-to-change-things-admin-level-and-guest-mode)).
A freshly placed sign was observed to start at `1`, which is why Hover is what a
new sign shows; vanilla offers no other default.

An object that drops itself when mined drops `max(1, amount)` unless the entity
has `AlwaysDropOneCD` (`Pug.Other:90860`, in `DropLootSystem.DropSelfJob`). A
label set to "always" sits at `2`, so without that component it would drop two.
Vanilla pairs the two: in the 1.3.0.4 assets the entity prefabs carrying
`DescriptionAuthoring` (the label text) and those carrying
`AlwaysDropOneAuthoring` are the same 80 — 77 chest entities and the three text
signs. The locked chests are the exception on both counts: the ten
`Locked*ChestEntity` prefabs and three `…_TitanTempleScene_*` variants of them carry
neither component.
A mod that gives a label to an object that had none has to add `AlwaysDropOneCD`
as well, and first, so that no partial failure of the rest leaves the label
without it. How such an object is made labelled at all is in [prefabs and rendering](prefabs-and-rendering.md#editing-a-vanilla-graphical-prefab-at-bake-time).

### Trap: `ObjectType.NonUsable` is where the raw materials live

Excluding `NonUsable` as engine junk silently drops every ore, bar, raw wood,
scrap and plain Wood from a catalogue. Measured on 1.2.1.4 the type held **126**
entries: **117** real materials, all of which carry an icon, and **9** internal
engine entities with neither an icon nor a localised name (four territory
spawners, `TheCore`, the `DroppedItem` entity, and three boss-statue prefab
stubs).

Filter on icon presence, not on the type:

```csharp
if (objectType == ObjectType.NonUsable && smallIcon == null && icon == null)
    continue;   // internal engine entity, not an item
```

The 117/9 split is pinned to 1.2.1.4; the predicate is not. Note that
ItemBrowser's `ObjectUtility.IsNonObtainable` does not exclude `NonUsable` at
all, so it is no substitute for this filter.

## Variations and paint

Player-applied paint colours are DB-authored variations. Fourteen paintbrushes
apply them, occupying a contiguous `ObjectID` block **70–83** in `Pug.Base`,
and the enum constant name *is* the English colour:

| ObjectID | Name | | ObjectID | Name |
|---|---|---|---|---|
| 70 | `PaintBrushRed` | | 77 | `PaintBrushBlack` |
| 71 | `PaintBrushYellow` | | 78 | `PaintBrushOrange` |
| 72 | `PaintBrushGreen` | | 79 | `PaintBrushCyan` |
| 73 | `PaintBrushPurple` | | 80 | `PaintBrushPink` |
| 74 | `PaintBrushBlue` | | 81 | `PaintBrushGrey` |
| 75 | `PaintBrushBrown` | | 82 | `PaintBrushPeach` |
| 76 | `PaintBrushWhite` | | 83 | `PaintBrushTeal` |

The link from brush to variation is `struct PaintToolCD { int paintIndex; }`
(`Pug.ECS.Components`): a brush's `paintIndex` **is** the `variation` it
applies. Measured in game, `paintIndex` ran **1–14** and matched the item
variations 1:1 — no off-by-one. Read it with
`PugDatabase.TryGetComponent<PaintToolCD>(brushOd, out var pt)`.

**`PaintableObjectCD` is the clean cosmetic filter, and it carries the colour.**
Its presence marks objects the player can paint, which is exactly what separates
real colour variants from the chest/seed state-junk above. It is not an empty
marker: it holds one field, `[GhostField] public PaintableColor color`. Note the
namespace — and note that `Pug.ECS.Components` is not one: `PaintableObjectCD`,
`PaintToolCD` and `PaintableObjectSerializedCD` all sit in the **global**
namespace, `Pug.ECS.Components` being the assembly they ship in. No `using`
reaches them and none is needed. The genuinely namespaced type in this section
is `ObjectPropertiesCD` — `Pug.Properties`, in `PugProperties.dll`.

To display a real colour name instead of "variation 7", read that field and name
its enum value — `paintable.color.ToString()`. `PaintableColor` (`Pug.Base`)
spells the colours out: `Unpainted`, then `Yellow`, `Green`, `Red`, `Purple`,
`Blue`, `Brown`, `White`, `Black`, `Orange`, `Cyan`, `Pink`, `Gray`, `Peach`,
`Teal`, closed by a `__max__` sentinel you should filter out. The result is an
English colour word, which you then run through your own localisation terms —
see [Localisation](localisation.md).

There is no need to go via the brushes for this. Enumerating `ObjectID` 70-83,
reading each brush's `PaintToolCD.paintIndex` and matching it back is a longer
route to the same word, and it breaks if the brush block ever moves.

**Reading a list-valued property** goes through
`Pug.Properties.ObjectPropertiesCD.TryGetList<T>`. The cattle breeding palette
is one of these:

```csharp
properties.TryGetList(239678920, out NativeArray<BreedStateCD.PossibleChildVariation> value,
    (AllocatorManager.AllocatorHandle)Allocator.Temp);
```

The element type is nested in `BreedStateCD`, which is itself in the global
namespace — `ObjectPropertiesCD` is the component you call `TryGetList` on, not
the declaring type. The id is the constant
`Pug.Properties.PropertyID.Breed.PossibleChildVariations` (plural), `239678920`.
`ObjectPropertiesCD` needs `PugProperties.dll` in your runtime asmdef's
`precompiledReferences` — check for it before assuming the type is reachable.

**Floors and walls are tilemap, not entities**, so per-colour tracking of a
painted floor is not an entity query — only placeable *entities* (rugs and
similar furniture) can be counted that way. See [World and mechanics](world-and-mechanics.md)
for the tile side.

## Item level and sell value

Both of these are easy to get wrong straight from `ObjectInfo` field names.

### Level: `ObjectInfo.level` is dead

`ObjectInfo.level` is a legacy field — **read nowhere** in the game, and broadly
0. The live value is the ECS component `LevelCD`:

```csharp
int level = PugDatabase.TryGetComponent<LevelCD>(od, out var cd) ? cd.level : 0;
```

Only upgradeable / levelled gear carries `LevelCD`; for everything else 0 is the
correct answer, not a lookup failure.

**The "level" in the in-game tooltip is a different number entirely.** It is
pets-only, computed per instance from XP (`SlotUIBase.GetLevel` →
`PetExtensions.GetLevelFromXP(amount)`), and unrelated to the catalog level.

### `sellValue == -1` means "auto-compute", not "unsellable"

A negative `sellValue` is a signal to derive the value, not a flag for an item
that cannot be sold. An item is genuinely unsellable only when:

- `PugDatabase.HasComponent<CantBeSoldCD>(od)`, **or**
- `rarity == Legendary` — legendaries return value 0.

For everything else the value is derived:

1. `GetRaritySellValue(rarity) = 1 + max(0, (int)rarity) * 5` is the base.
2. If `info.sellValue >= 0`, that value is used directly and the rest is
   skipped.
3. If `info.sellValue < 0`, the two cases diverge — and they are exclusive,
   not additive:
   - **cooked food** (`CookedFoodCD`): the value **is** the sum of the
     two ingredients' own values, resolved recursively via
     `CookedFoodCD.GetPrimaryIngredientFromVariation` /
     `GetSecondaryIngredientFromVariation`. The base plays no part and the fold
     in step 4 never runs.
   - **everything else**: `GetRaritySellValue(ingredientRarity) * amount`
     summed over `requiredObjectsToCraft`, **skipping any ingredient whose own
     `sellValue` is 0**.
4. For the craft case, when that sum is greater than zero, it is folded with the
   base as `round(max(1, base * 0.3) + extra)`.
5. **Levelled items add their upgrade cost.** When `variation > 0` and the item
   carries the upgrade tag, every step from the item's current `level + 1` up
   to its `variation` contributes — not the whole upgrade table:
   `AncientCoin` entries by their amount directly, everything else by
   `GetRaritySellValue(rarity) * amount`, **skipping any entry whose own
   `sellValue` is 0** just like the craft-ingredient case above — and a
   quarter of that total is added, `round(upgradeTotal * 0.25)`. Omit this and
   every upgradeable item comes out short.
6. Finally an objectID-seeded jitter,
   `Random.CreateFromIndex((uint)objectID).NextFloat(-0.1, 0.1)`, and a
   `max(1, …)` floor. The seed is the objectID, so the jitter is deterministic
   — the same item is worth the same in every session.
7. **This is the sell path (`buy == false`); the floored value is then
   multiplied by the stack's `amount`** when the item `isStackable`, or by 1
   otherwise: `num * (isStackable ? objectData.amount : 1)`. `GetCoinValue`
   returns the value of the whole stack, not of a single unit, on this path —
   a reader stopping at step 6 comes out low by that factor. With `buy ==
   true`, step 7 never runs: `GetCoinValue` returns earlier via
   `round(max(1, num) * 5 * buyValueMultiplier)` instead.

The authority is the game's own `InventoryUtility.GetCoinValue`. moorowl's
ItemBrowser carries a readable port of it
(`ItemBrowserPackage/Scripts/Utilities/ObjectUtility.cs`, alongside
`GetBaseLevel` and `GetRaritySellValue`) — useful to read, but it predates the
upgrade-cost term above and does not include it, which is worth knowing before
treating it as a reference.

All the types involved — `LevelCD`, `CantBeSoldCD`, `CookedFoodCD`, and
`Unity.Mathematics`' `math` and `Random` — compile inside the RoslynCSharp
sandbox; `Unity.Mathematics` needs to be referenced by your runtime asmdef. See [the load-time sandbox](sandbox.md).

## Display names for foreign-mod items

Any mod that enumerates `objectsByType` will hit items from *other* mods, and a
foreign mod that ships no I2 display term produces a null name — the same null
CK itself renders as `missing: Items/Mod:Name` in its tooltip.

| Call | Result for a term-less foreign item |
|---|---|
| `PlayerController.GetObjectName(buf, localize: true).text` | **`null`** — I2 `LocalizationManager.GetTranslation` returns null for a missing term |
| `PlayerController.GetObjectName(buf, localize: false).text` | the raw term path, e.g. `Items/Mod:Name` — never null |
| `API.Authoring.ObjectProperties.TryGetPropertyString(objectID, "name", out var n)` | `"Mod:InternalName"` — available regardless of localisation |

(I2 internally does `Term.Replace(':', '_')` on lookup, and `PugText.ProcessText`
turns the resulting null into `"missing: " + term`.)

**The fallback that produces something readable** is the third row: take the
`ObjectProperties` `"name"` string, strip the mod prefix up to the first `:`,
strip any CoreLib `$$N` suffix, then split the remaining PascalCase into words —
`Mod:WorkbenchChestExtra` becomes `Workbench Chest Extra`. That is strictly
better than falling back to the objectID: a **modded** `ObjectID.ToString()`
yields only the number, because there is no enum constant for it.

That last point is also a useful test in the other direction: an objectID whose
`ToString()` is **all digits** is modded. Every vanilla ID is a named enum
constant.

### CoreLib workbench chains are a mesh, not a tree

Mods that add crafting stations via CoreLib use
`CoreLib.Submodule.Entity.WorkbenchDefinition` (in the `CoreLib` assembly — one
asmdef, so referencing `CoreLib` is enough). Enumerating them is sandbox-safe:

```csharp
foreach (var mod in API.ModLoader.LoadedMods)
    foreach (var def in mod.Assets.OfType<CoreLib.Submodule.Entity.WorkbenchDefinition>())
        …
```

`WorkbenchDefinition.relatedWorkbenches` (runtime:
`ModCraftingAuthoring.includeCraftedObjectsFromBuildings`) is what makes opening
any one station show a single unified crafting UI with the I/II/III tabs.

**Trap: it is a mesh, not a chain.** Sibling workbenches reference the *named
base* workbenches as well, so the naive filter "this objectID is referenced by
another workbench ⇒ it is an internal continuation page" wrongly swallows the
real, user-facing base stations. Internal page objects (a mod's
`Workbench…Extra` / `Workbench…Next` entries) ship no display term and are
**leaves** — their own `relatedWorkbenches` is empty. The precise test for an
internal page is therefore: a *referenced* chain member that is a **leaf or
term-less**.

The CoreLib root workbench (`CoreLib:RootModWorkbench$$N`, "contains all modded
items") is a special case: it aggregates every mod workbench through each
entity's **`bindToRootWorkbench` flag**, not through `relatedWorkbenches`. Skip
it when walking the mesh.

## Script fileIDs in prefab YAML

When a mod prefab references a MonoBehaviour, the YAML line is
`m_Script: {fileID: …, guid: …}` — and the two halves have completely different
portability.

| Field | Scope | Rule |
|---|---|---|
| `fileID` | portable | Derived from the class name. Identical on every install and every SDK clone. |
| `guid` | per-SDK-clone | The `.meta` GUID of the DLL (e.g. `Pug.Other.dll.meta`), assigned randomly by the Unity Editor per clone. |

For a **game-DLL component**, Unity computes the fileID as the first 4 bytes,
little-endian signed int32, of `MD4("s\x00\x00\x00" + namespace + className)`
— empty namespace for global types.

**`namespace + className` is a plain concatenation, with no dot between them.**
`Affixes.Authoring` + `AffixAuthoring` is hashed as
`Affixes.AuthoringAffixAuthoring`, not as the dotted full name. Reading it the
other way is correct for every type that has no namespace and wrong for every
type that does — which is the worst available failure shape, because the table
keeps working most of the time and quietly resolves the wrong class the rest of
it. Measured against 1,647 known-good rows: 90.41 % correct with the dot,
100.00 % without.

Verified anchors — note that the first three are all **global** types, so they
pass either way and cannot catch the mistake. Calibrate against the last two:

| Type | fileID |
|---|---|
| `UIScrollWindow` | `197547074` |
| `ScrollBar` | `-277093456` |
| `ScrollBarHandle` | `-1490357010` |
| `Affixes.Authoring.AffixAuthoring` | `-1102179062` |
| `LootingProgress.Authoring.LootProgressAuthoring` | `-2121339178` |

The general lesson outlives this particular hash: **an anchor set that only
contains the easy case validates nothing.** Pick anchors that would come out
differently under the mistake you are trying to rule out.

For **a mod's own MonoBehaviours** there is usually no hash: they use
`fileID: 11500000`.

**Trap: that only holds for the class whose name matches the filename.** Unity
gives `11500000` to the one type it considers the file's script. A *second*
`MonoBehaviour` declared in the same `.cs` gets an MD4-hash fileID like a game
type — and prefab wiring against it then fails **silently**, with the component
simply never bound. Nothing in the Editor or the build complains.

The rule that avoids the whole class of problem: **one `MonoBehaviour` per
file, named after the file.**

One named exception is safe: an **abstract** `MonoBehaviour` base is
prefab-neutral. Unity serialises inherited public fields by name and never
instantiates the base, so hoisting shared serialized fields into an abstract
base needs no prefab change at all.

**Never copy a `guid` out of another repo's prefab.** The fileID transplants
cleanly; the GUID does not — read yours from any existing game-component
reference in your own prefab.

**Do not hand-hash.** A generated `{fileID: className}` map of this shape covers
every MonoBehaviour/ScriptableObject-derived game type, produced from the
decompile and aborting on any hash collision rather than guessing — an earlier
hand-maintained table had eyeballed-and-wrong entries, which is exactly the
failure mode the generated map removes. Generating one is a scripting job of its
own; see [Reverse engineering](reverse-engineering.md) for producing the decompile it reads.

If you ever do need the hash by hand (no decompile available): **MD4 is often
disabled** in OpenSSL 3 and on macOS, so `hashlib.new('md4')` may simply fail
— use a pure-Python MD4 implementation, and always validate a new computation
against a known anchor from your own prefab before trusting derived values.

### Sprite references: the fileID comes from the sprite's name

A prefab references a sub-sprite of a sheet the same way, with a third kind of
fileID:

```yaml
m_Sprite: {fileID: <internalID>, guid: <sheet guid>, type: 3}
```

The `guid` is the sheet's; the `fileID` is that sub-sprite's `internalID` from
the sheet `.meta`. And that `internalID` is **derived from the sprite's name** —
a signed int32 taken from the first 4 bytes, little-endian, of
`SHA1(final sprite name)`. (A sprite-sheet generator can author each
`.png.meta`'s `internalID` this same way, deterministically — not to
reproduce whatever Unity would itself assign, since that derivation is not a
documented Unity algorithm, but so a regenerated sheet keeps every reference
resolvable; a pin table exists to override the hash where one is needed.)

Two consequences follow:

- **Regenerating a sheet is safe** as long as the names do not change. Every
  sprite keeps its ID, and every prefab reference keeps resolving.
- **Trap: renaming a sub-sprite breaks every prefab reference to it, silently.**
  The new name yields a new `internalID`; the prefab still carries the old one,
  and the result is a missing or wrong sprite with no error anywhere. A rename
  is therefore never a one-step operation — every `m_Sprite` fileID that
  referenced the sprite has to be updated with it.

The practice of editing prefab YAML itself — nesting, variants, what the Editor
will and will not preserve — belongs to [Prefabs and rendering](prefabs-and-rendering.md).
