# Complete Tools — design

A published Core Keeper mod (`complete-tools` / `CompleteTools` / "Complete
Tools") that gives the five core tools — shovel, hoe, pickaxe, fishing rod and
sledge hammer — a variant in every material from Wood to Relucite, and lets
the player opt into crafting the tools vanilla only hands out as loot.

All game facts below were read from the decompile of build `1.3.0.5-cb48`
(assemblies and the AssetRipper export, Addressables included). Line
citations refer to that build.

## Goal and scope

**In scope (1.0):**

- Twelve new tools that fill the gaps in the material ladder.
- Two corrections to vanilla items that make the ladder regular.
- A per-player setting, off by default, that makes all nine sledge hammers —
  the six vanilla ones and the three new ones — the Garden Trowel, the Hand
  Drill and the Scarlet Hand Drill craftable.
- The three new hammers as loot, always on.

**Out of scope:** new variants of the Garden Trowel or the Hand Drill; any tool
type beyond the five; a larger hammer hit area; anything that needs MSM v2;
server-side enforcement of the setting (see *Multiplayer*).

**Success means:** every one of the 45 tool/material combinations is
obtainable in game; with the setting off, no hammer, Garden Trowel or Hand
Drill is offered at any workbench; no log spam, with the setting on or off;
client and server agree on which item a craft produces.

## The material ladder

| Tool | Wood | Copper | Tin | Iron | Scarlet | Octarine | Galaxite | Solarite | Relucite |
|---|---|---|---|---|---|---|---|---|---|
| Shovel | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | **new** | **new** |
| Hoe | ✔ | ✔ | ✔ | ✔ | ✔ | **new** | **new** | **new** | **new** |
| Pickaxe | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | **new** |
| Fishing rod | ✔ | **new** | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | **new** |
| Sledge hammer | **new** | loot | loot | loot | loot | loot | loot | **new** | **new** |

Relucite is the tier after Solarite: its gear (Void Fused armour, Minigun,
Flamethrower) sits at area `Excavation`, rarity Rare, level 18, crafted at the
Relucite Smithing Table (`VoidAltarWorkbench`).

## How a tool's values come about

Understanding this is what the numbers below rest on.

- **Level** = area base + rarity (`LevelScaling.GetLevelFromAreaLevelAndRarity`,
  `Pug.Base:15363`). Area bases: StartArea 1, Slime 2, Clay 4, Stone 6,
  Nature 8, Sea 10, Desert 12, Crystal 14, Excavation 16. Rarity adds −1
  (Poor) to +4. Set level only through area and rarity:
  `AreaLevelAuthoring.OnValidate` recomputes a hand-set `level` the next time
  the prefab is edited.
- **Power** (mining, digging, fishing) = base(level) × `valueMultiplier` ×
  a random factor in [0.9, 1.1], divided by the item's number of conditions
  (1 for every tool here), computed once at conversion
  (`ConditionExtensions.LevelToConditionValues`). The factor is seeded with
  `objectID + 1`, or for an `ObjectAuthoring` item with
  `objectName.GetHashCode()` — so it is fixed per item type, not per swing or
  instance, *provided* the string hash is stable across launches under Mono,
  which is unverified (test 6).
- **Combat damage** is derived from level and `damageMultiplier` by the game's
  weapon formula; the new tools copy their neighbour's multiplier, so no number
  is chosen here.
- **Durability** and **tile size** are plain prefab values.

Each tool type progresses differently, which is why each was checked against
its own mechanic:

| Type | Progression | Mechanic |
|---|---|---|
| Pickaxe, hammer | threshold | a hit whose damage after a wall's `DamageReductionCD.reduction` is ≤ 0 bounces (`Pug.Other:314129`); displayed damage is (20 + Σ mining) × (1 + mining %) |
| Fishing rod | threshold + speed | fishing power must reach the water's requirement `(level(area, Common) − 1) × 20` (`Pug.Base:17170`; dirt water takes the biome's requirement instead); surplus shortens the bite wait down to 50 % and eases the minigame |
| Shovel | speed + area | ground tiles have health, no reduction; digging damage is the digging power; area via `prefabTileSize` |
| Hoe | area only | no power condition; vanilla grows the area one step per tier |

The sledge hammer hits every target in its swing like an explosive
(`Pug.Other:314118`); its hit area (`baseHitColliderSize` 1.4, 270° arc) is
identical across all vanilla tiers.

## Game values of the new tools

Rules: tool-type traits (swing, reach, power multiplier, damage multiplier)
come from the vanilla neighbour of the same type; tier traits (light, own
sounds, repair cost) from the vanilla neighbour of the same material. Four power
multipliers deliberately depart from that neighbour, each because of a
threshold explained below: Copper Fishing Rod ×0.8, Solarite Sledge Hammer
×0.7, Relucite Sledge Hammer ×0.85, Relucite Pickaxe ×0.89. Every tool with a
size above 1×1 carries `ResizableTileSizeAuthoring`, or it ignores the size the
player picks with R.

| Tool | Area / rarity → level | Power (mult. → value; mining incl. the +20 base) | Size | Durability | Notes |
|---|---|---|---|---|---|
| Wood Sledge Hammer | StartArea / Common → 1 | mining ×0.6 → ~33 | 1×1 | 150 | repair ×0.1 |
| Copper Fishing Rod | Slime / **Uncommon** → 3 | fishing ×0.8 → 43–53 | – | – | |
| Octarine Hoe | Sea / Uncommon → 11 | – | 6×6 | 250 | |
| Galaxite Hoe | Desert / Rare → 14 | – | 7×7 | 250 | Galaxite light |
| Solarite Hoe | Crystal / Rare → 16 | – | 8×8 | 250 | |
| Relucite Hoe | Excavation / Rare → 18 | – | 9×9 | 250 | |
| Solarite Shovel | Crystal / Rare → 16 | digging ×1.1 → 208–254 | 4×4 | 700 | |
| Relucite Shovel | Excavation / Rare → 18 | digging ×1.1 → 228–278 | 5×5 | 750 | |
| Relucite Pickaxe | Excavation / Rare → 18 | mining **×0.89** → 859–1045 | 1×1 | 800 | |
| Relucite Fishing Rod | Excavation / Rare → 18 | fishing ×0.95 → 308–376 | – | – | |
| Solarite Sledge Hammer | Crystal / Rare → 16 | mining **×0.7** → 554–673 | 1×1 | 650 | |
| Relucite Sledge Hammer | Excavation / Rare → 18 | mining **×0.85** → 821–999 | 1×1 | 700 | |

Damage multipliers as the nearest vanilla neighbour: shovel 0.45, hoe 0.55,
hammer 0.2, pickaxe 0.5 (vanilla uses 0.55 up to Iron and 0.5 from Scarlet).

What the numbers buy, tool alone:

- **Relucite Pickaxe** always breaks both common Excavation walls (806, 847) and
  never a City wall (1050), whatever its random factor. In between lies only the
  Desert maze wall (`WallDesertTempleBlock2`, 895), which it breaks or not
  depending on its factor. The Void Infused Tuff (1129) and the Industrial
  Block (2419) stay out of reach.
- **Relucite Sledge Hammer** always breaks Excavation Rock (806), usually the
  plain Excavation wall. Its range may overlap the pickaxe's — accepted.
- **Solarite Sledge Hammer** always breaks Crystal, Alien and Gleam Wood walls
  (535) — the vanilla rule that every hammer breaks its own tier's wall.
- **Relucite Fishing Rod** is the only rod that reaches Excavation water (300)
  without other gear; the Solarite rod stops at 287.
- **Copper Fishing Rod** opens no new water — there is none between 20 and 60 —
  and stays below the Larva Hive (60) on purpose, so the Tin rod keeps its
  role. Its level 3 gives maximum bite speed in dirt water. Rarity Uncommon has
  a vanilla precedent: the Garden Trowel (Slime + Uncommon = 3).
- **Shovels** have no threshold; the new tiers save at most one hit per tile.
  Their progress is the area.

Sizes above 5×5 do not occur in vanilla, but the Tool Resizer mod has run all
shovels and hoes at 9×9 on the vanilla preview and dig code for a long time
(the author's daily setup). No probe is planned.

## Changes to vanilla items (always on)

| Item | Change | Side effects |
|---|---|---|
| Galaxite Sledge Hammer | recipe gains 20× Coral Wood Plank — every other hammer has a handle | sell value and salvage follow the recipe (`sellValue: -1`) |
| Galaxite Shovel | size 3×3 → 4×4, so shovel sizes run 1/1/2/2/3/3/4/4/5 | applies to every existing Galaxite Shovel; reverts on uninstall |

## Recipes

Pickaxe and hammer handles follow the material ladder: Wood up to Iron, Tin at
Scarlet, Coral Wood at Octarine, Coral Wood Plank at Galaxite, Gleam Wood at
Solarite, Gleam Wood Plank at Relucite. A hammer costs one bar more than the
pickaxe of its tier and shares its handle. Vanilla itself departs from the
ladder elsewhere (Scarlet Shovel uses Iron, Solarite Fishing Rod uses Gleam
Wood Plank); the new tools follow the ladder.

| Tool | Recipe |
|---|---|
| Wood Sledge Hammer | 5× Wood |
| Copper Fishing Rod | 5× Wood, 3× Copper Bar |
| Octarine Hoe | 10× Coral Wood, 10× Octarine Bar |
| Galaxite Hoe | 18× Coral Wood Plank, 18× Galaxite Bar |
| Solarite Shovel | 18× Solarite Bar, 18× Gleam Wood |
| Solarite Hoe | 18× Solarite Bar, 18× Gleam Wood |
| Solarite Sledge Hammer | 21× Solarite Bar, 20× Gleam Wood |
| Relucite Pickaxe | 22× Relucite Bar, 20× Gleam Wood Plank |
| Relucite Sledge Hammer | 23× Relucite Bar, 20× Gleam Wood Plank |
| Relucite Shovel | 20× Relucite Bar, 18× Gleam Wood Plank |
| Relucite Hoe | 20× Relucite Bar, 18× Gleam Wood Plank |
| Relucite Fishing Rod | 19× Relucite Bar, 17× Gleam Wood Plank |

## Workbench placement

A workbench craft carries the item's **`ObjectID`**, not the slot: the client
resolves the slot itself (`CraftingUIBase.ActivateRecipeSlot`,
`Pug.Other:334113`) and sends `Create.Craft(objectID, …)` (`Pug.Other:305187`).
Only the cooking and processing stations send a slot index. The server then
checks materials and station conditions only, never whether the station offers
the item (`InventoryUtility.CanCraft`, `Pug.Other:430210`). So a shifted slot
cannot produce a wrong item, and the station list governs only what a player
**sees**.

Rules: the setting changes what a slot holds, never where it is — with the
setting off a `[S]` slot holds `ObjectID.None`, which keeps both layouts
identical and lets one table describe them; tools go into gaps in the first
window or into a window of their own, never between stations or building
parts; indices count within the station's own list (the metal workbenches show
each lower workbench's list as a category of its own,
`Pug.ECS.Conversion:1690`).

Two kinds of entry, placed differently:

- **Gap entries** (Galaxite, Solarite) overwrite a vanilla `None` at a fixed
  index. Each is written only if that slot is still a placeholder — `None` with
  no `moddedObjectID`; if another mod took it, that one entry is skipped and
  logged.
- **Window entries** (all other stations) form a window of their own, appended
  after the list's **current** end: placeholders pad the list up to the next
  six-slot boundary, then our entries follow. The table shows the result on a
  vanilla list; another mod that appended first — `caveling-divining-rod` puts
  its rod at the end of the Iron Workbench — shifts our window back, never into
  its group. If that would need a sixth window, beyond the pool extender's
  ceiling of five, the station is skipped and logged.

| Workbench | Vanilla list | New entries on a vanilla list (index: item) | Window |
|---|---|---|---|
| Wood | 17 | 17: `None` (padding) · 18: Wood Sledge Hammer `[S]` | 4 |
| Copper | 18 | 18: Copper Fishing Rod · 19: Copper Sledge Hammer `[S]` | 4 |
| Tin | 18 | 18: Tin Sledge Hammer `[S]` · 19: Hand Drill `[S]` | 4 |
| Iron | 18 | 18: Iron Sledge Hammer `[S]` · 19: Garden Trowel `[S]` | 4 |
| Scarlet | 18 | 18: Scarlet Sledge Hammer `[S]` · 19: Scarlet Hand Drill `[S]` | 4 |
| Octarine | 18 | 18: Octarine Hoe · 19: Octarine Sledge Hammer `[S]` | 4 |
| Galaxite | 18 | 3: Galaxite Hoe · 4: Galaxite Sledge Hammer `[S]` (existing gaps) | 1 |
| Solarite | 18 | 2: Solarite Shovel · 3: Solarite Hoe · 4: Solarite Sledge Hammer `[S]` (existing gaps) | 1 |
| Relucite Smithing Table | 8 | 8–11: `None` (padding) · 12–16: Pickaxe, Shovel, Hoe, Fishing Rod, Sledge Hammer `[S]` | 3 |

- A window whose six slots are all `None` is skipped (`Pug.Other:339027`), so
  with the setting off the Wood, Tin, Iron and Scarlet workbenches look exactly
  like vanilla.
- Every added window gets the title term `tools` — a missing title logs a
  warning every frame (`Pug.Other:370826`, `:370859`).
- At most four windows per station; vanilla has three, so the mod depends on
  `simple-crafting-pool-extender` (ceiling five).

## Loot

The three new hammers are always added as **random** drops through CoreLib's
`LootDropModule.AddNewDrop`, never as guaranteed ones: a guaranteed entry
appended after load is never reached (handbook, *Adding an item to a vanilla
loot table*). Weights are solved per table with the game's own chance formula
(`LootTableBank.InitLoot`, `Pug.Base:17334`), checked against the Copper hammer
(0.0101 computed, 0.01 vanilla).

| Hammer | Table | Weight | Target |
|---|---|---|---|
| Wood | `WoodenDestructible` | 0.012 | ~1 % |
| Wood | `WorldChest` | 0.01 | ~3 % |
| Solarite | `SolariteChest` | 0.024 | ~7 % |
| Relucite | `ReluciteChest` | 0.04 | ~7 % |

Vanilla loot of all other tools stays untouched.

## The setting

"Loot tools craftable" — one toggle for the six vanilla hammers, the three new
hammers, the Garden Trowel and both Hand Drills. Off by default.

- Declared through **Mod Settings Menu v1** (the published 1.2.1):
  `ModSettings.Section(this).Toggle(…).RequiresRestart().Build()`, in
  **`EarlyInit`** — a value consumed by the bake must be bound before it, or
  the default is baked in for good (handbook, *a config value the bake reads
  must be bound in `EarlyInit`*).
- No access level: v1 has no `access` parameter, and code against the
  unpublished v2 API would fail to compile for every v1 user. Each process
  therefore holds its own value — see *Multiplayer* for what that means.

## Architecture

| Unit | Responsibility | When |
|---|---|---|
| `ToolCatalog` | pure data: tools, recipes, stations, indices, `[S]` flags, loot entries | – |
| `SlotPlanner` | pure logic, no game types: given a station's current list and the wanted entries, returns the writes or a skip reason | – |
| `Settings` | the toggle via MSM v1 | `EarlyInit` |
| `ItemRegistration` | one runtime `EntityAuthoringDataBlock` per new prefab, as `caveling-divining-rod` does | `EarlyInit` |
| `VanillaTweaks` | Galaxite hammer recipe, Galaxite shovel size, on the authoring data | before conversion |
| `WorkbenchInjector` | applies `SlotPlanner` to each station's `CraftingAuthoring.canCraftObjects` (1.3 path via `GetDataBlocks<EntityAuthoringDataBlock>`) | `Init` |
| `LootRegistration` | the four drops via CoreLib | `EarlyInit` |
| `WindowTitlePatch` | Harmony postfix on `CraftingBuilding.GetCraftingUISettings`, returning a copy with `tools` appended for our stations | runtime, display only |

Runtime data blocks rather than authored assets because that path is proven in
this workspace and the asset path is not. Window titles through a postfix
rather than a prefab edit because they live on the graphical prefab
(`SimpleCraftingBuilding`), whose runtime reach is unsolved.

**Errors are loud, never silent:**

- **Slot guard.** `WorkbenchInjector` never overwrites anything but a
  placeholder, and never writes inside an existing window group. A gap entry
  whose slot is taken is skipped with an error naming station, index and what
  occupies it; a station whose window entries would need a sixth window is
  skipped whole. A list *longer* than vanilla — another mod appended — is not an
  error: the window goes after it.
- A missing prefab or unresolved item logs its name and skips that tool only.
- Lifecycle calls catch and log: the loader reports only the first exception any
  mod throws.

## Multiplayer

`requiredOn: 3` — items, recipes and loot are needed on both sides.

**The setting is per player in 1.0.** Each process bakes its own value, and
because the server never checks a station's offer, a player with the setting on
can craft hammers on a server whose setting is off. Enforcing it on the server
would need a check in `InventoryUpdateSystem.ProcessCraftingJob`
(`Pug.Other:427830`), which is Burst-compiled together with its system and
handles every inventory change in the game; disabling Burst there is
process-wide and its cost unmeasured, so 1.0 does not. The description says so
plainly: in single-player and when hosting the setting does what it says; a
dedicated server cannot forbid it.

**Correctness rests on item IDs, not slots.** Since a craft sends an
`ObjectID`, client and server must give the twelve new items the same ids. How
a modded item's id is assigned is not traced in the handbook — open question 2.

## Assets and texts

- **Prefabs:** copies of the same-type neighbour with the values above, under
  `unity/CompleteTools/`.
- **Sprites:** icon and held sprites per tool, recoloured from the neighbour in
  the Pixaki pipeline, sheet GUID and `internalIds` pinned.
- **Localisation EN + DE** in the game's wording ("Relucite Pickaxe" /
  "Reluzit-Spitzhacke", "Solarite Sledge Hammer" / "Solarit-Hammer"), with
  descriptions and the setting's texts. The window title reuses vanilla `tools`.
- **Manifest:** dependencies CoreLib, SimpleCraftingPoolExtender,
  ModSettingsMenu (all required); `skipSafetyChecks: false`.
- **Logo** in the family style; gesture: the five tools fanned with a small gold
  "+". Judged at ~200 px; no rotationally symmetric silhouette with hooks.
- **Descriptions** name the vanilla changes, the setting and its restart, that
  it is per player and a dedicated server cannot enforce it, and compatibility:
  Tool Resizer and PlacementPlus override the tool sizes (harmless); mods that
  append to the same workbenches coexist; a mod that fills a Galaxite or
  Solarite gap first costs that one entry, with a log line.

## Tests

**Harness** (`dotnet run --project tests/catalog-harness`, the `sign-labels`
pattern, not a gate): `SlotPlanner` — writes at the vanilla state, padding
included; setting off yields the same indices with `None`; a longer list moves
the window behind it to the next six-slot boundary; an occupied gap skips that
entry only; a sixth window skips the station. `ToolCatalog` — twelve tools,
unique names, no duplicate index per station, index < 24 on a vanilla list,
`[S]` only on hammers, drills and the trowel, Relucite hammer multiplier below
the pickaxe's, every tool above 1×1 marked resizable.

**In game** (`docs/manual-tests.md`). Preconditions: only Complete Tools and
its dependencies; Tool Resizer off for size checks.

1. Setting off: Wood, Tin, Iron, Scarlet workbenches look vanilla.
2. Setting off: Copper and Octarine window 4 and the Smithing Table window 3
   show the title, and no title warning appears in the log.
3. Setting on, restart: hammers, drills and trowel in their slots; every added
   window titled, and again no title warning in the log.
4. Craft each new tool.
5. Read every power value against the ranges above.
6. Second launch: identical power values (string-hash stability under Mono is
   unverified).
7. Sizes with R, including the Galaxite Shovel at 4×4.
8. Galaxite Hoe glows.
9. Galaxite hammer recipe and its salvage yield.
10. Log: eight CoreLib `<name> is <ObjectID>` lines — two per drop, one for
    each list `AddDrops` writes — all with valid ids.
11. Loot: open the four tables until each new hammer has dropped once (test
    fixtures may raise the weights for this run).
12. **Multiplayer**, local dedicated server: every new tool crafted on the
    client arrives as that tool — client and server agree on the ids. With the
    server's setting off and the client's on, a hammer craft succeeds, as
    documented.
13. Coexistence: with `caveling-divining-rod` installed, the Iron Workbench
    shows the rod in its own place and our window after it, both craftable.
14. Whole log after a session with the setting on and off: no warning or error
    from Complete Tools.

## Open questions for the plan

1. **Sprite count per tool** (icon, small icon, swing frames) — decides the art
   effort, the largest unknown. First step of the plan.
2. **Do client and server assign a modded item the same `ObjectID`?** A craft
   carries the id, so this is what "never a wrong item" rests on. The handbook
   leaves the assignment path untraced. High priority: trace it in the loader
   before any item is built.
3. **Editing a vanilla item's `requiredObjectsToCraft` and `prefabTileSize`
   on 1.3** — the handbook's recipe example uses `DatabaseConversionUtility`,
   which 1.3 removed; the workbench list has a documented 1.3 path, these two
   fields do not. Fallback for the size: rewrite the baked blob after
   conversion, as Tool Resizer does.
4. Which Excavation wall dominates in the world — informational. The pickaxe
   breaks both always; the Relucite hammer breaks Rock (806) always and the
   plain wall (847) usually.

## Later

- After MSM v2 ships: declare the setting `ConfigAccessLevel.Server`, so GMCM
  syncs it and MSM-19 later. Clients then take the server's value and stop
  showing recipes the server has switched off — a display rule for honest
  players, not enforcement. A synced bake-time value takes effect only after
  a restart.
- Garden Trowel and Hand Drill variants, if wanted.
