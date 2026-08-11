#!/usr/bin/env python3
"""Extract the thinTiny full-build atlas + advance widths from a Pixaki master.

Reads the master's `Atlas` layer (the glyph pixels) and `Rects` layer (the
magenta advance boxes), writes the atlas PNG, and prints one advance width per
atlas cell as a 384-character string of digits.

Cell layout: 32 columns x 12 rows of 8x12 cells on a 257x144 canvas. The cell
index equals the charset position AND the PugFont.glyphData index -- CK's
`latinCharset` is exactly 384 characters long, one per cell. Every rect box in
the master sits at y=0 with height 10 and x-offset 0 (verified in
complete-tiny-font/sources/thinTiny-review.md), so only the width varies;
`validate()` fails loud if that ever stops holding.

Usage:
    python3 utils/pixaki_to_glyphs.py --pixaki <master.pixaki> --sheet <out.png>
    python3 utils/pixaki_to_glyphs.py --pixaki <master.pixaki> --check-only
"""

import argparse
import json
import sys
import zipfile

from PIL import Image

CDX, CDY = 8, 12  # cell size (thinSmall grid)
COLS, ROWS = 32, 12
CELLS = COLS * ROWS  # 384 == len(PugFont.latinCharset)
BOX_Y, BOX_H = 0, 10  # the rect box inside every cell (thinTiny metric)
# BOX_Y was 1 until 2026-08-12: PugFont.InitCodePoints derives every glyph
# sprite from (y+1, h-1), discarding the box's bottom row. At y=1 that row
# sat inside the drawn glyph, so every glyph rendered a pixel low and 15
# diacritics lost their bottom row. The master was shifted up by one row so
# CK's discarded row falls outside the drawn glyph.
RECTS_RGB = (229, 59, 223)  # the Rects layer colour


def layer_full(zf, sprite, cels, name):
    """Composite one named layer onto a full-canvas RGBA image."""
    w, h = sprite["size"]
    layer = next(l for l in sprite["layers"] if l.get("name") == name)
    cel = cels[layer["clips"][0]["itemIdentifier"]]
    (fx, fy), _ = cel["frame"]
    full = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    drawing = Image.open(zf.open(f"images/drawings/{cel['identifier']}.png"))
    full.alpha_composite(drawing.convert("RGBA"), (fx, fy))
    return full


def load_layers(pixaki_path):
    """Return (rects_img, atlas_img) from a .pixaki (a plain ZIP)."""
    zf = zipfile.ZipFile(pixaki_path)
    doc = json.load(zf.open("document.json"))
    sprite = doc["sprites"][0]
    cels = {c["identifier"]: c for c in sprite["cels"]}
    return layer_full(zf, sprite, cels, "Rects"), layer_full(zf, sprite, cels, "Atlas")


def cell_box(index):
    """Top-left pixel box of a cell: (x, y_top, w, h)."""
    return ((index % COLS) * CDX, (index // COLS) * CDY, CDX, CDY)


def cell_geometry(index, atlas_h=None):
    """(x, y_unity, h) of a cell's rect box, y flipped to Unity's bottom-left."""
    if atlas_h is None:
        atlas_h = ROWS * CDY
    x, y_top, _, _ = cell_box(index)
    return (x, atlas_h - (y_top + BOX_Y + BOX_H), BOX_H)


def _bbox(img, index, predicate):
    x0, y0, w, h = cell_box(index)
    px = img.load()
    xs, ys = [], []
    for dy in range(h):
        for dx in range(w):
            if predicate(px[x0 + dx, y0 + dy]):
                xs.append(dx)
                ys.append(dy)
    if not xs:
        return None
    return (min(xs), min(ys), max(xs) - min(xs) + 1, max(ys) - min(ys) + 1)


def _is_rects_colour(rgba):
    r, g, b, a = rgba
    return a > 0 and r > 140 and b > 140 and g < 130


def _is_opaque(rgba):
    return rgba[3] > 0


def rect_bbox(rects_img, index):
    """The magenta advance box within cell coordinates, or None."""
    return _bbox(rects_img, index, _is_rects_colour)


def glyph_bbox(atlas_img, index):
    """The glyph's pixel box within cell coordinates, or None."""
    return _bbox(atlas_img, index, _is_opaque)


def widths(rects_img, cell_count=CELLS):
    """One advance width per cell; 0 for a cell with no rect box."""
    out = []
    for i in range(cell_count):
        box = rect_bbox(rects_img, i)
        out.append(box[2] if box else 0)
    return out


def validate(rects_img, atlas_img, cell_count=CELLS):
    """Fail-loud invariant report. Empty list == clean.

    Geometry problems on an existing rect box take precedence over the
    presence/absence mismatch: a box with a wrong offset is already flagged
    for that, so it does not also get a redundant "no glyph pixels" entry.
    """
    problems = []
    for i in range(cell_count):
        rb = rect_bbox(rects_img, i)
        gb = glyph_bbox(atlas_img, i)
        if rb is None:
            if gb is not None:
                problems.append(f"cell {i}: glyph pixels but no rect box")
            continue
        dx, dy, w, h = rb
        had_geometry_issue = False
        if dy != BOX_Y:
            problems.append(f"cell {i}: rect box y is {dy}, expected {BOX_Y}")
            had_geometry_issue = True
        if h != BOX_H:
            problems.append(f"cell {i}: rect box height is {h}, expected {BOX_H}")
            had_geometry_issue = True
        if dx != 0:
            problems.append(f"cell {i}: rect box x-offset is {dx}, expected 0")
            had_geometry_issue = True
        if gb is None and not had_geometry_issue:
            problems.append(f"cell {i}: rect box but no glyph pixels")
    return problems


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pixaki", required=True, help="path to the .pixaki master")
    ap.add_argument("--sheet", help="write the Atlas layer here as PNG")
    ap.add_argument(
        "--check-only",
        action="store_true",
        help="only run the invariant checks, write nothing",
    )
    ns = ap.parse_args(argv)

    rects, atlas = load_layers(ns.pixaki)
    if atlas.size != (COLS * CDX + 1, ROWS * CDY):
        sys.exit(
            f"canvas is {atlas.size}, expected {(COLS * CDX + 1, ROWS * CDY)} "
            "(the +1 column is required by PugFont's outline padding check)"
        )

    problems = validate(rects, atlas)
    if problems:
        for p in problems:
            print(f"INVARIANT: {p}", file=sys.stderr)
        sys.exit(f"{len(problems)} invariant violation(s) — refusing to emit")

    w = widths(rects)
    painted = sum(1 for x in w if x)
    if ns.check_only:
        print(f"OK — {painted} painted cells, all invariants hold")
        return 0

    if ns.sheet:
        atlas.save(ns.sheet)
        print(f"// wrote {ns.sheet} ({atlas.width}x{atlas.height}), {painted} cells")
    if max(w) > 9:
        sys.exit(
            f"an advance width exceeds 9 ({max(w)}) — the digit string cannot hold it"
        )
    print("// paste into ThinTinyFontPatch.cs Widths")
    print("        private const string Widths =")
    for row in range(ROWS):
        chunk = "".join(str(x) for x in w[row * COLS : (row + 1) * COLS])
        tail = ";" if row == ROWS - 1 else ""
        print(f'            "{chunk}"{"" if row == ROWS - 1 else " +"}{tail}')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
