# Prefabs, sprites and text rendering

This chapter covers the asset side of a Core Keeper mod: when a prefab may be edited
by script and when it must be touched in the Unity Editor, how sprites have to be
imported so they survive the AssetBundle bake, and the rendering traps — on-grid
distortion, Z-sorting ties, self-deactivating text, the font atlas system — that make
a structurally correct prefab render wrong. It closes with the one geometric fact
that surprises every HUD author: the world and the HUD are different coordinate
spaces. Menu widgets, options entries, keybinds and scrolling belong to the
[UI framework](ui-framework.md); pixel-art authoring tooling is covered by
[the Pixaki format notes](../pixaki-format.md).

## Editing a prefab: script or Editor

The dividing line is **complexity, not convenience**.

| Kind of change | Where |
|---|---|
| A field value on an object the Editor already wrote — a `z`/position, a colour, `m_IsActive`, one serialized field | Script (Python/`Edit` on the YAML) is fine |
| A new GameObject or component, a new hierarchy level, wiring a serialized reference to a hand-made object, sprite/material/sorting setup | Unity Editor, always |

**Why:** hand-authored *new* prefab YAML does not survive Unity's reserialisation.
A `SpriteRenderer` plus its `LinearLayoutUIComponent.background` wiring, both appended
to the YAML by script with the Editor closed, were **silently dropped** by the next
`-batchmode` build — Unity reserialised the prefab to canonical form, the new object
was gone and `background` was back to `{fileID: 0}`. No error, no warning. Plain field
values on objects the Editor has already validated come through unharmed; genuinely
new structure does not. Note that the **build** reserialises too, not only an
interactive Editor session, so "I never opened the Editor" is not a safe harbour.

The practical consequence when you work with an assistant or a script: structural work
gets *described* precisely and then done in the Editor by hand; the script side stays
on code plus read-only prefab inspection.

### Put the value in the prefab, not in runtime code

If a value or a structure *can* live in the prefab, it belongs there. A box's sorting
layer, its material, a fixed width, a Z offset — set once in the prefab, consistent
everywhere. Reach for runtime `AddComponent` or per-frame field assignment only for
data that is genuinely dynamic per instance. Copying static properties onto a
`SpriteRenderer` on every `Populate()` is a shortcut around a prefab edit, and it hides
the real layout in code where nobody looks for it.

### LinearLayout backgrounds must be a separate child

CK's `LinearLayoutUIComponent.background` must point at a `SpriteRenderer` on a
**child** GameObject — never at a component on the layout GameObject itself.
`UpdateBackground` offsets `background.transform.localPosition` to `-height/2`; if the
background sits on the layout's own transform, that offset moves the entire layout.

## Nested prefabs and variants

Nested `PrefabInstance`s and prefab **variants** round-trip cleanly through the
Pugstorm `ModBuilder` → AssetBundle pipeline. A prefab that nests variant instances of
a shared chrome prefab loads, renders and responds to clicks in game. You are not
restricted to the older separate-prefab-plus-runtime-instantiation pattern (a
serialized `GameObject` field cloned at runtime).

**Author the nesting in the Editor.** A containing prefab references objects inside a
nested instance through **stripped object stubs** — `--- !u!N &id stripped` with
`m_CorrespondingSourceObject` / `m_PrefabInstance` — whose fileIDs Unity computes on
import. That is precisely what hand-authored YAML gets wrong.

### What a variant can and cannot do

A variant may **add** components and children, and **override** or **deactivate**
inherited ones. It **cannot remove** an inherited component. Design accordingly: the
base chrome must *omit* anything consumer-specific, and each consumer adds its own root
widget component.

**Trap: deleting a deactivated inherited object later strands its override.** If a
variant overrode `m_IsActive: 0` on a base object and that base object is subsequently
deleted, the variant keeps a target-less `m_Modification` that Unity never prunes —
reimport and Force-Reserialize do not help, and the Editor cannot surface it either,
because the Overrides dropdown only lists resolvable targets, so there is no Revert
path. The repair is to strip the entry straight from the variant YAML **with the Editor
closed** (concurrent writes collide with it), then validate by re-parsing the file with
a real YAML parser and running a build. The whole class is avoided by making the base a
pure skeleton and each consumer a clean variant of it.

### Serialized cross-prefab references break on extraction

**Trap:** a serialized reference pointing from a shared chrome component to a
consumer-specific component **nulls out** when the chrome is extracted into its own
prefab — the target has moved into an instance-added component. Wire such references
**at runtime** instead, e.g. in a `Configure` method via `GetComponentsInChildren<T>`.
The Editor's compile pass does not catch this; only running the game does.

To let one shared chrome component drive several different consumer widgets, introduce
a small **interface seam** (`IPopupToggle`-style), type the chrome's reference to the
interface and wire it at runtime. That is usually what lets near-duplicate per-consumer
classes collapse into one.

### Verify every wire, and do not trust names

**Verify each serialized widget reference against the expected component GUID after
every prefab save** — by tooling, not by eye. A missing wire (a `rowTemplate` left at
`fileID 0`, so the pool builder early-returns and the popup comes up empty) survives a
clean Editor compile *and* a successful build. Trust the field → fileID mapping over
the GameObject's *name*: an object literally named `RowTemplate` turned out to be a
different widget's `checkboxTemplate`, and deleting it by name would have broken that
widget.

Variant YAML also defeats `grep`/`awk` — stripped objects, modification blocks and
added objects do not read linearly. Use a real YAML parser for inspection.

### Side effect: a component-less prefab leaves ModObjectLoaded

Reducing a prefab to component-less chrome drops it from the mod's set of top-level
loaded objects — it becomes a nested dependency only — so it never reaches
`IMod.ModObjectLoaded` (see [mod anatomy](mod-anatomy.md)). Route `ModObjectLoaded` by
an explicit **name whitelist** of the objects you actually care about, rather than an
else-register-everything branch that silently stops firing.

## Sprite import: a PNG is not automatically a Sprite

`ModBuilder` calls `ContentPipeline.BuildAssetBundles(...)` with every asset path under
the mod path (excluding the Editor folder and `.cs`/`.dll`/`.asmdef`). The sprite
importer pipeline runs fully during the bundle bake — **but only for PNGs whose `.meta`
carries sprite settings.**

**Symptom:** `AssetBundle.LoadAsset<Sprite>(canonicalPath)` returns `null` although the
path is listed in `GetAllAssetNames()`. The bundle holds a `Texture2D` at that path, not
a `Sprite`.

**Fix — required in every PNG `.meta`:**

| Field | Value | Meaning |
|---|---|---|
| `textureType` | `8` | Sprite (2D and UI) — **not** `0` (default texture) |
| `spriteMode` | `1` | Single — **not** `2` (multiple, sub-sprite strip) |

Recommended alongside, matching CK's pixel-art convention:

| Field | Value | Meaning |
|---|---|---|
| `spritePixelsToUnits` | `16` | one 16×16 base tile = 1 world unit |
| `filterMode` | `0` | Point — no anti-aliasing smear |
| `spriteBorder` | `{x: L, y: B, z: R, w: T}` | 9-slice borders; the xyzw order is **left, bottom, right, top**, not XYZW |

**Why the defaults are wrong:** Unity's first import of a PNG in a folder writes
`textureType: 0` / `spriteMode: 2`. In the Editor everything still *looks* right — the
Inspector happily previews a default texture as a sprite — so the bug is invisible
until the mod runs. The bundle only contains what the sprite importer actually
produced, which for `textureType: 0` is nothing.

**Diagnostic loop:** in your mod bootstrap, log `AssetBundle.GetAllAssetNames()` and
check every `LoadAsset` result for `null` with a warning. Without that, a path mismatch
and a missing importer setting look identical from the outside.

**Alternative that sidesteps the trap entirely:** instead of `LoadAsset<Sprite>`, load a
**prefab** (`LoadAsset<GameObject>`) whose components already reference the sprites,
wired in the Editor. The bundle baker then pulls the sprites in as dependencies and
recognises them through the component references. The trade-off is an Editor touch for
every UI element; for code-built UI, setting `textureType: 8` is the pragmatic route.

For authoring the pixel art itself and converting it to sheets, see
[the Pixaki format notes](../pixaki-format.md).

## On-grid distortion of small sprites

Small point-filtered pixel-art `SpriteRenderer` sprites render **distorted** — uneven
pixel doubling, one row or column kicked into the neighbouring cell — when their
position lands **exactly on the 1/16-unit grid** (`x = k/16`, i.e. `x*16` is an
integer). Any tiny off-grid offset, even `+0.005`, makes them crisp again.

At the exact texel boundary the rasteriser's rounding is ambiguous (the `.5` case tips
either way, per axis), so one source texel maps to the wrong screen cell. The effect is
**world/texel based and therefore resolution-independent** — identical across
fullscreen, borderless and windowed at several resolutions. It is not a screen
sub-pixel effect and not a `filterMode` bug.

Measured on a 5×5 icon: `x = 4.0` and `x = 4.125` (both on-grid, 64/16 and 66/16)
distorted; `x = 4.005`, `x = 4.12`, `x = 4.2` (all off-grid) crisp, with sprite, scale
and `filterMode` unchanged throughout.

**How to apply:**

- Never place a small SpriteRenderer sprite at an exact `k/16` local or world position.
  Nudge it off-grid.
- Larger sprites (a 10×10 UI icon, say) are far less sensitive; this bites the small
  ones hardest.
- **Trap:** `CoreLib.Submodule.UserInterface.Component.PixelSnap` snaps `localPosition`
  *onto* the `k/16` grid, i.e. it forces exactly the distorted case for these sprites.
  It is editor-only (`OnDrawGizmos` / `OnValidate`, inert at runtime and in batchmode
  builds), so it will not fight you in the shipped build — but it will silently undo
  your nudge while you are working in the Editor.

## uiCamera Z-sorting, and the tie that dims a sprite

**CK's uiCamera sorts transparent renderers by Z position, not by `sortingOrder`.**
That is the standing rule for all HUD and menu work.

The trap follows from it: when a sprite and a box or panel **background** end up at the
**same absolute Z**, the sort is a tie, the order is undefined, and the background
intermittently renders *in front* of the sprite — dimming it to a washed-out grey. It
works whether the background is semi-transparent or opaque.

**It masquerades as a sprite colour bug.** The same icon renders correctly bright in one
layout and grey/desaturated in another, which looks exactly like a near-white colour
losing its saturation. It is not: the sprite pixels are bit-identical in the sheet and
in the built AssetBundle, and the *whole* icon — including frame pixels that are shared
between both variants — measures roughly twice as dark and half as saturated only when
it sits inside the box.

**Why it is layout-dependent:** the tie-break follows instantiation/render order. A
layout that instantiates several rows produces a different order than one that
instantiates a single element, so the tie breaks against the sprite in one layout and
not the other.

**Diagnosis:**

1. Measure the **rendered pixels in an in-game screenshot**, not the sprite in the sheet
   or in the bundle. A whole-icon dim at identical source pixels means render context,
   not sprite.
2. Move the element out of the box (scroll it out, for instance). Bright outside, grey
   inside means something is in front, position-dependent.
3. Compute the **absolute Z of every SpriteRenderer** involved by summing
   `localPosition.z` up the transform-parent chain. Two renderers at the same value —
   e.g. both at exactly `10.000` — is your tie.

**Fix:** give the foreground element a **distinct, smaller Z**. CK UI content sits at
world `z ≈ 0` with the uiCamera at `z = -10`, so a smaller local `z` is nearer the
camera and renders in front; a shift of `0 → -0.5` is enough.

Set it in the **prefab transform**, not in runtime code. It is a layout property, it
survives Editor reserialisation, and typical `SetLocalY`-style runtime positioning code
only writes `.y`, so a prefab-side `.z` persists untouched.

## PugText that switches itself off

`PugText.Start()` (Pug.Other, decompile offset ~351420) is:

```csharp
if (!renderOnStart) { if (!keepEnabledOnStart) { gameObject.SetActive(false); } return; }
```

So a `PugText` with **both** flags at `0` **deactivates its own GameObject** on its first
`Start`. The only thing that brings it back is a `PugText.Render(text, …, activate: true)`
call, which re-activates in `OnProfanityChecked`.

**Trap: that is only safe while every `Render` is unconditional.** An always-on mod HUD
normally change-gates its render, because a per-frame `PugText.Render` rebuilds the glyph
SpriteRenderers. Combine the two and you get a window where the text is off and the gate
withholds the very repaint that would switch it back on — the element stays blank until
the displayed string happens to change.

The reproducible case is a **second world entry in one session**: the HUD is
re-instantiated and rendered inside the same `Update` call stack, Unity runs `Start`
*afterwards* and deactivates the texts, and the gate's cache already holds the current
string. Nothing repaints until the value moves — e.g. until the player crosses a tile
boundary.

**Fix: `keepEnabledOnStart: 1`, leave `renderOnStart: 0`.** `Start` then returns without
deactivating *and* without painting. Do **not** set `renderOnStart: 1` to "solve" it —
that paints the prefab's design-time `textString` once. Clear that field as well, so a
later flip of the flag cannot resurrect a placeholder.

**Where the `0/0` comes from:** a prefab copied out of CK's own UI inherits CK's values,
and CK's own widgets render unconditionally every `LateUpdate`, so the combination never
bites them. Any prefab lifted from the game needs this pair checked.

## The font system

CK UI text is `PugText` rendering through `TextManager` / `PugFont`, all in
`Pug.Other.dll`. This matters for any mod with localised labels or a custom font.

`PugText.style.fontFace` is a `TextManager.FontFace` enum — a packed bitfield of
`weightMask | sizeFlags`. Each face is a separate `PugFont` ScriptableObject with its own
atlas, resolved via `Manager.text.GetFont(fontFace)`.

| Face | Enum value | Atlas texture | Size | Glyphs |
|---|---|---|---|---|
| `thinTiny` | `16777344` (0x1000080) | `rrs5` | 256×40 | 114 (vanilla) |
| `thinSmall` | `16777232` (0x1000010) | `rrsthin8` | 257×144 | 331 |
| `thinMedium` | `16777264` | `rrs10thin` | 513×192 | 331 |
| `boldSmall` | `67108880` | `rrs8` | 257×144 | 331 |
| `boldMedium` | `67108912` | `rrs10` | 513×192 | 331 |
| `boldLarge` | `67108896` | `rrs12b` | 514×192 | 212 |
| `boldHuge` | `67108928` | `rrs18` | 641×432 | 341 |
| `buttonFont` | `134217744` | `buttonfont_new` | 339×161 | 90 |

The atlases live in the `rrs*` family inside `resources.assets` — see
[reverse engineering](reverse-engineering.md) for getting at them.

### Missing-glyph fallback

`PugFont.GetGlyphData` resolves a character against `this.codePoints` first. On a miss it
walks a chain: `buttonFont → GetFont(style.fontFace) → chineseFont → japaneseFont →
koreanFont`, and only then falls back to `?` plus a `"Font X missing glyph"` warning.

**Trap:** a CJK fallback renders in **CJK metric**, so a Latin glyph missing from a small
Latin face comes out oversized and deformed — and **no warning fires**, because the glyph
*was* found, just in the wrong font. Deformed-looking text in an otherwise fine row is a
missing-glyph symptom, not a layout bug.

### Overriding glyphs at runtime, sandbox-safe

Adding or replacing a single glyph needs no `System.IO` and passes the
[Roslyn sandbox](sandbox-and-config.md):

```csharp
Manager.text.<face>.codePoints[c] = idx;
Manager.text.<face>.glyphData[idx].volatileSprite = ownSprite;
```

The `codePoints.TryGetValue` branch in `GetGlyphData` wins before any fallback, and the
renderer (`PugCoolText.UpdatePropertyBlock`) takes its UVs from `sprite.texture` /
`sprite.rect` — so the glyph may come from your own bundle's texture.
`InitCodePoints()` runs once at game boot, so an override applied before that point
persists.

### Replacing a whole atlas

For a full-face replacement the swap point is a Harmony **postfix on
`TextManager.Init2`** (called exactly once, from `TextManager.Init()`), plus a
late-arrival call from `IMod.Init()` for mods that finish loading after boot. The
postfix sets `texture`, clears `_customCharset` so the face falls back to the shared
static `PugFont.latinCharset`, rebuilds `glyphData`, then calls CK's own
`InitCodePoints()`. Patch mechanics are in [Harmony and ECS](harmony-and-ecs.md).

Three non-obvious constraints:

- **`latinCharset` is exactly 384 characters = a 32×12 atlas grid.** Charset position,
  `glyphData` index and atlas cell are one and the same coordinate, which is what makes a
  full-atlas rebuild index-stable instead of requiring per-glyph codePoint surgery.
- **`InitCodePoints` discards the bottom row of every source rect** (`rect2 = y+1, h-1`)
  and centres the pivot. The source atlas must therefore hand it a rect **two rows taller
  than the drawn glyph** (`RectH = BoxH + 2`): one row is eaten by the discard, the other
  lands the pivot on vanilla's baseline. `charDims` stays `(8, 10)` regardless — it is a
  layout metric (line advance, reported size), not atlas geometry, and does not track the
  rect inflation.
- **Kerning must be regenerated, not reused.** Vanilla `thinTiny` (`Font5.asset`) ships
  `enableKerning: 1` with a full 118×118 matrix, but the matrix is index-based and cannot
  survive a charset swap. A working generator derives a 384×384 matrix from glyph ink
  instead: for each shared ink row, `gap = (advance_a - 1 - right_a) + left_b`, take the
  minimum across rows, subtract one so stems can never touch, clamp to 2. Without the
  subtract-one step the table reproduces 97.66 % of vanilla's kerning but lets narrow
  glyphs collide (`l` followed by `t`, for example); with it, agreement with vanilla drops
  to about 84 % *by design* — the correctness criterion is "no collisions", not "matches
  vanilla". A welcome side effect: digit pairs stop kerning altogether, so counters and
  coordinate readouts keep a stable per-digit width.

### Correction: thinTiny does not render damage numbers

`CombatText.prefab` uses `thinSmall`. Measured usage of `thinTiny` across the shipped
assets is exactly 14 prefabs: the seven inventory/progress slots, `RecipeSlot`,
`RecipeCategorySlot`, `BossStatueRecipeSlot`, `DroppedItem`'s ground stack size,
`ConditionUI`, the score-text prefab and the main-manager prefab.

CK's `isDamageNumber → SetDefaultFont(thinTiny)` branch in `TextManager` is **dead code**:
rendering reads `style.fontFace`, `SetDefaultFont` only writes `defaultStyle.fontFace`,
and the single copy running in the other direction (`defaultStyle = style.GetCopy()`)
fires once in `Awake` — so a later `SetDefaultFont` call never reaches anything that
renders.

## HUD space and world space are not the same space

CK renders with exactly **two orthographic cameras**, and they are separate coordinate
spaces.

| Camera | Depth | Renders | Plane | Ortho size |
|---|---|---|---|---|
| Game Camera | 0 | the world | top-down **XZ** (`Position.y` is height, ≈0 on the ground) | 8.44 |
| UI Camera | 0.5 | the HUD (layer 27) | its own **XY** | 8.44 |

Neither uses a RenderTexture. The UI camera maps the player's world-Y (≈0) to a constant
viewport Y, so it cannot see the game-world position at all: **there is no clean
projection between world XZ and HUD XY.**

**Dead end — do not repeat it:** projecting a world position onto the HUD via
`gameCamera.WorldToScreenPoint(...)` → `uiCamera.ScreenToWorldPoint(...)` (or the
viewport variants). The game camera is a fixed internal camera that **does not follow the
player**, so `WorldToScreenPoint` returns a different pixel space — observed `screen.x ≈
6026` on a ~3632 px display, `viewport.x ≈ 1.4`. The projected "centre" lands at the
player's absolute world coordinate, i.e. off-screen, and the element simply vanishes.
This is only visible by logging the actual runtime values; static reasoning about the
camera setup will not reveal it.

**The working approach:** put the HUD root at **world origin `(0, 0, 0)`**. The UI camera
renders world-origin near screen centre, and the game camera renders the *player* near
screen centre too — so a HUD element at the root already sits approximately on the player
for free, with no projection. The residual is CK's fixed camera look-offset (the player
renders slightly above centre), absorbed by a constant vertical nudge:

```csharp
const float PlayerHudOffsetX = 0f;
const float PlayerHudOffsetY = 0.6f;   // uiCamera world units
Vector3 ringCenter = new Vector3(PlayerHudOffsetX, PlayerHudOffsetY, 0f);
```

CK tiles are 1 world unit and both cameras are size 8.44, giving a **1:1 tile ↔
uiCamera-unit mapping** — distances and offsets expressed in tiles translate directly
into HUD units. `PlayerHudOffsetY = 0.6` is a calibrated constant of the shared camera
setup, so the same value holds for any mod using this anchor.

**Bearing to a world target** (an arrow pointing from the player at something): the world
is XZ, so

```csharp
float bearing = Mathf.Atan2(target.z - player.z, target.x - player.x);
```

Using `delta.y` gives you height, which is ≈0 and pins the arrow at 0°/180°. World
geometry in general is covered by [world and mechanics](world-and-mechanics.md).

**Gate world-anchored HUD elements on playability.** Use a predicate equivalent to
`isInGame && isSceneHandlerReady && !Manager.load.IsLoading() && !cutsceneIsPlaying`, not
`isInGame && player != null`. The player object already exists at `OnOccupied` while the
load screen is up, and it survives the exit transition — a raw player-null check lets a
world-anchored HUD flash over teleport and Save-&-Quit load screens.
