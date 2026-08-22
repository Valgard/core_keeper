"""Unit tests for pixaki_to_sheet (Iter-12 sprite-sheet generator)."""

import os

from PIL import Image
from conftest import PIXAKI_DIRECTORIES, PIXAKI_FORMS, write_pixaki
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


# Distinct pixels per sprite -- dedup() collapses identical ones, so a repeated
# colour would silently shrink the sheet the tests reason about.
_SPRITE_COLOURS = [
    (255, 0, 0, 255),
    (0, 255, 0, 255),
    (0, 0, 255, 255),
    (255, 255, 0, 255),
    (255, 0, 255, 255),
    (0, 255, 255, 255),
    (128, 64, 32, 255),
    (32, 64, 128, 255),
    (200, 200, 200, 255),
    (10, 20, 30, 255),
    (90, 10, 200, 255),
    (5, 250, 90, 255),
]


def _write_sprite_pixaki(tmp_path, cfg_json, form="zip", count=2):
    """A .pixaki with `count` DISTINCT sprites named 'Icon', 'Icon2', … plus a
    sibling s.json holding cfg_json. Returns the .pixaki path.

    `form` selects the packaging (see conftest.write_pixaki) and defaults to the
    ZIP that Pixaki's Export produces. It also carries the directory members a
    real export stores, so the archive hands load_pixaki the one member shape
    only an archive has and its '.png' filter is actually exercised."""
    import json, io

    names = [f"Icon{i + 1}" if i else "Icon" for i in range(count)]
    doc = {
        "sprites": [
            {
                "cels": [
                    {"identifier": f"D{i + 1}", "frame": [[0, 0], [4, 4]]}
                    for i in range(count)
                ],
                "layers": [
                    {
                        "name": name,
                        "clips": [{"itemIdentifier": f"D{i + 1}"}],
                        "isVisible": True,
                    }
                    for i, name in enumerate(names)
                ],
            }
        ]
    }
    members = {"document.json": json.dumps(doc).encode()}
    for i in range(count):
        bio = io.BytesIO()
        Image.new("RGBA", (4, 4), _SPRITE_COLOURS[i]).save(bio, "PNG")
        members[f"images/drawings/D{i + 1}.png"] = bio.getvalue()
    pixaki = write_pixaki(
        tmp_path / "s.pixaki", members, form, directories=PIXAKI_DIRECTORIES
    )
    (tmp_path / "s.json").write_text(cfg_json)
    return pixaki


def test_validate_pins_rejects_collision(tmp_path):
    """Two sprites pinned to the SAME internalID would emit an ambiguous Unity
    fileID; the build must fail loud (before writing) rather than ship it."""
    import pytest

    pixaki = _write_sprite_pixaki(tmp_path, '{"internalIds":{"Icon":5,"Icon2":5}}')
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
        pixaki = _write_sprite_pixaki(home, "{}", form=form, count=len(_SPRITE_COLOURS))
        # Without this the "directory" run could quietly be an archive -- if
        # write_pixaki's branch or open_pixaki's dispatch broke, the comparison
        # would still pass, on two identical runs of the same backend.
        assert os.path.isdir(pixaki) == (form == "directory")
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
    # A big enough sheet that the two listings can actually differ in order:
    # at two or three members, archive order and os.walk order coincide by
    # chance and the comparison is blind on that axis.
    assert len(mapping_zip) == len(_SPRITE_COLOURS)
    assert mapping_dir == mapping_zip
    assert guid_dir == guid_zip
    assert meta_dir == meta_zip
    assert png_dir == png_zip  # last: a mismatch here prints two PNG blobs


def test_build_sheet_accepts_a_directory_package_with_a_trailing_slash(tmp_path):
    """Shell completion appends a slash to a DIRECTORY and never to a file, so
    this is the likelier way the new packaging gets typed at all.

    `os.path.splitext` sees no extension on '…/s.pixaki/' and left the sibling
    lookup pointing INSIDE the package, at '…/s.pixaki/.json' -- while the
    error said "next to the .pixaki". The line is untouched by the adapter and
    was correct as long as it was unreachable: a directory path used to die one
    level earlier on IsADirectoryError."""
    pixaki = _write_sprite_pixaki(tmp_path, "{}", form="directory")
    (tmp_path / "s.png.meta").write_text(_TEMPLATE_META)
    mapping, _ = p.build_sheet(f"{pixaki}/", str(tmp_path / "s.png"))
    assert len(mapping) == 2


def test_load_pixaki_names_an_icloud_placeholder_instead_of_dying_on_a_uuid(tmp_path):
    """A package whose contents iCloud has evicted carries '.D1.png.icloud'
    stubs where the drawings were. The stub misses the '.png' filter, so the
    drawing dropped out of the dict without a word and the run died later on
    `KeyError: '<cel uuid>'` -- no filename, no cause, and the actual remedy is
    one click in the Finder. Exactly the route docs/pixaki-format.md names as
    where directory packages come from."""
    import pytest

    pixaki = _write_sprite_pixaki(tmp_path, "{}", form="directory")
    drawing = pixaki / "images" / "drawings" / "D1.png"
    drawing.rename(drawing.with_name(".D1.png.icloud"))
    with pytest.raises(FileNotFoundError, match="iCloud placeholder"):
        p.load_pixaki(str(pixaki))


def test_load_pixaki_ignores_an_appledouble_sidecar(tmp_path):
    """'._D1.png' is macOS metadata, not a drawing, and it slips through the
    '.png' filter. Newly reachable because a package's listing is whatever sits
    on disk rather than whatever Pixaki wrote -- complete-tiny-font/sources
    already carries a .DS_Store."""
    pixaki = _write_sprite_pixaki(tmp_path, "{}", form="directory")
    (pixaki / "images" / "drawings" / "._D1.png").write_bytes(b"\x00\x05\x16\x07junk")
    _, drawings = p.load_pixaki(str(pixaki))
    assert sorted(drawings) == ["D1", "D2"]


def test_load_pixaki_names_the_member_it_cannot_decode(tmp_path):
    """PIL reports 'cannot identify image file <_io.BytesIO object at 0x...>'
    -- the bytes went through BytesIO, so nothing in the message says which
    member. Every drawing is decoded eagerly, referenced by document.json or
    not, so one unreadable leftover takes the whole run down."""
    import pytest

    pixaki = _write_sprite_pixaki(tmp_path, "{}", form="directory")
    (pixaki / "images" / "drawings" / "D9.png").write_bytes(b"not a png at all")
    with pytest.raises(OSError, match="images/drawings/D9.png"):
        p.load_pixaki(str(pixaki))


def test_validate_pins_rejects_unused_pin(tmp_path):
    """A pin key that matches no produced sprite (a typo) silently no-ops the
    pin; the build must fail loud so the typo can't ship a hash-id sprite."""
    import pytest

    pixaki = _write_sprite_pixaki(tmp_path, '{"internalIds":{"Iconnn":5}}')
    with pytest.raises(ValueError, match="match no produced sprite"):
        p.build_sheet(str(pixaki), str(tmp_path / "s.png"))
