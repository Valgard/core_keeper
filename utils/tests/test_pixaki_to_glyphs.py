"""Unit tests for pixaki_to_glyphs (the thinTiny full-build extractor)."""

import io
import json
import zipfile

import pixaki_to_glyphs as g
import pytest
from PIL import Image

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


def _pixaki(path, layers, size=(257, 144), offset=(0, 0)):
    """Write a minimal .pixaki holding {layer name: image}.

    Enough of the real format for load_layers(): one cel per layer, each
    placed at `offset` on a `size` canvas. Lets the loader be tested without
    the mod repo's real master, which is only present in a full checkout.
    """
    doc = {
        "sprites": [
            {
                "size": list(size),
                "layers": [
                    {"name": name, "clips": [{"itemIdentifier": f"cel-{name}"}]}
                    for name in layers
                ],
                "cels": [
                    {"identifier": f"cel-{name}", "frame": [list(offset), [1, 1]]}
                    for name in layers
                ],
            }
        ]
    }
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("document.json", json.dumps(doc))
        for name, img in layers.items():
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            zf.writestr(f"images/drawings/cel-{name}.png", buf.getvalue())
    return path


def test_load_layers_composites_each_layer_at_its_cel_offset(tmp_path):
    # A Pixaki drawing is stored cropped to its own bounds; the cel's frame
    # origin is where it belongs on the canvas. Getting that offset wrong
    # shifts every cell index by a constant, so pin it with a 1px marker.
    rects_drawing = Image.new("RGBA", (1, 1), MAGENTA)
    atlas_drawing = Image.new("RGBA", (1, 1), WHITE)
    master = _pixaki(
        tmp_path / "m.pixaki",
        {"Rects": rects_drawing, "Atlas": atlas_drawing},
        offset=(16, 12),
    )
    rects, atlas = g.load_layers(master)
    assert rects.size == (257, 144) and atlas.size == (257, 144)
    assert rects.getpixel((16, 12)) == MAGENTA
    assert atlas.getpixel((16, 12)) == WHITE
    assert rects.getpixel((0, 0)) == CLEAR


def test_load_layers_names_the_layer_a_renamed_master_lacks(tmp_path):
    # Renaming a layer in Pixaki is the likeliest way to break the tool; the
    # message has to say which name it wanted and what the master has.
    master = _pixaki(
        tmp_path / "m.pixaki",
        {"Boxes": _blank(1, 1), "Atlas": _blank(1, 1)},  # 'Rects' renamed
    )
    with pytest.raises(SystemExit) as exc:
        g.load_layers(master)
    assert "'Rects'" in str(exc.value)
    assert "'Boxes'" in str(exc.value)


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


def test_validate_flags_ink_wider_than_its_advance():
    # A 3px advance box with 6px of ink. Before this check the cell passed as
    # clean: ink_edges() reads only columns 0..advance-1, so the overflow was
    # silently clipped and the pair's kerning came out of a truncated glyph --
    # which then overlaps its neighbour in game.
    rects, atlas = _blank(), _blank()
    _paint_rect(rects, 4, dx=0, dy=0, w=3, h=10)
    _paint_rect(atlas, 4, dx=0, dy=0, w=6, h=10, colour=WHITE)
    problems = g.validate(rects, atlas)
    assert problems == [
        "cell 4: glyph ink reaches column 5, outside its advance width 3"
    ]


def test_validate_flags_a_last_column_advance_that_crowds_the_outline_padding():
    # CK widens each sprite rect by 2 px only while
    # `rect2.x + rect2.width + 2 < texture.width`; at x=248 (column 31) on the
    # 257 px canvas that caps the advance at 6. A 7 costs one "make the font
    # texture wider" error per glyph on every launch, plus a glyph drawn
    # without its padding -- and it used to validate clean.
    rects, atlas = _blank(), _blank()
    _paint_rect(rects, 31, dx=0, dy=0, w=7, h=10)
    _paint_rect(atlas, 31, dx=0, dy=0, w=7, h=10, colour=WHITE)
    assert g.validate(rects, atlas) == [
        "cell 31: advance 7 at x=248 leaves no room for the outline padding "
        "CK adds (needs x + advance + 2 < 257)"
    ]


def test_validate_accepts_the_widest_advance_the_last_column_can_hold():
    # 248 + 6 + 2 == 256 < 257: the padding still fits, so this must pass --
    # the shipped atlas has a 5 here, one column of headroom.
    rects, atlas = _blank(), _blank()
    _paint_rect(rects, 31, dx=0, dy=0, w=6, h=10)
    _paint_rect(atlas, 31, dx=0, dy=0, w=6, h=10, colour=WHITE)
    assert g.validate(rects, atlas) == []


def test_validate_flags_ink_below_the_rect_box_rows():
    # Same clipping hazard on the other axis: ink_edges() reads only rows
    # 0..BOX_H-1, so ink in the cell's two spare bottom rows would be invisible
    # to the kerning pass while still rendering (the sprite covers rows 0..10).
    rects, atlas = _blank(), _blank()
    _paint_rect(rects, 4, dx=0, dy=0, w=3, h=10)
    _paint_rect(atlas, 4, dx=0, dy=2, w=3, h=10, colour=WHITE)
    problems = g.validate(rects, atlas)
    assert problems == [
        "cell 4: glyph ink spans rows 2..11, outside the rect box rows 0..9"
    ]


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


def test_kerning_two_empty_columns_each_side_is_clamped_to_two():
    # cell 0: ink in columns 0-1 of a 4px advance (columns 2-3 empty -> 2px
    # gap to the advance edge). Cell 1: ink in columns 2-3 (columns 0-1 empty
    # -> 2px gap from its own edge). Raw gap 2 + 2 = 4, minus one is 3,
    # clamped down to the cap, 2. Deliberately a literal, not
    # g.KERNING_CLAMP: this pins the clamp's actual settled value (2) so a
    # future accidental change to the constant is caught here, not silently
    # carried along by an assertion that reads the same constant it's meant
    # to check.
    atlas = _blank()
    _paint_rect(atlas, 0, dx=0, dy=0, w=2, h=10, colour=WHITE)
    _paint_rect(atlas, 1, dx=2, dy=0, w=2, h=10, colour=WHITE)
    matrix = g.kerning_matrix(atlas, _ws({0: 4, 1: 4}))
    assert matrix[0 * 384 + 1] == 2


def test_kerning_non_overlapping_ink_rows_default_to_two():
    # cell 0 has ink only in row 0, cell 1 only in row 5 -- no row has ink in
    # both, so the pair falls back to the cap rather than a measured gap (the
    # no-overlap case is exempt from the "one less" adjustment below).
    # Literal 2, not g.KERNING_CLAMP, for the same reason as the test above.
    atlas = _blank()
    _paint_rect(atlas, 0, dx=0, dy=0, w=4, h=1, colour=WHITE)
    _paint_rect(atlas, 1, dx=0, dy=5, w=4, h=1, colour=WHITE)
    matrix = g.kerning_matrix(atlas, _ws({0: 4, 1: 4}))
    assert matrix[0 * 384 + 1] == 2


def test_kerning_partial_gap_is_exact():
    # only row 0 has ink in both: cell 0 stops 2px short of its advance edge,
    # cell 1 starts flush at column 0. Raw gap is 2, minus one is 1 -- within
    # the clamp, so the result is the exact value, not the cap.
    atlas = _blank()
    _paint_rect(atlas, 0, dx=0, dy=0, w=2, h=1, colour=WHITE)
    _paint_rect(atlas, 1, dx=0, dy=0, w=4, h=1, colour=WHITE)
    matrix = g.kerning_matrix(atlas, _ws({0: 4, 1: 4}))
    assert matrix[0 * 384 + 1] == 1


def test_kerning_one_free_column_becomes_zero_not_one():
    # Regression for the l/t collision observed in game ("Seltenheit",
    # "Entdeckt"): cell 0 stops 1px short of its advance edge, cell 1 starts
    # flush at column 0 -- a raw gap of exactly 1. The pre-round-4 rule (no
    # subtraction) returned kerning 1 here, subtracting the *entire* 1px gap
    # from the advance and leaving zero columns of air -- the stems touched.
    # Minus one is 0: no pixels get subtracted, so that 1px gap survives
    # untouched instead of being closed to nothing.
    atlas = _blank()
    _paint_rect(atlas, 0, dx=0, dy=0, w=3, h=1, colour=WHITE)
    _paint_rect(atlas, 1, dx=0, dy=0, w=4, h=1, colour=WHITE)
    matrix = g.kerning_matrix(atlas, _ws({0: 4, 1: 4}))
    assert matrix[0 * 384 + 1] == 0


def test_kerning_unpainted_cell_is_zero_in_both_directions():
    atlas = _blank()
    _paint_rect(atlas, 0, dx=0, dy=0, w=4, h=1, colour=WHITE)
    matrix = g.kerning_matrix(atlas, _ws({0: 4}))  # cell 1 stays unpainted
    assert matrix[0 * 384 + 1] == 0
    assert matrix[1 * 384 + 0] == 0


def _clean_master(tmp_path):
    """A master that validates clean: an empty canvas of the required size."""
    return _pixaki(tmp_path / "clean.pixaki", {"Rects": _blank(), "Atlas": _blank()})


def test_check_only_reports_the_master_as_clean(tmp_path, capsys):
    assert g.main(["--pixaki", str(_clean_master(tmp_path)), "--check-only"]) == 0
    assert "all invariants hold" in capsys.readouterr().out


@pytest.mark.parametrize("write_flag", ["--sheet", "--kerning"])
def test_check_only_refuses_the_write_flags(tmp_path, capsys, write_flag):
    # The combination used to write nothing and print OK -- indistinguishable
    # from a successful regeneration, with the stale artifacts left on disk.
    target = tmp_path / "out"
    with pytest.raises(SystemExit) as exc:
        g.main(
            [
                "--pixaki",
                str(_clean_master(tmp_path)),
                "--check-only",
                write_flag,
                str(target),
            ]
        )
    assert exc.value.code == 2  # argparse usage error, not a clean exit
    assert "--check-only writes nothing" in capsys.readouterr().err
    assert not target.exists()
