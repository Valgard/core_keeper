"""Unit tests for pixaki_to_sheet (Iter-12 sprite-sheet generator)."""
from PIL import Image
import pixaki_to_sheet as p

EXCLUDE_TOP = {"Outsorted", "Background", "Search Field Complete", "Dropdown Complete"}


def _doc():
    # minimal document.json shape
    return {"sprites": [{
        "cels": [
            {"identifier": "D1", "frame": [[0, 0], [8, 8]]},
            {"identifier": "D2", "frame": [[0, 0], [6, 6]]},
            {"identifier": "DH", "frame": [[0, 0], [8, 8]]},
        ],
        "layers": [
            {"name": "Window", "clips": [{"itemIdentifier": "D1"}], "isVisible": True},
            {"name": "Outsorted", "isVisible": False, "clips": [],
             "children": [{"name": "Icon Sort", "clips": [{"itemIdentifier": "DH"}], "isVisible": True}]},
            {"name": "Clear", "clips": [{"itemIdentifier": "D2"}], "isVisible": True},
        ],
    }]}


def test_collect_visible_layers_excludes_groups_and_hidden():
    layers = p.collect_layers(_doc(), EXCLUDE_TOP)
    names = {(l.name, l.w, l.h) for l in layers}
    assert names == {("Window", 8, 8), ("Clear", 6, 6)}
    # the "Icon Sort" under Outsorted is excluded by top-group
    assert all(l.name != "Icon Sort" for l in layers)


def _img(pixels_rgba, w, h):
    im = Image.new("RGBA", (w, h))
    im.putdata(pixels_rgba)
    return im


def test_dedup_collapses_identical_pixels():
    a = _img([(255, 0, 0, 255)] * 4, 2, 2)
    b = _img([(255, 0, 0, 255)] * 4, 2, 2)   # identical to a
    c = _img([(0, 255, 0, 255)] * 4, 2, 2)   # different
    layers = [p.Layer("X", "A", 2, 2), p.Layer("Y", "B", 2, 2), p.Layer("Z", "C", 2, 2)]
    drawings = {"A": a, "B": b, "C": c}
    distinct, name_to_key = p.dedup(layers, drawings)
    assert len(distinct) == 2           # A/B collapse, C separate
    assert name_to_key["X"] == name_to_key["Y"]
    assert name_to_key["Z"] != name_to_key["X"]


def test_internalid_is_deterministic_and_size_disambiguated():
    # two distinct sprites share a base name but differ in size -> unique names
    items = [("k8", None, 8, 8, "Icon Sort Asc"), ("k6", None, 6, 6, "Icon Sort Asc")]
    named = p.assign_names(items)
    assert len(set(named.values())) == 2          # unique
    assert set(named.values()) == {"Icon Sort Asc 8x8", "Icon Sort Asc 6x6"}
    # a non-repeating base name stays bare
    solo = p.assign_names([("k", None, 8, 8, "Window")])
    assert solo["k"] == "Window"
    # deterministic id from final name
    assert p.internal_id("Icon Sort Asc 8x8") == p.internal_id("Icon Sort Asc 8x8")
    assert p.internal_id("Icon Sort Asc 8x8") != p.internal_id("Icon Sort Asc 6x6")


def test_pack_places_without_overlap_and_bottom_left_rects():
    sprites = [("a", None, 8, 8), ("b", None, 6, 6), ("c", None, 4, 8)]
    placements, sheet_w, sheet_h = p.pack(sprites, sheet_w=20, gutter=2)
    for key, x, y, w, h in placements:
        assert 0 <= x and x + w <= sheet_w
        assert 0 <= y and y + h <= sheet_h
    # unique positions, all three placed
    assert len({(x, y) for (_, x, y, _, _) in placements}) == 3


def test_border_table_defaults():
    # 9-slice chrome gets a border; icons get none. Called with the BASE name + final size.
    assert p.border_for("Entry Background", 8, 8) == (1, 1, 1, 1)
    assert p.border_for("Window", 16, 16) == (4, 4, 4, 4)
    assert p.border_for("Icon Sort", 8, 8) == (0, 0, 0, 0)         # icon: simple
    # manual Sprite-Editor border tweaks folded back into BORDER_OVERRIDE:
    assert p.border_for("Entry Selected", 8, 8) == (3, 3, 3, 3)
    assert p.border_for("Scrollbar Selector", 4, 8) == (1, 3, 1, 3)
    assert p.border_for("Caret", 2, 8) == (0, 1, 0, 1)
    assert p.border_for("Checkbox empty", 6, 6) == (1, 1, 1, 1)


def test_pad_bottom_anchor():
    # the option separator: a 1px line padded up to its 8x8 grid cell, at the bottom
    from PIL import Image
    line = Image.new("RGBA", (8, 1), (255, 255, 255, 255))
    out = p._pad(line, 8, 8, "bottom")
    assert out.size == (8, 8)
    assert out.getpixel((0, 7))[3] == 255   # line at the bottom row
    assert out.getpixel((0, 0))[3] == 0     # transparent on top


def test_render_meta_replaces_guid_and_sprites(tmp_path):
    template = (
        "fileFormatVersion: 2\n"
        "guid: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n"
        "TextureImporter:\n"
        "  spriteMode: 2\n"
        "  spriteSheet:\n"
        "    serializedVersion: 2\n"
        "    sprites:\n"
        "    - serializedVersion: 2\n"
        "      name: old_sprite\n"
        "    nameFileIdTable:\n"
        "      old_sprite: 123\n"
        "  mipmapLimitGroupName: \n"
        "  userData: \n"
    )
    tf = tmp_path / "tpl.png.meta"
    tf.write_text(template)
    placed = [dict(name="Window", internal_id=42, x=2, y=2, w=16, h=16, border=(4, 4, 4, 4))]
    out = p.render_meta(str(tf), "b" * 32, placed)
    assert "guid: " + "b" * 32 in out
    assert "name: Window" in out
    assert "internalID: 42" in out
    assert "      Window: 42" in out                  # nameFileIdTable entry
    assert "old_sprite" not in out                    # old sprites replaced
    assert "  mipmapLimitGroupName: " in out          # tail preserved
    assert "border: {x: 4, y: 4, z: 4, w: 4}" in out
