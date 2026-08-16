# PugDatabase and bake-time data

Core Keeper's object catalog — every item, placeable, creature and recipe — is
authored in the Unity project as `ObjectInfo` data and *baked* into immutable
ECS blobs at world-conversion time. This chapter covers how to read that catalog
at runtime (`PugDatabase`), how to change a vanilla object's baked values before
they freeze, and the data conventions around it: variations and paint, item
level and sell value, display names for foreign-mod items, and the script
fileIDs that let you reference game components from a mod's prefab YAML.

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
- **All of these types live in the global namespace** — `PugDatabaseAuthoring`,
  `DatabaseConversionUtility`, `PrefabData`, `ObjectInfo`. No `using` gets you
  to them and none is needed.

### Trap: `CraftingObject` is ambiguous — use `var`

The element type of `requiredObjectsToCraft` exists twice: as a **class** in
`Pug.Base` and as a **struct** in `Pug.ECS.Authoring`. Both are in the global
namespace, and a mod's runtime asmdef references both DLLs. Naming the type
anywhere in this code — a local declaration, a `foreach` element type, a method
signature — is a hard `CS0104` ambiguous-reference compile error.

Iterate with `var` and never write the type name. Reading the element into a
`var` local, mutating it, and assigning back through the list indexer (as
above) is also the shape that works regardless of which of the two it resolves
to.

### Why bake time and not the craft path

The obvious alternative — patching the runtime craft — is closed. The path is
`InventoryUpdateSystem` → `ProcessCraftingJob` → `InventoryUtility.Craft`, and
it is **double Burst-compiled**: not patchable, and not rescuable with
`BurstDisabler`. Bake time is the supported seam, not a shortcut.

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

**`PaintableObjectCD` is the clean cosmetic filter.** It is an (essentially
empty) marker component on objects the player can paint, and it is exactly what
separates real colour variants from the chest/seed state-junk above. Note its
namespace: `PaintableObjectCD` is in the **global** namespace, *not*
`Pug.Properties`, even though the related `PaintToolCD` and
`PaintableObjectSerializedCD` sit in `Pug.ECS.Components`.

To display a real colour name instead of "variation 7", map the `paintIndex`
back to the brush's enum name and strip the `PaintBrush` prefix:
`((ObjectID)id).ToString()` is sandbox-safe. The result is an English colour
word, which you then run through your own localisation terms — see
[Localisation](localisation.md).

**Reading a list-valued property** (for example a breeding palette of possible
child variations) goes through `Pug.Properties.ObjectPropertiesCD.TryGetList`.
That type needs `PugProperties.dll` in your runtime asmdef's
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
entries, which is exactly the failure mode the generated map removes. See
[the README](../../README.md) for the tooling, and
[Reverse engineering](reverse-engineering.md) for producing the decompile it
reads.

If you ever do need the hash by hand (no decompile available): **MD4 is often
disabled** in OpenSSL 3 and on macOS, so `hashlib.new('md4')` may simply fail
— use a pure-Python MD4 implementation, and always validate a new computation
against a known anchor from your own prefab before trusting derived values.

The practice of editing prefab YAML itself — nesting, variants, what the Editor
will and will not preserve — belongs to
[Prefabs and rendering](prefabs-and-rendering.md).
