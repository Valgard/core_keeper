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
