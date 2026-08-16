# Prefabs, sprites and text rendering

This chapter covers the asset side of a Core Keeper mod: when a prefab may be edited
by script and when it must be touched in the Unity Editor, how sprites have to be
imported so they survive the AssetBundle bake, and the rendering traps — on-grid
distortion, Z-sorting ties, mask clipping, self-deactivating text, the font atlas
system — that make a structurally correct prefab render wrong. It closes with how a
HUD is mounted at all and with the one geometric fact that surprises every HUD
author: the world and the HUD are different coordinate spaces. Menu widgets, options entries, keybinds and scrolling belong to the
[UI framework](ui-framework.md). What the game requires of a sprite is covered
here; which program you draw it in is up to you.

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

### A newly added serialized field is zero in every older prefab

**Trap: adding a serialized field silently activates it everywhere.** A new `public`
serialized field is simply **absent** from prefab YAML that was written before the field
existed, so Unity deserialises it to `0`. The C# field initializer does *not* survive —
the serialized value, here the implicit zero, wins.

Pick the sentinel so that `0` means "off / no-op". A non-zero "off" — `float.MaxValue`
for "unbounded", say — turns every prefab authored before the change into an *active
broken* state instead of a neutral one, and mod prefabs ship inside your AssetBundle, so
that includes the ones already in players' hands.

### Put the value in the prefab, not in runtime code

If a value or a structure *can* live in the prefab, it belongs there. A box's sorting
layer, its material, a fixed width, a Z offset — set once in the prefab, consistent
everywhere. Reach for runtime `AddComponent` or per-frame field assignment only for
data that is genuinely dynamic per instance. Copying static properties onto a
`SpriteRenderer` on every `Populate()` is a shortcut around a prefab edit, and it hides
the real layout in code where nobody looks for it.

**The runtime-pool form of the same rule: clone a deactivated template child.** For a HUD
that shows a varying number of like elements, keep one *deactivated* child in the prefab
as the template and instantiate the pool from it. The clone inherits sprite, material,
sorting layer, `sortingOrder` and Unity layer, so the C# has to set no render property at
all. Let the pool **only ever grow**: switch surplus entries off with
`sr.enabled = false` instead of destroying them.

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

**Trap: a mod prefab may only reference assets from its own AssetBundle.** A serialized
field pointing at a CK *runtime* asset — `Manager.ui.GetCraftingUITheme(...).slotHoverSprite`,
for instance — has no counterpart in the bundle, so the reference bundles broken and comes
up null. There is no Editor-side fix for this one: either assign it at runtime from
`Manager.ui` (which is sandbox-safe) or ship your own sprite.

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

**Renaming the class is prefab-neutral; renaming a serialized field is not.** A prefab
references a script as `m_Script: {fileID: 11500000, guid: <meta guid>}` — the class name
appears **nowhere** in the prefab, so moving the `.cs` together with its `.cs.meta` keeps
every reference intact. A *serialized field* is the opposite case: the prefab stores it
**by key**, so renaming it needs a matching YAML edit in every prefab that carries it, and
a mismatch deserialises silently to null with no compile error and no warning.

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
| `spriteMode` | `1` | Single — the right value for the `LoadAsset<Sprite>(path)` route. A sheet atlas referenced from prefab YAML is `2`; see below |

Recommended alongside, matching CK's pixel-art convention:

| Field | Value | Meaning |
|---|---|---|
| `spritePixelsToUnits` | `16` | one 16×16 base tile = 1 world unit |
| `filterMode` | `0` | Point — no anti-aliasing smear |
| `spriteBorder` | `{x: L, y: B, z: R, w: T}` | 9-slice borders; the xyzw order is **left, bottom, right, top**, not XYZW |

**Drawing for that border.** Corners are border-sized and never stretch, so all corner
detail has to fit inside the border. Edges stretch along one axis and must therefore be
constant/tileable along it. The centre stretches both ways and has to stay flat. When
several sprites are packed into one sheet, leave a **2 px gutter** between them so 9-slice
tiling can never sample a neighbour's pixels — that is padding in the sheet layout, not
bleed painted into the sprite by hand.

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

### Sheet atlases: `spriteMode: 2` is correct on the prefab route

CK's own UI sprite sources (`ui_icon.png`, `ui_group.png`) are **multiple-mode sheet
atlases** — `textureType: 8`, `spriteMode: 2` — with named sub-sprites, referenced from
prefab YAML as `{fileID: <internalID>, guid: <atlas guid>, type: 3}`. So the two modes are
not a right-and-wrong pair: `1` belongs to the `LoadAsset<Sprite>(path)` route, `2` to the
prefab-reference route.

**Never extract a single sprite out of an atlas.** An individually exported PNG loses the
sheet-atlas meta and typically comes back as `textureType: 0`, at which point
`LoadAsset<Sprite>` returns null and the renderer silently shows nothing.

**Corollary for inspection: an atlas GUID in a prefab tells you nothing about the
graphic.** It only proves that *the atlas* is referenced, never which sub-sprite — two
renderers on the same GUID with different `fileID`s show completely different pictures.
Read the `fileID`.

### When you actually want the `Texture2D`

`ModBuilder` packs a PNG left at the default `textureType: 0` as a `Texture2D`, and then
`LoadAsset<Sprite>` returns null — that is the trap above. The reverse case, needing the
raw texture rather than a sprite, therefore does **not** get solved by leaving the
defaults alone. Ship the PNG with the same sprite settings (`textureType: 8`,
`spriteMode: 1`) and take `LoadAsset<Sprite>(path).texture` at runtime.

**Which program you draw in is entirely your choice.** Core Keeper never sees your
source file — it sees the imported PNG, so the only requirements are the import
settings above and the pixel conventions that follow from the game's art: 16 pixels
per unit and point filtering. Any editor that can produce that works.
[One such workflow](../pixaki-format.md), including sheet conversion, is written up
in this repository because it happens to be the one used here.

## A freshly added SpriteRenderer starts out broken

Two independent traps that co-occur often enough to look like one.

**Trap: the default material does not exist.** "Add Component → SpriteRenderer" in this
SDK project assigns material `guid 274d4544…`, which is not backed by any asset. A
renderer with a missing material **draws nothing** — with a valid sprite, correct sorting
and a fully opaque colour, in the Editor as well as in game. Every working CK UI renderer
uses Unity's built-in **Sprites-Default**:
`{fileID: 10754, guid: 0000000000000000f000000000000000, type: 0}`. The dangling GUID is a
property of this SDK project's defaults; the Sprites-Default convention is CK-wide.

**Trap: the sorting layer is `0`, not `"GUI"`.** A new renderer lands on sorting layer
`0` ("Default"). This is not limited to runtime `AddComponent` — it recurs just as
reliably on prefab children authored in the Editor.

Duplicating an existing, working element inherits both correctly, which is the cheapest
way to avoid the pair altogether.

**A copied custom-shader material ignores `SpriteRenderer.m_Color` in the bundle.** If the
sprite has to be tinted at all, put built-in Sprites-Default (`fileID: 10754`) on it.

**Trap: `Shader.Find` returning non-null proves nothing.** CK's gradient shader is
`Amplify/UISpriteColorReplace` — it is the one carrying `_GradientMap` and the
`USE_GRADIENT_MAP` keyword. `Radical/SpritesDefault` *also* exists in the game, so a wrong
guess at the name still yields a real shader: the sprite renders, the keyword is ignored,
nothing is recoloured, and no error anywhere points at the cause. Identify a shader by the
properties and keywords it exposes, never by the lookup having succeeded.

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

## Clipping with a SpriteMask

CK's `UIScrollWindow` does not clip its content — a scrolling list needs a `SpriteMask`
of your own (the scrolling machinery itself is in the
[UI framework](ui-framework.md)). Adding the mask is only the first of several steps, and
every one of the remaining ones fails *silently*, with a clean build: either a sprite that
should be clipped is not, or a sprite that should be visible is gone.

### A renderer is clipped only when both conditions hold

1. **`maskInteraction = VisibleInsideMask`** — `m_MaskInteraction: 1` on a
   `SpriteRenderer`, `style: maskInteraction` on a `PugText`. The default `0` (None)
   ignores every mask there is.
2. **Its sorting order lies inside the mask's custom sorting-layer range.** The range is
   about *capture* — which renderers this mask governs — not about draw order.

The corollary is the deliberate exemption: leaving a renderer at `maskInteraction: None`
is how you keep it visible even though it sits inside the range. CK's own `ScrollBar` and
handle sprites, at orders 46/47/48 inside a 40..55 mask range, need exactly that, or the
row mask eats them.

### `VisibleInsideMask` with no active mask renders nothing at all

A renderer with `m_MaskInteraction: 1` is invisible whenever no `SpriteMask` covers it.
Two consequences worth knowing before you go hunting:

- **Opening such a prefab in Editor isolation renders blank.** That is expected, not a
  bug. Do not "fix" it by setting `maskInteraction: None` — that breaks the runtime
  clipping.
- **The mask GameObject must stay active for as long as its content is shown.** Never gate
  it on "is the content currently overflowing": a short or collapsed list then vanishes
  entirely. Size the mask to the cap and let it clip only when there is something to clip.

`PugText` glyphs inherit `style.maskInteraction`, so the same rule applies to them —
which is the argument for leaving titles and chrome at `maskInteraction = 0`. They then
never clip, and they need no sorting band of their own.

### Trap: order equal to the mask's back-order is not reliably captured

With a mask band's `m_BackSortingOrder` set to N, renderers at exactly order N render
**invisible**, while N+1…N+4 show. A row background at order 56 against a
`m_BackSortingOrder` of 56 disappeared; lowering the back order to 55 fixed it. Set the
back order **strictly below** the lowest order you want clipped.

The symptom — row backgrounds gone, labels on top of them fine — reads like a sprite or
material bug, and it is a pure off-by-one.

### Mask setup facts

- A `SpriteMask` needs Unity's built-in **Sprites-Mask** material
  (`fileID: 10758, guid: 0000000000000000f000000000000000`). Prefabs imported via
  AssetRipper arrive with a placeholder sprite *and* a placeholder material
  (`0000000deadbeef15deadf00d0000000`) — both have to be replaced.
- **The mask's scale *is* its size.** A mask still carrying the calibration for a
  different sprite clips nothing at all, and the whole screen then counts as "inside the
  mask" — which looks like the `maskInteraction` flags being wrong.
- The mask sprite itself is imported with `spritePixelsToUnits: 1`.

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

### Tinting: set the colour after `Render()`

`PugText.color`'s setter goes through `SetTempColor`, which writes the glyph
`SpriteRenderer`s that `Render(text)` (re)builds. A colour applied **before** the render
call is therefore discarded — order matters, and the wrong order costs nothing at compile
time.

`renderOnStart: 1` adds a second failure on top: such a prefab re-renders once on `Start`
— one frame after a freshly instantiated object first activates — which resets the glyphs
to `style.color` and blanks the tint. `SetTempColor(c, keepColorOnStart: true)` makes it
re-apply `tmpColor` on that start-render.

**The symptom is distinctive:** the tint appears only seconds later on the **first** open
after a world load, and is correct on every subsequent open.

## The font system

CK UI text is `PugText` rendering through `TextManager` / `PugFont`, all in
`Pug.Other.dll`. This matters for any mod with localised labels or a custom font.

### Every PugText draws in front of every sprite

`PugText.style.sortingLayer` defaults to `int.MinValue`, which is a **sentinel, not a
layer**: `PugText.Render` resolves it to `SortingLayer.NameToID("GUI")` and then applies
`style.orderInLayer` verbatim as the renderer's `sortingOrder`, with no runtime reset. The
default `orderInLayer` is **9999**.

Glyphs and `SpriteRenderer`s therefore share the GUI layer, and at 9999 every `PugText`
draws in front of every sprite. A popup background at order 54 cannot cover a label until
that label's order is lowered — the symptom (text bleeding through your own panel) reads
like a Z-order bug and has no visible cause, because 9999 is not a number anyone guesses.

`orderInLayer` is freely settable in prefab YAML (`style: orderInLayer`), and lowering it
is the correct fix rather than a workaround. Two worked cases: a footer status line
drawing over an open popup was fixed by moving it from 9999 to 50, below the popup
background's 54; the popup's own labels were pulled from 9999 into a 56..63 band so that
the popup's mask could clip them.

### PugText fields that must be set in the prefab

- **`maxWidth` must stay `0`.** Any non-zero value routes the text through CK's word-wrap
  `PugFont.AddNewLinesToLinesExceedingMaxWidth`, which throws an
  `IndexOutOfRangeException` **every frame**. Check this on any `PugText` copied out of
  the game.
- **Alignment is a real serialized field, not a transform trick.**
  `PugTextStyle.HorizontalAlignment { left, center, right }` serialises as `0/1/2`, and
  `verticalAlignment` likewise.

### CK's drop shadow is a second text object

CK's text shadow does **not** come from `PugText`'s built-in `outline` — that field is `0`
on the widgets that have a shadow. The shadow is a second, black `PugText` carrying the
same string, offset by `0.0625` world units to the right and down (exactly 1 px at 16
pixels per unit) and drawn behind the real one with an `orderInLayer` one lower. Reaching
for `outline` instead gives you a visible deviation from the vanilla look.

### Faces and atlases

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
[reverse engineering](reverse-engineering.md) for getting at them. The table is not the
complete set: `TextManager.Init2` calls `InitCodePoints()` on **twelve** faces.

Which charset a face uses differs per face. `thinTiny` carries its own `_customCharset`
starting at ASCII 33, `thinSmall` uses the shared static `latinCharset`; the `charset`
property (`Pug.Other:350400`) picks `_customCharset` whenever it is not null or
whitespace. `thinTiny`'s 114 codepoints are a **true subset** of `thinSmall`'s 331 — the
difference measures empty, so going from one to the other is a pure gain of 217
characters.

### What the atlases do and do not contain

**No CK font maps any whitespace codepoint.** Not `thinSmall` (331), not `thinTiny`
(114), not `boldHuge` (341), not the Chinese font (3891): none of them contains `U+0020`,
`U+00A0` or the typographic spaces `U+2000–U+200A`. CK handles spacing outside glyph
resolution, so space width is neither definable nor changeable through a font atlas — and
an empty-looking rect slot in an atlas is not a space glyph waiting to be widened.

**Glyph coverage differs per face, so a character can be missing from one atlas only.**
`♦` (U+2666) and `♢` (U+2662) exist **only** in the `boldLarge` atlas; `thinMedium`
renders `?` for them. Reaching them means switching that `PugText`'s `fontFace` at
runtime. When you write such a character in mod source, write it as a Unicode escape
(`'\u2666'`, `'\u2662'`) and keep the source pure ASCII: a literal non-ASCII character is
encoding-unsafe through the [Roslyn sandbox](sandbox-and-config.md) compile.

**Some painted cells carry no codepoint and are structurally unreachable by character.**
`PugFont.GetGlyphData` starts at `codePoints.TryGetValue(c, …)`, so a glyph slot without a
codepoint cannot be addressed by a character at all. CK's coloured controller symbols
(A/B/X/Y, `+`, `−`) are exactly that class — CK addresses them internally by glyph
*index*. Characters that do carry codepoints behave normally; the two hearts `♥`/`♡`
(`U+2665`/`U+2661`) are ordinary mapped glyphs. In the vanilla atlases the
painted-but-codepointless indices are `{97, 98}` in `thinTiny` (unmapped `Ç`/`ç`) and
`{2..7, 378..381}` in `thinSmall` — the six controller symbols plus four template orphans
left over from the grid (`adv = 5`, `chars = []`), which are harmless precisely because
nothing can reach them.

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

Non-obvious constraints:

- **`latinCharset` is exactly 384 characters = a 32×12 atlas grid.** Charset position,
  `glyphData` index and atlas cell are one and the same coordinate, which is what makes a
  full-atlas rebuild index-stable instead of requiring per-glyph codePoint surgery.
- **`InitCodePoints` discards the bottom row of every source rect** (`rect2 = y+1, h-1`)
  and centres the pivot. The source atlas must therefore hand it a rect **two rows taller
  than the drawn glyph** (`RectH = BoxH + 2`): one row is eaten by the discard, the other
  lands the pivot on vanilla's baseline. `charDims` stays `(8, 10)` regardless — it is a
  layout metric (line advance, reported size), not atlas geometry, and does not track the
  rect inflation.
- **The atlases are 257 px wide rather than 256 because of the horizontal inflation.**
  `InitCodePoints` widens every rect by `x -= 1; width += 2` — but only while
  `rect2.width + rect2.x + 2 < texture.width`. When that fails it leaves the glyph
  un-inflated and logs *"you need to make the font texture 1 pixel wider to the right to
  support outlines"*. The same pass **skips** two kinds of cell: one whose charset
  character is a space, and one with a zero-size rect — a zero-size rect is the encoding
  for "empty cell".
- **A codepoint-keyed replacement cannot reach index-addressed glyphs.** The slots that
  carry no codepoint (CK's controller symbols, template orphans) will receive your pixels
  and never render them, because character lookup cannot address them at all. Glyphs with
  real codepoints — the hearts, for example — are replaced normally.
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

### Reading a vanilla atlas back

Mapping an atlas cell to its character on the 32×12 `latinCharset` grid:

```text
col = rect.x // 8
row = 11 - (rect.y // 12)
```

The subtraction is the part that bites: CK's glyph rects are in Unity coordinates with the
origin at the **bottom left**, while a cell grid is read top-down. Miss it and you get a
silent off-by-N-rows error rather than an obviously wrong result.

Metrics of vanilla `thinTiny`, measured against the shipped `rrs5` atlas: cap height 6 px,
digit height 6 px, x-height 4 px, and `C E F L` are 2 px wide. Digit advance is **3**.

**Keep the digit advance when you replace a face.** Identical digit advance means every
counter and coordinate readout in the game keeps its existing width, so no layout that was
tuned around numbers shifts.

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

**The uiCamera shows a constant world area, so a fixed-size prefab is
resolution-independent.** `Manager.camera.uiCamera.orthographicSize` is exactly
**8.4375** — the 8.44 in the table rounded — so the visible height is
`2 × orthoSize = 16.875` world units and the width is
`height × aspect` — a **30 × 16.875** viewport at 16:9. That area does not change with
resolution (confirmed empirically across several), and CK exposes no UI-scale option at
all. A prefab authored at a fixed size is therefore "fullscreen with a border" at every
resolution, and a mod window needs **no runtime sizing logic**. For matching the vanilla
look, CK's own inventory margin is 0.25 world units.

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

## Mounting an always-on HUD

A non-modal HUD is **not** registered through CoreLib's
`UserInterfaceModule.RegisterModUI` — that route belongs to modal windows (see the
[UI framework](ui-framework.md)). The plain route is two steps:

1. In `IMod.ModObjectLoaded`, fish the prefab out of the asset stream **by its GameObject
   name**.
2. In `IMod.Update`, instantiate it lazily under
   `Manager.ui.chestInventoryUI.transform.parent` — the `IngameUI` root — as soon as
   `Manager.ui != null && Manager.ui.chestInventoryUI != null`.

That is the same parent modal CoreLib windows end up under; what differs between a HUD and
a modal window is the layer and the activation path, not the mount point.

**Trap: guard the lazy instantiation on a static `Instance` that the HUD class sets in
`Awake`, not in `Start`.** With the assignment in `Start` there is a one-frame window in
which the update loop still sees no instance and instantiates the HUD a second time.

## Why a mod HUD stays invisible

Four unrelated mistakes produce the same complaint — "my HUD element exists,
it is active, and I cannot see it". They are distinguishable, and the first
signal to read is `SpriteRenderer.isVisible`.

| Cause | `isVisible` | What is happening |
|---|---|---|
| Wrong layer | `true` | The renderer is fine; the camera is not drawing that layer |
| Wrong Z | `false` | Outside the uiCamera frustum, so it is culled |
| Scaled to nothing | `true` | Drawn at zero size |
| Fully transparent sprite | `true` | Drawn correctly — there is nothing in the pixels |

**`isVisible == false` means culled, not occluded.** Nothing in this game hides
a HUD element behind something else — if the flag is false, the element is
outside the frustum or on an unrendered layer. That single check isolates the
wrong-Z row from all the others.

The last row is the meanest of the four, because *every* diagnostic reads healthy:
a placeholder sprite whose pixels are fully transparent — an empty "frame", say — has
the right layer, the right Z, a non-zero scale and `isVisible == true`, and renders
nothing at all. Open the sprite, not the prefab.

### Layer: the HUD renders on 27, not on 5

During ordinary gameplay the uiCamera draws the **HUD** layer. Layer 5 ("UI") is
*not* in its culling mask then — it is switched on only for the modal UI path.
So a HUD element built like a UI window renders reliably in menus and never
during play.

`CameraManager.ShowHUD(bool)` is the mechanism, and it operates on exactly that
one layer:

```csharp
if (show) uiCamera.cullingMask |=  1 << ObjectLayerID.HUD;
else      uiCamera.cullingMask &= ~(1 << ObjectLayerID.HUD);
```

Put **every** GameObject of the HUD prefab on the HUD layer — in the prefab via
the `m_Layer` field, at runtime via `gameObject.layer =
LayerMask.NameToLayer("HUD")`. `ObjectLayerID` (`Pug.Base`) resolves its layers
by name rather than hard-coding numbers, so use the name and let it resolve; in
stock Core Keeper it comes out as 27.

Doing this buys most of a feature for free: because the whole gameplay HUD hangs
off that one layer, `ShowHUD(false)` culls your element along with the rest
wherever the game calls it.

**But it does not cover every hiding case, and the gap is the one you will see
first.** The spawn-from-Core intro cutscene does not go through `ShowHUD` at all
— it calls `FadeOutAllGameplayUI()`, which fades CK's **own registered** gameplay
UI and not arbitrary renderers that merely happen to sit on the HUD layer. Your
element stays visible straight through the cutscene.

So the layer buys you the ordinary cases, and cutscenes still need an explicit
gate on `!sceneHandler.cutsceneIsPlaying` — which the playability predicate
below includes for exactly this reason.

### Z: the parent sits at −10, so content needs local z = 10

`IngameUI` sits at world z = −10, which is outside the uiCamera frustum. A child
left at local z = 0 inherits that position and is never rendered. Give the HUD
content **local z = 10**, bringing it to world z ≈ 0 — the plane the camera
actually renders, and the same z CoreLib moves modal UIs to when it opens them.

### Never scale a mod HUD with `CalcGameplayUITargetScaleMultiplier`

`Manager.ui.CalcGameplayUITargetScaleMultiplier()` is CK's own idiom — the
vanilla health bar and its siblings assign it to `localScale` every frame. For a
mod HUD mounted under `IngameUI` it returns **`(0, 0, 0)`**. Used as a scale
source it collapses the element to nothing, while every other diagnostic still
looks healthy.

Drive visibility with an explicit boolean instead of a scale. Which predicate
depends on what the element does: a world-anchored element needs the stricter
playability gate described above, while an element that merely has to stay out
of the way of open interfaces can gate on `!Manager.ui.isAnyInventoryShowing &&
!Manager.menu.IsAnyMenuActive()` in addition. Toggle with `SetActive`, and only
when the value changes.

**Trap: never put the component that drives visibility on the GameObject it
switches off.** Deactivating that object stops the component's own `LateUpdate`
from running, so it can never switch the display back on — hidden once means
hidden for the rest of the session, with no error anywhere, and only a restart
brings it back. The symptom looks like a random bug ("the HUD is sometimes
gone").

Give the prefab an intermediate level for this — `root` → `hudRoot` → contents.
The driving component sits on the always-active `root`, holds `hudRoot` as a
serialized field, and toggles *that*.

**Trap: `isAnyInventoryShowing` is not a plain vanilla signal once CoreLib is
loaded.** CoreLib patches that aggregate getter and forces it **true whenever
any CoreLib-managed mod window is open — including windows belonging to other
mods** — while the per-UI getters such as
`Manager.ui.isPlayerInventoryShowing` stay unpatched. For a HUD that simply
wants to disappear behind open interfaces, that is exactly right, and it is the
reason to prefer this one predicate over querying the individual UIs: your own
window counts as an interface too, and so does a stranger's, without your
knowing anything about it. (All of this holds only while CoreLib is loaded.)
But the same patch makes the aggregate useless as a
window's *own* guard — gate a window on it and the window blocks itself. Read a
per-UI getter when you need to tell "a vanilla menu is open" from "my own window
is open".
