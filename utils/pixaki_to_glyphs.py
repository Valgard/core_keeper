"""Extract the thinTiny full-build atlas + advance widths from a Pixaki master.

Reads the master's `Atlas` layer (the glyph pixels) and `Rects` layer (the
magenta advance boxes), writes the atlas PNG, prints one advance width per
atlas cell as a 384-character string of digits, and (optionally) generates a
kerning matrix from the same glyph ink -- see `kerning_pair()` for the rule.

Cell layout: 32 columns x 12 rows of 8x12 cells on a 257x144 canvas. The cell
index equals the charset position AND the PugFont.glyphData index -- CK's
`latinCharset` is exactly 384 characters long, one per cell. Every rect box in
the master sits at y=0 with height 10 and x-offset 0 (verified in
complete-tiny-font/sources/thinTiny-review.md), so only the width varies;
`validate()` fails loud if that ever stops holding.

Run it through `uv run`, which resolves the Pillow pinned in the repo's
`pyproject.toml`. The pin is not cosmetic: PNG bytes are encoder-dependent, and
byte-identity against the committed atlas is how a regeneration is checked, so
an unpinned Pillow makes "the file changed" and "my encoder differs"
indistinguishable. `test_shipped_artifacts.py` fails if the running Pillow is
not the pinned one.

Usage:
    uv run utils/pixaki_to_glyphs.py --pixaki <master.pixaki> --sheet <out.png>
    uv run utils/pixaki_to_glyphs.py --pixaki <master.pixaki> --kerning <out.bytes>
    uv run utils/pixaki_to_glyphs.py --pixaki <master.pixaki> --check-only
"""

import argparse
import json
import sys

from PIL import Image
from pixaki_container import open_pixaki

CDX, CDY = 8, 12  # cell size (thinSmall grid)
COLS, ROWS = 32, 12
CELLS = COLS * ROWS  # 384 == len(PugFont.latinCharset)
# The +1 column exists solely for PugFont.InitCodePoints' outline-padding check.
ATLAS_W = COLS * CDX + 1
BOX_Y, BOX_H = 0, 10  # the rect box inside every cell (thinTiny metric)
# BOX_Y was 1 until 2026-08-12: PugFont.InitCodePoints derives every glyph
# sprite from (y+1, h-1), discarding the box's bottom row. At y=1 that row
# sat inside the drawn glyph, so every glyph rendered a pixel low and 15
# diacritics lost their bottom row. The master was shifted up by one row so
# CK's discarded row falls outside the drawn glyph.


def layer_full(container, sprite, cels, name):
    """Composite one named layer onto a full-canvas RGBA image.

    Exits with the layer names the master actually has if `name` is not among
    them: renaming a layer in Pixaki is the likeliest way to break this tool,
    and it is worth saying so in one line rather than through a traceback.
    """
    w, h = sprite["size"]
    layer = next((l for l in sprite["layers"] if l.get("name") == name), None)
    if layer is None:
        have = ", ".join(repr(l.get("name")) for l in sprite["layers"]) or "none"
        sys.exit(f"the master has no layer named {name!r} (its layers: {have})")
    cel = cels[layer["clips"][0]["itemIdentifier"]]
    (fx, fy), _ = cel["frame"]
    full = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    drawing = Image.open(container.open(f"images/drawings/{cel['identifier']}.png"))
    full.alpha_composite(drawing.convert("RGBA"), (fx, fy))
    return full


def load_layers(pixaki_path):
    """Return (rects_img, atlas_img) from a .pixaki in either packaging.

    The exported ZIP and the native directory package are both accepted; see
    pixaki_container. Both layers are composited before the container closes,
    so the returned images own their pixels and never read it again.
    """
    with open_pixaki(pixaki_path) as container:
        doc = json.load(container.open("document.json"))
        sprite = doc["sprites"][0]
        cels = {c["identifier"]: c for c in sprite["cels"]}
        rects = layer_full(container, sprite, cels, "Rects")
        atlas = layer_full(container, sprite, cels, "Atlas")
    return rects, atlas


def cell_box(index):
    """Top-left pixel box of a cell: (x, y_top, w, h)."""
    return ((index % COLS) * CDX, (index // COLS) * CDY, CDX, CDY)


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
    """A loose per-channel threshold for the Rects layer's magenta (Pixaki
    paints it RGB 229, 59, 223) -- not an exact match, to tolerate
    anti-aliased edges."""
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


def ink_edges(atlas_img, index, advance_width):
    """Per-row leftmost/rightmost ink column of one glyph, in cell coordinates.

    Two length-BOX_H lists (`left`, `right`); an entry is None for a row with
    no ink. Only columns 0..advance_width-1 and rows BOX_Y..BOX_Y+BOX_H-1 are
    read. That clip is belt-and-braces, not load-bearing: validate() rejects
    any glyph with ink outside its advance box, so a master that passes the
    gate has nothing here to clip. It stays because clipping silently is the
    wrong failure mode for this function -- rejecting is validate()'s job, and
    quietly measuring a truncated glyph is what shipped a collision once.
    """
    x0, y0, _, _ = cell_box(index)
    px = atlas_img.load()
    left = [None] * BOX_H
    right = [None] * BOX_H
    for row in range(BOX_H):
        y = y0 + BOX_Y + row
        for col in range(advance_width):
            if _is_opaque(px[x0 + col, y]):
                if left[row] is None:
                    left[row] = col
                right[row] = col
    return left, right


KERNING_CLAMP = 2  # settled 2026-08-12 -- see kerning_pair()'s docstring


def kerning_pair(right_a, left_b, advance_a):
    """The kerning correction for glyph `a` immediately followed by `b`.

    For every row where BOTH glyphs have ink, the gap is how far `b`'s ink
    would sit from the end of `a`'s advance if kerning were zero: the empty
    columns after `a`'s ink, plus the empty columns before `b`'s ink. The
    kerning is one less than the smallest such gap across those rows, clamped
    to [0, KERNING_CLAMP]. A pair with no row where both have ink (e.g. an
    underscore and an acute accent) defaults to KERNING_CLAMP rather than
    going through that subtraction -- they never touch, so nothing measured
    limits them.

    The "one less" is deliberate, not a rounding nicety: a rule that closes
    the tightest gap completely (no subtraction) reproduces 97.66% of
    vanilla's own thinTiny kerning table, but vanilla's numbers describe
    vanilla's glyph shapes, and those differ from this build's in both
    directions -- vanilla's digits are a row taller (6px vs. 5px here),
    while several of its letters are narrower: `C E F L` sit in advance 2
    against 3 here, `M`/`m` in 3 against 5. Of the 114 characters vanilla
    carries, 25 have a different advance here, every one of them wider.
    Applied to these shapes, closing the last column made stems collide in
    game (`l` immediately followed by `t`, both advance 2, tightest row 1
    column of air -- closed to 0, the stems touched in
    "Seltenheit"/"Entdeckt"). This variant reproduces only ~84% of vanilla's
    table -- agreement with vanilla is deliberately no longer the criterion.
    Collision-freedom on our own shapes is, and that's what leaving one
    column of air buys: the tightest legal gap before subtraction is 1, so
    it can go to 0 but never below it, regardless of the clamp's upper
    bound.

    KERNING_CLAMP = 3 was tried and rejected after an in-game look: raising
    it only changes low-ink punctuation/symbol pairs (1,071 of them in this
    atlas), never letters or digits, so the difference was invisible in
    ordinary text and not worth trading away the settled variant's stronger
    footing (measured against real gameplay text, not just vanilla's table).
    Settled back at 2.
    """
    gaps = [
        (advance_a - 1 - right_a[y]) + left_b[y]
        for y in range(BOX_H)
        if right_a[y] is not None and left_b[y] is not None
    ]
    if not gaps:
        return KERNING_CLAMP
    return max(0, min(min(gaps) - 1, KERNING_CLAMP))


def kerning_matrix(atlas_img, ws, cell_count=CELLS):
    """Dense cell_count x cell_count byte matrix, row-major by cell index.

    Byte [a * cell_count + b] is `kerning_pair` for "a followed by b". Rows
    and columns of unpainted cells (ws[i] == 0) stay zero.
    """
    edges = {i: ink_edges(atlas_img, i, w) for i, w in enumerate(ws) if w}
    matrix = bytearray(cell_count * cell_count)
    for a, (_, right_a) in edges.items():
        for b, (left_b, _) in edges.items():
            matrix[a * cell_count + b] = kerning_pair(right_a, left_b, ws[a])
    return bytes(matrix)


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
        dx, dy, _, h = rb
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
        if gb is None:
            if not had_geometry_issue:
                problems.append(f"cell {i}: rect box but no glyph pixels")
            continue
        # Ink containment. Both bounds mirror exactly what ink_edges() reads --
        # columns 0..advance-1 and rows BOX_Y..BOX_Y+BOX_H-1 -- because ink
        # outside them is silently clipped there, so the pair's kerning would be
        # computed from a truncated glyph and could overlap its neighbour in
        # game. That is the collision class the kerning margin exists to
        # prevent, which makes it this gate's job to catch.
        gx, gy, gw, gh = gb
        advance = rb[2]
        # CK widens every sprite rect by 2 px for its outline, but only when
        # `rect2.width + rect2.x + 2 < texture.width`; otherwise it takes the
        # else branch and logs "You need to make the font texture 1 pixel
        # wider" once per glyph, every launch, and that glyph renders without
        # its padding. Only the last column can run out of room (x = 248 on a
        # 257 px canvas leaves advance <= 6); every earlier column has slack no
        # 8 px cell can use up.
        x0, _, _, _ = cell_box(i)
        if x0 + advance + 2 >= ATLAS_W:
            problems.append(
                f"cell {i}: advance {advance} at x={x0} leaves no room for the "
                f"outline padding CK adds (needs x + advance + 2 < {ATLAS_W})"
            )
        if gx + gw > advance:
            problems.append(
                f"cell {i}: glyph ink reaches column {gx + gw - 1}, "
                f"outside its advance width {advance}"
            )
        if gy < BOX_Y or gy + gh > BOX_Y + BOX_H:
            problems.append(
                f"cell {i}: glyph ink spans rows {gy}..{gy + gh - 1}, "
                f"outside the rect box rows {BOX_Y}..{BOX_Y + BOX_H - 1}"
            )
    return problems


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pixaki", required=True, help="path to the .pixaki master")
    ap.add_argument("--sheet", help="write the Atlas layer here as PNG")
    ap.add_argument(
        "--kerning", help="write the CELLS x CELLS kerning matrix here as raw bytes"
    )
    ap.add_argument(
        "--check-only",
        action="store_true",
        help="only run the invariant checks, write nothing (excludes the two above)",
    )
    ns = ap.parse_args(argv)
    if ns.check_only and (ns.sheet or ns.kerning):
        # It used to accept the combination, write neither file and print OK --
        # which reads exactly like a successful regeneration. Nobody would
        # notice until the stale artifacts shipped.
        ap.error("--check-only writes nothing; drop it, or drop --sheet/--kerning")

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
    # Belt-and-braces: `_bbox` only scans CDX columns per cell, so a width
    # cannot exceed 8 today. Checked here rather than after the writes, so it
    # can still honour the "refusing to emit" contract above if CDX ever grows.
    if max(w) > 9:
        sys.exit(
            f"an advance width exceeds 9 ({max(w)}) — the digit string cannot hold it"
        )
    if ns.check_only:
        print(f"OK — {painted} painted cells, all invariants hold")
        return 0

    if ns.sheet:
        atlas.save(ns.sheet)
        print(f"// wrote {ns.sheet} ({atlas.width}x{atlas.height}), {painted} cells")
    if ns.kerning:
        matrix = kerning_matrix(atlas, w)
        with open(ns.kerning, "wb") as f:
            f.write(matrix)
        nonzero = sum(1 for b in matrix if b)
        print(f"// wrote {ns.kerning} ({len(matrix)} bytes), {nonzero} non-zero pairs")
    print("// paste into ThinTinyFontPatch.cs Widths")
    print("        private const string Widths =")
    # Leading `+`, not trailing: CSharpier moves binary operators to the start
    # of the continuation line, so trailing ones made every regeneration pass
    # through a reformat -- one hand-touch too many on a string where a single
    # lost digit shifts every later cell's advance and kerning row silently.
    # This shape is what the formatter would produce, so the paste is the last
    # step. `test_shipped_artifacts.py` holds it to that.
    for row in range(ROWS):
        chunk = "".join(str(x) for x in w[row * COLS : (row + 1) * COLS])
        operator = "" if row == 0 else "+ "
        tail = ";" if row == ROWS - 1 else ""
        print(f'            {operator}"{chunk}"{tail}')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
