# Map Markers Enhanced — Design

- **Date:** 2026-09-28
- **Mod:** `map-markers-enhanced` (new), `MapMarkersEnhanced`, "Map Markers
  Enhanced"
- **Origin:** a fork of moorowl's MapMarkers+ (MIT), which no longer compiles
  on Core Keeper 1.3
- **Status:** design, nothing built; a throwaway probe mod verified the core
  mechanism in game

Terms, used strictly below: an **icon** is one `MapMarkerIconDataBlock` — one
tile in the dialog's upper row; a **variant** is one entry of an icon's sprite
list — one tile in the lower row; a **marker** is a placed map-marker entity.

## Problem

MapMarkers+ offers 57 markers in four shipped categories, 53 of them its own
art and four standing in for vanilla markers, plus 26 letters it drew but never
shipped. On 1.3 it fails to load with `CompileFailed`: every error traces back
to two types the update removed, `UserMapMarkerType` (a fixed enum of four
marker slots) and `UserMapMarkerToggle`.

This is not a rename. 1.3 replaced the whole user-marker system. Icons are now
`MapMarkerIconDataBlock`s, each with a list of sprite variants (large map,
minimap, colour icon); a marker stores `{iconAddress, variantIndex}` plus an
optional name; the player picks from a dialog with an icon row and a variant
row, and keeps five presets in the client prefs. MapMarkers+ had built its own
drawer UI and its own client/server command pair to do what vanilla now does
natively.

Its users have a second problem they may not have noticed. The mod stored every
marker with its own art as the vanilla slot `Marker2` and kept the real type in
the entity's otherwise unused `Amount` field (`6000 + PlusMarkerType`). The 1.3
world migration (version 13) converts old markers by their vanilla slot, so all
of them became the same yellow question mark. Measured on one real world: 62
markers, all "?", all still carrying their original `Amount`.

## Acceptance criteria

| # | Criterion |
|---|---|
| AC1 | The mod compiles and loads on 1.3 with no errors of its own in `Player.log`. |
| AC2 | With no other marker-icon mod installed, the marker dialog lists the eight vanilla icons first, then General, Ores and Gems, Flags, Numbers and Letters, in that order. |
| AC3 | Every marker from MapMarkers+'s categories General, OresAndGems, Flags and Numbers is selectable as a variant, plus the letters A–Z. The Ping category is dropped: 1.3 has its own ping. |
| AC4 | A placed marker shows its icon on the large map and on the minimap, and still does after a restart. |
| AC5 | Wherever the mod runs as or on the server — single-player, hosting, or a dedicated server with the mod — the question marks the version-13 migration made of MapMarkers+ markers are restored to their original icons, exactly once per marker, and the result is saved. A marker the player has restyled since is left alone; a name the player gave it is kept. |
| AC6 | `requiredOn` is `1`. A player with the mod can join a server without it, and a marker placed there still shows its icon after a server restart. |
| AC7 | Every mapping the mod relies on — sprite per variant, address per icon, variant per legacy type — comes from one hand-kept table, is generated into both the assets and the runtime code, and is covered by tests. |

## Decisions

**Data-native rather than a straight port.** The mod ships
`MapMarkerIconDataBlock` assets and nothing else of the old architecture: the
drawer UI, its 214 KB prefab, the networking systems, `PlusMarkerManager` and
the category `TextDataBlock`s go. Vanilla then provides picking, naming,
presets, minimap display, networking and saving. A faithful port of the drawer
onto the new UI types was the alternative; it is the largest option and would
be exactly as fragile at the next UI rework. A hybrid with a slim own picker was
kept in reserve in case the vanilla rows could not carry the volume — the probe
showed they can.

**One icon per category, one variant per marker.** The dialog has two levels,
and the categories map onto them without friction: selecting a variant also
swaps the icon tile to that variant's sprite. The variant row scrolls; the
probe showed 26 entries working.

| Icon | Variants | Minimap sprite |
|---|---|---|
| General | 22 | `_small` slice; Skull uses `markers_skull_small` |
| Ores and Gems | 11 | `_small` slice; Ancient Crystal uses `markers_ancient_crystal_small` |
| Flags | 14 | `_small` slice |
| Numbers | 10 | the large sprite — no small slice exists |
| Letters | 26 | the large sprite — no small slice exists |

Variant order follows `PlusMarkerCategory.cs`. The four markers MapMarkers+
backed with vanilla art — Question Mark and Skull in General, Ancient Crystal in
Ores and Gems, Green Flag in Flags — are ordinary variants here, drawn from the
sheet like every other. The first variant is what the icon tile shows. Letters
were drawn but commented out upstream, most likely because the old drawer could
not hold them; they are included.

**Assets with pinned addresses, not runtime blocks.** A marker stores the
icon's address. `API.DataBlocks.CreateRuntimeInstance<T>(modId)` mints a new
random address on every launch, so every marker would be orphaned by the next
restart — the probe demonstrated exactly that. The overload taking an address
does produce a stable one, hashed from the mod GUID and the given address, but it
also marks the block as overloading that given address, which names no existing
block; what the loader makes of such a block is untested. Assets avoid the
question: they carry their address in `m_address`, as MapMarkers+'s own
`TextDataBlock`s did.

**One table, generated twice.** A hand-kept table in the mod repository lists
every icon with its pinned address and every variant with its sprite names and,
where one exists, the legacy `PlusMarkerType` it restores. A script generates
two things from it: the five asset files, resolving each sprite through its
`internalID` in `markers.png.meta`, and a C# source file holding the legacy
mapping the restoration system reads. A missing sprite aborts generation.
MapMarkers+ resolved sprites by naming convention at runtime and fell back to a
placeholder silently; Skull and Ancient Crystal, whose small slices are spelled
differently, show how easily that hides a gap.

**Mod icons are moved behind vanilla's.** In the probe run the log shows
`ScriptableData` gathering every mod loader before the `addressables` loader,
and the dialog showed the probe's icons in front of vanilla's. The decompile
does not explain that order — the addressables loader registers itself at
startup, which suggests the opposite — so the design does not rely on it either
way. `TryGetDataBlocks<MapMarkerIconDataBlock>` hands out the live
`List<MapMarkerIconDataBlock>`, and `MapMarkerCustomizationPanel.PopulateIconRow`
is its only reader. A Harmony prefix on that method moves the mod's blocks to
the end, stably, before the row is built: a type cast, no reflection, no copy of
vanilla code. The address-to-index lookup indexes a different list and is
unaffected. Among the mod's own blocks, order is the address order, because each
loader sorts its blocks by address — so the pins are assigned ascending in the
wanted order. After moving, the prefix fetches the list again and checks that the
mod's blocks are last; if they are not — a later game version handing out a
copy, say — it logs a warning once.

**Legacy restoration runs on the server.** An ECS system in the server world
acts on markers that meet all three conditions: object id `MapMarker`; an
`Amount` of `6000 + t` for a type `t` the legacy mapping knows; and custom data
still equal to the migration's question mark (icon
`7e09f30c-8838-5604-2b46-8c13b0ef771e`, variant 9). It sets
`MapMarkerCustomDataCD` to the mapped icon and variant and sets `Amount` to `1`,
the value vanilla gives a marker. Clearing `Amount` is what makes the pass run
exactly once per marker: a player who later sets a restored marker back to the
question mark keeps it, and a second mod with the same idea finds nothing to act
on. A marker the player restyled is skipped by the third condition; a name is
not part of any condition, so a renamed question mark is restored and keeps its
name. Vanilla does the rest: the serializer persists the change and ghost
serialization sends it to every client. That the serializer also persists a
changed `Amount` on an existing entity is inferred, not yet observed — the first
in-game check below settles it. The system keeps running, at the cost of one
empty query once everything is restored, so it neither depends on running after
the vanilla migration nor on every marker entity existing at load.

The four vanilla-backed markers need nothing. MapMarkers+ let vanilla create
them, so they carry vanilla's `Amount` of 1 and a vanilla slot, the migration
gave them matching vanilla icons, and nothing distinguishes them from markers
placed without the mod.

**`requiredOn: 1`, not the original's `3`.** The original needed `3` because it
had its own network commands. This design uses vanilla's `MapMarkerRpc`, whose
server handler stores the address without checking it (`Pug.Other:413849`), so
the server does not need the mod for markers to work. Every client does: a
client without it cannot resolve the icon, shows no correct sprite for the
marker, and logs an error on every redraw. The `Client` flag makes a server that
has the mod demand it from every client — and only such a server, because the
check is built from the server's own loaded mods (`Pug.Other:130388`).
Restoration happens wherever the mod runs as or on the server, as AC5 states.

**Own identity.** Name, manifest GUID and every block address are new. The mod
can be installed alongside MapMarkers+ without either shadowing the other. The
repository is moorowl's history moved into `unity/MapMarkersEnhanced/` with
`git filter-repo --to-subdirectory-filter`, so moorowl's commits keep their
authorship; the MIT licence and copyright notice stay. The shared build scripts
also need what upstream never had — the ModBuilderSettings asset
`unity/MapMarkersEnhanced.asset` and the two Assets-level `.meta` files beside it
— which come from the usual scaffold. Whether to open an issue or a pull request
upstream is deferred.

## Consequences

- **Uninstalling breaks markers.** A restored or newly placed marker refers to
  one of the mod's icons; without the mod it resolves to nothing, shows no
  correct sprite, and floods the log. Before restoration the old markers were at
  least visible question marks, and because restoration clears `Amount`, the
  original type cannot be recovered afterwards. The README says so.
- **Servers without the mod.** A player with the mod can place markers there
  that other players, who lack it, cannot see. The server cannot prevent this,
  because it does not know the mod. Restoration does not run there.
- **The reorder depends on an implementation detail.** If a later game version
  returns a copy from `TryGetDataBlocks`, the icons move back to the front of
  the row. Nothing else breaks, and the prefix's check logs it.

## Verification

Automated, under the mod repository's test suite:

- every variant in the table resolves to a large sprite in `markers.png.meta`;
- minimap sprites use the `_small` slice where one exists, including the two
  spelled differently, and the large sprite exactly where none does;
- every marker of the four shipped MapMarkers+ categories is a variant, the
  four vanilla-backed ones included;
- icon addresses are unique, pinned, and ascending in the wanted order;
- every `PlusMarkerType` value is either in the legacy mapping or on its
  explicit exclusion list — the four vanilla-backed types, Ping and None, none
  of which ever carried a `6000 + t` amount;
- the generated C# legacy mapping agrees with the table;
- regenerating assets and C# reproduces them byte for byte.

In game, recorded in the mod's `docs/manual-tests.md`:

1. `Player.log` after launch: the mod compiles, and no error line names it or
   one of its icons (AC1).
2. The dialog order of AC2.
3. One marker per icon, checked on the large map and the minimap.
4. A restart, after which every placed marker still shows its icon (AC4).
5. Restoration on a **copy** of a world that carries MapMarkers+ markers, never
   on the live one: question marks become their icons; a question mark renamed
   beforehand becomes its icon and keeps the name; a restyled one stays; after a
   restart the result holds, and a scan of the saved copy shows the restored
   markers at `Amount` 1. Then set one restored marker back to the question mark
   and restart: it stays a question mark (AC5).
6. The local dedicated server without the mod: a client with the mod places a
   marker, the server restarts, the marker still shows its icon (AC6).

MapMarkers+ stays disabled in the client during all of this — not for a name
clash, which the own identity removes, but so its load failure does not
accompany every launch.

## Handbook

Findings from this design that belong in `docs/ck/`, independent of this mod:

- `savegame-formats.md`: the marker table describes pre-1.3 saves. Migration
  version 13 sets `Variation` to 0 for slots 0–3 and moves the icon into
  `MapMarkerCustomDataSerializedCD`; `Amount` is kept. Its row "0 alongside a
  fixed variation" does not hold for MapMarkers+: the markers it backed with
  vanilla slots were created by vanilla and carry `Amount` 1.
- `database-and-baking.md`: blocks are sorted by address within each loader.
  In one measured run mod blocks preceded vanilla blocks in the typed lists,
  which the decompile does not explain — record it as observed, not as a rule.
  A runtime block created without an address gets a new one on every launch and
  cannot be referenced persistently.
- When a mod bundle ships its `.manifest`, `LoadedMod.Assets` holds only each
  listed asset's main object — a sliced texture contributes its `Texture2D`, not
  its sprites; they are reachable through the bundle.

## Open

**More than five presets.** Asked for, deferred until the port stands. What is
known: five is a literal in six places — the preset bar's construction,
`EnsurePresetsInitialized`, and four range checks in `MapUI` — while the prefs
list grows on demand. A transpiler would need `OpCodes` from
`System.Reflection.Emit`, which the sandbox denies; whether Harmony helpers
outside the deny list avoid naming it is untested. The fallback is prefixes that
reimplement those methods. Slots beyond five would also have to be pre-filled,
because the bar hides a slot without an icon. How many slots the bar can show
has not been looked at.
