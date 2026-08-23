"""Unit tests for pixaki_inspect (the .pixaki layer report)."""

import io
import json

import pytest
from PIL import Image

from conftest import PIXAKI_DIRECTORIES, PIXAKI_FORMS, write_pixaki
import pixaki_inspect as p


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
    img = _img([OPAQUE, ERASED_WHITE, CLEAR, (9, 9, 9, 0)], 2, 2)
    assert p.palette_of(img) == {OPAQUE: 1}


def test_palette_keeps_semi_transparent_pixels():
    faint = (255, 255, 255, 128)
    palette = p.palette_of(_img([OPAQUE, faint, CLEAR, CLEAR], 2, 2))
    assert palette == {OPAQUE: 1, faint: 1}


def test_ink_bounds_ignores_erased_rgb():
    # getbbox() would call the erased corner ink and report the full 2x2
    img = _img([CLEAR, ERASED_WHITE, CLEAR, OPAQUE], 2, 2)
    assert p.ink_bounds(img) == (1, 1, 1, 1)


def test_ink_bounds_of_empty_layer_is_none():
    assert p.ink_bounds(_img([CLEAR] * 4, 2, 2)) is None


def test_symbol_map_gives_a_to_the_most_frequent_colour():
    red, green = (255, 0, 0, 255), (0, 255, 0, 255)
    symbols = p.symbol_map({red: 2, green: 7})
    assert symbols[green] == "A"
    assert symbols[red] == "B"


def test_symbol_map_is_stable_when_counts_tie():
    a, b = (1, 1, 1, 255), (2, 2, 2, 255)
    first = p.symbol_map({a: 3, b: 3})
    second = p.symbol_map({b: 3, a: 3})
    assert first == second


def test_symbol_map_names_the_overflow_instead_of_folding_silently():
    # one colour past the alphabet+digits: the extras must be distinguishable
    palette = {(i, 0, 0, 255): 1 for i in range(len(p.SYMBOLS) + 1)}
    symbols = p.symbol_map(palette)
    assert sum(1 for s in symbols.values() if s == p.OVERFLOW) == 1
    assert len(set(symbols.values())) == len(p.SYMBOLS) + 1  # incl. the '?'


def test_grid_marks_transparent_pixels_with_a_dot():
    img = _img([OPAQUE, CLEAR, ERASED_WHITE, OPAQUE], 2, 2)
    assert p.grid_rows(img, {OPAQUE: "A"}) == ["A .", ". A"]


def test_opaque_corners_reports_only_the_painted_ones():
    px = [CLEAR] * 9
    px[0] = OPAQUE  # top-left
    px[8] = OPAQUE  # bottom-right
    assert p.opaque_corners(_img(px, 3, 3)) == [(0, 0), (2, 2)]


def test_describe_reports_size_palette_and_checks():
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
    path = _fixture(tmp_path / f"m-{form}.pixaki", form)
    lines = p.report(path)
    assert lines[0] == "=== 1 visible layers ==="  # the hidden layer is not one
    assert "'Solid'" in lines[1]
    assert "A ." in "\n".join(lines)


def test_report_of_both_packagings_matches(tmp_path):
    reports = [
        p.report(_fixture(tmp_path / f"same-{form}.pixaki", form))
        for form in PIXAKI_FORMS
    ]
    assert reports[0] == reports[1]


def test_list_stops_before_the_grids(tmp_path):
    path = _fixture(tmp_path / "l.pixaki", "zip")
    lines = p.report(path, names_only=True)
    assert len(lines) == 2  # header + the one visible layer
    assert "Grid:" not in "\n".join(lines)


def test_unknown_layer_name_names_what_is_there(tmp_path):
    path = _fixture(tmp_path / "u.pixaki", "zip")
    with pytest.raises(SystemExit) as exc:
        p.report(path, want="Nope")
    assert "'Solid'" in str(exc.value)


def test_named_layer_excludes_the_others(tmp_path):
    doc_path = _fixture(tmp_path / "n.pixaki", "zip")
    body = "\n".join(p.report(doc_path, want="Solid"))
    assert body.count("Grid:") == 1
