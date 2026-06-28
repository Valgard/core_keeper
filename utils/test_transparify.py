"""Unit tests for transparify.py — white/black difference matting."""
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
    # F visible identically on both backgrounds => alpha 255, colour = F.
    out = t.difference_matte(_solid((200, 100, 50)), _solid((200, 100, 50)))
    _close(out.getpixel((0, 0)), (200, 100, 50, 255))


def test_fully_transparent_pixel():
    # white-on-white, black-on-black => alpha 0.
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


def test_output_is_rgba_same_size():
    out = t.difference_matte(_solid((10, 20, 30), (5, 7)), _solid((1, 2, 3), (5, 7)))
    assert out.mode == "RGBA"
    assert out.size == (5, 7)


def test_size_mismatch_raises():
    with pytest.raises(ValueError):
        t.difference_matte(_solid((0, 0, 0), (2, 2)), _solid((0, 0, 0), (3, 3)))
