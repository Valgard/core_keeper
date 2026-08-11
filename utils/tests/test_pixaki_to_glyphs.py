"""Unit tests for pixaki_to_glyphs (the thinTiny full-build extractor)."""

from PIL import Image
import pixaki_to_glyphs as g

MAGENTA = (229, 59, 223, 255)
WHITE = (255, 255, 255, 255)
CLEAR = (0, 0, 0, 0)


def _blank(w=257, h=144):
    return Image.new("RGBA", (w, h), CLEAR)


def _paint_rect(img, cell_index, dx, dy, w, h, colour=MAGENTA):
    """Paint a w×h block at (dx, dy) inside the given cell."""
    x0 = (cell_index % 32) * 8
    y0 = (cell_index // 32) * 12
    for yy in range(h):
        for xx in range(w):
            img.putpixel((x0 + dx + xx, y0 + dy + yy), colour)


def test_cell_geometry_maps_index_to_unity_coordinates():
    # cell 0: top-left cell, rect box on rows 1..10 of a 12px cell
    assert g.cell_geometry(0) == (0, 144 - 11, 10)
    # cell 31: last column of row 0
    assert g.cell_geometry(31) == (31 * 8, 144 - 11, 10)
    # cell 32: first column of row 1
    assert g.cell_geometry(32) == (0, 144 - (12 + 11), 10)
    # cell 383: last cell (row 11)
    assert g.cell_geometry(383) == (31 * 8, 144 - (11 * 12 + 11), 10)


def test_rect_bbox_reads_magenta_box_in_cell_coordinates():
    img = _blank()
    _paint_rect(img, 5, dx=0, dy=1, w=3, h=10)
    assert g.rect_bbox(img, 5) == (0, 1, 3, 10)
    assert g.rect_bbox(img, 6) is None


def test_rect_bbox_ignores_non_magenta_pixels():
    img = _blank()
    _paint_rect(img, 7, dx=0, dy=1, w=4, h=10, colour=WHITE)
    assert g.rect_bbox(img, 7) is None


def test_widths_returns_one_entry_per_cell_zero_for_empty():
    img = _blank()
    _paint_rect(img, 0, 0, 1, 5, 10)
    _paint_rect(img, 3, 0, 1, 2, 10)
    w = g.widths(img)
    assert len(w) == 384
    assert w[0] == 5
    assert w[1] == 0
    assert w[3] == 2


def test_validate_flags_rect_box_with_wrong_y_or_height():
    img = _blank()
    _paint_rect(img, 0, dx=0, dy=0, w=3, h=10)  # dy must be 1
    _paint_rect(img, 1, dx=0, dy=1, w=3, h=9)  # h must be 10
    _paint_rect(img, 2, dx=1, dy=1, w=3, h=10)  # dx must be 0
    problems = g.validate(img, _blank())
    assert len(problems) == 3
    assert any("cell 0" in p and "y" in p for p in problems)
    assert any("cell 1" in p and "height" in p for p in problems)
    assert any("cell 2" in p and "x-offset" in p for p in problems)


def test_validate_flags_painted_cell_without_rect_box_and_vice_versa():
    rects = _blank()
    atlas = _blank()
    _paint_rect(atlas, 10, dx=0, dy=2, w=3, h=5, colour=WHITE)  # glyph, no rect box
    _paint_rect(rects, 20, dx=0, dy=1, w=3, h=10)  # rect box, no glyph
    problems = g.validate(rects, atlas)
    assert any("cell 10" in p and "no rect box" in p for p in problems)
    assert any("cell 20" in p and "no glyph" in p for p in problems)


def test_validate_clean_sheet_reports_nothing():
    rects, atlas = _blank(), _blank()
    _paint_rect(rects, 4, dx=0, dy=1, w=3, h=10)
    _paint_rect(atlas, 4, dx=0, dy=2, w=3, h=8, colour=WHITE)
    assert g.validate(rects, atlas) == []
