# Pixaki File Format (`.pixaki`) — Reverse-Engineering Notes

Findings from dissecting `item-checklist/sources/Item checklist sprites.pixaki`
(Pixaki on iPad, file written 2026-06). **Undocumented, proprietary,
version-dependent** — treat as a snapshot, not a spec. Useful if we ever want to
*generate* a `.pixaki` (e.g. to ship the glyph-template layers as a
ready-to-edit document) rather than import PNGs manually.

## Container

Whichever form a `.pixaki` arrives in, it holds the same payload:

```
metadata.json                         # tiny: canvas size + duration
document.json                         # the whole document model (layers, cels, UI state)
images/preview.png                    # flattened thumbnail
images/drawings/<UUID>.png            # one TRIMMED bitmap per cel (the actual pixels)
images/selections/  images/references/   # (empty in this file)
cache/keyframes/<long-hash>.png       # rendered keyframe cache (regenerable)
```

### Two packagings, one payload

**How a document leaves the iPad decides its form** — and the payload is
identical either way. Verified 2026-08-22 on two levels: the same four
documents were fetched over *both* routes and every drawing came back
pixel-identical, down to the trimmed bounding boxes and layer visibility; and
across seven documents both forms carry the same directories and the same kinds
of file. The export adds nothing and drops nothing.

| Route off the iPad | Form on disk | `file -b` reports |
|---|---|---|
| Pixaki **Export**, then AirDrop | **ZIP archive**, compression `store` (uncompressed) | `Zip archive data, at least v2.0 to extract, compression method=store` |
| Pulled straight out of **iCloud** | **directory** — the native document package | `directory` |

So the ZIP is not the format; it is what Pixaki's export step wraps around the
package. Both open in Pixaki, and a document can be moved between the forms by
zipping/unzipping without losing anything.

**The Finder shows both as a single file**, so the difference is invisible
exactly where you would normally look. That presentation comes from the Finder
bundle bit in the package's `com.apple.FinderInfo`, *not* from a registered
document type — macOS does not know the extension at all (`mdls -name
kMDItemContentType` returns a dynamic `dyn.…` UTI, since Pixaki runs on the
iPad and nothing here claims `.pixaki`). Tell the two apart from a shell:

```bash
file -b "<path>"           # "directory" vs "Zip archive data…"
GetFileInfo -aB "<path>"   # 1 = bundle bit set, i.e. a package
ls -ld "<path>"            # leading "d" = directory; trailing "@" = has xattrs
```

A package that came through iCloud also carries a `com.apple.fileprovider.fpfs#P`
xattr — a dependable fingerprint of that route.

**Two consequences, both real:**

- **`utils/pixaki_to_sheet.py` and `utils/pixaki_to_glyphs.py` read either
  form**, through `utils/pixaki_container.py`. It dispatches on
  `os.path.isdir()` and hands back `zipfile.ZipFile` itself for an archive, or
  a directory backend carrying the three members the two readers use:
  `namelist()`, `read()` and `open()`. The third is not optional — the glyph
  tool passes its container on to `layer_full()`, so the adapter has to satisfy
  that call site too, not just the loader. The backend lists files only, so the
  six directory entries an export stores (`cache/`, `cache/keyframes/`,
  `images/`, `images/drawings/`, `images/references/`, `images/selections/`)
  have no counterpart in a package's listing. That reaches neither reader,
  though for *different* reasons: `pixaki_to_sheet` scans `namelist()` and
  keeps only `images/drawings/*.png`, while `pixaki_to_glyphs` never enumerates
  at all and opens each member by the name `document.json` gives it. Both
  suites build one payload in both packagings and compare the tool's own
  output, so the equality is checked rather than assumed. A package whose
  contents iCloud has evicted — `.<name>.png.icloud` placeholders where the
  drawings were — is refused by name, not by a later `KeyError` on a cel UUID.
- **Committing a package loses the empty directories.** A ZIP stores directory
  entries, empty `images/references/` and `images/selections/` included; git
  stores blobs at paths and cannot represent an empty directory. What it buys
  is a diffable history — `document.json` reads as JSON in a diff, and an
  edited drawing appears as one changed PNG rather than a wholly rewritten
  binary blob.

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
