"""Unit tests for deriving a Workshop-legal preview image.

Steam rejects a preview above 1 MB outright, and every logo in this family is a
1024² PNG with a soft golden glow — the one thing PNG compresses badly. The
ladder therefore matters more than any single size: it must come down in
resolution before it gives up colour depth, because the Workshop renders
previews at roughly 268² while banding in a gradient stays visible at any size.
"""

import random

import pytest
import steam_preview
from PIL import Image


def _flat_logo(tmp_path, side=1024):
    """A stand-in logo with nothing for a size assertion to trip over: a single
    solid colour, which PNG compresses to a few hundred bytes at any
    resolution. Only fit for a test that needs a *valid small image*, not a
    hard-to-compress one -- see `_incompressible_logo` for that."""
    img = Image.new("RGBA", (side, side), (10, 80, 90, 255))
    path = tmp_path / "logo.png"
    img.save(path)
    return path


def _incompressible_logo(tmp_path, side=1024, seed=20260826):
    """A stand-in for a mod logo that actually resists PNG compression.

    An earlier version of this fixture built a deterministic pattern --
    `(x*7)%256, (y*11)%256, ...` -- and called it "noisy". It is not: the
    pattern repeats every few dozen pixels, and PNG's row filters find that
    structure immediately. Measured, it compressed to 5,725 bytes at 1024² and
    4,192 bytes at 256² -- so far under any limit the tests used that every
    ladder rung already fit, and the tests built on it "proved" stepping and
    quantisation without either loop ever running past its first iteration.

    Per-pixel randomness from a seeded PRNG has no structure to exploit.
    Measured on this fixture: 3,658,908 bytes lossless at 1024², dropping to
    819,987 at 512² and 180,054 at 256² -- genuinely too large at the top of
    the ladder and genuinely smaller further down, so a test against it can
    tell "stepped down" from "didn't need to." The fixed seed keeps the PNG
    output reproducible run to run.
    """
    raw = random.Random(seed).randbytes(side * side * 3)
    img = Image.frombytes("RGB", (side, side), raw).convert("RGBA")
    path = tmp_path / "logo.png"
    img.save(path)
    return path


def test_a_small_image_is_taken_at_full_resolution(tmp_path):
    src = _flat_logo(tmp_path, side=64)
    dest = tmp_path / "preview.png"

    size, how = steam_preview.derive_preview(src, dest)

    assert dest.is_file()
    assert "1024" not in how  # not upscaled
    assert size < 1_048_576


def test_it_steps_down_until_the_result_fits(tmp_path):
    """1024² lossless is 3,658,908 bytes for this fixture (measured) -- well
    over the default 1 MB limit -- so the default limit can only be met after
    the ladder has actually come down in resolution, not by accepting the
    first candidate tried."""
    src = _incompressible_logo(tmp_path)
    dest = tmp_path / "preview.png"

    size, how = steam_preview.derive_preview(src, dest)

    assert size <= 1_048_576
    assert "lossless" in how
    reported_side = int(how.split("²")[0])
    assert reported_side < 1024, (
        "must have actually stepped down, not merely fit at full resolution"
    )


def test_transparency_survives(tmp_path):
    img = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    img.paste(Image.new("RGBA", (64, 64), (255, 200, 0, 255)), (96, 96))
    src = tmp_path / "logo.png"
    img.save(src)
    dest = tmp_path / "preview.png"

    steam_preview.derive_preview(src, dest)

    assert Image.open(dest).convert("RGBA").getpixel((0, 0))[3] == 0


def test_quantisation_is_the_last_resort_not_the_first(tmp_path):
    """At limit=400,000, 640² quantised is 399,169 bytes (measured) -- it would
    also clear this limit, at four times the pixel count of the 256² lossless
    result. The only way lossless still wins is that the lossless loop runs
    through the whole ladder before the quantised loop is even entered, which
    is exactly the preference this test exists to prove."""
    src = _incompressible_logo(tmp_path)
    dest = tmp_path / "preview.png"

    _, how = steam_preview.derive_preview(src, dest, limit=400_000)

    assert "lossless" in how
    assert "quantised" not in how, "a lossless smaller size must be preferred"


def test_the_quantised_path_can_succeed(tmp_path):
    """No lossless rung fits under 100,000 bytes -- even the smallest, 256², is
    180,054 bytes (measured) -- but quantised 256² is 45,429 bytes. This is the
    one test in the suite that takes a *successful* return out of the
    quantised branch; the impossible-limit test below only ever watches it
    fail on every rung."""
    src = _incompressible_logo(tmp_path)
    dest = tmp_path / "preview.png"

    size, how = steam_preview.derive_preview(src, dest, limit=100_000)

    assert size <= 100_000
    assert "quantised" in how


def test_an_impossible_limit_is_reported_rather_than_silently_shipped(tmp_path):
    src = _incompressible_logo(tmp_path)
    dest = tmp_path / "preview.png"

    with pytest.raises(ValueError, match="1 MB|fit|limit"):
        steam_preview.derive_preview(src, dest, limit=200)
