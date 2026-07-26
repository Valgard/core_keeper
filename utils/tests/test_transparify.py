"""Unit tests for transparify.py — a faithful port of transparify.app's
white/black difference matting (Euclidean-distance alpha + un-premultiply)."""

import pytest
from PIL import Image

import transparify as t


def _solid(rgb, size=(2, 2)):
    return Image.new("RGB", size, rgb)


def _close(actual, expected, tol=2):
    assert len(actual) == len(expected)
    for a, e in zip(actual, expected):
        assert abs(a - e) <= tol, f"{actual} vs {expected}"


def test_opaque_pixel_keeps_colour_at_full_alpha():
    # Identical on both backgrounds => distance 0 => alpha 255, colour = F.
    out = t.difference_matte(_solid((200, 100, 50)), _solid((200, 100, 50)))
    _close(out.getpixel((0, 0)), (200, 100, 50, 255))


def test_fully_transparent_pixel():
    # white-on-white, black-on-black => max distance => alpha 0.
    out = t.difference_matte(_solid((255, 255, 255)), _solid((0, 0, 0)))
    _close(out.getpixel((0, 0)), (0, 0, 0, 0))


def test_semi_transparent_colour_is_unpremultiplied():
    # F=(200,100,50), a=0.5: black=F*a=(100,50,25), white=F*a+(1-a)*255.
    out = t.difference_matte(_solid((228, 178, 153)), _solid((100, 50, 25)))
    _close(out.getpixel((0, 0)), (200, 100, 50, 127), tol=3)


def test_white_glow_recovers_partial_alpha():
    # A pure-white glow at a=0.4: black=0.4*255=102, white stays 255.
    out = t.difference_matte(_solid((255, 255, 255)), _solid((102, 102, 102)))
    _close(out.getpixel((0, 0)), (255, 255, 255, 102), tol=2)


def test_below_threshold_zeroes_colour():
    # W=(255,255,255), B=(2,2,2) => a ~ 0.008 < 0.01: colour forced to 0,
    # alpha kept (round(255*a) ~ 2) — matches transparify's u>0.01 colour gate.
    out = t.difference_matte(_solid((255, 255, 255)), _solid((2, 2, 2))).getpixel(
        (0, 0)
    )
    assert out[:3] == (0, 0, 0)
    assert out[3] <= 3


def test_output_is_rgba_same_size():
    out = t.difference_matte(_solid((10, 20, 30), (5, 7)), _solid((1, 2, 3), (5, 7)))
    assert out.mode == "RGBA"
    assert out.size == (5, 7)


def test_size_mismatch_raises():
    with pytest.raises(ValueError):
        t.difference_matte(_solid((0, 0, 0), (2, 2)), _solid((0, 0, 0), (3, 3)))
