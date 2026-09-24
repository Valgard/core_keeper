"""Unit tests for deriving a Workshop-legal preview image.

Steam rejects an oversized preview outright, and every logo in this family is a
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
    """A stand-in logo with nothing for a size assertion to trip over.

    A single solid colour, which PNG compresses to a few hundred bytes at
    any resolution. Only fit for a test that needs a *valid small image*,
    not a hard-to-compress one -- see `_incompressible_logo` for that.
    """
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


def _band_logo(tmp_path, seed=20260826):
    """A logo whose full-resolution PNG lands *between* the two readings of "1 MB".

    Measured: 1,017,794 bytes -- 17,794 over the decimal 1,000,000 and 30,782
    under the binary 1,048,576. That gap is the whole point: an image in it is
    accepted at full resolution under one definition and stepped down under the
    other, so a test against it can tell which limit is actually in force. Three
    of this family's real logos sit in exactly this band (item-checklist,
    refill-ore-boulders, reusable-cattle-box, measured 2026-08-27), so it is the
    band a publish really lands in, not a contrived one.

    512² is deliberate: it is a LADDER rung, so it is tried unresized and its
    size is the one measured above. The extra bytes over plain RGB noise come
    from randomising alpha over the top three quarters -- a fourth noise channel
    -- because RGB noise alone tops out at 917,883 bytes here, below the band.
    """
    side, opaque_from = 512, 384
    px = bytearray(random.Random(seed).randbytes(side * side * 4))
    px[opaque_from * side * 4 + 3 :: 4] = b"\xff" * (side * (side - opaque_from))
    path = tmp_path / "logo.png"
    Image.frombytes("RGBA", (side, side), bytes(px)).save(path)
    return path


def test_the_limit_is_the_decimal_megabyte_not_the_binary_one(tmp_path):
    """Valve documents "roughly one megabyte" and never says which reading is meant.

    This fixture is sized to fall between the two, so accepting it at full
    resolution is the binary reading and stepping down is the decimal one --
    and only the decimal one is safe, because the cost of guessing wrong is
    paid after the Workshop item has already been created.
    """
    src = _band_logo(tmp_path)
    dest = tmp_path / "preview.png"

    size, how = steam_preview.derive_preview(src, dest)

    assert size <= 1_000_000, f"{size:,} bytes would fail a decimal-MB limit"
    assert "512" not in how, "must not have been accepted at full resolution"


def test_the_ladder_yields_the_largest_rung_that_fits(tmp_path):
    """`derive_preview` promises the *largest* preview that fits, not merely one that fits.

    The only thing enforcing that is LADDER descending. Reversing it still
    returns something that fits -- the smallest rung fits trivially -- so a
    test that only asserts "fits" cannot see the difference. This one names
    the rung above the chosen one and shows it does not fit, which is what
    "largest" means.
    """
    src = _incompressible_logo(tmp_path)
    dest = tmp_path / "preview.png"

    _, how = steam_preview.derive_preview(src, dest)

    chosen = int(how.split("²")[0])
    bigger = [rung for rung in steam_preview.LADDER if rung > chosen]
    assert bigger, "fixture must not be answered at the top rung, or nothing is proven"
    next_up = min(bigger)
    original = Image.open(src).convert("RGBA")
    probe = tmp_path / "probe.png"
    original.resize((next_up, next_up), Image.LANCZOS).save(probe, optimize=True, compress_level=9)
    assert probe.stat().st_size > steam_preview.LIMIT, (
        f"{next_up}² also fits, so {chosen}² was not the largest that does"
    )


def test_a_small_image_is_taken_at_full_resolution(tmp_path):
    """A logo smaller than the ladder's top rung is used at its own resolution.

    It must not be upscaled to 1024² first.

    Pins the exact rung chosen (64², the source's own side) rather than only
    excluding 1024²: `_flat_logo` compresses to a few hundred bytes at EVERY
    resolution, so the size assertion alone cannot tell 64² apart from any
    other sub-1024 rung. A `_targets` defect that picked some other ladder
    rung below 1024 — 512², say, instead of falling back to the source's own
    size when none of the ladder's fixed rungs are small enough — would still
    satisfy "1024 not in how" and go unnoticed.
    """
    src = _flat_logo(tmp_path, side=64)
    dest = tmp_path / "preview.png"

    size, how = steam_preview.derive_preview(src, dest)

    assert dest.is_file()
    assert how == "64² lossless"
    assert size < steam_preview.LIMIT


def test_it_steps_down_until_the_result_fits(tmp_path):
    """The default limit can only be met once the ladder actually comes down in resolution.

    1024² lossless is 3,658,908 bytes for this fixture (measured) -- well
    over the default limit under either reading of "1 MB" -- so it is not
    met by accepting the first candidate tried.
    """
    src = _incompressible_logo(tmp_path)
    dest = tmp_path / "preview.png"

    size, how = steam_preview.derive_preview(src, dest)

    assert size <= steam_preview.LIMIT
    assert "lossless" in how
    reported_side = int(how.split("²")[0])
    assert reported_side < 1024, (
        "must have actually stepped down, not merely fit at full resolution"
    )


def test_transparency_survives(tmp_path):
    """The alpha channel survives resizing and re-encoding.

    The Workshop item page composites the preview onto its own
    background, so a flattened, opaque result would not be composited
    correctly.
    """
    img = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    img.paste(Image.new("RGBA", (64, 64), (255, 200, 0, 255)), (96, 96))
    src = tmp_path / "logo.png"
    img.save(src)
    dest = tmp_path / "preview.png"

    steam_preview.derive_preview(src, dest)

    assert Image.open(dest).convert("RGBA").getpixel((0, 0))[3] == 0


def test_quantisation_is_the_last_resort_not_the_first(tmp_path):
    """A larger quantised rung would also clear the limit, but the lossless loop still wins.

    At limit=400,000, 640² quantised is 399,169 bytes (measured) -- it
    would also clear this limit, at four times the pixel count of the
    256² lossless result. The only way lossless still wins is that the
    lossless loop runs through the whole ladder before the quantised loop
    is even entered, which is exactly the preference this test exists to
    prove.
    """
    src = _incompressible_logo(tmp_path)
    dest = tmp_path / "preview.png"

    _, how = steam_preview.derive_preview(src, dest, limit=400_000)

    assert "lossless" in how
    assert "quantised" not in how, "a lossless smaller size must be preferred"


def test_the_quantised_path_can_succeed(tmp_path):
    """No lossless rung fits under 100,000 bytes, but quantised 256² does.

    Even the smallest lossless rung, 256², is 180,054 bytes (measured),
    while quantised 256² is 45,429 bytes. This is the one test in the
    suite that takes a *successful* return out of the quantised branch;
    the impossible-limit test below only ever watches it fail on every
    rung.
    """
    src = _incompressible_logo(tmp_path)
    dest = tmp_path / "preview.png"

    size, how = steam_preview.derive_preview(src, dest, limit=100_000)

    assert size <= 100_000
    assert "quantised" in how


def test_an_impossible_limit_is_reported_rather_than_silently_shipped(tmp_path):
    """A limit no rung can meet, lossless or quantised, raises ValueError.

    The alternative would be shipping an over-limit preview that Steam
    rejects only after the Workshop item already exists.
    """
    src = _incompressible_logo(tmp_path)
    dest = tmp_path / "preview.png"

    with pytest.raises(ValueError, match=r"1 MB|fit|limit"):
        steam_preview.derive_preview(src, dest, limit=200)
