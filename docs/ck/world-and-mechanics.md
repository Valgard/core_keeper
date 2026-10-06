# World, tiles and game mechanics

This chapter is about the game itself: how the world is laid out in space, what
the rules are for putting a tile or an object somewhere, how far the world
around a player actually exists, and how a handful of frequently-modded systems
(ore boulders, livestock, pets, cooked food) really behave. You need it when
your mod computes positions, places or removes things, scans the world for
entities, or reasons about creature and item identity. How to *hook* any of it
is [Harmony and ECS](harmony-and-ecs.md); how to change baked prefab data is [database and baking](database-and-baking.md).

## World geometry: the plane is XZ, not XY

Core Keeper looks top-down but is a 3D scene with a fixed overhead camera. The
axes are the usual Unity ones, which means the map plane is **XZ**:

| Axis | Meaning |
|---|---|
| `x` | left/right on screen |
| `y` | **height** (3D up). For every ground-level entity — players, enemies, dropped items, digging spots — it is `0` |
| `z` | up/down on screen, i.e. what a map would call its Y axis |

So a top-down distance and bearing from `LocalTransform.Position` (`float3`)
use `x` and `z`:

```csharp
float3 delta   = targetWorldPos - playerWorldPos;
float distance = math.sqrt(delta.x * delta.x + delta.z * delta.z);
float bearing  = math.atan2(delta.z, delta.x);   // radians, top-down
```

**Trap: `delta.y` is not the map's Y.** It is the height axis and is ~0 for
everything on the ground, so `math.atan2(delta.y, delta.x)` returns 0 or π for
every target depending only on the sign of `delta.x`. The symptom is unmistakable
once you know it: direction indicators that all point horizontally and never
rotate as you move. Measured example — target at `(111.00, 0.00, -114.00)`,
player at `(91.49, 0.00, -49.78)`, so `delta = (+19.51, 0, -64.22)`: the correct
bearing is ~−73°, the `delta.y` version gives 0°.

`math.length(delta)` for *distance* is safe as long as `y` is 0, since
`sqrt(dx² + 0 + dz²) == sqrt(dx² + dz²)`. Only the bearing is fragile.

Once you have the bearing scalar, screen-space work needs nothing else from the
world — a HUD arrow on a ring is `cos(bearing)` for its screen X and
`sin(bearing)` for its screen Y. Screen versus world coordinate handling is
covered in [prefabs and rendering](prefabs-and-rendering.md).

### The origin is not the Core

Every world is generated around `(0, 0)`, and the Core sits there — which makes
it natural to treat "the origin" and "the Core" as the same point. They are not,
and a mod that measures distance or draws a direction to the Core will be
consistently wrong if it uses `(0, 0)`.

Measured across the map data of eight separate worlds, the built-up **Core base**
— the whole region around the Core, not the 5×5 `TheCore` object itself
(`ObjectID.TheCore = 4002`) — is centred on `x = 0`, its west and east edges
equidistant in every one of them. In `z` it sits **north of the origin**: the
southern edge came out at `z = -1` in all eight, and the region reached `z = 10`
or `z = 11`.

Those are tile-quantised edges read off a fog-of-war raster, so treat them as
±1 tile. What they support is the qualitative claim: **the origin sits near the
southern edge of the Core base, not in its middle** — at the waypoint below the
Core rather than in the Core.

**One number in the code agrees with that.** When `ECSManager` finds more than
one entity carrying `TheCoreCD`, it deletes the extras and repositions the
survivor to a hardcoded `LocalTransform.FromPosition(new float3(0f, 0f, 4f))`
(`Pug.Other:188066`) — the only hardcoded Core position in the assemblies, and it
lands inside the range the map measurement gives. Read it as corroboration of the
direction and rough size of the offset, not as the Core's position: it is a repair
value on one code path, and a world that never needed repairing never went through
it. For an actual position, query the entity (below).

**Trap: do not derive the offset from the region's midpoint.** Only the southern
edge was stable across all eight worlds; the northern one came out at `10` or
`11`, and what makes the difference is **unverified**. A midpoint computed from
the two is therefore not reproducible across saves — and it would in any case
describe the base, not the Core object.

Practical consequences:

- The parenthesised distance in vanilla's coordinate readout is a distance to
  the **origin**, not to the Core.
- A "distance to Core" or "arrow pointing home" feature needs the Core's actual
  position, not `float3.zero`.
- Conversely, if you want the *spawn point*, the origin is right — that is what
  sits there.

**Getting the Core's position at runtime.** You do not have to measure anything:
the Core carries a dedicated tag component, `TheCoreCD`
(`Pug.ECS.Components:1478`) — zero bytes, and `[GhostComponent(PrefabType =
GhostPrefabType.All)]`, so it exists on the client ghost as well as on the
server. Query it, take the single entity, read its `LocalTransform.Position`.
The game does exactly that query itself (`Pug.Other:188059`, in the routine that
deletes duplicate cores). Two conditions apply: the Core resolves only while it
is loaded — see [entity radii](#entity-radii-loaded-is-not-observed) — and the sandbox's verdict on ECS reads is per
component type, so verify the load as described in [reading the live ECS world](harmony-and-ecs.md#reading-the-live-ecs-world-from-a-mod).

Do not shortcut this with a constant. That same cleanup routine pins the
surviving core at `float3(0, 0, 4)`, which corroborates that the Core sits north
of the origin but is a repair value written on one code path, not where the Core
is in a world that never needed repairing.

### Floor world coordinates, never cast them

`math.floor` and an `(int)` cast agree on positive numbers and part company on
negative ones: `-14.3` floors to `-15` but casts to `-14`. Core Keeper worlds
sit around the origin, so negative coordinates are the ordinary case rather than
an edge case, and CK's own code floors.

**A systematic off-by-one that shows up only in the negative half of the world
is the signature of this mistake.** It is invisible in any test run east and
south of the Core.

### What the map's coordinate readout actually shows

Vanilla's coordinate display is not a player readout. `CoordinatesUI.LateUpdate`
computes

```csharp
int2 x = (int2)math.floor(mapUI.GetCursorWorldPosition());
```

— the map **cursor**, not the player — and renders each coordinate through
`ToString("F0")` (`Pug.Other:330522-330530`), not a printf-style `"%d, %d"`
template. That parenthesised number is the straight-line distance to the world
origin, computed **from the already-floored ints** rather than from the float
position, formatted the same way. Measured: at `63, -14` the readout shows
`(65)`, matching `sqrt(63² + 14²) = 64.5 → 65`.

**Which cursor depends on the input device.** `MapUI.GetCursorScreenPosition`
(`Pug.Other:347596`) branches on `inputModule.PrefersKeyboardAndMouse()`: with
keyboard and mouse it returns the mouse pointer, and otherwise the map's own
centre transform. So on a gamepad the readout follows where the map is centred,
not a pointer — and reproducing vanilla's number means reading the same source it
does, rather than assuming a mouse exists.

The player marker drawn on the map is rasterised independently, through
`MakePixelPerfectMapPosition` (`Pug.Other:347582`, called from `Pug.Other:346946`), which
quantises with `GetPixelPerfectQuantization()` — `0.0625f / GetCurrentZoom()`
(`Pug.Other:346473`) — so the step shrinks as you zoom in rather than staying fixed at
`0.0625f`. The literal `RoundToMultiple(0.0625f)` does exist in the code, but
in `MapUI.CenterMapOnLocalPlayer` (`Pug.Other:347064`), operating on a screen-coordinate
offset, not on the marker.

**Trap: at a tile boundary the readout and the marker may differ by 1.** They are
two separate quantities, so reproducing vanilla's numbers exactly means copying
its floor-then-measure order, not reading its marker position.

### Map markers are entities, and the waypoint is its own kind

Most marker icons vanilla draws on the map come from an entity carrying
`MapMarkerCD`. The exceptions are the Core, pings and the players themselves:
`MapUI` draws those without a marker entity behind them and keeps them in a list
of their own, `_allNonEntityMarkers` (`Pug.Other:346255`). On 1.3 the
component's two fields are `mapMarkerType` and `uniqueMarkerId`
(`Pug.ECS.Components:6525`). That covers the icons, not the map as a whole: the
explored terrain itself is map data rather than entities (see [savegame formats](savegame-formats.md)),
and another mod may draw client-side markers of its own that no entity backs.
`MapMarkerType` divides the vanilla space:

| `MapMarkerType` | |
|---|---|
| `None`, `Player`, `PlayerGrave`, `Ping`, `Portal` | transient or per-player |
| `UniqueBoss`, `TitanShrine`, `UniqueScene`, `CoreAttention` | world content |
| **`Waypoint`** | the waypoints you teleport between |
| **`UserPlacedMarker`** | what the player pins by hand |

Up to 1.2 a third field, `userMapMarkerType`, picked a hand-placed pin's icon
from a second enum: `None`, `Ping`, `Marker1` … `Marker4` — four icons, not an
open set. 1.3 removed both the field and the enum and made the icon a data
block; see [below](#since-13-a-user-markers-icon-is-a-data-block).

Note that `Waypoint` is a **separate marker type from the Core**, which is the
data-side counterpart of the origin offset above: the point at `(0, 0)` is the
waypoint entity, and the Core is a different object north of it.

`MapMarkerActivatedCD` carries a generated ghost serializer, so activation state
is replicated rather than recomputed per client.

What of this survives into a save is less than it looks — `MapMarkerCD` is not
written at all, and up to 1.2 a marker on disk is three integers; 1.3 adds the
icon and the name. Reading markers out of a world file is covered in [savegame formats](savegame-formats.md).

**Reading the markers of a world means reading them at runtime.** They are
ordinary entities, so a query over the server world returns each marker with its
transform in one pass. Recovering them from a save file instead is impractical
for the reasons in [savegame formats](savegame-formats.md).

### Since 1.3 a user marker's icon is a data block

A hand-placed marker stores its icon as `MapMarkerCustomDataCD` — an
`iconAddress` and a `variantIndex`, both ghost fields
(`Pug.ECS.Components:3249`) — and its name in `NameCD`. The address names a
`MapMarkerIconDataBlock` (`Pug.Base:15143`), whose `variants` list holds one
entry per colour or form: `largeMapSprite`, `miniMapSprite` and `colorIcon`. An
index out of range is clamped to the first or last variant rather than failing
(`Pug.Base:15163`), but an empty or null `variants` list returns a default
`Variant` (`Pug.Base:15159-15161`) whose sprites are all null, so a marker using such a
block is drawn with no sprite at all.

**A mod adds icons by shipping such blocks.** The marker dialog,
`MapMarkerCustomizationPanel`, builds its icon row from
`ScriptableData.TryGetDataBlocks<MapMarkerIconDataBlock>` (`Pug.Other:345044`),
once per panel instance (`Pug.Other:344966`), in the order of that list — which is not
the order you might expect: see [database and baking](database-and-baking.md#scriptabledata-blocks-addresses-and-order).
Verified on 1.3.0.2 with five mod-shipped icon assets: they appear in the
dialog, place, save and survive a restart like vanilla's. A saved marker refers
to its block only by address, so the block needs one that never changes, and to
the variant only by its index, so the order of `variants` has to stay stable
too: new variants go at the end. Reordering or removing one changes what the
markers whose stored index it shifts show, not every marker: those below the
change keep their variant, and an index past the shortened end is clamped to the
last variant (`Pug.Base:15163`).

**The server stores an icon address without resolving it.** Placing a marker
sends `CreateCustomMapMarker`; the server's `MapMarkerRpc` handler
(`Pug.Other:414855`) copies the address and variant into the new entity, created
with amount 1 (`Pug.Other:414865`), and never looks the block up. So a dedicated server
does not need the mod whose icons its players use. A hosting player is a
different case: that process is also a client that draws the markers, so the
host needs the mod to see the icons like any other player. Measured on 1.3.0.2:
a client with an icon mod placed a marker on a dedicated server without it, the
server restarted, and the marker still showed its icon.

**A marker whose block is missing keeps whatever sprite its display element last
had, and logs an error every frame it is drawn.**
`MapMarkerUIElement.LateUpdate` calls `TryApplyCustomMarkerSprite` for every
user marker (`Pug.Other:345757`), which logs `Failed to resolve
MapMarkerIconDataBlock at address …` and returns (`Pug.Other:345815`) without assigning a
sprite. The map draws markers through pooled elements: `MarkerPool.GetMarker`
reuses a returned element before it instantiates a new one (`Pug.Other:346082-346084`),
and `ReturnToPool` clears the element's entity and player but not its sprite
(`Pug.Other:347537-347540`). So a freshly instantiated element shows the prefab's
default sprite — `userPlacedMapMarker.prefab` references `map_markers_1`, the
second tile of the marker sheet `map_markers.png` that 1.2 drew user markers
from — 1.2's first user marker, a blue diamond on a dark framed square; observed
on 1.3.0.2 right after launch (map-markers-enhanced, `docs/manual-tests.md`,
"Without the mod on the client") and on 1.3.0.4 for a mod icon whose mod was
uninstalled — while a reused one can go on showing the icon of another user
marker it displayed before. `UpdateColor()` still runs first and tints the
element's colour renderer in the local player's colour (`Pug.Other:345754`), which only
the resolved path resets to white (`Pug.Other:345823-345827`) — but in the 1.3.0.2
`userPlacedMapMarker.prefab`, read from the extracted resources, both colour
renderers carry no sprite and no code assigns them one, so the tint has nothing
visible to colour. That is what players without an icon mod see for markers
placed with it, and what everyone sees after uninstalling it — so do not expect
it to look like any one particular icon.

**1.3.0.2 cannot edit a placed marker.** The pieces exist:
`MapUI.ApplyEditToExistingMarker` (`Pug.Other:346589`) sends
`EditCustomMapMarker`, and the server handler's `targetEntity` branch (`Pug.Other:414875`)
updates icon, variant and name of an existing marker. That branch checks only
that the target carries `MapMarkerCustomDataCD`: it never looks at who sent the
request, and unlike the command path it has no guest-mode check either (`Pug.Other:415585`
runs it unconditionally), so any client could edit any player's marker it has as
a ghost. The target travels as a ghost id; one the server cannot map arrives as
`Entity.Null` (`Pug.Other:454422-454429`), and the handler then takes its create branch
(`Pug.Other:414862`) and places a new marker at the request's position, which
`EditCustomMapMarker` never sets (`Pug.Other:414572-414581`), so at the origin. The edit
branch also writes the request's name unconditionally (`Pug.Other:414878-414881`), so an
edit with an empty name clears the marker's name, where creation sets a name
only when one is given (`Pug.Other:414867`). But nothing calls
`ApplyEditToExistingMarker`, in the client or the dedicated-server build, and
the game offers no way to reach it — changing a marker means deleting it and
placing a new one. A mod that wants editing has to open the dialog on an
existing marker itself; whether the dead path works as it stands is untested.

**The 1.3 world migration turned old markers into these** — by their old slot
alone, which cost one widely used marker mod every marker it had drawn with its
own art. What it did and what survived it is in [savegame formats](savegame-formats.md#worked-example-reading-map-markers-out-of-the-file).

### Vanilla marker icons

As of 1.3.0.4 vanilla ships eight icon blocks with ten variants each. Variant
*v* of the block in row *r* uses `map_marker_large_<10·r + v>`,
`map_marker_small_<10·r + v>` and `map_marker_color_<v>`, so *v* is a colour
column of `map_marker_large.png` (variant 1 sits at x=10, variant 9 at x=90) and
means the same colour in every block, roughly: pale grey-white, red, blue,
green, light cyan, teal, brown, pink, slate blue, yellow.

| Row | Block asset | Address | Large sprites |
|---|---|---|---|
| 0 | `UserMarker1_Cross` | `adbecb0c-1236-bf84-d9ea-0516e188e2d0` | `map_marker_large_0`–`9` |
| 1 | `UserMarker2_Dot` | `f9203606-618b-6384-7a99-a790e5c6de35` | `_10`–`19` |
| 2 | `UserMarker3_Flag` | `3005a608-1b77-8604-8abe-d189ae05a0d8` | `_20`–`29` |
| 3 | `UserMarker4_Home` | `64007694-5b2f-5474-b8ad-9f972e822421` | `_30`–`39` |
| 4 | `UserMarker5_Pickaxe` | `a707985f-1e22-c2f4-e837-0cc32288f9c5` | `_40`–`49` |
| 5 | `UserMarker6_Question` | `7e09f30c-8838-5604-2b46-8c13b0ef771e` | `_50`–`59` |
| 6 | `UserMarker7_Skuill` (sic, the asset's own spelling) | `169f71d7-f86d-7234-abf0-0120b015262b` | `_60`–`69` |
| 7 | `UserMarker8_Star` | `0eafefb1-8776-40d4-3af9-98637e55183e` | `_70`–`79` |

Measured on 1.3.0.4 by logging every block that
`ScriptableData.TryGetDataBlocks<MapMarkerIconDataBlock>` returns, with its
name, address and each variant's sprite names. The address and the variants are
serialized fields (`m_address`, `ScriptableData:1703-1706`; `variants`,
`Pug.Base:15155`), but the extracted block assets carry only the header, because
the extraction drops the data-block fields — so they cannot supply this. Two
serialized sources in the extracted resources do record addresses.
`MapUI.defaultPresets`, in `Global Objects (Main Manager).prefab`, stores five
icon/variant pairs as `m_low`/`m_high` halves: Dot 2, Question 9, Skull 0, Flag
3 and Pickaxe 1. And the game's code hard-codes four of them for the markers of
1.2: in `ConvertOldMapMarkersSystem` of 1.3.0.4 (client), `Pug.Other:175131`
assigns, `Pug.Other:175151` picks the block and `Pug.Other:175163` the variant —
Dot variant 2, Question 9 (yellow question mark), Skull 0 (white skull) and Flag
3 (green flag). Cross, Home and Star rest on the probe alone. The Dot-2 pair is
1.3's redraw of the first user marker of 1.2, a blue diamond; it is not the
fallback sprite described above, which is the 1.2 original of the same motif.

## Tile layers: what may sit on what

`TileType.GetNeededTile` (`Pug.Base:19957`) and `GetInvalidTile` (`Pug.Base:20002`) are
the authority. A tile is applied only if at least one of its needed tiles is
present at that position and none of its invalid ones is.

| Tile | Requires (ANY of) |
|---|---|
| `rail`, `wall`, `thinWall`, `floor`, `fence`, `rug`, `litFloor`, `looseFlooring`, `circuitPlate`, `ancientCircuitPlate`, `smallStones`, `debris`, `debris2`, `bigRoot`, `groundSlime`, `chrysalis` | `ground`, `bridge` |
| `bridge` | `pit`, `water` |
| `dugUpGround`, `smallGrass`, `floorCrack` | `ground` |
| `wateredGround` | `ground`, `dugUpGround` |
| `wallGrass`, `wallCrack`, `ore`, `ancientCrystal` | `wall` |

`GetInvalidTile` contains exactly one mirror pair: **`bridge` is invalid where
`ground` is present, and `ground` is invalid where `bridge` is.** A bridge can
therefore never be laid over normal ground.

### The bridge family

Nine objects produce the `bridge` tile (`Pug.Base:2840-2884`):

| `ObjectID` | Object |
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

`ObjectID.Rail` is `6550` (`Pug.Base:3454`).

Pugstorm hands out IDs as content ships, so the numeric order *roughly* tracks
biome progression and hence roughly tracks scarcity. Treat that as a heuristic
for ordering a fallback list, never as a rule — `GlassBridge` and
`MetalGrateBridge` are both counterexamples.

**Do not substitute `TileType.IsWalkableTile()` for this check.**
`IsWalkableTile` (`Pug.Base:19631`) also accepts `floor`, `rug`, `litFloor`,
`looseFlooring`, `rail`, `circuitPlate` and more — a strictly wider set than the
apply-time rule uses. The correct predicate for "can a rail/floor/wall go here"
is `ground || bridge`.

Vanilla itself substitutes a tile the player never asked for:
`PlaceObjectSlot.GetTileTypeToPlace` (`Pug.Other:323187-323194`) returns
`TileType.ground` **instead of** `wall` when a wall is placed on a position
with neither `ground` nor `bridge` — gated on a third condition alongside the
missing-substrate check: a ground item must exist for that tileset. The wall
itself does not follow automatically in the same click; it needs a second
click, handled by `IsPlacingWallAfterPreviouslyPlacedGround`
(`Pug.Other:323197-323204`). Inserting a missing substrate is an established pattern,
not a hack.

## `AddTile` is a queue append, not a commit

```csharp
EntityUtility.AddTile(int tileSet, TileType tileType, int2 position,
                      bool isWorldModeCreative,
                      DynamicBuffer<TileUpdateBuffer> tileUpdateBuffer)
```

`Pug.Other:265219`. Its core is `tileUpdateBuffer.Add(new TileUpdateBuffer {
command = Add, … })`. It rejects `tileSet < 0 || tileSet >= 75` and guards the
spawn-area tiles. **The layer rules above are judged later**, when the buffer
is applied.

**Two tile types queue extra removals of their own.** A `wall` pairs its `Add`
with a `Remove` of `roofHole`; a `ground` pairs it with a `Remove` of both
`pit` and `water`. The second matters if you follow this chapter's advice to
lay `ground` as a substrate — doing so destroys any pit or water already at
that position, silently and without a placement check.

### Ordering: the buffer is reversed twice, so insertion order survives

- `UpdateSubMapCommon.FilterUpdates` (`Pug.Other:248441`) walks the buffer
  backwards while building `addList`, de-duplicating per `(position, tileType)`.
- `ApplyAdd` (`Pug.Other:249501`) walks `addList` backwards again.

Two reversals cancel. Net effect: **write the substrate tile first and it is
applied first.** A bridge under a rail means queueing `bridge`, then `rail`. A
single additional reversal introduced anywhere in that chain by a game update
would silently invert this, so re-verify after updates.

### A rejected tile drops the item, it does not destroy it

In `ApplyAdd`, when the needed tile is missing or an invalid one is present, the
tile is simply not set — instead `EntityUtility.DropNewEntity` puts the
corresponding item into the world as a pickup (`Pug.Other:257325`), unless its
`objectType` is `NonObtainable`. So queueing a tile that then fails validation
costs the player a walk to pick it back up, nothing more.

### Never suppress an `AddTile` call to veto a placement

`AddTile` is the convergence point of **equipment-driven** tile placement: every
path where the player's held item produces a tile — placing, digging, watering,
painting, roofing — routes through it. Vanilla calls it at `Pug.Other:323004`,
and third-party placement mods call it too. That makes it the right place to
*change* a placement — but the wrong place to *cancel* one:

**The item is debited from the inventory *after* the `AddTile` call.** Vanilla
does it in the same method, one statement later: `EntityUtility.AddTile(...)`
followed immediately by `Create.ConsumeEntityAt(..., destroy: true, ...)` pushed
onto the inventory update buffer (`Pug.Other:323004`, then `Pug.Other:323007`). The one
foreign placement mod measured here, PlacementPlus, behaves the same way.
Blocking the call therefore consumes the item and produces nothing: a straight
item loss. Letting the call through and having it fail validation only drops a
pickup (see above). If you need to veto, veto earlier, at the placement
decision, not at the tile write.

Another placement mod probably orders it the same way — it is the natural shape,
since the debit belongs to a placement that succeeded — but that is an
expectation, not a measurement. If your veto matters, measure the mod you are
actually running against, as described above.

**Trap: `AddTile` is not the only writer of the buffer.** Nine call sites reach
it, and outside them `Pug.Other` builds a `TileUpdateBuffer` entry with
`command = Add` directly at 28 further places — world spawning
(`SpawnObjectAtPosition`), the `SpawnTileOnDeathCD` handler, plant growth
(`RootPlantCD`), caveling territory, melee-attack state code, and a private
`AddTile(ref EntityCommandBuffer, …)` helper with a different signature. Patching
`EntityUtility.AddTile` therefore sees what the player's equipment does and
nothing else; a mod that means to observe *every* tile the world gains has to
work at the buffer or at `ApplyAdd`, not here.

`AddTile`'s parameters carry no player or inventory reference, so a mod that
needs that context has to capture it upstream. The patch mechanics — priority,
prefix/postfix interplay, and coexisting with mods that replace the placement
path wholesale — are in [Harmony and ECS](harmony-and-ecs.md).

## The placement permission model

Whether an item may be placed on a given tile is decided by
`PlacementHandler.ShouldCheckPlaceObjectOnTile` (`Pug.Other:306182`), and it
grants permission through **two independent, OR-ed routes**:

1. **`PlacementCD` bool flags** — `canPlaceOnWalkableTiles`, `canPlaceOnWater`,
   `canBePlacedOnLava` (which is `water` with `tileset == 3`), `canPlaceOnPit`,
   … They are set in `PlacementHandler.Activate` (`Pug.Other:306476`) from
   `ObjectPropertiesCD` hashes:

   | Hash | Flag |
   |---|---|
   | `1497889171` | `canPlaceOnWalkableTiles` (`Pug.Other:306488`) |
   | `-1324171664` | `canPlaceOnWater` |
   | `-1535225238` | `canBePlacedOnLava` |
   | `-1827158511` | `canPlaceOnPit` |

2. **An object list** — `ObjectCanBePlacedOnObject(<the ObjectID the target TILE
   maps to>, …, canBePlacedOnObjects)` at `Pug.Other:306237`, which sets
   `foundValidTileToPlaceOn = true` **regardless of every flag**.

**Trap: bridges use route 2, not route 1.** Measured live on `WoodBridge`, the
`PlaceableObject` master gate (hash `-975748197`) is `True`, but
`canPlaceOnPit`, `canPlaceOnWater` and `canBePlacedOnLava` are all **`False`** —
both on the database prefab and in `PlacementCD` while the bridge is equipped.
A design built on "read the bridge's pit/water flags and copy them onto another
item" has nothing to copy. What actually makes a bridge reach an abyss is its
membership list.

### The two list properties are passed crossed

`CanPlaceObjectAtPosition` (`Pug.Other:306041-306048`) reads both list properties into
locals and then calls `ShouldCheckPlaceObjectOnTile(…, tilesChecked, value2,
value, …)` at `Pug.Other:306093` against a signature of `(…, canBePlacedOnObjects,
canNotBePlaceOnObjects, …)`. Reading the hashes in declaration order gets the
meaning exactly backwards:

| Property hash | Meaning |
|---|---|
| `-789473209` | `canBePlacedOnObjects` — the **allow** list |
| `1757427560` | `canNotBePlaceOnObjects` — the **veto** list |

Measured contents under `-789473209`:

| Object | `canBePlacedOnObjects` |
|---|---|
| `WoodBridge` | `Water`, `Pit`, `Lava` |
| `Rail` | `ConveyorBelt`, `ElectricalDoor` |

The rail entry is independently observable in game: rails can be placed on
conveyor belts.

`ObjectCanBePlacedOnObject` is a plain membership scan — veto list first as a
hard block, then the allow list, where a hit returns `true` with no further
condition. A third, reciprocal step follows if neither list resolves it:
`Pug.Other:306360-306392` resolves the **target**'s own primary prefab and tests
whether *its* `-789473209` (`canBePlacedOnObjects`) list contains the object
being placed — so either object naming the other is enough.

Note that permission and layer rules are separate gates. Being allowed to place
a rail on a pit does not conjure a substrate: the rail still needs `ground` or
`bridge` underneath once permission is granted.

### Changing the list requires the bake-time hook

`PlaceableObjectConverter.Convert(PlaceableObjectAuthoring)`
(`Pug.ECS.Conversion:2975`) **does run in the shipped game.** Zero *static* call
sites is expected, not a sign the converter never fires: converters are found by
reflection and invoked virtually.
`ConversionManager.FindAllConvertersInCurrentAssembly()`
(`PugConversion:724-742`) scans the executing assembly and every loaded assembly
referencing it; `RunConverters` (`PugConversion:1080-1091`) calls
`converter.Convert(gameObject)`, which `SingleAuthoringComponentConverter<T>`
(`PugConversion:1478-1488`) forwards to the abstract `Convert(T authoring)` — the same
conversion pipeline that [database and baking](database-and-baking.md#changing-a-vanilla-objects-baked-data) describes for
`PugDatabasePostConverter`.

The accurate reason to prefer the `PostConvert` seam is **ordering, not
non-existence**: `Convert` snapshots the list
(`SetPropertyList("PlaceableObject/canBePlacedOnObjects", …)`,
`Pug.ECS.Conversion:3043`) and all converters run before any post-converter
(`PugConversion:850-889`), so a `PostConvert` mutation lands in the *next*
conversion pass.

That next pass comes within the same session, because each world is converted
separately and the mutation stays on the in-memory prefab: `ECSManager.Init`
converts the Default World first (`Pug.Other:2542-2554`), and every world load
or join later runs `ConvertAuthoringDataRoutine`, which converts the ServerWorld
and the ClientWorld, whichever of the two the process has (`Pug.Other:2817`,
`Pug.Other:2839`). An edit made during the Default World's `PostConvert`
therefore reaches the worlds that are actually played in, while the Default
World keeps the unpatched list — and so does
`Manager.mod.Authoring.ObjectProperties`, which is read from it
(`Pug.Other:2560`). A dedicated server orders these the same way: its
`ECSManager.Init` converts the Default World too
(`DedicatedServer/Pug.Other:2531` in the server build), and its log shows that
conversion before the ServerWorld's. Observed working in `auto-rail-bridges` on
1.3.0.2 in a host session; the edit's effect on a dedicated server has not been
measured.

Two consequences. `PostConvert` runs again on every one of those conversions, so
the edit has to be idempotent — add an entry only if it is missing. And the
mutation outlives a settings change: a later world load picks up an added entry
without a restart, but taking it back needs code that removes it, or a restart.

The list is reachable from `PugDatabasePostConverter.PostConvert(GameObject)`
(`Pug.Other:3645`/`Pug.Other:3707`), which does run per world/database
conversion. Since 1.3, walk the prefabs the way vanilla `PostConvert` itself
does: `ScriptableData.GetDataBlocks<EntityAuthoringDataBlock>()`
(`Pug.Other:3716`) → every block whose `prefab`'s
`IEntityMonoBehaviourData.ObjectInfo.objectID` matches (`Pug.Other:3732`,
`Pug.Other:3738`; vanilla keys on objectID *and* variation, `Pug.Other:3745`, so
one object can have several blocks) →
`block.prefab.TryGetComponent<PlaceableObjectAuthoring>()` → mutate
`canBePlacedOnObjects`, a `List<ObjectID>` (`Pug.ECS.Authoring:3251`). The 1.2
route through `DatabaseConversionUtility.GetPrefabList(...)` and
`ObjectInfo.prefabInfos[].ecsPrefab` no longer compiles on 1.3; [database and baking](database-and-baking.md#injecting-a-craftable-into-a-vanilla-station-at-runtime)
has the two versions side by side. Filter on `PugDatabaseAuthoring` first, since
a prefix on `PostConvert` fires for every converted root object. Identify the
game's own prefabs by their `objectID` enum, not by `objectName` string —
objects a mod adds are a different case and are commonly looked up by name.
Useful constants: `ObjectID.Pit = 233`, `ObjectID.Water = 232`. The Default
World's bake runs after `EarlyInit` and before `Init`, so binding the patch in
`IMod.EarlyInit` is what catches it; the world conversions that follow come
later still. The full `PostConvert` pattern is in [database and baking](database-and-baking.md).

**Permission has to exist before placement runs.** `canPlaceObject` is computed
in `UpdatePlaceablePosition`, and `PlaceItem` returns early at `Pug.Other:322947` when it
is false. You cannot "place first and justify it afterwards" — a hook that would
insert the supporting tile is never reached.

### Placement flags are re-initialised every tick

`PlacementHandler.Activate` — the call that populates `PlacementCD` from the
object's properties — is invoked from
`SelectedEquipmentChangeSystem.EquippedSlotChangeJob` (`Pug.Other:446965`, call
at `Pug.Other:447199`).

**Trap: do not read that system's name as its cadence.** Its `OnUpdate` schedules
the job **unconditionally every tick** (`Pug.Other:448151-448154`; its queries carry no
`SetChangedVersionFilter`), and the `Activate` call sits *outside* the
equip-change branch above it. The flags are refreshed per tick, not only when
the equipped item changes.

A mod that mutates those flags should nevertheless clear its own mutation on
every invocation — not because vanilla forgets to, but because a hook cannot
know what state it is entered in, nor the relative ordering of the two systems.
Idempotence that depends on another system's cadence is not idempotence.

### Reaching the player's inventory from a placement hook

The two placement entry points are not interchangeable: only one of them carries
the player at all.

| Method | What it receives | Inventory reachable |
|---|---|---|
| `PlacementHandler.UpdatePlaceablePosition` (`Pug.Other:305813`) | the full `EquipmentUpdateAspect`, and through `LookupEquipmentUpdateData` the `BufferLookup<ContainedObjectsBuffer> containedObjectsBufferLookup` (`Pug.Other:438077`) | yes |
| `PlacementHandler.Activate` | `(ref PlacementCD, Entity placementPrefab, ComponentLookup<ObjectPropertiesCD>, ComponentLookup<TileCD>, ComponentLookup<PseudoTileCD>)` | no — there is no player entity in the signature |

Vanilla reads that buffer lookup exactly this way in `UpdateJob.Execute`
(`Pug.Other:438877`), so it is a supported route rather than a trick. If your
hook sits on `Activate`, no amount of lookup juggling will get you an inventory;
move the work to `UpdatePlaceablePosition` instead.

## Consuming an item from an inventory slot

`InventoryUtility.ConsumeEntityAt` (`Pug.Other:428794`, class at `Pug.Other:428538`)
takes an `optionalTargetObjectID`.

**Trap: despite the name, it is not optional.** The slot's ObjectID is compared
**only** when that argument is set. Left at `ObjectID.None`, the call consumes
whatever happens to lie in the slot at that instant — so an inventory operation
that gets queued in between makes your mod eat the wrong item. That is silent
data loss for the player, and because it needs a race to happen it will not show
up in an unhurried manual test. With the argument set, the consume fails
instead, which is the direction you want this failure to go.

`Create.ConsumeEntityAt(Entity inventory, int index, …)` (`Pug.Other:426617`,
class `Create` at `Pug.Other:426604`) looks like an overload of the same method but is
not — it is a different class. It builds an `InventoryChangeData` command and
pushes it onto the inventory-update buffer; it consumes nothing itself.
`InventoryUtility.ConsumeEntityAt` above already takes an `Entity inventory`,
so reaching for `Create`'s version for that reason buys nothing.

## Entity radii: loaded is not observed

Core Keeper keeps chunks loaded in a bubble around the **player**, driven by
`KeepAreaLoadedCD` on the player entity (set at conversion to
`KeepLoadedRadius = 300`, `StartLoadRadius = 250`, `ImmediateLoadRadius = 200`).
The named constants:

| Constant | Value |
|---|---|
| `PLAYER_DISTANCE_TO_UNLOAD_ENTITIES` | 300 |
| `PLAYER_DISTANCE_TO_START_LOAD_ENTITIES` | 250 |
| `PLAYER_DISTANCE_TO_LOAD_ENTITIES` | 200 |
| `DISTANCE_TO_RESPAWN_ENVIRONMENT` | 200 |
| `UNLOADED_WORLD_SEGMENT_SIZE_LOG2` | 7 (serialized world segment = 128 tiles) |

`UnloadToSerializeWorldSystem` / `FindUnloadedChunksToLoad`
(`Pug.Other:186098-186676`) build the keep-loaded, load and load-immediately
circles from those radii: a segment's entities are destroyed when its AABB
overlaps no 300-circle, and re-created when it overlaps the 250 or 200 circles.

`defaultSimDistance = 100` and `SessionConfiguration.SimulationDistance = 50`
exist but are unreferenced in the shipped DLLs — **the player load bubble is not
shrinkable by any in-game setting.**

Client ghost relevancy is a much smaller and entirely separate thing: `SpawnRect
(22,14)` / `DespawnRect (24,16)`. A scan that resolves the ServerWorld therefore
sees entities out to 200-300 tiles, not the ~24-tile client ghost set;
multiplayer world separation is covered in [multiplayer and server](multiplayer-and-server.md).

**unverified** — those two names and their values were read from `1.2.1.5` and
occur **nowhere** in the `1.3.0.2` checkout, so the mechanism was renamed,
restructured or removed. The wider claim (server sees far more than the client
ghost set) rests on the chunk-load radii above and is unaffected; what needs
re-deriving is the ghost relevancy figure itself.

### `IncludeDisabledEntities` is mandatory for a world scan

Well inside the load bubble, Core Keeper **disables** entities while keeping them
loaded out to the 200-300 radii above. Disabled is not unloaded — but a DOTS
query skips disabled entities by default.

**A query built without `EntityQueryOptions.IncludeDisabledEntities` therefore
sees only a fraction of what is loaded**, no matter how large the load bubble is.
Measured in one world, such a scan reached roughly 40 tiles against a 300-tile
load radius. This is the first thing to check when a world scan "only finds the
ones near me": it is a query option, not a radius problem, and no amount of
walking around fixes it.

**Do not pin that distance to a constant.** `Pug.Base` declares
`DISTANCE_FROM_PLAYER_TO_UPDATE_ENTITY = 40`, which is tempting to cite and is
**dead** — the name occurs exactly once in the whole decompile, at its own
declaration, with no reader anywhere. Whatever governs the disable distance now,
it is not that field, so treat the measured figure as a measurement and re-measure
it rather than trusting the number.

### The trap

**A loaded entity is not necessarily an observed one.** Rule out the query option
above first — the two effects are numerically distinct, one cutting off at 40
tiles and the one below at around 91. Measured in game, base placed-object
entities leave a mod's per-scan query set at only **~91-115 tiles**
from the player — far inside the 200-tile load floor. That boundary matches no
named constant. The best-supported explanation is DOTS `ArchetypeChunk` unload
granularity: a container and a workbench standing next to each other are
different archetypes, hence different chunks with different AABBs, so one can
leave the query while the other stays. A camera reference-frame offset may
contribute.

**Consequence for any spatial-scan mod** that self-heals, prunes, or asks "is
this thing still there?": you may only infer "not observed ⇒ destroyed" inside
the **observed** boundary (~91), never at the load radius (200). Choosing a
prune threshold just under `ImmediateLoadRadius` — say 180, which looks
conservative — deletes loaded-but-unobserved entities as the player walks away
and quietly destroys your own records. A safe threshold is well below the
observed dropout (48 is comfortable), ideally combined with a
"would-be-observed" gate that mirrors whatever coverage rule your scan itself
uses.

## Player-placed versus world-spawned

Core Keeper has no concept of a "base" and no per-object provenance. Both
questions that follow from that sound easy and are not.

### There is no "world-spawned vs. player-placed" signal — stop looking for one

Three rounds of in-game probing turned up no object-level discriminator, and the
collisions are not near-misses:

| Candidate | Why it fails |
|---|---|
| `cat`, `stack`, `icon` | Uniformly true on both sides |
| `craft` (is it craftable) | Collides — a potted bush is craftable, a trophy is not, and both are furniture |
| Object tags | Collide — `Stalagmite` (5610) and `WaterLily` (5614) are tag-less, exactly like `WayPoint` (6514), which the classification has to include |
| `DontDropSelfCD` | An `IEnableableComponent` present on *everything*, and its enabled state is not stable from inside the sandbox |
| `DiggableCD` / `DestructibleObjectCD` | Collide — `Stalagmite` ≡ `CavelingFloorTile`, and `GraveTree` ≡ `WayPoint` ≡ `Idol` ≡ `RuinsPiece` |
| `MineableCD` | Not a discriminator either |

This is a property of Core Keeper's data, not a search that was given up on too
early. The sanctioned fallback is a curated tag + `ObjectID` list that the user
can edit.

### The moment of placement is recorded on the player, not the object

What the stored object lacks, the placing player's entity carries until the next
placement overwrites it. `PlaceObjectSlot.PlaceItem` restarts
`PlacementCD.timeSincePlaced` (`Pug.Other:322969`) — for anything but a critter
(`Pug.Other:322967`) — and writes the placed tile to
`PlacementCD.positionLastPlacedAt` (`Pug.Other:322973`). Both are
`[GhostField]`s (`Pug.ECS.Components:4434-4438`), so the placing client holds
them whether it predicted the placement or received it from the server. A client
that reads its local player's `PlacementCD` every frame therefore sees each of
its own placement attempts as a new `timeSincePlaced.startTick`, together with
the tile. That needs no Harmony patch and, in particular, not the process-wide
Burst change a patch on the placement path would bring (see [Harmony and ECS](harmony-and-ecs.md)).

**A new `startTick` means a placement was attempted, not that an object
spawned.** Both writes come before checks that can still abort the placement —
the consume check (`Pug.Other:322974`) and, for an object, the object-properties
check (`Pug.Other:323015`) — and a tile placement (`Pug.Other:323000`), which
spawns no object at all, writes them as well. So pair the record with the object
that spawns on that tile shortly afterwards; the record does not name the
object, and a watcher that trusts it alone reacts to placements that produced
nothing. The object spawns on the recorded tile for any footprint — the tile
already has the object's `prefabCornerOffset` subtracted, and the spawn position
is taken from it (`Pug.Other:323014`) — except for a wall-mounted placement,
where the spawn position is shifted by `wallSideToPlaceObject`
(`Pug.Other:323044`). `SeederSlot` writes `positionLastPlacedAt` for a seed
(`Pug.Other:323883`) without restarting the timer, so seeding is invisible to a
watch keyed on `startTick`.

Observed working on 1.3.0.4 in singleplayer, for signs placed by the local player and
matched against the sign's own spawn on the same tile. Whether another player's
`PlacementCD` reaches this client is **unverified**. It is an event, not a property —
nothing of it survives in the save.

### A workbench is CK's de-facto "the player built this" marker

Neither position nor cluster density separates a base from a world structure,
because CK's generated structures **pack** functional crafting stations: an
abandoned camp ships with a campfire and a cooking pot, a mechanical vault with a
seed extractor and a generator. A "two or more stations close together" filter
fires on every one of them.

What CK places in **no** world structure is a workbench. Validated against a real
save: 11 workbenches, all at the Core base, none out in the world.

So anchor on workbenches and take the stations inside a workbench's radius. Link
**workbench → station only, never station → station** — chaining station to
station walks straight back into the packed world structures.

The reusable form of this: when you need "does the player own this place?",
reach for a player-built marker object before any spatial or type-based
heuristic.

## Ore boulders

**An ore boulder's `maxHealth` is `12,960,480`** — identical for every ore type,
read off `HealthAuthoring` on the boulder prefabs. A boulder's remaining ore
**is** its health; drilling drains the same field that damage does, so refilling
a boulder means setting `HealthCD.health` back to `maxHealth`.

**Trap: the "1800" that circulates in mod descriptions as the base-game limit is
the ore *yield*, not the health.** At `12,960,480` health for 1,800 ore that is
~7,200 health per unit of ore. Mistaking the yield for the health misestimates
the scale by a factor of thousands and makes narrow health windows look
unreachable when they are in fact enormous. A worked case: the mod.io mod
*EternalOreBoulders* (6042718) does not prevent mining but heals afterwards —
every 30 ticks it sets every entity carrying `RequiresDrillCD` and
`DontDropSelfCD` back to `maxHealth`, but only while `0 < health < maxHealth *
0.1` (a boulder already at `health <= 0` is deliberately not reanimated). At
Core Keeper's 20 Hz simulation rate (`defaultSimulationTickRate = 20`,
`Pug.Base:14788`/`Pug.Base:15620`) 30 ticks is ≈1.5 s, not the ≈0.5 s a 60 Hz frame
rate would give — if the mod is instead counting Unity frames rather than
simulation ticks, the ≈0.5 s figure stands, but the qualitative point holds
either way. That 10% window is 1.296 million health wide — with eight drills
at an 11× speed multiplier it stays open for roughly 12 minutes and, at 1.5 s
per heal, some 480 heal opportunities. "The drill speed skips the window" is
arithmetic that does not work out; when the numbers say a window cannot be
missed, look for a situation in which the system is not running at all rather
than for a collision.

### `RequiresDrillCD` selects exactly the ore boulders

Exactly one converter hands out `RequiresDrillCD`: `DestructibleObjectConverter`,
gated on `DestructibleObjectAuthoring.requiresDrill`
(`Pug.ECS.Conversion:1157-1167`). Of the 177 prefabs carrying
`DestructibleObjectAuthoring`, exactly **12** set `requiresDrill: 1` — the ten
ore types plus two scene variants. Counted against the unpacked prefabs, not
assumed.

Amber Boulder and Crystal Meteor Boulder are *not* in that set. The flag draws
precisely the line between a renewable ore source and a one-off world object,
which makes it the discriminator you want.

**Query for the component instead of hardcoding an ObjectID list.** A hardcoded
list is not just more work — it silently misses any ore tier a future game update
adds, and it fails quietly, as a mod that simply does nothing to the new boulder.

### Ore boulders are ordinary placeable prefabs

All ten ore types (`CopperOreBoulder` 2200 … `ReluciteOreBoulder` 2218) carry
`objectType: 800` = `ObjectType.PlaceablePrefab` (`Pug.Base:4889`), a real `icon`
and `smallIcon`, `isStackable: 1` and `prefabTileSize: 2×2`. Nothing in the
prefab data marks them as world-only decoration.

**The only gate is the creative catalogue, and it is a single runtime call.**
Vanilla hangs the creative object browser off
`UIManager.OnPlayerInventoryOpen` → `if (_creativeModeUIShouldBeOn &&
Manager.saves.IsCreativeModeWorld() && …) creativeModeUI.ShowContainerUI()`
(`Pug.Other:282128`). The mod.io mod *Item Spawner* (6103095) consists
essentially of one prefix on that predicate:

```csharp
[HarmonyPatch(typeof(SaveManager), "IsCreativeModeWorld")]
static bool Prefix(ref bool __result) { __result = true; return false; }
```

which makes the browser — boulders included — available in any survival world.
(Its own filter drops foreign-mod items with `objectID >= 30000` outside real
creative worlds; vanilla 2200-2218 are unaffected. It bails out on
`IsDedicatedServer`, so the patch has no effect on a dedicated server.)

**The reusable lesson: Core Keeper separates "is this object placeable"
(prefab data, `objectInfo.objectType`) from "may the player see it in the
catalogue" (a runtime gate).** Never assume a world object is unreachable
because the game never offers it to you.

To make a genuinely non-placeable object placeable, the same mod's converter
patch shows the minimal pattern: prefix `ConversionManager.RunConverters` and set
`gameObject.GetComponent<EntityMonoBehaviourData>().objectInfo.objectType =
ObjectType.PlaceablePrefab`. Three lines, no bake-time work required.

## Livestock, pets and critters

The `ObjectType` enum (`Pug.Base`) is the first thing to get right, because the
three creature families are typed differently and any bake-time filter you write
will silently include or exclude whole categories:

| `ObjectType` | Value |
|---|---|
| `PlaceablePrefab` | 800 |
| `Critter` | 801 |
| `Pet` | 802 |
| `Creature` | 900 |
| `PlayerType` | 6000 |

### Livestock (cattle)

Farm livestock are `ObjectType.Creature` (900) — confirmed in game, not
inferred. They are marked by an empty `struct CattleCD` (`Pug.ECS.Components`),
which `CattleConverter` assigns to every `: Cattle` prefab, so
`PugDatabase.HasComponent<CattleCD>(objectData)` determines the set without
hardcoding IDs.

| Species | Adult `ObjectID` | Baby `ObjectID` |
|---|---|---|
| Cow | 1300 | 1304 |
| Goat | 1302 | 1305 |
| RolyPoly | 1303 | 1306 |
| Turtle | 1307 | 1308 |
| Dodo | 1309 | 1310 |
| Camel | 1311 | 1312 |

`CattleFeedTray` (1301) sits inside that ID range but is a `Table`, not cattle.

**The baby↔adult relation is structural and readable at bake time.** The adult
carries `BreedStateCD` (from `BreedStateAuthoring.babyType` via
`BreedStateConverter`) whose `ObjectID babyType` points at its baby; a baby
carries no `BreedStateCD` at all. So "is some adult's `babyType`" is the fold
criterion — no name parsing needed.

**Discovery is per `(objectID, colour variation)`.** Cattle have no
`CanBeDiscoveredCD`, so there is no proximity discovery, but the game does
discover them through the inventory-pickup path
(`DetectUndiscoveredObjectsInInventory` → `SetObjectAsDiscovered`), keyed on the
animal's **colour variant** as the variation. The consequence is
counter-intuitive: a species you have only ever owned in a non-zero colour reads
as undiscovered on its variation-0 row. A caged animal is stored as the
*animal's* `ObjectID` plus aux data in a buffer.

**Enumerating a species' colour palette.** There is no per-species colour-count
API — no `CattleInfosTable`, no `maxColors` field, and `GetObjectInfo(id, v)`
falls back to variation 0 for every `v`, so it gives no "this variation exists"
signal. The full set is nonetheless authored: each cattle prefab's
`Pug.Properties.ObjectPropertiesCD` carries a `PossibleChildVariation[]` list
under property id **`239678920`** — the breeding-outcome list that
`Pug.Other.GetChildVariation` rolls from.

```csharp
PugDatabase.TryGetComponent<Pug.Properties.ObjectPropertiesCD>(objectData, out var props);
props.TryGetList(239678920, out NativeArray<BreedStateCD.PossibleChildVariation> list,
                 (AllocatorManager.AllocatorHandle)Allocator.Temp);
// distinct list[i].Variation values = the species' colours
```

Probed in game, every species yields `{0, 1, 2, 3, 4}` — five colours — and
every colour of a *wild-caught* animal falls inside that set, so despite the
name the list is the species' full palette, not a breeding-only subset. The call
is sandbox-safe; it needs `PugProperties.dll` in the runtime asmdef's
`precompiledReferences` and the namespace-qualified
`Pug.Properties.ObjectPropertiesCD`. Other unexplored property-list hashes on
cattle: `396300893`, `1985931659`, `158600710`, `594131635`, `1126076739`.

### The cattle cage is consumed at two points

The vanilla Cattle Transport Box (`ObjectID.CattleCage`, crafted from 6 Plank,
2 Tin Bar and 3 Iron Bar at the Livestock Workbench) is single-use, and there are
two distinct consume sites:

| Event | Where | What happens |
|---|---|---|
| Capture | `CageCattle()` `Pug.Other:422841` | Gated on `objectID == ObjectID.CattleCage`; calls `EntityUtility.DropPetInCage(...)`, `DestroyEntity(cattle)` (`Pug.Other:422887`), then `Create.ConsumeEntityAt(.., 1, destroy: true, ..)` (`Pug.Other:422891`) eats the empty box |
| Release | `PlaceItem()` `Pug.Other:323090` | The carried item is placed and consumed via `Create.ConsumeEntityAt(.., destroy: false, ..)`, amount from `objectDataCD2.amount` (`Pug.Other:323076-323079`); `Pug.Other:323012` is the `else` branch, not the consume |

**There is no "filled box" item.** This is the natural assumption and it is
wrong. `DropPetInCage` spawns a `DroppedItem` that carries the
animal itself as an **`ObjectType.Creature` item**, preserving its auxiliary
data — `NameCD`, `MealsEatenCD`, `BreedToggleCD` — while the cattle entity is
destroyed. The box is gone; what you hold is the animal.

**unverified** — `DropPetInCage` does not exist anywhere in the `1.3.0.2`
checkout, and `CageCattle` (which still does) no longer calls it: its body was
rebuilt around `IsValidEntityToCage` and a `SphereCastAll`. The described
outcome may well still hold, since it is about what the dropped item *is*, but
the mechanism above it was read from `1.2.1.5` and needs re-deriving before
anything is built on the detail.

That changes how you detect a release: test `objectType == Creature` **and**
`CattleCD` on the prefab. Testing for a cage object finds nothing.

The `amount < 1 && HasComponent<CattleCD>` exception in `CanConsumeEntityInSlot`
(`Pug.Other:311914`, static overload `Pug.Other:311921`) exists precisely so the
carried item can still be placed at amount 0.

Both sites live in Burst-compiled DOTS player systems (state-update and
equipment-update aspects), so intercepting them needs the Burst treatment in [Harmony and ECS](harmony-and-ecs.md).
Which call that treatment needs depends on where the patch target sits: patching
a system's own `OnUpdate` directly needs only the plain `DisableBurstForSystem`;
patching something a nested job calls — as `PlaceItem` is, from
`EquipmentUpdateSystem.UpdateJob` — needs `DisableBurstForSystemAndJobs` (see [nested jobs need the `AndJobs` variant](harmony-and-ecs.md#nested-jobs-need-the-andjobs-variant)).

**Trap: the data-only loot path does not fire on placement.** Emitting an empty
`CattleCage` through `SpawnsItemsOnUseCD` / `OpenItemAndSpawnLoot` (`Pug.Other:422703`)
looks like an elegant way to avoid a Burst patch entirely — it is a dead end.
That path is not reached when an item is *placed*, so a pure CoreLib data patch
cannot dispense anything at placement time. This was tested and rejected before
the equivalent mod was built as a code patch instead. (Verified for this case;
whether the path never fires on *any* placement is **unverified**.)

### Pets

Pets are `ObjectType.Pet` (802) — **not** `Creature`, which is a common wrong
guess when relaxing a bake filter to "include pets".

`SaveManager.SetObjectAsDiscovered` (`Pug.Other` ~`Pug.Other:380890`) force-zeroes
`variation` for anything with a `PetCD`, so `discoveredObjects2` only ever holds
a pet at `(objectID, 0)`. **The game does not track which pet skins you have
seen** — a skin collection is necessarily mod-owned state.

| Fact | Detail |
|---|---|
| Skin storage | `PetSkinCD { int skinIndex }`, an `[InventoryAuxDataComponent]` in the world-global `InventoryAuxDataSystem` — not a variation, not a direct entity component |
| Assignment | Random on hatch, `rng.NextInt(maxSkins)` |
| ObjectID | All skins of a pet share one ID (`PetDog` = 1222) |
| Skin count | `Manager.ui.petInfosTable.GetPetSkinInfo(id).skins.Count` — `PetCD.maxSkins` is baked from this same value (`Pug.ECS.Conversion:2910`) |
| Rendering | Gradient recolours of the base `ObjectInfo.icon` (`_GradientMap` from `skins[i].primaryGradientMap` plus the `USE_GRADIENT_MAP` keyword on the `Amplify/UISpriteColorReplace` shader), not separate sprites; `GradientMapDataBlock` lives in `PugSprite.dll` (`PugSprite:42`, global namespace) — only its base `ScriptableDataBlock` is in `ScriptableData.dll` (`ScriptableData:1648`) |
| Stacking | Pets are non-stackable, one per slot |

Reading `skinIndex` is sandbox-safe:
`InventoryHandler.TryGetExtraInventoryData<PetSkinCD>(containedObject, out
data)` (static; works for inventory and chest alike, since the aux data is
world-global). For the currently summoned pet, go `PetOwnerCD.PetEntity` →
`PetCD.inventoryAuxDataIndex` → the same lookup.

**Trap for possession counting:** a stored pet sits in a `ContainedObjectsBuffer`
and is found by an inventory scan, but a **summoned pet is a live entity outside
that buffer** and will be missed — the classic "I own 8, it counts 7" symptom.

Pets also carry generic `Level` and `Value` defaults (in game, Level 7 / Value 6
for every pet); those numbers are meaningless for pets and should not be
surfaced.

### Critters

Critters are `ObjectType.Critter` (801). Catchable ones become carriable items
with the **same ObjectID** when caught with the Bug Net, and
`SetObjectAsDiscovered` has no critter special case, so caught critters *are*
discovery-tracked exactly like items.

There are **25** obtainable critters, and a decompile-only survey does not find
them all:

| Group | ObjectIDs | Note |
|---|---|---|
| Net-catchable critters | 9800-9819 | 20 entries, no gaps |
| Fireflies / glowbugs | 3500-3504 | `YellowFirefly` (`Pug.Base:2719`, lower-case `f` — vanilla is inconsistent here), `BlueFireFly`, `GreenFireFly`, `RedFireFly`, `PurpleFireFly` (`Pug.Base:2723`); carry `FireflyCD`, **not** `CritterCD` |

Because the fireflies use a different component, following `TryCatchAnyCritters`
in the decompile leads away from them entirely. They are bug-net catchable
through a firefly path and appear in players' chests. `CritterCatcherCatchableCD`
is *automation* catchability and is not a clean predicate for "catchable with a
net".

### Pet talents

Pet talents are structurally unlike player talents, which live in `SaveManager`.

- **The budget lives in managed code.** The static class `PetExtensions` (global
  namespace, `Pug.Other.dll`) owns the curve:
  `GetTotalTalentPoints(int xp) = floor(GetLevelFromXP(xp) / 2)` and
  `GetAvailableTalentPoints(xp, ContainedObjectsBuffer) = total -
  GetSpentTalentPoints(buffer)`. With `maxLevel = 10`, vanilla tops out at
  **5 points**. Every caller is managed UI (`PetTalentUIElement.CanPlacePoints`,
  the pet-info `UpdatePointsText`), so it is Harmony-patchable **with no
  BurstDisabler**.
- **Trap: patching `GetTotalTalentPoints` alone may not move the budget.**
  Inlining a one-line method is a known Harmony pitfall: if the JIT inlines
  that call inside `GetAvailableTalentPoints`, a patch on
  `GetTotalTalentPoints` alone would not change what `GetAvailableTalentPoints`
  returns. A mod that scales this budget patches both methods defensively,
  against exactly that risk.
- **The server does not validate the budget.** `InventoryUtility.
  SetPetTalentPoints` writes `buffer[talentIndex].points = points` directly and
  trusts the client; the only enforcement anywhere is the client-side UI reading
  `PetExtensions`. Verified in game: a server accepted 7 spent points on a
  level-8 pet.
- **The tree is 9 talents, 3 rows of 3.** Each talent costs exactly 1 point
  (binary, `points > 0`). Row `talentIndex / 3` unlocks once `spentPoints >=
  rowIndex`. `PetTalentBuffer` has `InternalBufferCapacity(9)` and is stored in
  the pet's inventory aux data alongside `PetSkinCD`.
- **Level-up feedback is level-driven, not talent-driven.** `Pet.UpdateLevel`
  fires the "PetLeveledUp" chat line, the `GainTalentEffect` puff and the success
  tone on a level change, independent of the talent-point formula. Pet damage is
  `GetDamage(xp, type)` via `GetLevelFromXP` — also independent.

## Cooked food is combinatorial

There is no curated dish list. Cooking combines **two** ingredients; the dish's
`ObjectID` is one of **15 base families** — Soup, Cake, Cereal, Cheese, DipSnack,
Fillet, FishBalls, PanCurry, Pudding, Salad, Sandwich, Smoothie, Steak, Sushi,
Wrap — and the concrete identity is packed into the `variation`:

```csharp
// the arguments are the two RAW ingredients, in either order
CookedFoodCD.GetFoodVariation(i1, i2) =
    ((int)GetPrimaryIngredient(i1, i2) << 16) | (int)GetSecondaryIngredient(i1, i2)
```

**Do not do the shift yourself.** Which ingredient becomes primary is decided
inside: golden plants and `StarlightNautilus` win by rule
(`IngredientShouldBePrimary`), everything else by a seeded tiebreak
(`FirstIngredientIsPrimary`). That normalisation is *why* the pair is symmetric
— packing your own two arguments produces the wrong variation for about half of
all pairs. It also decides the dish family: the **primary** ingredient's
`CookingIngredientCD.turnsIntoFood` picks it.

The name is generated per pair (`Pug.Other` ~`Pug.Other:312445`): `foodFormat` composes an
adjective (`FoodAdjectives/<secondary>`), a noun (`FoodNouns/<primary>`) and the
dish type (`Items/<family>`), with grammatical gender. A "Mushroom Soup" is
simply mushroom in both slots. Each pair is a genuinely distinct, separately
tracked recipe: the in-game cookbook lists one row per variation via
`Manager.saves.GetDiscoveredCookedFoods()` and shows no total — just the count
discovered.

The arithmetic, measured in game on Core Keeper 1.2.1.5:

| Quantity | Value |
|---|---|
| Distinct ingredient pairs | 3,003 (symmetric — `GetFoodVariation(a,b) == GetFoodVariation(b,a)`) |
| Rarity tiers per pair | base and `rareVersion` unconditionally; `epicVersion` gated — see below |
| Cooked-food `ObjectID`s (15 families × 3 tiers) | 45 |
| Pairs whose epic tier is actually reachable | 858 |
| Pairs whose epic tier is baked but phantom | 2,145 |
| **Distinct obtainable dishes** | **6,864** — `3,003 × 2` (base + rare, unconditional) `+ 858` (reachable epic) |

**The epic tier is gated, not unconditional.** A `flag` in
`Pug.Other:336153-336193` guards the epic counter (`num5++`) entirely: it
requires a Rare-rarity Flower among the ingredients or any Legendary
ingredient. Without it, only base and rare are reachable — which is why
2,145 of the 3,003 pairs have an epic `ObjectID`/variation baked into the
database that no cooking roll can ever produce. That same roll
(`ChanceToGainExtraCookedFood` → `ChanceForExtraCookedFoodToBeRare`,
`Pug.Other:336149-336150`) shifts by one tier when `flag` is set: a roll that
would otherwise add base instead adds rare, and one that would otherwise add
rare instead adds epic.

**Trap: the widely cited wiki figure of 5,550 dishes is wrong.** It lists three
rarity colours and then multiplies by two — self-contradicting. The code has
three tiers, and a runtime enumeration counts 3,003 pairs across them, of
which only 858 ever reach epic.

This still dominates any exhaustive item catalogue: a bake enumerates every
baked `ObjectID`/variation row, phantom epics included, so the cooked block
in a catalogue is larger than the 6,864 dishes a player can actually obtain.
The exact ratio against the rest of the database moves with the game version
and needs its own fresh count; what has not changed is that the block is
large enough that any UI rendering it needs viewport virtualisation, because
naive per-item `GameObject`s choke on it.
