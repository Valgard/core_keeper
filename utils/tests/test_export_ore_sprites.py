"""Unit tests for the ore sprite export, on synthetic AssetRipper trees.

The two places a wrong export would still look right are the atlas crop and the
tileset filter: a y-flip off by one row yields a believable but shifted icon,
and a texture map sharing a tileset's folder once overwrote the real veins. No
test reads the real decompile checkout -- scanning it takes the whole Assets tree.
"""

import pytest
from export_ore_sprites import ORE_COLUMN
from export_ore_sprites import TILESET_HEIGHT
from export_ore_sprites import WALL_ORE_DIRS
from export_ore_sprites import Exporter
from export_ore_sprites import ores_from_enum
from PIL import Image

GUID = "0123456789abcdef0123456789abcdef"


def _sprite_tree(tmp_path, x, y, w, h):
    """A 10x8 sheet whose every pixel encodes its own PNG coordinates, plus one Sprite."""
    assets = tmp_path / "Assets"
    (assets / "Texture2D").mkdir(parents=True)
    (assets / "Sprite").mkdir()
    sheet = Image.new("RGBA", (10, 8))
    for px in range(10):
        for py in range(8):
            sheet.putpixel((px, py), (px, py, 0, 255))
    sheet.save(assets / "Texture2D/atlas.png")
    (assets / "Texture2D/atlas.png.meta").write_text(f"fileFormatVersion: 2\nguid: {GUID}\n")
    (assets / "Sprite/probe.asset").write_text(
        "%YAML 1.1\n--- !u!213 &21300000\nSprite:\n  m_Name: probe\n"
        f"  m_Rect:\n    serializedVersion: 2\n    x: {x}\n    y: {y}\n"
        f"    width: {w}\n    height: {h}\n"
        "  m_RD:\n    serializedVersion: 3\n"
        f"    texture: {{fileID: 2800000, guid: {GUID}, type: 3}}\n"
    )
    return assets


def test_sprite_crop_flips_bottom_left_rect_into_png_rows(tmp_path):
    """Unity rect y=1 from the bottom of an 8-row sheet, height 2, is PNG rows 5 and 6."""
    assets = _sprite_tree(tmp_path, x=2, y=1, w=3, h=2)
    img = Exporter(assets, tmp_path / "out").sprite("probe")
    assert img.size == (3, 2)
    assert [img.getpixel((c, r))[:2] for r in range(2) for c in range(3)] == [
        (2, 5), (3, 5), (4, 5),
        (2, 6), (3, 6), (4, 6),
    ]  # fmt: skip


def _sheet(path, with_ore=True, height=TILESET_HEIGHT):
    """A blank tileset sheet, optionally with one vein pixel inside the ore column."""
    path.parent.mkdir(parents=True, exist_ok=True)
    im = Image.new("RGBA", (336, height))
    if with_ore:
        im.putpixel((ORE_COLUMN[0] + 3, ORE_COLUMN[1] + 20), (200, 100, 0, 255))
    im.save(path)


def _tileset_tree(tmp_path):
    """Three real ore sheets among every kind of file the filter has to leave out."""
    assets = tmp_path / "Assets"
    root = assets / "Art/Tilesets"
    _sheet(root / "Dirt/NoSeason/dirt_tileset.png")
    _sheet(root / "Dirt/Easter/dirt_tileset_easter.png")
    _sheet(root / "Crystal/NoSeason/crystal_tileset.png")
    _sheet(root / "Crystal/NoSeason/crystal_tileset_normal.png")  # singular, as in the game
    _sheet(root / "Crystal/NoSeason/crystal_tileset_emissive.png")
    _sheet(root / "Dirt/NoSeason/tileset_Dirt_wall.png")  # per-layer file
    _sheet(root / "Sand/NoSeason/sand_tileset.png", with_ore=False)
    _sheet(root / "Extras/NoSeason/special_tileset.png", height=512)
    return assets


def test_wall_ore_keeps_colour_sheets_and_drops_maps_and_layers(tmp_path, monkeypatch):
    """Normal and emissive maps, per-layer files, empty and odd-sized sheets stay out."""
    monkeypatch.setattr("export_ore_sprites.WALL_ORE_DIRS", {"Dirt", "Dirt_Easter", "Crystal"})
    strips = Exporter(_tileset_tree(tmp_path), tmp_path / "out")._wall_ore_sheets()
    assert set(strips) == {"Dirt", "Dirt_Easter", "Crystal"}
    assert strips["Crystal"].size == (16, 48)
    assert strips["Crystal"].getpixel((3, 20)) == (200, 100, 0, 255)


def test_wall_ore_aborts_when_two_sheets_claim_one_tileset(tmp_path, monkeypatch):
    """A map the suffix filter does not know must stop the run, not overwrite the veins."""
    monkeypatch.setattr("export_ore_sprites.WALL_ORE_DIRS", {"Dirt", "Dirt_Easter", "Crystal"})
    assets = _tileset_tree(tmp_path)
    _sheet(assets / "Art/Tilesets/Crystal/NoSeason/crystal_tileset_normalmap.png")
    with pytest.raises(SystemExit, match="both export to Crystal"):
        Exporter(assets, tmp_path / "out")._wall_ore_sheets()


def test_wall_ore_aborts_when_the_vein_set_drifts(tmp_path):
    """The pinned 1.3.0.4 set against a tree holding only three of its tilesets."""
    assert {"Dirt", "Crystal"} <= WALL_ORE_DIRS
    with pytest.raises(SystemExit, match="wall-ore tilesets changed"):
        Exporter(_tileset_tree(tmp_path), tmp_path / "out")._wall_ore_sheets()


ENUM = """\
public enum Biome
{
	CopperOre = 7,
}
public enum ObjectID
{
	None = 0,
	CopperOre = 1500,
	MoonOre = 1599,
	Core = 30,
	OreAndBlockPouch = 8450,
	CopperOreBoulder = 2200,
}
public enum Other
{
	TinOreBoulder = 9,
}
"""


def test_ores_come_from_the_object_id_enum_only(tmp_path):
    """Members outside ObjectID, `Core` and `OreAndBlockPouch` are no ores; Moon has no boulder."""
    source = tmp_path / "Pug.Base.decompiled.cs"
    source.write_text(ENUM)
    assert ores_from_enum(source) == (["copper", "moon"], {"copper"})


def test_a_boulder_without_its_ore_item_aborts(tmp_path):
    """A boulder named after no ore item means the naming rule no longer holds."""
    source = tmp_path / "Pug.Base.decompiled.cs"
    source.write_text(ENUM.replace("\tCopperOre = 1500,\n", ""))
    with pytest.raises(SystemExit, match="boulders without an ore item"):
        ores_from_enum(source)


def test_a_missing_enum_aborts(tmp_path):
    """No decompile next to the asset dump is an error, not an empty ore list."""
    with pytest.raises(SystemExit, match="no decompiled ObjectID enum"):
        ores_from_enum(tmp_path / "Pug.Base.decompiled.cs")
