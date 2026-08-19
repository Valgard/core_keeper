# Save file formats

Core Keeper writes worlds, characters and explored maps to disk in three
different formats, and they are not equally approachable. This chapter covers
what each file actually is, what you can realistically read out of it, and the
traps that make a naive reading wrong. You need it whenever a question is about
*world state* — where objects stand, what a world contains, whether a given save
copy is still the one that matters — because that question is answered by
parsing the save, not by reasoning about the code.

## Where the saves live

Everything sits under one save root:

```text
…/LocalLow/Pugstorm/Core Keeper/<platform>/<user-id>/
```

`<platform>/<user-id>` is e.g. `Steam/<numeric id>`. This is the same root under
which the loader hands a mod its own `mods/<ModName>/` directory — see
[sandbox-and-config.md](sandbox-and-config.md) for the API that reads and writes
there.

| Path below the save root | Holds |
|---|---|
| `worlds/<n>.world.gzip` | one world — Brotli-compressed DOTS entity dump |
| `worldinfos/<slot>.worldinfo` | plain JSON metadata for that world slot |
| `saves/<slot>.json` | one **character** |
| `maps/<character>/<world>.mapparts.gzip` | that character's explored map of that world |
| `mods/<ModName>/` | a mod's own persisted files |

**Characters are in `saves/`, worlds are in `worlds/`.** The directory names
invite exactly the wrong guess, and the two use independent slot numbering.

## The world file

### It is Brotli, despite the `.gzip` extension

`WorldDeserializer.DecompressSerializedWorld` sniffs both containers —
`TryGetGzipCompressedSize` first, then `TryGetBrotliCompressedSize`. Real files
on disk are Brotli. In Python, one call over the whole file works:

```python
import brotli
raw = brotli.decompress(open(path, "rb").read())   # e.g. 1.5 MB → 23 MB
```

Feeding it to `gzip` fails, which reads as a corrupt save and is not.

### Decompressed, it is a DOTS `EntityBinaryFile`

| Offset | Content |
|---|---|
| 0 | magic `DOTSBIN!` |
| 8 | `int version` |

| Version | Meaning |
|---|---|
| 77 | current |
| 76 | older post-DOTS-1.1 layout |
| below 76 | gets patched on load |
| 57 | also patched |

From there it is a full ECS world dump: archetype tables, 16 KB chunks, entity
remapping.

### The file contains no type names, which is what makes it opaque

This is the fact that decides whether a given question can be answered from the
world file at all, so it is worth stating before you start.

**Component types appear as numeric indices, never as names.** Searching a
decompressed world for `MapMarkerCD`, `LocalTransform` or `ObjectDataCD` returns
**zero** hits. Which index means which component is decided by the build's
`TypeManager` registry, and which component sits at which offset inside a chunk
comes from that chunk's archetype table.

**Plain strings are a different matter, and a `strings` pass is worth one minute
before you conclude the file is opaque.** A real 24 MB world here yields 191
readable runs of eight characters or more, in three groups:

| Group | Source | Examples |
|---|---|---|
| ~180 scene and structure names | `CustomSceneBlob.sceneName` | `AbandonedCampScene`, `CavelingCampfire`, `SeedVault1`, `AmberBoulderScene` |
| the player's own labels | `NameCD`, length-prefixed | whatever they named chests and pets |
| the world-generation parameters | plain JSON, ~4 KB | `{"globalSeed":…,"worldScale":…,"biomeChaos":…}` — identical to `worldgenparams/<n>.json` |

So "which named structures does this world contain?" and "what did the player
label things?" are `grep` questions, answerable in seconds without any registry.

What a string pass cannot give you is the **pairing** — which label belongs to
which entity, at which position, carrying which components. That needs two
things the file does not contain: the type registry of **exactly** that game
build, and an archetype-aware chunk walker. Without both you cannot tell that a
field is a `MapMarkerCD`, and you cannot tie it to the `LocalTransform` of the
same entity — which is usually the half you actually wanted.

**Trap: a byte-pattern search will produce convincing false positives.** Looking
for a plausible struct layout — say three little-endian `int32`s whose values
fall inside two enums — finds matches, and they even cluster the way real chunk
arrays would. Dumping the surrounding bytes is what settles it: a run of small
integers with no consistent stride is an index or tile array, not a component
array. Test any such hit by its context before believing it.

**The practical route is the running game, not the file.** Inside the process
the type registry exists and the entity-to-component mapping is free, so a query
like `WithAll<MapMarkerCD>()` over the server world hands you the component and
its transform together. See [reading the live ECS world](harmony-and-ecs.md) —
for anything entity-shaped, that is the cheaper answer by a wide margin. The
file is worth parsing only for what a running game cannot show you, such as a
world you are not in.

### Unloaded segments are a recycled entity pool

Anything outside the loaded area is not stored as loose objects.
`UnloadToSerializeWorldSystem` / `SerializeObjectJob` pack 128-tile world
segments (`UNLOADED_WORLD_SEGMENT_SIZE_LOG2 = 7`) into a recycled entity pool
held by `SerializeWorldDataCD { serializedEntities, freeRangeList, chunks,
freeChunks }`.

**Merging two save files at the binary level is practically ruled out.** You
would have to keep archetype layouts, chunk occupancy, entity IDs *and* the
free-range pool mutually consistent. A mistake does not yield a missing object;
it yields `DeserializationStates.SaveFileCorrupt`. A **read-only** parser is a
different matter — the exact serialization code is in `Unity.Entities`, so it is
buildable, but treat it as a real project rather than a quick script (see
[reverse-engineering.md](reverse-engineering.md) for getting at that code).

### Cheap indicative measurement, without a parser

When you only need a signal — "did this world lose ore boulders between these
two copies?" — you can count 4-byte-aligned `<i` packed ObjectIDs in the
decompressed blob.

**This is an indicator, never a census.** It sees only entities still in plain
ECS form; the vast majority sit in the segment pool and are invisible to it. In
a world with thousands of boulders such a scan finds on the order of 150.

What makes such a count trustworthy is **selectivity, not the absolute number**:
compare several copies and include control object types that the suspected
mechanism cannot touch. If the counts move only downward and only for the types
under suspicion, while controls such as `AmberBoulder` (ObjectID 5606) and
`CrystalMeteorBoulder` (5879) stay flat across the same copies, the signal is
real even though every number is an undercount.

## The map file

`maps/<character>/<world>.mapparts.gzip` is the friendly one, and it is
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

Its elements come back plain 0–255 — every array starts `137, 80, 78, 71`, the
PNG magic, with 137 stored positive — so `bytes(arr)` works directly. Masking
each element with `& 0xFF` costs nothing and guards against a JSON reader that
hands you signed values, but a decode failure here is not caused by sign: the
field is a plain `byte[]` on `MapPartSerialized`.

### Objects are pixels in their own map colour

Every object whose data has `appearInMapUI: 1` is drawn into the tile in its own
`mapColor` from the prefab. That makes objects findable **pixel-exact by
colour** — and note the map is the *only* place that colour appears: the world
save does not store it.

An object is drawn over the tiles it occupies, so a boulder — 2×2 and square —
comes out as a clean 2×2 cluster, and connected-component clustering per colour
recovers individual boulders.

**Do not turn the cluster shape into a decode check.** The drawing loop
(`UpdateAppearanceInMapUI`) uses the *direction-adjusted* size and corner offset,
not the raw ones: `EntityUtility.GetPrefabSize` returns `prefabTileSize` verbatim
only for an object without a `DirectionCD`, and otherwise routes it through
`DirectionCD.GetPrefabTileSize`, which **transposes** it when
`abs(direction.x) > 0.5`. A square prefab is unaffected — which is why the
boulder example holds — but a 3×1 prefab is drawn 3×1 or 1×3 depending on how it
was placed, so an unexpected cluster shape says nothing about your decode.

### Tile index and in-tile position

Both formulas come from `MapUI`, componentwise:

| Function | Formula |
|---|---|
| `WorldPositionToMapPartIndex(worldPos)` | `floor((worldPos + 0.5) / 256)` |
| `WorldPositionToMapPartPosition(worldPos)` | `((worldPos % 256) + 256) % 256` |

`worldPos.y` in those functions is the world **z**, not height — CK's ground
plane is XZ.

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

A map tile only updates while a player is near it. An object destroyed far away
leaves its pixel behind indefinitely.

So a map pixel records **where something once was, not where it is**. Which cuts
both ways:

- For recovery work this staleness is the feature — the map still shows where
  objects stood before they were removed.
- For counting losses it is disastrous. A diff of two maps undercounts badly:
  in one case it surfaced 2 losses where roughly 19 had occurred.

If you need current state rather than remembered state, read the live ECS world
instead — see [harmony-and-ecs.md](harmony-and-ecs.md).

## Telling save copies apart — GUID, never slot number

`worldinfos/<slot>.worldinfo` is plain JSON, roughly 1.3 KB, no compression:

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
version of it. The pair `guid` + `seed` settles it; `bossesKilled` and
`activatedCrystals` then tell you how far behind a same-GUID copy is.

Getting this wrong loses worlds. Two backups that looked like one
undifferentiated pile of debug leftovers turned out to be a *different* world
(other GUID and seed — i.e. the last copy of it in existence) and a same-GUID
snapshot two bosses behind the live world.

### Which character played which world

`saves/<slot>.json` carries a `servers` list of `serverGuid`s plus a
`serverConnectCount`. Match a `serverGuid` against a `worldinfo` `guid` to see
which worlds a character has been in.

**Trap:** a purely local, never-hosted world also appears in that list.
The entry proves the character played that world — it does **not** prove a
server was involved. (Whether a local session is internally a listen server is
plausible but unproven.)

## Validate against the save, don't infer

Standing rule for anything about world state: **check a real savegame before
asserting it or building a fix on it.** Inference about world layout is
unreliable and the data is usually reachable in minutes.

The failure mode is confident geometry. Asserting that a set of objects "lies
within the base's anchor radius" felt safe and was wrong twice; the actual save
data put them 337–693 tiles out, anchored by remote world structures
(abandoned-camp campfires, a mechanical vault's seed extractor) rather than by
the base at all.

Practical order of attack:

1. **Read whatever is already plain text** — `worldinfo`, `saves/<slot>.json`,
   any mod ledger. No decompression needed.
2. **Read the map file** for positions and clusters, remembering it is a
   snapshot.
3. **Only then** consider the world file, and only for an indicative count.
4. Cross-check a structural hypothesis *before* coding it. "A base is anchored
   by a workbench" was only adopted after confirming in the save that every
   workbench sat at the base and none in any remote cluster.

Decode ObjectIDs you do not recognise from the game's `ObjectID` enum in the
decompile — a single-file bounded grep, see
[reverse-engineering.md](reverse-engineering.md).

### Reading a mod's own ledger

When a mod persists its own scan results, that file is often the fastest ground
truth available — it already holds the mod's *interpretation* of the world, so
it answers "what does the mod actually count, and where?" directly.

Such ledgers are typically plain ASCII under the mod's own
`mods/<ModName>/` directory, in a line format like:

```text
x,z|id:count,id:count,…
```

Parsing one gives you positions, cluster membership and which IDs cluster
together — enough to check distance to the Core, spot that a "base" scan is
really picking up a remote structure, or confirm which objects a rule fires on.
How a mod writes such a file in the first place belongs to
[sandbox-and-config.md](sandbox-and-config.md).
