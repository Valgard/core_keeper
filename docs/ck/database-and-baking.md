# PugDatabase and bake-time data

Core Keeper's object catalog — every item, placeable, creature and recipe — is
authored in the Unity project as `ObjectInfo` data and *baked* into immutable
ECS blobs at world-conversion time. This chapter covers how to read that catalog
at runtime (`PugDatabase`), how to change a vanilla object's baked values before
they freeze, how a new item becomes craftable at a vanilla station, and the data
conventions around it: naming objects in the enums, variations and paint, item
level and sell value, display names for foreign-mod items, and the fileIDs that
let a mod's prefab YAML reference game components and sprites.

## Changing a vanilla object's baked data

**The authoring converters never run in the shipped game.** In the Editor,
authoring components are converted to entity data; in the shipped game that
conversion has already happened for vanilla content, and the values you want to
change (recipe ingredient amounts, craft time, sell value) live in a
`BlobArray` that is read-only once built. There is **no official API and no
CoreLib API** for editing vanilla object data.

The one window where the data is still mutable is
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
                required[i] = req;              // write back
            }
        }

        return true;   // always let the original bake run
    }
}
```

Four things about this pattern are load-bearing:

- **`PostConvert` is managed, not Burst.** It manipulates `List`, `GameObject`,
  `BlobBuilder` and `EntityManager`, so the prefix binds normally — **no
  `BurstDisabler` call is needed**. See [Harmony and ECS](harmony-and-ecs.md)
  for how patch binding works and when Burst *does* get in the way.
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
| `CraftingObject` | a **class**, global namespace (`Pug.Base:4541`) | `{ ObjectID objectID; int amount; }` |
| `InventoryItemAuthoring.CraftingObject` | a **struct** nested inside `InventoryItemAuthoring` (`Pug.ECS.Authoring:2848`) | `{ string objectName; int amount; }` |

Only the first is global, so a bare `CraftingObject` resolves to it and the
compiler never has to choose between the two — there is no `CS0104` to trip over
here. The ambiguity is the reader's: the bare name does not say which of the two
you are holding, and they disagree about the one thing that matters, how the
item is named.

Iterate with `var` and never write the type name. Where you must name the nested
one — in a method signature, say, where `var` is not available — qualify it in
full; that is what CK's own bake code does (`foreach
(InventoryItemAuthoring.CraftingObject item in …)`, `Pug.ECS.Authoring:2971`),
and CoreLib too. Reading the element into a `var` local, mutating it, and
assigning back through the list indexer (as above) is the shape that works for
both — and is not optional for the nested struct, where the local is a copy.

### Trap: a config value the bake reads must be bound in `EarlyInit`

The loader's order is: **`EarlyInit` (all mods) → database and world conversion
(`PugDatabasePostConverter.PostConvert`) → `Init` (all mods)**. A value your
prefix consumes *during* the conversion must therefore already be read and bound
in `EarlyInit`.

Bound in `Init`, the bake has already run and copied the **hard-coded default**
instead — and the idempotency guard that `PostConvert` needs anyway then freezes
that default in place. Restarting does not repair it: the ordering is the same
every session, so a one-line timing mistake becomes a permanent one.

`API.ConfigFilesystem` is initialised before any mod's `EarlyInit`, so reading
configuration that early does work — see [Sandbox and
config](sandbox-and-config.md). The lifecycle itself is in [Mod
anatomy](mod-anatomy.md).

| A value that is… | Read it in | Tell the player |
|---|---|---|
| read live at runtime | `Init` | takes effect immediately |
| consumed by the bake | `EarlyInit` | requires a restart |

### Why bake time and not the craft path

The obvious alternative — patching the runtime craft — is closed to a plain
Harmony patch. The path is `InventoryUpdateSystem` → `ProcessCraftingJob` →
`InventoryUtility.Craft`, and it is **Burst-compiled twice over**:
`InventoryUpdateSystem` is a `[BurstCompile] ISystem` (`Pug.Other:408486`), and
the work sits in the separately `[BurstCompile]`d `IJob` it schedules
(`ProcessCraftingJob`, `:408848`; scheduled at `:409176`, calling
`InventoryUtility.Craft` at `:408902`).

**The distinction that matters is which `BurstDisabler` call.**
`DisableBurstForSystem<InventoryUpdateSystem>()` does not reach it — that takes
the *system's* `OnUpdate` off Burst and leaves the job it schedules to run its
own Burst-compiled form. A nested job needs `DisableBurstForSystemAndJobs<T>()`
(`PugMod.SDK.Runtime:783`), which additionally completes the system's job
dependency inside the un-Bursted window. That variant is verified to make
patches fire on another `ISystem` whose work sits in a nested `[BurstCompile]`
job, but nobody has run it against the craft path — see [Harmony and
ECS](harmony-and-ecs.md) for how it works and what it costs.

Bake time remains the seam this chapter recommends: one edit at conversion time,
against a per-craft patch on a hot simulation path that has to be taken off Burst
to exist at all.

## Adding an item and making it craftable

**A new item needs no CoreLib.** It is a prefab authored in the Editor carrying
`ObjectAuthoring` + `InventoryItemAuthoring`. Its own craft materials sit on
`InventoryItemAuthoring.requiredObjectsToCraft`, a `List<CraftingObject>` whose
elements are `{ objectName: string, amount: int }`. CoreLib is needed for UI,
not for the item.

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

### The recipe entry: `CraftingAuthoring.CraftableObject`

A station's craftable list is `CraftingAuthoring.canCraftObjects`, declared
`public List<CraftableObject>`. `CraftableObject` is a struct **nested inside
`CraftingAuthoring`**, not a top-level type — reference it accordingly.

Beside `objectID`, `moddedObjectID`, `amount` and `entityAmountToConsume`, the
struct carries `allowCraftingNone`, `craftingTime`, `hasPrerequisites` and a
nested `Prerequisites` struct.

**`Prerequisites` gates a recipe on game progress.** It keys off the presence or
absence of content bundles and off individual boss kills — fields such as
`birdBossKilled`, `octopusBossKilled`, `scarabBossKilled` and
`hydraBossNatureKilled`.

**Trap: `moddedObjectID` is only read while `objectID` is `ObjectID.None`.** The
string field carries `[ShowIf("objectID", ObjectID.None)]`, so a modded recipe
entry must leave `objectID` unset. A `[ShowIf]`-gated field looks optional; for
a modded item it *is* the mechanism.

**Reuse an `ObjectID.None` slot rather than appending.** Vanilla
`canCraftObjects` lists carry `ObjectID.None` placeholders, and the established
idiom overwrites the first of those instead of adding an entry. Why the
convention exists is not verified — treat it as the idiom other mods follow.

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
involved in it**: walk the prefab list off the live database, find the station,
and mutate its authoring list.

| Step | Expression |
|---|---|
| 1 | `DatabaseConversionUtility.GetPrefabList(Manager.ecs.pugDatabase)` |
| 2 | pick the `DatabaseConversionUtility.PrefabData` whose `ObjectInfo.objectID` is the station |
| 3 | `ObjectInfo.prefabInfos[0].ecsPrefab` |
| 4 | its `CraftingAuthoring.canCraftObjects` |

**What is not established:** this path is known to work when called from `Init`
— that is, *after* the bake — and it mutates the authoring list rather than the
blob. Whether the change survives a further world conversion, or has to be
reapplied (or guarded against re-applying) the way a `PostConvert` prefix must
be, is open. Treat the idempotency question above as unanswered here rather than
as settled either way.

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
while CK's own checks (`objectID == ObjectID.DiggingSpot`, in `Pug.Other` at
`296438` and `310904`) test only the generic one. Filtering on a single
`ObjectID` then produces a mod that works in one biome and not in another —
which reads like a bug everywhere except at the filter. Biome variants are
common but not universal, so the rule is: **check the enum neighbourhood before
filtering on one ObjectID.**

## `PugDatabase.objectsByType` and the `(objectID, variation)` key

At runtime the catalog is `PugDatabase.objectsByType`, a
`Dictionary<ObjectDataCD, ObjectInfo>`. The key is **not** just the objectID:
`ObjectDataCD.Equals`/`GetHashCode` (in `Pug.ECS.Components`) include the
`variation` field, so the dictionary is keyed on the pair
`(objectID, variation)`.

That makes dictionary membership a genuine discriminator:

| Key state | Meaning |
|---|---|
| `(id, v)` present in `objectsByType` | **DB-authored** variation — it exists in the baked catalog |
| `(id, v)` absent | **Runtime-assigned** variation — created during play (cattle colours and similar), never authored |

**Trap: you cannot probe for a variation's existence via the getters.**
`PugDatabase.GetObjectInfo(id, v)` and `TryGetObjectInfo` **fall back to
variation 0** for an unauthored variation. They never return null for a valid
objectID, so "call it until it fails" does not enumerate a colour set — the
only "does this variation exist" signal is a direct lookup in
`objectsByType`.

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
similar furniture) can be counted that way. See
[World and mechanics](world-and-mechanics.md) for the tile side.

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

- `PugDatabase.HasComponent<CantBeSoldAuthoring>(od)`, **or**
- `rarity == Legendary` — legendaries return value 0.

For everything else the value is derived:

1. `GetRaritySellValue(rarity) = 1 + max(0, (int)rarity) * 5` is the base.
2. If `info.sellValue >= 0`, that value is used directly and the rest is
   skipped.
3. If `info.sellValue < 0`, start from the base, then add an ingredient
   contribution (`extra`):
   - **cooked food** (`CookedFoodAuthoring`): the sum of the two ingredients'
     values, resolved via
     `CookedFoodCD.GetPrimaryIngredientFromVariation` /
     `GetSecondaryIngredientFromVariation`;
   - **everything else**: `GetRaritySellValue(ingredientRarity) * amount`
     summed over `requiredObjectsToCraft`.
4. When `extra > 0`, the two are folded as
   `round(max(1, base * 0.3) + extra)`.
5. Finally an objectID-seeded jitter,
   `Random.CreateFromIndex((uint)objectID).NextFloat(-0.1, 0.1)`, and a
   `max(1, …)` floor. The seed is the objectID, so the jitter is deterministic
   — the same item is worth the same in every session.

The canonical implementation of this is `ObjectUtility.GetValue` (sell mode) in
moorowl's ItemBrowser (`ItemBrowserPackage/Scripts/Utilities/ObjectUtility.cs`),
alongside `GetBaseLevel` and `GetRaritySellValue`.

All the types involved — `LevelCD`, `CantBeSoldAuthoring`,
`CookedFoodAuthoring`, and `Unity.Mathematics`' `math` and `Random` — compile
inside the RoslynCSharp sandbox; `Unity.Mathematics` needs to be referenced by
your runtime asmdef. See [Sandbox and config](sandbox-and-config.md).

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
— empty namespace for global types. Verified anchors:

| Type | fileID |
|---|---|
| `UIScrollWindow` | `197547074` |
| `ScrollBar` | `-277093456` |
| `ScrollBarHandle` | `-1490357010` |

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

**Do not hand-hash.** This repo's tooling ships a generated
`{fileID: className}` map covering every MonoBehaviour/ScriptableObject-derived
game type, produced from the decompile and aborting on any hash collision
rather than guessing — an earlier hand-maintained table had eyeballed-and-wrong
entries, which is exactly the failure mode the generated map removes. Generating one is a scripting job of its own; see
[Reverse engineering](reverse-engineering.md) for producing the decompile it
reads.

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
`SHA1(final sprite name)`. (That is how this repo's sheet generator reproduces
the IDs Unity assigns, matching Unity's output; it is not a documented Unity
algorithm.)

Two consequences follow:

- **Regenerating a sheet is safe** as long as the names do not change. Every
  sprite keeps its ID, and every prefab reference keeps resolving.
- **Trap: renaming a sub-sprite breaks every prefab reference to it, silently.**
  The new name yields a new `internalID`; the prefab still carries the old one,
  and the result is a missing or wrong sprite with no error anywhere. A rename
  is therefore never a one-step operation — every `m_Sprite` fileID that
  referenced the sprite has to be updated with it.

The practice of editing prefab YAML itself — nesting, variants, what the Editor
will and will not preserve — belongs to [Prefabs and
rendering](prefabs-and-rendering.md).
