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
    # cell 0: top-left cell, rect box on rows 0..9 of a 12px cell
    assert g.cell_geometry(0) == (0, 144 - 10, 10)
    # cell 31: last column of row 0
    assert g.cell_geometry(31) == (31 * 8, 144 - 10, 10)
    # cell 32: first column of row 1
    assert g.cell_geometry(32) == (0, 144 - (12 + 10), 10)
    # cell 383: last cell (row 11)
    assert g.cell_geometry(383) == (31 * 8, 144 - (11 * 12 + 10), 10)


def test_rect_bbox_reads_magenta_box_in_cell_coordinates():
    img = _blank()
    _paint_rect(img, 5, dx=0, dy=0, w=3, h=10)
    assert g.rect_bbox(img, 5) == (0, 0, 3, 10)
    assert g.rect_bbox(img, 6) is None


def test_rect_bbox_ignores_non_magenta_pixels():
    img = _blank()
    _paint_rect(img, 7, dx=0, dy=0, w=4, h=10, colour=WHITE)
    assert g.rect_bbox(img, 7) is None


def test_widths_returns_one_entry_per_cell_zero_for_empty():
    img = _blank()
    _paint_rect(img, 0, 0, 0, 5, 10)
    _paint_rect(img, 3, 0, 0, 2, 10)
    w = g.widths(img)
    assert len(w) == 384
    assert w[0] == 5
    assert w[1] == 0
    assert w[3] == 2


def test_validate_flags_rect_box_with_wrong_y_or_height():
    img = _blank()
    _paint_rect(img, 0, dx=0, dy=1, w=3, h=10)  # dy must be 0
    _paint_rect(img, 1, dx=0, dy=0, w=3, h=9)  # h must be 10
    _paint_rect(img, 2, dx=1, dy=0, w=3, h=10)  # dx must be 0
    problems = g.validate(img, _blank())
    # Assert the exact messages: a substring like "y" also matches the word
    # "glyph" in the presence-mismatch message, which would let this test pass
    # even with the y check deleted (proven by mutation testing).
    assert len(problems) == 3
    assert "cell 0: rect box y is 1, expected 0" in problems
    assert "cell 1: rect box height is 9, expected 10" in problems
    assert "cell 2: rect box x-offset is 1, expected 0" in problems


def test_validate_flags_painted_cell_without_rect_box_and_vice_versa():
    rects = _blank()
    atlas = _blank()
    _paint_rect(atlas, 10, dx=0, dy=2, w=3, h=5, colour=WHITE)  # glyph, no rect box
    _paint_rect(rects, 20, dx=0, dy=0, w=3, h=10)  # rect box, no glyph
    problems = g.validate(rects, atlas)
    assert any("cell 10" in p and "no rect box" in p for p in problems)
    assert any("cell 20" in p and "no glyph" in p for p in problems)


def test_validate_clean_sheet_reports_nothing():
    rects, atlas = _blank(), _blank()
    _paint_rect(rects, 4, dx=0, dy=0, w=3, h=10)
    _paint_rect(atlas, 4, dx=0, dy=2, w=3, h=8, colour=WHITE)
    assert g.validate(rects, atlas) == []


def _ws(widths_by_index):
    """A 384-entry width vector with only the given indices set."""
    ws = [0] * 384
    for i, w in widths_by_index.items():
        ws[i] = w
    return ws


def test_kerning_flush_blocks_have_zero_kerning():
    # two solid 4px blocks, ink flush against both advance edges: no gap.
    atlas = _blank()
    _paint_rect(atlas, 0, dx=0, dy=0, w=4, h=10, colour=WHITE)
    _paint_rect(atlas, 1, dx=0, dy=0, w=4, h=10, colour=WHITE)
    matrix = g.kerning_matrix(atlas, _ws({0: 4, 1: 4}))
    assert matrix[0 * 384 + 1] == 0


def test_kerning_one_empty_column_each_side_is_clamped_to_two():
    # cell 0: ink in columns 0-2 of a 4px advance (column 3 empty -> 1px gap
    # to the advance edge). Cell 1: ink in columns 1-3 (column 0 empty -> 1px
    # gap from its own edge). Combined gap is 1 + 1 = 2, the clamp's cap.
    atlas = _blank()
    _paint_rect(atlas, 0, dx=0, dy=0, w=3, h=10, colour=WHITE)
    _paint_rect(atlas, 1, dx=1, dy=0, w=3, h=10, colour=WHITE)
    matrix = g.kerning_matrix(atlas, _ws({0: 4, 1: 4}))
    assert matrix[0 * 384 + 1] == 2


def test_kerning_non_overlapping_ink_rows_default_to_two():
    # cell 0 has ink only in row 0, cell 1 only in row 5 -- no row has ink in
    # both, so the pair falls back to the cap rather than a measured gap.
    atlas = _blank()
    _paint_rect(atlas, 0, dx=0, dy=0, w=4, h=1, colour=WHITE)
    _paint_rect(atlas, 1, dx=0, dy=5, w=4, h=1, colour=WHITE)
    matrix = g.kerning_matrix(atlas, _ws({0: 4, 1: 4}))
    assert matrix[0 * 384 + 1] == 2


def test_kerning_partial_gap_is_exact():
    # only row 0 has ink in both: cell 0 stops 1px short of its advance edge,
    # cell 1 starts flush at column 0 -- the measured gap is exactly 1.
    atlas = _blank()
    _paint_rect(atlas, 0, dx=0, dy=0, w=3, h=1, colour=WHITE)
    _paint_rect(atlas, 1, dx=0, dy=0, w=4, h=1, colour=WHITE)
    matrix = g.kerning_matrix(atlas, _ws({0: 4, 1: 4}))
    assert matrix[0 * 384 + 1] == 1


def test_kerning_unpainted_cell_is_zero_in_both_directions():
    atlas = _blank()
    _paint_rect(atlas, 0, dx=0, dy=0, w=4, h=1, colour=WHITE)
    matrix = g.kerning_matrix(atlas, _ws({0: 4}))  # cell 1 stays unpainted
    assert matrix[0 * 384 + 1] == 0
    assert matrix[1 * 384 + 0] == 0
