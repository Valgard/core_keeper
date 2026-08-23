"""Print what a .pixaki holds: its visible layers, their palettes and pixels.

Reads a Pixaki master the way `pixaki_to_sheet` does -- same loader, same layer
walk, so what this prints is what the sheet generator would pack -- and renders
each layer as a character grid with a colour legend beside it.

Why a grid and not the PNG: the sprites in this repo are 4x4 to 16x16, which is
too small to judge on screen, and the questions asked of them are positional
("is the core centred", "which pixel carries the rounding"). A grid answers
those by counting, survives a paste into a commit message or a chat, and diffs.

Three checks ride along, each from a bug that actually shipped:

- **Opaque corners.** CK's own player marker fakes its rounded corner by
  painting the map's background blue into the corner pixels. Correct on the
  map, a blue speck anywhere else -- so a sprite meant for the HUD wants its
  corners transparent, and this says which ones are not.
- **Semi-transparent pixels.** CK's UI sprites are point-filtered, so alpha
  between 0 and 255 is never smoothed into a soft edge; it just reads as dirt.
  Their presence usually means a brush with a soft edge was used by accident.
- **Ink bounds.** The drawn extent inside the layer's canvas. A layer whose ink
  sits off-centre or leaves a margin packs differently than it looks, and the
  margin is invisible in Pixaki itself.

Usage:
    uv run utils/pixaki_inspect.py <file.pixaki>
    uv run utils/pixaki_inspect.py <file.pixaki> --layer "Player"
    uv run utils/pixaki_inspect.py <file.pixaki> --list
"""

import argparse
import string
import sys
from collections import Counter

from pixaki_to_sheet import collect_layers, load_pixaki, normalize

# One character per distinct colour, most frequent first, so the dominant shape
# reads as 'A' without consulting the legend. Digits extend the alphabet far
# past any pixel-art palette; what overflows is named rather than silently
# folded together, because two colours sharing a symbol turns the grid from
# terse into wrong.
SYMBOLS = string.ascii_uppercase + string.digits
OVERFLOW = "?"
TRANSPARENT = "."


def palette_of(img):
    """Return a Counter of the layer's fully or partly opaque pixels."""
    px = img.load()
    return Counter(
        px[x, y]
        for y in range(img.height)
        for x in range(img.width)
        # Alpha alone decides: a fully erased pixel keeps whatever RGB the
        # brush left behind, so (255, 255, 255, 0) and (0, 0, 0, 0) are the
        # same nothing and must not enter the palette as two colours.
        if px[x, y][3] != 0
    )


def symbol_map(palette):
    """Map each colour to its grid character, most frequent colour first."""
    ordered = sorted(palette, key=lambda c: (-palette[c], c))
    return {
        c: (SYMBOLS[i] if i < len(SYMBOLS) else OVERFLOW) for i, c in enumerate(ordered)
    }


def grid_rows(img, symbols):
    """Render the layer as one string per pixel row, space-separated."""
    px = img.load()
    return [
        " ".join(
            TRANSPARENT if px[x, y][3] == 0 else symbols.get(px[x, y], OVERFLOW)
            for x in range(img.width)
        )
        for y in range(img.height)
    ]


def ink_bounds(img):
    """Return (left, top, right, bottom) of the drawn pixels, or None if empty.

    Deliberately not `Image.getbbox()`: that one treats any non-zero channel as
    ink, so a fully transparent pixel carrying leftover RGB would widen the box
    -- the very case `palette_of` excludes."""
    px = img.load()
    drawn = [
        (x, y) for y in range(img.height) for x in range(img.width) if px[x, y][3] != 0
    ]
    if not drawn:
        return None
    xs = [p[0] for p in drawn]
    ys = [p[1] for p in drawn]
    return min(xs), min(ys), max(xs), max(ys)


def opaque_corners(img):
    """Return the corner coordinates that are not transparent."""
    px = img.load()
    corners = (
        (0, 0),
        (img.width - 1, 0),
        (0, img.height - 1),
        (img.width - 1, img.height - 1),
    )
    return [c for c in corners if px[c][3] != 0]


def describe(name, img):
    """Return the full report for one layer as a list of lines."""
    palette = palette_of(img)
    symbols = symbol_map(palette)
    total = img.width * img.height
    opaque = sum(palette.values())
    semi = sum(n for c, n in palette.items() if c[3] < 255)

    lines = [f"=== {name!r} — {img.width}x{img.height} ==="]
    lines.append("")
    lines.append("Palette (by frequency):")
    for colour in sorted(palette, key=lambda c: (-palette[c], c)):
        r, g, b, a = colour
        lines.append(
            f"  {symbols[colour]}  #{r:02X}{g:02X}{b:02X}  alpha {a:3d}  {palette[colour]:4d} px"
        )
    overflowed = sum(1 for s in symbols.values() if s == OVERFLOW)
    if overflowed:
        lines.append(f"  {OVERFLOW}  shared by {overflowed} further colours")
    lines.append(f"  transparent: {total - opaque} px")
    lines.append(f"  semi-transparent (0 < alpha < 255): {semi} px")

    lines.append("")
    lines.append("Grid:")
    lines.extend("  " + row for row in grid_rows(img, symbols))

    lines.append("")
    bounds = ink_bounds(img)
    if bounds is None:
        lines.append("  ink bounds: none — the layer is empty")
    else:
        left, top, right, bottom = bounds
        lines.append(
            f"  ink bounds: x {left}..{right}, y {top}..{bottom} "
            f"({right - left + 1}x{bottom - top + 1} of {img.width}x{img.height})"
        )
    corners = opaque_corners(img)
    lines.append(f"  opaque corners: {corners if corners else 'none — clean'}")
    return lines


def report(path, want=None, names_only=False):
    """Return the report for `path` as a list of lines.

    `want` limits the output to one layer by name; an unmatched name is an
    error naming what is there, since a silent empty report reads exactly like
    a layer that is empty."""
    doc, drawings = load_pixaki(path)
    # No excludes: the sheet generator drops top-level groups a mod's sprite
    # config names, but an inspection that hid layers would answer a question
    # nobody asked -- what is in the file is the whole point.
    layers = collect_layers(doc, set())

    lines = [f"=== {len(layers)} visible layers ==="]
    lines.extend(f"  {lay.name!r:28s} {lay.w}x{lay.h}" for lay in layers)
    if names_only:
        return lines

    if want is not None and not any(lay.name == want for lay in layers):
        raise SystemExit(
            f"no visible layer named {want!r} in {path}; "
            f"present: {', '.join(repr(lay.name) for lay in layers)}"
        )

    for lay in layers:
        if want is not None and lay.name != want:
            continue
        lines.append("")
        lines.extend(describe(lay.name, normalize(lay, drawings)))
    return lines


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("pixaki", help="the .pixaki master, in either packaging")
    ap.add_argument("--layer", help="report only the layer with this exact name")
    ap.add_argument(
        "--list",
        action="store_true",
        dest="names_only",
        help="list the layers and stop",
    )
    args = ap.parse_args()
    print("\n".join(report(args.pixaki, args.layer, args.names_only)))


if __name__ == "__main__":
    sys.exit(main())
