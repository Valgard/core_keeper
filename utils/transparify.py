#!/usr/bin/env python3
"""Recover a transparent PNG from a white-background and a black-background
render of the same image (difference matting) — a local, scriptable
transparify.app equivalent (transparify.app has no API; it runs the same math
client-side in the browser).

The same subject is rendered once on pure white and once on pure black; the
per-pixel alpha and true (un-premultiplied) colour are recovered by comparing
them. Unlike single-image background removal, this preserves glows, halos and
soft edges — which is why the Core Keeper mod logos are generated as a
white/black pair (see the logo workflow in ../CLAUDE.md).

Math, per pixel and channel (0..255), with W = white render, B = black render:

    W = F*a + (1 - a)*255      (white background = 255)
    B = F*a                    (black background = 0)
  => 1 - a = (W - B) / 255  ->  a = 1 - (W - B)/255    (averaged over channels)
     F     = B / a                                     (straight, un-premultiplied)

Usage:
    transparify.py --white "logo 3 - white background.jpeg" \\
                   --black "logo 3 - black background.jpeg" \\
                   --out   "logo 3.png"
"""
import argparse

from PIL import Image, ImageMath


def difference_matte(white: Image.Image, black: Image.Image) -> Image.Image:
    """Recover an RGBA image from a white-bg and black-bg render of the same
    subject. Alpha is the channel-averaged ``1 - (W - B)`` (robust to AI/JPEG
    noise); colour is un-premultiplied (``B / a``) so the result composites
    correctly on any background. Raises ValueError on a size mismatch."""
    white = white.convert("RGB")
    black = black.convert("RGB")
    if white.size != black.size:
        raise ValueError(
            f"white {white.size} and black {black.size} differ in size")

    rw, gw, bw = white.split()
    rb, gb, bb = black.split()

    # alpha = 255 - mean_over_channels(max(W - B, 0)). NB: an ImageMath operand
    # must be the FIRST argument to max()/min(); scalars come second.
    alpha = ImageMath.unsafe_eval(
        "convert(255 - (max(float(rw)-float(rb), 0) + max(float(gw)-float(gb), 0)"
        " + max(float(bw)-float(bb), 0)) / 3, 'L')",
        rw=rw, rb=rb, gw=gw, gb=gb, bw=bw, bb=bb)

    def unpremultiply(channel: Image.Image) -> Image.Image:
        # F_c = B_c / a, clamped to [0, 255]; a floored at 1 to avoid /0.
        return ImageMath.unsafe_eval(
            "convert(min(float(c)*255 / max(float(a), 1), 255), 'L')",
            c=channel, a=alpha)

    return Image.merge(
        "RGBA",
        (unpremultiply(rb), unpremultiply(gb), unpremultiply(bb), alpha))


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Recover a transparent PNG from a white/black render pair "
                    "(local transparify.app equivalent).")
    ap.add_argument("--white", "-w", required=True,
                    help="path to the render on a pure WHITE background")
    ap.add_argument("--black", "-b", required=True,
                    help="path to the render on a pure BLACK background")
    ap.add_argument("--out", "-o", required=True,
                    help="output transparent PNG path")
    args = ap.parse_args()

    with Image.open(args.white) as white, Image.open(args.black) as black:
        out = difference_matte(white, black)
    out.save(args.out)
    print(f"wrote {args.out}  ({out.width}x{out.height} RGBA)")


if __name__ == "__main__":
    main()
