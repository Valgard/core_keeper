# Save file formats

Core Keeper writes worlds, characters and explored maps to disk in three
different formats, and they are not equally approachable. This chapter covers
what each file actually is, what you can realistically read out of it, and the
traps that make a naive reading wrong. You need it whenever a question is about
*world state* — where objects stand, what a world contains, whether a given save
copy is still the one that matters — because that question is answered by
data, not by reasoning about the code: the save, or for a world your own game
process hosts, the running game.

## Where the saves live

On the client, everything sits under one save root:

```text
…/LocalLow/Pugstorm/Core Keeper/<platform>/<user-id>/
```

`<platform>/<user-id>` is e.g. `Steam/<numeric id>`; the Steam beta branch named
`experimental` inserts an `experimental/` segment before it. The dedicated server has no
`<platform>/<user-id>` part: its root is the `-datapath` argument, or
`persistentDataPath/DedicatedServer` without one
(`DedicatedServer/Pug.Other:StandaloneFilesystem:StandaloneFilesystem(string, PlatformInterface):3-11`).
This is the same root under which the loader hands every mod one shared `mods/`
directory; a subdirectory per mod inside it is convention, not something the
loader creates or confines a mod to — see [the sandbox](sandbox.md) for the API that reads and
writes there.

| Path below the save root | Holds |
|---|---|
| `worlds/<n>.world.gzip` | one world — Brotli-compressed DOTS entity dump |
| `worldinfos/<slot>.worldinfo` | plain JSON metadata for that world slot (as current builds write it — see below) |
| `saves/<slot>.json` | one **character** |
| `maps/<character-slot>/<server-index>.mapparts.gzip` | that character's explored map of one server they visited |
| `mods/` | every mod's persisted files, by convention one `<ModName>/` each |

**Characters are in `saves/`, worlds are in `worlds/`.** The directory names
invite exactly the wrong guess, and the two use independent slot numbering.

## The world file

### It is Brotli, despite the `.gzip` extension

`WorldDeserializer.DecompressSerializedWorld` sniffs both containers —
`TryGetGzipCompressedSize` first, then `TryGetBrotliCompressedSize`. Real files
on disk are Brotli. In Python, one call over the whole file works:

```python
import brotli

raw = brotli.decompress(open(path, "rb").read())  # e.g. 1.5 MB → 23 MB
```

Feeding it to `gzip` fails, which reads as a corrupt save and is not.

### Decompressed, it is a DOTS `EntityBinaryFile`

| Offset | Content |
|---|---|
| 0 | magic `DOTSBIN!` |
| 8 | `int version` |

| Version at offset 8 | Meaning |
|---|---|
| 77 | current |
| 76 | older post-DOTS-1.1 layout |
| below 76 | gets patched on load |
| above 77 | not readable — ends as `SaveFileCorrupt` |

One older format predates that header: a file whose first `int`, at offset 0,
is 57 is recognised before any magic check and patched too
(`Pug.ECS.Serialization:WorldDeserializer:ShouldPatch:9-12`).

From there it is a full ECS world dump: archetype tables, 16 KB chunks, entity
remapping — and a table of the 64-bit `StableTypeHash` of every component type
the archetypes use, which the next section turns on.

### The file carries type hashes, not type names

This is the fact that decides whether a given question can be answered from the
world file at all, so it is worth stating before you start.

**Component types appear as 64-bit stable type hashes, and in the files measured
here never as names.** `WriteArchetypesNode` writes the `StableTypeHash` of every
component type into a table of the file's own, and each archetype refers to its
types by position in that table (`Unity.Entities:SerializeUtility:WriteArchetypesNode`).
So which type an archetype holds is recorded in the file itself; what the file
does not tell you is which type a hash *is*. A stable hash does not change
between builds as long as the type does not, and Pugstorm pins many of theirs
explicitly with `[TypeManager.OverrideTypeHash(…)]` — `NameSerializedCD`
carries one (`Pug.ECS.Components:NameSerializedCD:4`).

The names are a measurement, not a code fact, and the code points the other way:
the game serialises with Unity's default settings, which have
`SerializeComponentTypeNames = true` and write a debug section pairing each hash
with its type name (`Unity.Entities:SerializeUtility:WriteTypeNames`). Yet
measured on all nine worlds on this machine (2026-10-15, each last saved by a
1.3 build), not one serialised type name appears — `NameSerializedCD`,
`Translation`, `ObjectDataSerializedCD`, `Unity.` and `Pug` all return zero hits
— while the pinned hash of `NameSerializedCD` appears exactly twice in each. Why
the names come out empty in a shipped build is **unverified**: the decompile of
`TypeManager.GetTypeName` is too mangled to say. (Until 2026-10-15 this section
said the types appear as "numeric indices" decided by "the build's `TypeManager`
registry", and offered as evidence a search for `MapMarkerCD`, `LocalTransform`
and `ObjectDataCD` — three runtime types the file would not contain even if it
carried names.)

Which component sits at which offset inside a chunk comes from that chunk's
archetype table.

**Plain strings are a different matter, and a `strings` pass is worth one minute
before you conclude the file is opaque.** A real 24 MB world here yields 191
readable runs of eight characters or more, in three groups:

| Group | Source | Examples |
|---|---|---|
| ~180 scene and structure names | `CustomSceneBlob.sceneName` | `AbandonedCampScene`, `CavelingCampfire`, `SeedVault1`, `AmberBoulderScene` |
| the player's own labels | `NameSerializedCD`, length-prefixed | whatever they named chests and pets |
| the world-generation parameters | plain JSON, ~4 KB | `{"globalSeed":…,"worldScale":…,"biomeChaos":…}` — identical to `worldgenparams/<n>.json` |

So "which named structures does this world contain?" and "what did the player
label things?" are `grep` questions, answerable in seconds without any registry.

What a string pass cannot give you is the **pairing** — which label belongs to
which entity, at which position, carrying which components. That needs two
things the file does not contain: a mapping from stable type hash to type,
taken from a build whose types match the file's, and an archetype-aware chunk
walker. Without both you cannot tell that a record is an
`ObjectDataSerializedCD`, and you cannot tie it to the `Translation` of the
same entity — which is usually the half you actually wanted.

**Trap: a byte-pattern search will produce convincing false positives.** Looking
for a plausible struct layout — say three little-endian `int32`s whose values
fall inside two enums — finds matches, and they even cluster the way real chunk
arrays would. Dumping the surrounding bytes is what settles it: a run of small
integers with no consistent stride is an index or tile array, not a component
array. Test any such hit by its context before believing it. That does not make the
approach useless — the marker walk below is exactly such a scan — but it does
mean a match is a hypothesis until something outside the file confirms it.

### Worked example: reading map markers out of the file

Of everything in a world file, markers are the easiest thing for a byte-level
scan to reach — a marker is not a separate save format, it is an ordinary world
entity, and its on-disk record is small enough to find without a chunk walker.
Markers are also never packed into the unloaded-segment pool described below:
`DontUnloadConverter` gives every `MapMarkerAuthoring` a `DontUnloadCD`
(`Pug.Other:DontUnloadConverter:Convert`), so wherever a marker stands it stays a
plain entity. That earns the marker walk below its place as a worked example; it is
not a claim that the file is the route to take — this section closes by naming
the running game instead.

**There is no marker file.** No `.mapmarkers`, and markers are *not* in
`mapparts` — those are fog-of-war pixels. A marker lives in the world file
because nothing that creates it attaches `DontSerializeCD`: neither the 1.3
`MapMarkerRpc` handler vanilla uses today (cited below) nor the older
`CreateMapUI` command, whose neighbouring case in the same switch does attach it
(`Pug.Other:ServerSystem:OnUpdate`).

**What survives the trip is less than the component you know.** On save,
`ObjectDataCD` is repacked into `ObjectDataSerializedCD` — three `int`s, **12
bytes**: `ObjectID`, `Amount`, `Variation`. The fourth runtime field is dropped,
which is why these records sit at a stride of 12 and not 16, the likelier guess.
`MapMarkerCD` itself is never written; it comes back from the prefab at load,
when `DeserializeComponentsSystem` recreates each object through
`EntityUtility.CreateEntity` — which instantiates the prefab and passes the
stored `Amount` through unchanged. When this section was first written, against
1.2, markers carried **no text** — the type enums were the entire vocabulary.
The 1.2.1.5 decompile agrees: the server's `CreateMapUI` handler creates the
marker from a position and a variation, with amount 1, and sets no name
(1.2.1.5: the `case Command.CreateMapUI` branch of
`PlayerCommand.ServerSystem.OnUpdate` in `Pug.Other`). The 1.3 migration adds an
empty name only where none exists
(`Pug.Other:ConvertOldMapMarkersSystem:OnUpdate:27-30`), which leaves room for
markers that already had one.

**Since 1.3 a player's marker carries two more serialized components**, because
its icon is no longer a slot but a data block ([world and mechanics](world-and-mechanics.md#since-13-a-user-markers-icon-is-a-data-block)):
`MapMarkerCustomDataSerializedCD` — the icon's `DataBlockAddress`, a 16-byte
GUID, and a variant index
(`Pug.ECS.Components:MapMarkerCustomDataSerializedCD:iconAddress:1`,
`Pug.ECS.Components:MapMarkerCustomDataSerializedCD:variantIndex:1`), written from the
runtime `MapMarkerCustomDataCD` (`Pug.Other:SerializeObjectJob:Execute:559`) —
and `NameSerializedCD`, the marker's name as a `FixedString64Bytes`
(`Pug.ECS.Components:NameSerializedCD:Value:1`). So a 1.3 save does hold marker text.

The two ObjectIDs are `MapMarker = 2402` and `MapMarkerCoreAttention = 2403`.

**Classify on the pair `(Amount, Variation)`, never on `Variation` alone:**

| Amount | Variation | Meaning |
|---|---|---|
| 1 | 0–3 | placed by the player through the vanilla UI, up to 1.2 |
| 1 | 0 | placed by the player through the vanilla UI since 1.3 — the icon is in `MapMarkerCustomDataSerializedCD` |
| 1 | 14 | automatic, lowest-segment marker — exists only while that segment does |
| 1 | 30–37 | automatic, echo dungeons |
| 1 | 44 | automatic, observed; source not traced |
| ≥ 6000 | 1 up to 1.2, 0 once migrated | written by a mod, see below |

Match the automatic ranges on `Variation` and treat `Amount` as confirmation
rather than as the key. Measured on the nine worlds on this machine
(2026-10-15): every echo-dungeon marker carries amount 1, five worlds hold one
marker at variation 44, and none holds a 14 — that one marks the snake boss's
lowest segment, is created while the segment exists and destroyed three seconds
after it is gone (`Pug.Other:UpdateMapMarkerJob:Execute`, nested in
`SnakeBossSystem`). The 1 on the echo markers is not what every route writes:
the migration that injects them into a world below version 10 sets only the
object id and the variation
(`Pug.Other:AddEchoMapMarkersToSpawnedDungeons:OnUpdate`), so it leaves amount
0, and loading passes that through. The worlds measured here carry 1, so their
markers came by another route; which one, and what variation 44 marks, is
**unverified**. A marker arriving by some other route need not carry an amount
of 1 at all. A marker the 1.3 client places is prespawned with variation 0
(`Pug.Other:MapUI:PlaceMarker:7`) and created by the server with amount 1
(`Pug.Other:ServerSystem_4A171A05_LambdaJob_1_Job:OriginalLambdaBody:11`). That
covers markers the vanilla client creates, not every 1.3 marker: the pre-1.3
path is still in the game, a `CreateMapUI` command
(`Pug.Other:ClientSystem:CreateMapUI:1`) whose server handler creates a marker
at the variation the caller asks for, minus 2, and always at amount 1
(`Pug.Other:ServerSystem:OnUpdate:100-107`). Vanilla no longer calls it, but a
mod can, and its markers can carry a non-zero variation — except in a
guest-mode world, where the server drops the command from a player who is not an
admin (`Pug.Other:ServerSystem:OnUpdate:41-47`). What such a marker cannot carry
is an amount of the mod's choosing.

**World version 13 converts the old slots once.** `ConvertOldMapMarkersSystem`
runs while a world is below version 13, or carries no version record at all
(`Pug.Other:ConvertOldMapMarkersSystem:OnUpdate:4`), and touches only
`MapMarker` records — never `MapMarkerCoreAttention` — with variation 0–3
(`Pug.Other:ConvertOldMapMarkersSystem:OnUpdate:18`): each gets a
`MapMarkerCustomDataSerializedCD` holding the vanilla icon its slot used to show
(`GetDefaultIconForVariation`,
`Pug.Other:ConvertOldMapMarkersSystem:GetDefaultIconForVariation:1`; variation 1
becomes the yellow question mark, icon `7e09f30c-8838-5604-2b46-8c13b0ef771e`
with variant 9), its variation is set to 0
(`Pug.Other:ConvertOldMapMarkersSystem:OnUpdate:26`), and an empty
`NameSerializedCD` is added where none exists
(`Pug.Other:ConvertOldMapMarkersSystem:OnUpdate:29`). **`Amount` is not
touched** — which is what the next paragraph turns on.

An earlier version of the table above also listed an `Amount` of 0 alongside a
fixed variation as a mod's. The value exists in the source of the mod meant,
MapMarkers+, for five of its types — the four placeable markers it backs with
vanilla art, and Ping — but it does not reach the world: the mod hands those
markers to the game's own creation path. In the world measured below, the
recorded scan counts nine player markers at `Amount` 1 besides the mod's 62
(map-markers-enhanced, `docs/manual-tests.md`, "Legacy restoration") — "at
`Amount` 1" is the scan's counting criterion, not a finding, so a marker at any
other amount would not appear in it. That no marker there carries 0 was observed
without a recorded count.

**Third-party mods can repurpose `Amount`.** A marker has no use for an amount,
so the field is free — and at least one marker mod, MapMarkers+, stores its icon
type there as `6000` plus the type's index, keeping `Variation` fixed. Three
consequences follow, and each bites whether or not you care about that mod:

- **A filter like `Amount == 1` as "noise reduction" silently discards every
  modded marker.** In one real world, scanned before 1.3 and without a recorded
  count, 64 of 76 markers were the mod's; read with the vanilla rule alone they
  all decode as one wrong icon type. This was written after doing exactly that —
  the out-of-range values looked like garbage and were the payload.
- **A modded marker outlives the mod.** It rides on vanilla's entity, so
  uninstalling leaves it in the world. Up to 1.2 it then renders as whatever
  plain icon its `Variation` names; since 1.3 a marker's icon is its
  `MapMarkerCustomDataSerializedCD`, which the next point supplies.
- **And the 1.3 migration reads that `Variation` too.** MapMarkers+ stored all
  of its own markers in slot `Marker2`, variation 1, so version 13 turned every
  one of them into the same question mark. Measured on one real world (1.3.0.2):
  62 markers, all question marks, all still carrying their original `6016` to
  `6028`. Because `Amount` survives, the original type is still recoverable
  from the save — until something rewrites it.

A mod's own icon table is in its installed sources, and nothing keeps it fixed
between releases — read it rather than hardcoding it.

**A changed `Amount` on an existing marker is saved.** `SerializeObjectJob`
rewrites `ObjectDataSerializedCD` from the live `ObjectDataCD` in every chunk
whose `ObjectDataCD` changed since the last save
(`Pug.Other:SerializeObjectJob:Execute:238`, the `Amount` copy at
`Pug.Other:SerializeObjectJob:Execute:248`). Measured on 1.3.0.2: a mod set
`Amount` from `6016`–`6028` to 1 on those 62 markers on a copy of the world, and
a scan of the next save found none left at or above 6000.

**Position comes from a fixed offset, not from a parser** — and the position is
stored under a different type than the one the running entity carries. A live
entity has `LocalTransform` (position, rotation, scale); serialisation reduces it
to **`Translation`, a bare `float3`**, exactly as `ObjectDataCD` is reduced to
`ObjectDataSerializedCD`. The name simply lacks the `Serialized` suffix, which
makes it easy to reach for the runtime type and compute a stride that finds
nothing.

That reduction is also where the arithmetic comes from. A chunk stores one array
per component, slot-parallel, in the components' memory order — which Pugstorm
pins for both types here with `[TypeManager.ForcedMemoryOrdering(…)]`. In the
1.2 marker archetype the `Translation` array (12 bytes per element) followed the
object array directly, so the position of the record at offset *N* was at *N* +
(chunk capacity × 12), +1536. In the 1.2 worlds scanned, `y` was always exactly
`0.0` and x/z were integers. Whether 1.3 player markers keep integer x/z is
**unverified**: `MapUI.PlaceMarker` builds the position from the map position
with `y = 0` and no rounding, and `CreateEntity` stores what it is handed, but
the conversion in between (`ToRenderFromWorld`) was not traced. **Derive the
summand for any other archetype rather than reusing this one** — it is the
capacity times the element sizes of every array lying between the two, and all
of these change. The echo-dungeon markers a migration injects are already a
different archetype, with a `CustomSceneObjectSerializedCD` beside the two.

**1.3 changed exactly that.** A 1.3 player marker carries the two components
above as well, which makes it a different archetype, and on 1.3.0.2 the +1536
walk no longer landed on the positions — observed while scanning, without a
recorded test. The object records themselves are still found by the pattern
below; the position summand for the 1.3 player-marker archetype is
**unverified** — it has to be derived again, and has not been here.

That makes the whole scan: decompress, walk 4-byte-aligned for the little-endian
ObjectID, read the next two `int`s as amount and variation, take the position at
the fixed offset.

**Trap: a count taken right after a save can include a record that is not
there.** Counting player markers by this pattern in one 1.3.0.2 world gave 72
after the save in which a mod had restored 62 legacy markers, and 71 — the 9
other player markers plus the 62 — after the save of the next launch. The extra
record was gone on its own, and what it was is **unverified**. It was not a
marker parked in the unloaded-segment pool described below, since markers carry
`DontUnloadCD` and are never put there. Before trusting a count, compare two
consecutive saves.

**How to know the scan is right, which is the harder half.** A byte pattern that
matches is not a finding — see the false-positive trap above. What settles it is
a *second, independent* source for the same world: look up the map pixel under
each candidate in the `mapparts` PNGs and require that different marker types
land on **different** colours. The first version of that test asked only whether
all markers of one type hit the same colour, which the background rock satisfies
trivially because it is everywhere. A consistency check that the trivial case
also passes measures nothing.

**The practical route is the running game, not the file.** Inside the process
the type registry exists and the entity-to-component mapping is free, so a query
like `WithAll<MapMarkerCD>()` over the server world hands you the component and
its transform together — for a world your own process hosts (singleplayer, a
hosted game, a dedicated server), that beats the scan above. A client joined to
someone else's server has no server world, only the ghosts it was sent. See [reading the live ECS world](harmony-and-ecs.md)
— for anything entity-shaped and loaded, or kept loaded like a marker, that is
the cheaper answer by a wide margin; an object packed into an unloaded segment
is not in the live world at all. The file is worth parsing only for what a
running game cannot show you, such as a world you are not in.

### Unloaded segments are a recycled entity pool

Outside the loaded area, objects are not stored as loose entities — except those
carrying `DontUnloadCD` (players, bosses, map markers and a list more, set by
`DontUnloadConverter`), which stay plain wherever they stand.
`UnloadToSerializeWorldSystem` / `SerializeObjectJob` pack 128-tile world
segments (`UNLOADED_WORLD_SEGMENT_SIZE_LOG2 = 7`) into a recycled entity pool
held by `SerializeWorldDataCD { serializedEntities, freeRangeList, chunks,
freeChunks }`.

**Merging two save files at the binary level is practically ruled out.** You
would have to keep archetype layouts, chunk occupancy, entity IDs *and* the
free-range pool mutually consistent. A mistake that makes the reader throw
yields `DeserializationStates.SaveFileCorrupt` — every exception during
deserialisation ends there
(`Pug.ECS.Serialization:WorldDeserializer:DeserializeWorld`). One that stays
structurally valid loads as finished, and nothing then catches a wrong or
missing object. A **read-only** parser is a different matter — the exact
serialization code is in `Unity.Entities`, so it is buildable, but treat it as a
real project rather than a quick script (see [Reverse engineering](reverse-engineering.md) for getting at
that code).

### Cheap indicative measurement, without a parser

When you only need a signal — "did this world lose ore boulders between these
two copies?" — you can count 4-byte-aligned `<i` packed ObjectIDs in the
decompressed blob.

**This is an indicator, never a census.** In a world with thousands of
boulders such a scan finds on the order of 150. Why it misses the rest is
**unverified**: the segment pool is the obvious suspect, but its entities are
written with the same 12-byte `ObjectDataSerializedCD` record the scan matches,
so the code read so far does not explain the gap.

What makes such a count trustworthy is **selectivity, not the absolute number**:
compare several copies and include control object types that the suspected
mechanism cannot touch. If the counts move only downward and only for the types
under suspicion, while controls such as `AmberBoulder` (ObjectID 5606) and
`CrystalMeteorBoulder` (5879) stay flat across the same copies, the signal is
real even though every number is an undercount.

## The map file

`maps/<character-slot>/<server-index>.mapparts.gzip` is the friendly one, and it is
object-aware.

### gzip → JSON → PNG tiles

It is **real gzip** (`1f8b` magic). Inside is JSON:

```json
{"mapParts": {"keys":   [{"x": 0, "y": 0}],
              "values": [{"png": [ … ], "timestampPng": [ … ]}]}}
```

`keys`/`values` are a serialized `SerializableDictionary<Vector2Int,
MapPartSerialized>`. `png` is a byte array of a **256×256 RGBA PNG**, one per map
tile, written with `Texture2D.EncodeToPNG` and read back with `LoadImage`.
`timestampPng` is a second PNG of the same size holding, per pixel, when that
pixel was last written — it is what map sharing compares to decide which copy of
a pixel is newer (`MapUI.TimestampIsNewer`), and the one field that tells you how
stale a pixel is.

Its elements come back plain 0–255 — every array starts `137, 80, 78, 71`, the
PNG magic, with 137 stored positive — so `bytes(arr)` works directly. Masking
each element with `& 0xFF` costs nothing and guards against a JSON reader that
hands you signed values, but a decode failure here is not caused by sign: the
field is a plain `byte[]` on `MapPartSerialized`.

### Objects are pixels in their own map colour

Every object whose data has `appearInMapUI: 1` and is not currently hidden is
drawn into the tile in its own `mapColor` from the prefab. That makes objects
findable **pixel-exact by colour** — and note the map is the *only* place that
colour appears: the world save does not store it.

An object is drawn over the tiles it occupies, so a boulder — 2×2 and square —
comes out as a clean 2×2 cluster, and connected-component clustering per colour
recovers individual boulders as long as they do not touch: two adjacent
boulders of one colour merge into one component, and a later-drawn object
overwrites the pixels it shares with an earlier one.

**Do not turn the cluster shape into a decode check.** The drawing loop
(`UpdateAppearanceInMapUI`) uses the *direction-adjusted* size — the corner
offset is passed through unchanged, not the raw ones:
`EntityUtility.GetPrefabSize` returns `prefabTileSize` verbatim only for an
object without a `DirectionCD`, and otherwise routes it through
`DirectionCD.GetPrefabTileSize`, which **transposes** it when `abs(direction.x)
> 0.5`. A square prefab is unaffected — which is why the boulder example holds —
but a 3×1 prefab is drawn 3×1 or 1×3 depending on how it was placed, so an
unexpected cluster shape says nothing about your decode.

### Tile index and in-tile position

Both formulas come from `MapUI`, componentwise:

| Function | Formula |
|---|---|
| `WorldPositionToMapPartIndex(worldPos)` | `floor((worldPos + 0.5) / 256)` |
| `WorldPositionToMapPartPosition(worldPos)` | `((worldPos % 256) + 256) % 256` |

`worldPos.y` in those functions is the world **z**, not height — CK's ground
plane is XZ. The index formula is the practical form: the code truncates after
shifting negative values by −256 (`Pug.Other:MapUI:WorldPositionToMapPartIndex`),
which equals the `floor` above for every whole-tile position and differs only
where `worldPos + 0.5` is an exact negative multiple of 256.

### Trap: PNG rows are mirrored against the Unity texture

`WorldPositionToMapPartPosition` returns a *texture* coordinate, with y = 0 at
the bottom. `EncodeToPNG` writes rows so the image displays upright, and an
image library reads row 0 as the top. So going from a pixel back to a world
coordinate:

```python
z = key["y"] * 256 + (255 - png_row)
x = key["x"] * 256 + png_col
```

This flip is derived from the encode/decode path, not confirmed in-game.
Confirm it in ten seconds before you build on it: render a composite of the
tiles and compare it against the in-game map with a landmark (a ruin anchors it
well), or read one object's coordinates off a coordinate HUD that prints raw
`floor(pos.x)` / `floor(pos.z)`.

### Trap: the map is a fog-of-war snapshot, not live state

A map tile is drawn from live objects only while a player is near it; the other
way it changes is map sharing, which merges in pixels another player's map holds
with a newer timestamp (`ShareMapServerSystem`). Without either, an object
destroyed far away leaves its pixel behind indefinitely.

So a map pixel records **where something once was, not where it is** — and its
`timestampPng` entry records when. Which cuts both ways:

- For recovery work this staleness is the feature — the map still shows where
  objects stood before they were removed.
- For counting losses it is disastrous. A diff of two maps undercounts badly:
  in one case it surfaced 2 losses where roughly 19 had occurred.

If you need current state rather than remembered state, read the live ECS world
instead, for whatever is loaded there — see [Harmony and ECS](harmony-and-ecs.md).

## Telling save copies apart — GUID, never slot number

`worldinfos/<slot>.worldinfo` is plain JSON, roughly 1.3 KB, no compression, as
current builds write it — the file manager still flags it as encrypted in older
builds (`usedToHaveEncryption`), so a very old copy need not be readable as
text. Among its fields:

| Field | Meaning |
|---|---|
| `name` | display name of the world |
| `guid` | the world's identity |
| `seed` | generation seed |
| `bossesKilled` | progression |
| `activatedCrystals` | progression |
| `creationDate` | when it was created |

**Before you discard any save copy, compare `guid`.** The slot number is only a
filename: the same slot holds different worlds over time, and a backup labelled
"Slot 1" may be a *different* world than today's Slot 1 rather than an older
version of it. The pair `guid` + `seed` settles which world a copy descends
from; `bossesKilled` and `activatedCrystals` then tell you how far behind a
same-GUID copy is. That last step assumes one copy is an ancestor of the other:
a copied world keeps its `guid`, so two copies played on independently share
`guid` + `seed` while their contents diverge.

Getting this wrong loses worlds. Two backups that looked like one
undifferentiated pile of debug leftovers turned out to be a *different* world
(other GUID and seed — i.e. the last copy of it in existence) and a same-GUID
snapshot two bosses behind the live world.

### Which character played which world

`saves/<slot>.json` carries a `servers` list of `serverGuid`s plus a
`serverConnectCount`. Match a `serverGuid` against a `worldinfo` `guid` to see
which worlds a character has been in.

**Trap:** a purely local, never-hosted world also appears in that list.
The entry proves the character played that world — it does **not** prove that
anybody else could connect. A local game runs its own server world in the same
process (`ECSManager.StartEcs` creates a `ServerWorld` beside the client world
whenever a world is loaded and the play type is not client-only), and the
character's entry is made from that server world's connect answer, the same way
as for a remote server (`Manager.networking.serverGuid = answer.serverGuid`).

## Validate against the save, don't infer

Standing rule for anything about world state: **check a real savegame before
asserting it or building a fix on it.** Inference about world layout is
unreliable and the data is usually reachable in minutes.

The failure mode is confident geometry. Asserting that a set of objects "lies
within the base's anchor radius" felt safe and was wrong twice; parsing the
mod's own ledger (see below) put them 337–693 tiles out, anchored by remote
world structures (abandoned-camp campfires, a mechanical vault's seed extractor)
rather than by the base at all.

Practical order of attack:

1. **Read whatever is already plain text** — `worldinfo`, `saves/<slot>.json`,
   any mod ledger. No decompression needed.
2. **Read the map file** for positions and clusters, remembering it is a
   snapshot.
3. **Only then** consider the world file — for an indicative count, or for the
   few records a scan can reach, such as the markers above.
4. Cross-check a structural hypothesis *before* coding it. "A base is anchored
   by a workbench" was only adopted after confirming in the save that every
   workbench sat at the base and none in any remote cluster.

Decode ObjectIDs you do not recognise from the game's `ObjectID` enum in the
decompile — a single-file bounded grep, see [Reverse engineering](reverse-engineering.md).

### Reading a mod's own ledger

When a mod persists its own scan results, that file is often the fastest ground
truth available — it already holds the mod's *interpretation* of the world, so
it answers "what does the mod actually count, and where?" directly.

The one the examples in this chapter come from — Item Checklist's possession
ledger, `mods/ItemChecklist/possession-<character guid>.txt` — is plain ASCII,
one line per container:

```text
x,z|id:count,id:count,…
```

Parsing one gives you positions, cluster membership and which IDs cluster
together — enough to check distance to the Core, spot that a "base" scan is
really picking up a remote structure, or confirm which objects a rule fires on.
How a mod writes such a file in the first place belongs to [Storing configuration and state](persistence.md).
