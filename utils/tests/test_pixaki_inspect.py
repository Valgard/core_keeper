"""Unit tests for pixaki_inspect (the .pixaki layer report)."""

import io
import json

import pixaki_inspect as p
import pytest
from conftest import PIXAKI_DIRECTORIES
from conftest import PIXAKI_FORMS
from conftest import write_pixaki
from PIL import Image


def _img(pixels_rgba, w, h):
    im = Image.new("RGBA", (w, h))
    im.putdata(pixels_rgba)
    return im


def _png(img):
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


OPAQUE = (255, 255, 255, 255)
CLEAR = (0, 0, 0, 0)
# An erased pixel keeps whatever RGB the brush left behind. Pixaki writes these,
# and they are what separates "alpha decides" from "any non-zero channel is ink".
ERASED_WHITE = (255, 255, 255, 0)


def test_palette_ignores_alpha_zero_whatever_its_rgb():
    """palette_of() excludes every alpha-zero pixel regardless of its leftover RGB.

    An erased white pixel and an already-black transparent pixel must both
    be dropped, since alpha alone — not the RGB channels — decides what
    counts as ink.
    """
    img = _img([OPAQUE, ERASED_WHITE, CLEAR, (9, 9, 9, 0)], 2, 2)
    assert p.palette_of(img) == {OPAQUE: 1}


def test_palette_keeps_semi_transparent_pixels():
    """palette_of() keeps a semi-transparent pixel as its own colour rather than dropping it."""
    faint = (255, 255, 255, 128)
    palette = p.palette_of(_img([OPAQUE, faint, CLEAR, CLEAR], 2, 2))
    assert palette == {OPAQUE: 1, faint: 1}


def test_ink_bounds_ignores_erased_rgb():
    """ink_bounds() must not use Image.getbbox() semantics, which would call an erased corner ink.

    getbbox() treats any non-zero RGB channel as content, so the erased
    white corner would widen the box to the full 2x2; ink_bounds() must
    instead shrink to the one genuinely opaque pixel.
    """
    img = _img([CLEAR, ERASED_WHITE, CLEAR, OPAQUE], 2, 2)
    assert p.ink_bounds(img) == (1, 1, 1, 1)


def test_ink_bounds_of_empty_layer_is_none():
    """ink_bounds() returns None for an all-transparent layer, not a box spanning the canvas."""
    assert p.ink_bounds(_img([CLEAR] * 4, 2, 2)) is None


def test_symbol_map_gives_a_to_the_most_frequent_colour():
    """symbol_map() assigns 'A' by pixel frequency, not by the palette's insertion order."""
    red, green = (255, 0, 0, 255), (0, 255, 0, 255)
    symbols = p.symbol_map({red: 2, green: 7})
    assert symbols[green] == "A"
    assert symbols[red] == "B"


def test_symbol_map_is_stable_when_counts_tie():
    """symbol_map() breaks a frequency tie by colour value, so insertion order cannot change it."""
    a, b = (1, 1, 1, 255), (2, 2, 2, 255)
    first = p.symbol_map({a: 3, b: 3})
    second = p.symbol_map({b: 3, a: 3})
    assert first == second


def test_symbol_map_names_the_overflow_instead_of_folding_silently():
    """A colour past the 36-symbol alphabet gets '?', not a letter an earlier colour already used.

    One colour more than len(SYMBOLS) must produce exactly one '?' and as
    many distinct symbols as colours — silently folding the 37th colour
    onto an already-used letter would make two different colours
    indistinguishable in the grid.
    """
    palette = {(i, 0, 0, 255): 1 for i in range(len(p.SYMBOLS) + 1)}
    symbols = p.symbol_map(palette)
    assert sum(1 for s in symbols.values() if s == p.OVERFLOW) == 1
    assert len(set(symbols.values())) == len(p.SYMBOLS) + 1


def test_grid_marks_transparent_pixels_with_a_dot():
    """grid_rows() renders an alpha-zero pixel as '.' even when its colour is not in the symbol map.

    ERASED_WHITE has alpha 0 but is not a key in `{OPAQUE: "A"}`; it must
    still render as the transparent dot rather than falling through to the
    overflow marker.
    """
    img = _img([OPAQUE, CLEAR, ERASED_WHITE, OPAQUE], 2, 2)
    assert p.grid_rows(img, {OPAQUE: "A"}) == ["A .", ". A"]


def test_opaque_corners_reports_only_the_painted_ones():
    """opaque_corners() reports only the corners that are actually non-transparent, not all four."""
    px = [CLEAR] * 9
    px[0] = OPAQUE  # top-left
    px[8] = OPAQUE  # bottom-right
    assert p.opaque_corners(_img(px, 3, 3)) == [(0, 0), (2, 2)]


def test_describe_reports_size_palette_and_checks():
    """describe() assembles the size header, hex palette, semi-transparent count and opaque corners.

    One fully opaque 2x2 layer exercises each of describe()'s sub-parts at
    once: the '{name} — WxH' header, a hex colour code, a zero
    semi-transparent count, and all four corners listed as opaque.
    """
    lines = "\n".join(p.describe("Player", _img([OPAQUE] * 4, 2, 2)))
    assert "'Player' — 2x2" in lines
    assert "#FFFFFF" in lines
    assert "semi-transparent (0 < alpha < 255): 0 px" in lines
    assert "opaque corners: [(0, 0), (1, 0), (0, 1), (1, 1)]" in lines


def _fixture(path, form):
    """Write a two-layer .pixaki: a 2x2 'Solid' and a hidden 'Ghost'."""
    doc = {
        "sprites": [
            {
                "cels": [{"identifier": "D1", "frame": [[0, 0], [2, 2]]}],
                "layers": [
                    {
                        "name": "Solid",
                        "clips": [{"itemIdentifier": "D1"}],
                        "isVisible": True,
                    },
                    {
                        "name": "Ghost",
                        "clips": [{"itemIdentifier": "D1"}],
                        "isVisible": False,
                    },
                ],
            }
        ]
    }
    members = {
        "document.json": json.dumps(doc).encode(),
        "images/drawings/D1.png": _png(_img([OPAQUE, CLEAR, CLEAR, OPAQUE], 2, 2)),
    }
    return write_pixaki(str(path), members, form, PIXAKI_DIRECTORIES)


@pytest.mark.parametrize("form", PIXAKI_FORMS)
def test_report_reads_both_packagings_identically(tmp_path, form):
    """report() counts only the visible layer and renders its grid correctly, per packaging form.

    'Ghost' (isVisible False) must not be counted or named; 'Solid' must
    be, and its grid must actually render the drawn pixel pattern. Run
    once per packaging form via parametrize, not compared against each
    other here — that comparison is test_report_of_both_packagings_matches.
    """
    path = _fixture(tmp_path / f"m-{form}.pixaki", form)
    lines = p.report(path)
    assert lines[0] == "=== 1 visible layers ==="
    assert "'Solid'" in lines[1]
    assert "A ." in "\n".join(lines)


def test_report_of_both_packagings_matches(tmp_path):
    """report() returns identical lines for the same fixture built as a zip and as a directory."""
    reports = [p.report(_fixture(tmp_path / f"same-{form}.pixaki", form)) for form in PIXAKI_FORMS]
    assert reports[0] == reports[1]


def test_list_stops_before_the_grids(tmp_path):
    """report(names_only=True) stops after the layer header, with no per-layer detail or grid."""
    path = _fixture(tmp_path / "l.pixaki", "zip")
    lines = p.report(path, names_only=True)
    assert len(lines) == 2
    assert "Grid:" not in "\n".join(lines)


def test_unknown_layer_name_names_what_is_there(tmp_path):
    """An unmatched --layer name exits with an error naming the layers that actually exist.

    A silent empty report would read exactly like a layer that legitimately
    has no content, so the mismatch must raise instead of returning
    quietly.
    """
    path = _fixture(tmp_path / "u.pixaki", "zip")
    with pytest.raises(SystemExit) as exc:
        p.report(path, want="Nope")
    assert "'Solid'" in str(exc.value)


def test_named_layer_excludes_the_others(tmp_path):
    """report(want=...) includes only the requested layer's detail block, not any other layer's."""
    doc_path = _fixture(tmp_path / "n.pixaki", "zip")
    body = "\n".join(p.report(doc_path, want="Solid"))
    assert body.count("Grid:") == 1
