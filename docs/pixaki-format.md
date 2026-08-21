# Pixaki File Format (`.pixaki`) — Reverse-Engineering Notes

Findings from dissecting `item-checklist/sources/Item checklist sprites.pixaki`
(Pixaki on iPad, file written 2026-06). **Undocumented, proprietary,
version-dependent** — treat as a snapshot, not a spec. Useful if we ever want to
*generate* a `.pixaki` (e.g. to ship the glyph-template layers as a
ready-to-edit document) rather than import PNGs manually.

## Container

A `.pixaki` is a plain **ZIP archive** (compression `store`, i.e. uncompressed):

```
metadata.json                         # tiny: canvas size + duration
document.json                         # the whole document model (layers, cels, UI state)
images/preview.png                    # flattened thumbnail
images/drawings/<UUID>.png            # one TRIMMED bitmap per cel (the actual pixels)
images/selections/  images/references/   # (empty in this file)
cache/keyframes/<long-hash>.png       # rendered keyframe cache (regenerable)
```

`file` reports `Zip archive data, at least v2.0 to extract, compression method=store`.

## `metadata.json`

```json
{"duration": 1, "size": [300, 300]}
```

`size` = canvas `[w, h]`; `duration` = frame count (1 = single still image).

## `document.json`

Top-level keys: `sprites` (the content) plus editor/UI state that is **not** needed to
describe the image — `selectedColor`, `palette`, `brushOptions`, `eraserOptions`,
`brushIdentifier`, `eraserIdentifier`, `isIndexed`, `animationSpeed`, `onionSkinSettings`,
`gridSettings`, `primarySpriteIdentifier`, `selectedSpriteIdentifier`.

### `sprites[]` (one entry here)

Keys: `layers[]`, `cels[]`, `duration`, `size [w,h]`, `identifier`, `referenceImages[]`,
`timelineSelection`, `canvasConfiguration`, `symmetrySettings`.

### Layers — two types

`sprite.layers[]` is the **layer tree** (top→bottom). Each layer is either:

**`type: "cel"`** — a drawable layer:
```json
{ "type": "cel", "name": "Background", "identifier": "<UUID>",
  "opacity": 1, "isVisible": false, "isAlphaLocked": false, "blendMode": "normal",
  "clips": [ { "itemIdentifier": "<cel UUID>", "identifier": "<clip UUID>",
               "range": { "start": 0, "end": 1 } } ] }
```

**`type: "group"`** — a folder, recursively nesting more layers:
```json
{ "type": "group", "name": "Outsorted", "identifier": "<UUID>",
  "opacity": 1, "isVisible": true, "isExpanded": false, "blendMode": "passThrough",
  "group": { "identifier": "<UUID>", "layers": [ /* child layers, same shape */ ] } }
```
Groups nest arbitrarily deep (`group.group.layers[].group.layers[]…`). Group blend mode
is typically `passThrough`; cel layers use `normal`.

### `cels[]` — the pixel containers

`sprite.cels[]` is a **flat list** (all cels across all layers/frames; 60 here for the
nested layers at 1 frame). Each:
```json
{ "type": "drawing", "identifier": "<UUID>",
  "frame": [ [x, y], [w, h] ],      // TRIMMED bounding box in canvas space
  "containerSize": null, "requiresTrim": false, "opacity": 1, "isVisible": true }
```

### The linkage (verified)

```
layer(type=cel).clips[].itemIdentifier  ──→  cels[].identifier  ──→  images/drawings/<identifier>.png
```
- `clip.itemIdentifier` → a `cel.identifier` (all clip itemIdentifiers ∈ cel identifiers ✓).
- `cel.identifier` → the drawing file `images/drawings/<cel.identifier>.png`
  (60/60 matched ✓).
- `clip.identifier` is the clip's own timeline id; `clip.range {start,end}` is
  the frame span.

### Coordinates & trimming

- **Drawings are trimmed**, not full-canvas: a `4F81798D….png` is `8×8` inside a `300×300`
  canvas. `cel.frame = [[x,y],[w,h]]` places that trimmed bitmap at canvas position `(x,y)`.
- Pixaki canvas origin is **top-left** (unlike Unity textures, which are bottom-left).

### `cache/` + `preview`

- `images/preview.png` — flattened thumbnail of the whole document.
- `cache/keyframes/<hash>.png` — rendered frame cache; regenerable, not authoritative.

## Generating a `.pixaki` (if ever needed)

Minimum viable document would need: `metadata.json` (size+duration),
`document.json` with one sprite, N `cel`-layers each carrying one `clip` whose
`itemIdentifier` matches a `cels[]` entry, each cel's `frame` set to the
drawing's placement, and the trimmed `images/drawings/ <id>.png` files.
`preview.png` + a keyframe are likely expected too.

**Risks:** the format is undocumented and version-specific; Pixaki may validate strictly
(consistent identifiers, clip ranges, cache presence) and reject a hand-built
file. Recommended path for our glyph templates is still **importing the
per-layer PNGs into Pixaki** (native PNG import as layers) rather than
synthesising `.pixaki` — unless a generated file is verified to open. Editor/UI
keys (`palette`, brush options, etc.) can likely be copied verbatim from an
existing file or defaulted.

## Observed in this file (incidental)

The Iter-12 document already contains `8x8` and `10x10` helper layers at opacity `0.69` —
hand-made nominal-cell grids, the same idea as the iter-25 `charDims` checkerboard overlay.
