# Player Coordinates HUD — Design

- **Date:** 2026-08-05
- **Mod:** `player-coordinates-hud` (new repo)
- **Status:** design settled, pending implementation

## Problem

Core Keeper shows world coordinates in exactly one place: the map view
(Tab). Two limitations make that impractical for knowing where you are:

1. The numbers track the **mouse cursor**, not the player. The player's
   own position is only a green dot with no readout.
2. It requires opening the map, which interrupts what you were doing.

So reading your own position means: open the map, move the cursor onto
your own marker, read, close. A permanent readout in the HUD removes all
four steps.

## Decisions

| Question | Decision |
|---|---|
| Content / format | `123, -456 (478)` — plain numbers, **one line** |
| Anchor | bottom-left of the HUD |
| Widget origin | **own prefab, copied from CK's `CoordinatesUI` subtree** and edited in the Editor |
| Distance term | keep it (the `(478)`) |
| Settings | one `Enabled` toggle via Mod Settings Menu |
| Deferred | rebindable show/hide hotkey; corner as a setting |

### Format

CK's own format is the template, so the two surfaces never disagree:

```csharp
// Pug.Other, CoordinatesUI.LateUpdate (decompiled)
int2 x = (int2)math.floor(mapUI.GetCursorWorldPosition());
string text = x.x.ToString("F0") + ", " + x.y.ToString("F0");
string text2 = "(" + math.length(x.ToFloat2()).ToString("F0") + ")";
```

Three properties are inherited deliberately:

- **`, ` as separator** (not ` / `) — identical to the map.
- **`math.floor`, never `round`.** Rounding would disagree with the map
  readout by 1 on half a tile — a discrepancy only visible when
  comparing both surfaces, i.e. exactly the kind of bug that ships.
- **The distance is the straight line to the world origin** (The Core at
  `0,0`), computed from the **already floored integers**, not from the
  exact float position. Verified against an in-game screenshot rather
  than assumed: position `63, -14` renders `(65)`, and
  `sqrt(63² + 14²) = 64.5 → 65`.

**What "the player's position" means here:** the exact
`PlayerController.WorldPosition`, floored. Note that this is *not* the
same quantity the map's own numbers describe — those come from
`ScreenToWorldPosition(cursor)`, while the player's map marker is
separately snapped via `RoundToMultiple(0.0625f)`. Near a tile boundary
the two can therefore differ by one. What is inherited from CK is the
**format and the rounding rule**, not pixel-identical agreement with a
cursor the player has to aim by hand.

The one deviation from CK: the map renders **two lines** (coordinates,
then the distance below, `0.5625` apart). This mod renders **one**:

```
123, -456 (478)
```

so the `distance` / `distanceOutline` objects are **deleted from the
prefab** and the full string goes into the coordinate pair. Rendering both
values into one text also avoids the alternative — repositioning the
distance objects beside the coordinates — which cannot work: the X offset
would have to match the rendered width of the coordinate string, and that
changes with every digit (`5, 3` vs `-1234, -5678`), so it would need
per-frame text measurement.

## Where the prefab comes from

The widget is **not** a standalone asset. It is a five-GameObject subtree
inside CK's global manager prefab, located in the AssetRipper extraction
at `CoreKeeperDecompile/Resources/Assets/Resources/`:

```
Global Objects (Main Manager).prefab   — 6.5 MB, 2626 GameObjects
└── … mapMarkerToggle, RemoveMapMarkersButton …
    └── CoordinatesUI                  (line 7813)  pos 11.75, 5.75
        ├── coorindates                ← Pugstorm's own typo
        ├── coorindatesOutline
        ├── distance
        └── distanceOutline
```

That subtree is copied into `unity/PlayerCoordinatesHud/Prefabs/` once and
then edited freely in the Unity Editor. **It contains no Pugstorm assets**
— verified by resolving every external reference in it:

```
5 GameObjects, 5 Transforms, 5 MonoBehaviours (1× CoordinatesUI, 4× PugText)
External references: only the two script refs into Pug.Other.dll
  fileID -981571279  guid 548e3dd2…   CoordinatesUI
  fileID 1873953792  guid 548e3dd2…   PugText
```

No sprite, texture, font or material. `PugText` builds its glyphs at
runtime from `Manager.text`; the prefab holds only a `fontFace` enum
value. So what is copied is structure plus numbers, and the structure
("one root, four text nodes") is the minimum shape for "text with a drop
shadow", not a creative asset.

**Script GUID remap is required.** The `fileID`s above are portable
class-name hashes, but `guid 548e3dd2…` is the `Pug.Other.dll` GUID *of
the extraction environment*. It must be remapped to this SDK clone's GUID
via `utils/prefab_query.py` / `utils/ck-script-ids.json` — see the
`project_corekeeper_script_fileid_derivation` memory. After the remap,
open the prefab once in the Editor so Unity normalises the serialisation
before any further editing.

### Why a prefab and not a runtime clone

A runtime `Object.Instantiate` of the live widget was considered first and
rejected. It would have required, **on every game start**: finding the
source in the Vanilla hierarchy, instantiating it, disabling the inherited
`CoordinatesUI` component (its own `LateUpdate` would keep writing the
*cursor* position into the same texts), setting the layer recursively,
setting z, `Clear()`-ing and destroying two GameObjects, flipping the
alignment, and positioning. A prefab has all of that baked in.

Decisive on top of that: **calibration cost.** Anchor, alpha, sorting
order and alignment are values that need a few rounds of trial. In the
Editor that is seconds each; in code every round is a build plus a game
launch. This project has repeatedly lost time to exactly that loop.

The one argument that had favoured cloning — not shipping any Vanilla
content — does not hold, because the subtree contains no assets (above).

### Values read from the original

These come from the extracted prefab, so none of them has to be guessed —
which removes the failure mode that made a hand-authored prefab risky in
the first place (ItemChecklist Iter-1: an Editor-default `fontFace` that
is absent from the runtime bundle renders invisible text).

| Field | `coorindates` | `coorindatesOutline` |
|---|---|---|
| `fontFace` | `16777344` (thinTiny) | `16777344` |
| `color` | white, **α 0.447** | black, α 1.0 |
| `orderInLayer` | 30 | 29 (behind) |
| `localPosition` | `0, -0.1875` | `0.0625, -0.25` |
| `horizontalAlignment` | `2` (right) | `2` (right) |
| ↳ *source lines in the extracted prefab* | 86271 | 86343 |
| `verticalAlignment` | `1` (center) | `1` |
| `maxWidth` | `0` | `0` |
| `renderOnStart` / `keepEnabledOnStart` | `0` / `0` | `0` / `0` |
| `sortingLayer` | `1241602095` | `1241602095` |
| `outline` / `outlineColor` | `0` / α 0 | `0` / α 0 |

Four of these are load-bearing:

- **It is a drop shadow, not an outline.** `outline` is `0`, so PugText's
  built-in outline is unused. The effect comes from a second black text
  offset by `0.0625` (= exactly 1 px at PPU 16) down-right and drawn
  *behind* (order 29 vs 30).
- **`fontFace` thinTiny is the correct choice here, not a hazard.** It is
  CK's digits-only face and lacks umlauts (ItemChecklist Iter-25 had to
  inject 85 accented glyphs for prose labels). This readout is digits,
  a comma, a minus and parentheses — all present.
- **`maxWidth: 0` must stay 0.** A non-zero value routes every render
  through CK's buggy word-wrap (`PugFont.AddNewLinesToLinesExceedingMaxWidth`
  → per-frame `IndexOutOfRangeException`, ItemChecklist Iter-19).
- **`renderOnStart: 0` / `keepEnabledOnStart: 0` are correct** because
  this mod calls `Render()` itself. The usual advice to set both to `1`
  applies to texts that must paint themselves.

### Editor changes to make on the copy

1. Delete the `CoordinatesUI` component from the root (its `LateUpdate`
   renders the cursor position) and add `CoordinatesHud` instead.
2. Delete the `distance` and `distanceOutline` GameObjects.
2b. **Insert a `hudRoot` child** between the root and the two remaining
   texts, and wire it to `CoordinatesHud.hudRoot`. Required, not
   cosmetic — see § Visibility for why toggling the component's own
   GameObject would make the display unrecoverable.
3. Set the layer of all remaining objects to **27 (HUD)** and the root's
   `localPosition.z` to **10**. Layer 5 is only drawn by the uiCamera for
   modal UI; at the parent origin (world z = -10) the renderers fall
   outside the uiCamera frustum. Both facts are from ItemChecklist
   Iter-11.5.
4. Root `localPosition` from `11.75, 5.75` to the bottom-left anchor.
5. `horizontalAlignment` from `2` (right) to `0` (left) on both texts —
   in a left corner, right-aligned text would grow leftwards on a sign
   change.
6. Raise the main text's alpha from `0.447`. The map value is deliberately
   unobtrusive for a panel that is only open briefly; a permanent readout
   likely wants more. Exact value by eye.

## Architecture

Four runtime classes in namespace `PlayerCoordinatesHud`:

| Class | Responsibility |
|---|---|
| `PlayerCoordinatesHudMod : IMod` | Bootstrap. Registers the Mod Settings section in `Init`; captures the prefab in `ModObjectLoaded`; instantiates it under the HUD root and drives the per-frame update from `Update`. |
| `ModConfig` | Settings adapter (root-namespace `ModConfig`, per family convention). One `Enabled` toggle, default on. |
| `CoordinatesHud : UIelement` | Sits on the **always-active** prefab root. Holds the two PugText references and the `hudRoot` child (Editor-wired). Toggles `hudRoot` in `LateUpdate`; renders on request. |
| `WorldState` | The shared playable-world predicate, copied from ItemChecklist. |

### Mounting

`ModObjectLoaded` captures the prefab **by GameObject name** and
`Update` instantiates it lazily under
`Manager.ui.chestInventoryUI.transform.parent` (the in-game HUD root)
once the UIManager hierarchy exists — the pattern both sibling HUDs use.

It must **not** go through `UserInterfaceModule.RegisterModUI`: that path
is for modal UIs and hides them on `HideAllInventoryAndCraftingUI`, which
is the opposite of always-on.

### Per frame

- Read the player position **defensively**: `Manager.main?.player`, and
  return without rendering when it is null. The visibility gate lives in
  `LateUpdate` on a different object, so it cannot protect this read —
  `Update` runs during load and on the main menu, where the player does
  not exist. The divining-rod sibling guards exactly this way.
- `floor` the X/Z pair to `int2`. CK's world is the **XZ plane** — `.y`
  is height (≈0) and is not a map axis. `math.floor` rather than an
  `(int)` cast: the two differ for negative coordinates, which are
  ordinary in CK worlds (`-14.3` floors to `-15`, casts to `-14`).
- Build the string and **render only when it changed**. `PugText.Render()`
  rebuilds the glyph SpriteRenderers, and unlike the Vanilla original
  (which only runs while the map is open) this HUD is permanent. This is
  the ItemChecklist Iter-37 lesson applied up front.
- Both texts get the same string (main + shadow).

### Visibility

**Topology first — this is load-bearing, not cosmetic.** The component
that decides visibility must live on an object that is **never**
deactivated, otherwise its own `LateUpdate` stops running and it can
never turn the display back on: hide once (open the inventory, toggle the
setting off) and it is gone for the rest of the session. So the prefab
gets an intermediate child:

```
CoordinatesUI            ← always active, carries CoordinatesHud
└── hudRoot              ← the object actually toggled
    ├── coorindates
    └── coorindatesOutline
```

This is exactly why `ItemChecklistHud` has a serialized `hudRoot` field
rather than toggling its own GameObject. The copied subtree has no such
intermediate node — it must be inserted in the Editor.

One gate, in `CoordinatesHud.LateUpdate`, matching the sibling HUDs:

```
WorldState.IsInPlayableWorld
  && !Manager.ui.isAnyInventoryShowing
  && !Manager.menu.IsAnyMenuActive()
  && ModConfig.Enabled
```

`WorldState.IsInPlayableWorld` (`isInGame && isSceneHandlerReady &&
!Manager.load.IsLoading() && !cutsceneIsPlaying`) is used rather than
`Manager.main.player != null`: the player object exists at `OnOccupied`
while the load screen is still up and survives the exit transition, so a
player-null check lets a HUD flash over both load screens — the
ItemChecklist Iter-11.6/15 bug class.

`Manager.ui.CalcGameplayUITargetScaleMultiplier()` — CK's own HUD idiom
— returns `(0,0,0)` for a mod HUD and is deliberately not used.

## Not in this iteration

Both were explicitly deferred by the user, not dropped:

- **Rebindable show/hide hotkey** — would add CoreLib's
  `ControlMappingModule` plus loc terms for its own control category.
- **Corner as a setting** — four anchor positions each need in-game
  calibration; bottom-left is verified free (health/mana and buffs sit
  *top* left, the hotbar bottom-centre, the key hints bottom-right).

To keep both cheap to add later, two seams stay single-sited: the
visibility decision lives in exactly one place, and the anchor is one
prefab value. Nothing is pre-built for them.

## Open unknowns

None of these can invalidate the design — the runtime-resolve risk
disappeared with the runtime clone.

1. **Do the glyph SpriteRenderers inherit layer 27?** `PugText.Render()`
   creates them at runtime. If they do not inherit, the layer must be
   re-applied after each render. (ItemChecklist's Iter-11.5 counter works
   this way, so inheritance is likely, but it was never isolated as a
   fact.)
2. **Anchor, alpha and sorting order** — Editor calibration, cheap by
   construction now.
3. **Does the copied prefab survive the ModBuilder round-trip?** Nested
   prefabs and variants do (ItemChecklist Iter-13), and this is a flat
   5-object prefab, so the risk is low — but the remapped script GUIDs
   are worth verifying in the built bundle.

Resolved already, from data rather than by probing: the format and all
style values (above), that the subtree ships no assets, and that
`PugTextStyle.HorizontalAlignment { left, center, right }` is a real
serialized field rather than a transform trick.

## Division of work

Per this project's standing rule (`feedback_corekeeper_prefab_edits_in_editor`):
**new objects and structural prefab work happen in the Editor**, because a
batchmode build reserializes and can drop hand-authored objects or null
references. So:

- **User (Editor):** the changes listed above on the copied prefab —
  including the `hudRoot` insertion, which is structural.
- **Assistant:** the scaffold, all C#, localization YAML, README /
  mod.io description, builds, `Player.log` verification, docs.
- **Named exception — the initial copy + GUID remap is done by the
  assistant** as a file operation, even though it touches a prefab. The
  Editor-only rule exists because a batchmode build reserializes
  hand-authored YAML and can drop objects or null references; here
  nothing is *authored*, an existing subtree is transplanted and its two
  script GUIDs rewritten with `utils/prefab_query.py`. The prefab is then
  **opened once in the Editor and saved** before any structural edit, so
  Unity normalises the serialisation and everything after that point is
  ordinary Editor work.

While the Editor is open, the assistant makes **no** file writes in the
mod or SDK tree (concurrent writes collide with the Editor's own
serialisation).

## Verification

No offline test is possible (the constraint on every mod here): the
Roslyn sandbox, Harmony and the UI only exist in the running game. So:

1. `utils/build.sh`, then grep `Player.log` for `error CS`,
   `CompileFailed` and `safetyCheck=True`. An Editor build that compiles
   can still fail the runtime sandbox. Also confirm the prefab is listed
   in the generated `ModManifest.json` and the AssetBundle manifest.
2. In-game:
   - Readout present bottom-left, readable over light **and** dark ground
     (the drop-shadow check).
   - **Recovery after hiding** — open and close the inventory, toggle
     `Enabled` off and on: the readout must come back every time. This is
     the test for the `hudRoot` topology; getting it wrong hides the HUD
     permanently after the first time, which looks like a random bug.
   - Hidden on both load screens, during the intro cutscene, with
     inventory/crafting open and in any menu.
   - **Negative coordinates** — walk west/north of the Core and compare
     against the map. Expect agreement within one tile, not exact
     equality (see § Format: the map's cursor and the player marker use
     different quantizations). A systematic offset of exactly 1 on
     negatives would indicate a cast where a `floor` belongs.
   - The `Enabled` toggle applies live, without a restart, and its label
     renders localized rather than as a raw term key.

## Identity

- Repo `player-coordinates-hud`, internal name + namespace
  `PlayerCoordinatesHud`, DisplayName "Player Coordinates HUD".
  (`Hud` in Pascal, matching this project's own `ItemChecklistHud`
  class; only prefab filenames use `HUD`.)
- Scaffolded with `utils/new_mod.py player-coordinates-hud --corelib`.
- Fake mod.io dev ID **9999990** — verified free against the actual
  `FAKE_MOD_ID` values in the nine sibling `.envrc` files (9999991 …
  9999999 are taken).
- Dependencies: `ModSettingsMenu` + `CoreLib`, both `required: 1` in the
  ModBuilderSettings `.asset`.

## Deliverables beyond the scaffold

`utils/new_mod.py` produces the ModBuilderSettings `.asset`, both
`.asmdef`s, every `.meta`, `_modio.asset`, the `IMod` bootstrap, `.envrc`,
`.gitignore`, `CHANGELOG.md` and a **placeholder** logo. It does not
produce the following, all of which the sibling mods ship and this mod
therefore needs:

- **`localization/localization.yaml`** — required, not optional: without
  it the settings row renders its raw term key instead of a label. Needs
  a `PlayerCoordinatesHud-Config` section with `_hint` and `enabled`
  (EN + DE at minimum), matching the convention in ItemChecklist's and
  the divining rod's YAML. Leaf keys stay **unquoted** — the loc
  generator is a hand-rolled line parser that does not unquote keys, so
  `"enabled":` would bake a term with the quotes in it and silently fall
  back (ItemChecklist Iter-38).
- **`README.md`** and **`modio-description.md`** — the public-facing
  pair. Per `feedback_corekeeper_shipped_docs_build_env_free`, both must
  be free of build-environment detail (no `utils/`, no `.envrc`, no
  Wine/CrossOver, no fake IDs).
- **A real logo** at `unity/PlayerCoordinatesHud/Editor/logo.png`,
  replacing the placeholder, in the family style (teal/petrol hero object,
  gold accents, golden radial glow, 4-point sparkles, 1024², transparent).
  Its per-mod "gesture" still needs inventing — something coordinate-ish
  (a gold crosshair or grid marker) rather than a reused sibling motif.
- **`CLAUDE.md`** for the new repo.
