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
