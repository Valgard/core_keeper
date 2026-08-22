"""Unit tests for pixaki_to_sheet (Iter-12 sprite-sheet generator)."""

from PIL import Image
from conftest import PIXAKI_FORMS, write_pixaki
import pixaki_to_sheet as p

EXCLUDE_TOP = {"Outsorted", "Background", "Search Field Complete", "Dropdown Complete"}

_TEMPLATE_META = (
    "fileFormatVersion: 2\nguid: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n"
    "TextureImporter:\n  spriteMode: 2\n  spriteSheet:\n    serializedVersion: 2\n"
    "    sprites:\n    nameFileIdTable:\n  mipmapLimitGroupName: \n  userData: \n"
)


def _doc():
    # minimal document.json shape
    return {
        "sprites": [
            {
                "cels": [
                    {"identifier": "D1", "frame": [[0, 0], [8, 8]]},
                    {"identifier": "D2", "frame": [[0, 0], [6, 6]]},
                    {"identifier": "DH", "frame": [[0, 0], [8, 8]]},
                ],
                "layers": [
                    {
                        "name": "Window",
                        "clips": [{"itemIdentifier": "D1"}],
                        "isVisible": True,
                    },
                    {
                        "name": "Outsorted",
                        "isVisible": False,
                        "clips": [],
                        "children": [
                            {
                                "name": "Icon Sort",
                                "clips": [{"itemIdentifier": "DH"}],
                                "isVisible": True,
                            }
                        ],
                    },
                    {
                        "name": "Clear",
                        "clips": [{"itemIdentifier": "D2"}],
                        "isVisible": True,
                    },
                ],
            }
        ]
    }


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
    b = _img([(255, 0, 0, 255)] * 4, 2, 2)  # identical to a
    c = _img([(0, 255, 0, 255)] * 4, 2, 2)  # different
    layers = [p.Layer("X", "A", 2, 2), p.Layer("Y", "B", 2, 2), p.Layer("Z", "C", 2, 2)]
    drawings = {"A": a, "B": b, "C": c}
    distinct, name_to_key = p.dedup(layers, drawings)
    assert len(distinct) == 2  # A/B collapse, C separate
    assert name_to_key["X"] == name_to_key["Y"]
    assert name_to_key["Z"] != name_to_key["X"]


def test_internalid_is_deterministic_and_size_disambiguated():
    # two distinct sprites share a base name but differ in size -> unique names
    items = [("k8", None, 8, 8, "Icon Sort Asc"), ("k6", None, 6, 6, "Icon Sort Asc")]
    named = p.assign_names(items)
    assert len(set(named.values())) == 2  # unique
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


def test_border_for_reads_config():
    sliced = {"Entry Background"}
    ov = {("Window", 16, 16): (4, 4, 4, 4), ("Caret", 2, 8): (0, 1, 0, 1)}
    assert p.border_for("Entry Background", 8, 8, sliced, ov) == (1, 1, 1, 1)
    assert p.border_for("Window", 16, 16, sliced, ov) == (4, 4, 4, 4)
    assert p.border_for("Icon Sort", 8, 8, sliced, ov) == (0, 0, 0, 0)
    assert p.border_for("Caret", 2, 8, sliced, ov) == (0, 1, 0, 1)


def test_pad_bottom_anchor():
    # the option separator: a 1px line padded up to its 8x8 grid cell, at the bottom
    from PIL import Image

    line = Image.new("RGBA", (8, 1), (255, 255, 255, 255))
    out = p._pad(line, 8, 8, "bottom")
    assert out.size == (8, 8)
    assert out.getpixel((0, 7))[3] == 255  # line at the bottom row
    assert out.getpixel((0, 0))[3] == 0  # transparent on top


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
    placed = [
        dict(name="Window", internal_id=42, x=2, y=2, w=16, h=16, border=(4, 4, 4, 4))
    ]
    out = p.render_meta(str(tf), "b" * 32, placed)
    assert "guid: " + "b" * 32 in out
    assert "name: Window" in out
    assert "internalID: 42" in out
    assert "      Window: 42" in out  # nameFileIdTable entry
    assert "old_sprite" not in out  # old sprites replaced
    assert "  mipmapLimitGroupName: " in out  # tail preserved
    assert "border: {x: 4, y: 4, z: 4, w: 4}" in out


def test_internal_id_pinning():
    assert p.internal_id("Arrow", {"Arrow": 100007}) == 100007  # pinned wins
    assert p.internal_id("Arrow") == p.internal_id("Arrow", {})  # unpinned == hash
    assert p.internal_id("Other", {"Arrow": 100007}) == p.internal_id("Other")


def test_load_config_normalizes_and_defaults(tmp_path):
    (tmp_path / "s.pixaki").write_bytes(b"x")
    (tmp_path / "s.json").write_text(
        '{"exclude":["Bg"],"sliced":["Panel"],'
        '"borderOverride":[{"name":"Window","w":16,"h":16,"border":[4,4,4,4]}],'
        '"pad":{"Sep":{"w":8,"h":8,"anchor":"bottom"},"Ico":{"w":16,"h":16,"anchor":[5,3]}},'
        '"internalIds":{"Arrow":100007}}'
    )
    c = p.load_config(str(tmp_path / "s.pixaki"))
    assert c["exclude"] == {"Bg"} and c["sliced"] == {"Panel"}
    assert c["borderOverride"][("Window", 16, 16)] == (4, 4, 4, 4)
    assert c["pad"]["Sep"] == (8, 8, "bottom") and c["pad"]["Ico"] == (16, 16, (5, 3))
    assert c["internalIds"] == {"Arrow": 100007}
    assert c["sheetWidth"] == 128 and c["gutter"] == 2 and c["guid"] is None  # defaults
    import pytest

    with pytest.raises(FileNotFoundError):
        p.load_config(str(tmp_path / "missing.pixaki"))


def test_build_sheet_in_place_template_not_truncated(tmp_path):
    """Regression: in-place regen defaults --meta-template to <out>.meta; the
    template must be READ before the output .meta is opened-for-write (truncated)."""
    import zipfile, json, io

    doc = {
        "sprites": [
            {
                "cels": [{"identifier": "D1", "frame": [[0, 0], [4, 4]]}],
                "layers": [
                    {
                        "name": "Icon",
                        "clips": [{"itemIdentifier": "D1"}],
                        "isVisible": True,
                    }
                ],
            }
        ]
    }
    pixaki = tmp_path / "s.pixaki"
    with zipfile.ZipFile(pixaki, "w") as z:
        z.writestr("document.json", json.dumps(doc))
        bio = io.BytesIO()
        Image.new("RGBA", (4, 4), (255, 0, 0, 255)).save(bio, "PNG")
        z.writestr("images/drawings/D1.png", bio.getvalue())
    (tmp_path / "s.json").write_text("{}")
    out = tmp_path / "s.png"
    (tmp_path / "s.png.meta").write_text(
        "fileFormatVersion: 2\nguid: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n"
        "TextureImporter:\n  spriteMode: 2\n  spriteSheet:\n    serializedVersion: 2\n"
        "    sprites:\n    nameFileIdTable:\n  mipmapLimitGroupName: \n  userData: \n"
    )
    p.build_sheet(str(pixaki), str(out))  # in-place: template defaults to s.png.meta
    meta = (tmp_path / "s.png.meta").read_text()
    assert "name: Icon" in meta  # the sprite was written
    assert (
        "  mipmapLimitGroupName: " in meta
    )  # the template tail survived (not truncated)


def _write_two_sprite_pixaki(tmp_path, cfg_json, form="zip"):
    """A .pixaki with two DISTINCT sprites named 'Icon' and 'Icon2', plus a
    sibling s.json holding cfg_json. Returns the .pixaki path.

    `form` selects the packaging (see conftest.write_pixaki); it defaults to
    the ZIP that Pixaki's Export produces, which is what every caller but the
    equivalence test wants."""
    import json, io

    doc = {
        "sprites": [
            {
                "cels": [
                    {"identifier": "D1", "frame": [[0, 0], [4, 4]]},
                    {"identifier": "D2", "frame": [[0, 0], [4, 4]]},
                ],
                "layers": [
                    {
                        "name": "Icon",
                        "clips": [{"itemIdentifier": "D1"}],
                        "isVisible": True,
                    },
                    {
                        "name": "Icon2",
                        "clips": [{"itemIdentifier": "D2"}],
                        "isVisible": True,
                    },
                ],
            }
        ]
    }
    members = {"document.json": json.dumps(doc).encode()}
    for did, color in (
        ("D1", (255, 0, 0, 255)),
        ("D2", (0, 255, 0, 255)),
    ):  # distinct pixels
        bio = io.BytesIO()
        Image.new("RGBA", (4, 4), color).save(bio, "PNG")
        members[f"images/drawings/{did}.png"] = bio.getvalue()
    pixaki = write_pixaki(tmp_path / "s.pixaki", members, form)
    (tmp_path / "s.json").write_text(cfg_json)
    return pixaki


def test_validate_pins_rejects_collision(tmp_path):
    """Two sprites pinned to the SAME internalID would emit an ambiguous Unity
    fileID; the build must fail loud (before writing) rather than ship it."""
    import pytest

    pixaki = _write_two_sprite_pixaki(tmp_path, '{"internalIds":{"Icon":5,"Icon2":5}}')
    with pytest.raises(ValueError, match="duplicate internalID"):
        p.build_sheet(str(pixaki), str(tmp_path / "s.png"))
    assert not (tmp_path / "s.png").exists()  # nothing written on failure


def test_build_sheet_reads_a_directory_package_exactly_like_a_zip(tmp_path):
    """Both packagings must yield the same sheet, byte for byte.

    A .pixaki is a ZIP when it came through Pixaki's Export and a directory
    when it was pulled straight out of iCloud (docs/pixaki-format.md). "It
    reads at all" would be far too weak a check here: build_sheet is
    deterministic -- stable internalIDs, packing, dedup -- so anything the
    container form perturbed would surface as a differing byte."""
    built = {}
    for form in PIXAKI_FORMS:
        home = tmp_path / form
        home.mkdir()
        pixaki = _write_two_sprite_pixaki(home, "{}", form=form)
        (home / "s.png.meta").write_text(_TEMPLATE_META)
        # Pin the guid: unpinned it is derived from the out path, which differs
        # per run, and the packaging must be the only variable left.
        mapping, guid = p.build_sheet(str(pixaki), str(home / "s.png"), guid="c" * 32)
        built[form] = (
            mapping,
            guid,
            (home / "s.png").read_bytes(),
            (home / "s.png.meta").read_text(),
        )

    mapping_zip, guid_zip, png_zip, meta_zip = built["zip"]
    mapping_dir, guid_dir, png_dir, meta_dir = built["directory"]
    assert len(mapping_zip) == 2  # the ZIP run really did build a two-sprite sheet
    assert mapping_dir == mapping_zip
    assert guid_dir == guid_zip
    assert meta_dir == meta_zip
    assert png_dir == png_zip  # last: a mismatch here prints two PNG blobs


def test_validate_pins_rejects_unused_pin(tmp_path):
    """A pin key that matches no produced sprite (a typo) silently no-ops the
    pin; the build must fail loud so the typo can't ship a hash-id sprite."""
    import pytest

    pixaki = _write_two_sprite_pixaki(tmp_path, '{"internalIds":{"Iconnn":5}}')
    with pytest.raises(ValueError, match="match no produced sprite"):
        p.build_sheet(str(pixaki), str(tmp_path / "s.png"))
