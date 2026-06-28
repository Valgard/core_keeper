#!/usr/bin/env python3
"""Recover a transparent PNG from a white-background and a black-background
render of the same image — a faithful, scriptable port of transparify.app's
client-side algorithm (transparify.app has no API; it runs this same math in the
browser via the Canvas API).

The same subject is rendered once on pure white and once on pure black; the
per-pixel alpha and true (un-premultiplied) colour are recovered by comparing
them. Unlike single-image background removal, this preserves glows, halos and
soft edges — which is why the Core Keeper mod logos are generated as a
white/black pair (see the logo workflow in ../CLAUDE.md).

Algorithm (per pixel; ported 1:1 from transparify.app, W = white, B = black):

    dist = sqrt((Wr-Br)^2 + (Wg-Bg)^2 + (Wb-Bb)^2)     # white<->black distance
    a    = clamp(1 - dist / (255*sqrt(3)), 0, 1)        # 255*sqrt(3) = max dist
    if a > 0.01:  F = B / a   (per channel, clamped to 255)   # un-premultiply
    else:         F = 0
    out  = (F_r, F_g, F_b, round(255*a))

Rounding mirrors JavaScript's ``Math.round`` (half rounds up) so the output is
bit-for-bit equivalent to transparify.app for the same input pair.

Usage:
    transparify.py --white "logo 3 - white background.jpeg" \\
                   --black "logo 3 - black background.jpeg" \\
                   --out   "logo 3.png"
"""
import argparse
import math

from PIL import Image

# Maximum possible white<->black RGB distance: white (255,255,255) vs black
# (0,0,0) => sqrt(3 * 255^2) = sqrt(195075). transparify.app's Math.sqrt(195075).
_MAX_DIST = math.sqrt(3 * 255 * 255)


def _js_round(x: float) -> int:
    """JavaScript ``Math.round`` for x >= 0: nearest integer, half rounds up."""
    return math.floor(x + 0.5)


def difference_matte(
    white: Image.Image, black: Image.Image, threshold: float = 0.01
) -> Image.Image:
    """Recover an RGBA image from a white-bg and black-bg render of the same
    subject, exactly as transparify.app does: alpha is one minus the normalised
    Euclidean white<->black distance; colour is un-premultiplied (``B / a``) for
    ``a > threshold`` (else fully transparent), clamped to [0, 255]. Raises
    ValueError on a size mismatch."""
    white = white.convert("RGB")
    black = black.convert("RGB")
    if white.size != black.size:
        raise ValueError(
            f"white {white.size} and black {black.size} differ in size")

    wb = white.tobytes()
    kb = black.tobytes()
    out = bytearray(len(wb) // 3 * 4)
    j = 0
    for i in range(0, len(wb), 3):
        wr, wg, wbl = wb[i], wb[i + 1], wb[i + 2]
        br, bg, bbl = kb[i], kb[i + 1], kb[i + 2]
        dr, dg, db = wr - br, wg - bg, wbl - bbl
        a = 1.0 - math.sqrt(dr * dr + dg * dg + db * db) / _MAX_DIST
        a = 0.0 if a < 0.0 else 1.0 if a > 1.0 else a
        if a > threshold:
            inv = 1.0 / a
            out[j] = _js_round(min(255.0, br * inv))
            out[j + 1] = _js_round(min(255.0, bg * inv))
            out[j + 2] = _js_round(min(255.0, bbl * inv))
        # else: colour stays 0 (the bytearray is zero-initialised).
        out[j + 3] = _js_round(255.0 * a)
        j += 4

    return Image.frombytes("RGBA", white.size, bytes(out))


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Recover a transparent PNG from a white/black render pair "
                    "(a local, faithful port of transparify.app).")
    ap.add_argument("--white", "-w", required=True,
                    help="path to the render on a pure WHITE background")
    ap.add_argument("--black", "-b", required=True,
                    help="path to the render on a pure BLACK background")
    ap.add_argument("--out", "-o", required=True,
                    help="output transparent PNG path")
    ap.add_argument("--threshold", type=float, default=0.01,
                    help="below this alpha a pixel's colour is zeroed "
                         "(transparify.app uses 0.01)")
    args = ap.parse_args()

    with Image.open(args.white) as white, Image.open(args.black) as black:
        out = difference_matte(white, black, threshold=args.threshold)
    out.save(args.out)
    print(f"wrote {args.out}  ({out.width}x{out.height} RGBA)")


if __name__ == "__main__":
    main()
