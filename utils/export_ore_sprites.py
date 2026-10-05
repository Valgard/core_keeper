#!/usr/bin/env python3
"""Export every ore and ore-boulder sprite from the AssetRipper data dump as plain PNGs.

The sprites sit in three different shapes, and each needs its own handling:

- **Item icons, boulder icons and the shimmer frames** are `Sprite` assets cut
  from atlas sheets. Each is cropped by its `m_Rect`, whose origin is
  bottom-left while PNG rows run top-down, so y is flipped.
- **Boulder world graphics** are standalone textures in this dump, matched to
  their ore by file name. The copper boulder has no `_copper` texture: it is the
  base `oreBoulder.png`. Its shadow, by contrast, does carry the suffix.
- **Ore veins in walls** have no asset of their own. They are a region of the
  tileset sheets, and AssetRipper serializes no fields for the layer definitions
  that would say where (`TilesetLayerDefinitionDataBlock`), so the region below
  was read off the images. Which ore a tileset yields is not in the dump either
  -- the output is named by tileset, not by ore.

Usage:
    uv run utils/export_ore_sprites.py [<out-dir>] [--resources <dir>]

<out-dir> defaults to `ore_sprites/` in the current directory and must be empty
or absent, so an export never mixes with one from an earlier game build.
--resources defaults to the canonical decompile checkout's `Resources/`.

Everything the game data could quietly change after an update is pinned below
-- the ore list, which ores glow, which tilesets carry veins -- and a mismatch
aborts the run. A silent skip would hand over an export that looks complete.
"""

import argparse
import re
import shutil
import sys
from pathlib import Path

from PIL import Image

DEFAULT_RESOURCES = Path.home() / "Projects/checkouts/CoreKeeperDecompile/Resources"
ORES = [
    "copper",
    "tin",
    "iron",
    "gold",
    "scarlet",
    "octarine",
    "galaxite",
    "solarite",
    "pandorium",
    "relucite",
]

# Boulders with an extra emissive texture.
EMISSIVE_ORES = {"solarite"}

# Ore layer of the shared tileset layout: three 16x16 cells, PNG coordinates.
ORE_COLUMN = (176, 128, 192, 176)
TILESET_HEIGHT = 416
# Companion maps beside a colour sheet; the singular `_normal` occurs too (Crystal).
MAP_SUFFIXES = ("_normal", "_normals", "_emissive")
# Every tileset/season whose ore column held veins in 1.3.0.4. Re-derive and update
# after a game update that changes it; the run refuses to guess.
WALL_ORE_DIRS = {
    "Clay", "Clay_Easter", "Clay_Valentine", "Crystal", "Desert", "Desert_Valentine",
    "Dirt", "Dirt_Christmas", "Dirt_Easter", "Dirt_Valentine", "ExcavationRock",
    "LarvaHive", "LarvaHive_Valentine", "Nature", "Nature_Easter", "Nature_Valentine",
    "Oasis", "Obsidian", "Obsidian_Valentine", "Sea", "Sea_Valentine",
    "Stone", "Stone_Christmas", "Stone_Easter", "Stone_Valentine",
}  # fmt: skip

RECT = re.compile(
    r"m_Rect:\s*\n\s*serializedVersion: \d+\s*\n"
    r"\s*x: ([\d.]+)\s*\n\s*y: ([\d.]+)\s*\n"
    r"\s*width: ([\d.]+)\s*\n\s*height: ([\d.]+)"
)


class Exporter:
    """Writes the sprites below `out`, resolving them against one AssetRipper `Assets/` tree."""

    def __init__(self, assets: Path, out: Path) -> None:
        """Index every GUID and every Sprite asset once; lookups afterwards are by name."""
        self.assets = assets
        self.out = out
        self.written = 0
        self.textures = self._index_guids()
        self.sprites = self._index_sprites()

    def _index_guids(self) -> dict[str, Path]:
        index = {}
        for meta in self.assets.rglob("*.meta"):
            m = re.search(r"^guid: ([0-9a-f]{32})", meta.read_text(errors="ignore"), re.M)
            if m:
                index[m.group(1)] = meta.with_suffix("")
        return index

    def _index_sprites(self) -> dict[str, list[Path]]:
        index: dict[str, list[Path]] = {}
        for p in self.assets.rglob("*.asset"):
            with p.open(errors="ignore") as f:
                if "!u!213" in f.read(300):  # 213 = Sprite
                    index.setdefault(p.stem, []).append(p)
        return index

    def _target(self, rel: str) -> Path:
        p = self.out / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        self.written += 1
        return p

    def save(self, img: Image.Image, rel: str) -> None:
        """Write an image to `rel` below the output directory."""
        img.save(self._target(rel))

    def copy(self, src: Path, rel: str) -> None:
        """Copy a texture file unchanged to `rel` below the output directory."""
        shutil.copyfile(src, self._target(rel))

    def sprite(self, name: str) -> Image.Image:
        """Cut a Sprite out of its sheet; m_Rect is bottom-left origin, PNG rows run top-down."""
        hits = self.sprites.get(name, [])
        if len(hits) != 1:
            sys.exit(f"sprite {name}: expected exactly one asset, found {len(hits)}")
        text = hits[0].read_text()
        rect = RECT.search(text)
        guid = re.search(r"texture: \{fileID: 2800000, guid: ([0-9a-f]{32})", text)
        if not rect or not guid or guid.group(1) not in self.textures:
            sys.exit(f"sprite {name}: cannot resolve rect or texture in {hits[0]}")
        x, y, w, h = (round(float(v)) for v in rect.groups())
        sheet = Image.open(self.textures[guid.group(1)]).convert("RGBA")
        return sheet.crop((x, sheet.height - y - h, x + w, sheet.height - y))

    def texture(self, name: str) -> Path:
        """Path of a standalone texture; a missing one aborts rather than leaving a gap."""
        p = self.assets / "Texture2D" / f"{name}.png"
        if not p.is_file():
            sys.exit(f"texture missing: {p}")
        return p

    def run(self) -> None:
        """Export items, boulders, boulder debris, wall veins and the shimmer effect."""
        tex = self.assets / "Texture2D"
        # Every boulder has a shadow, so the shadows name the ores the game ships.
        shipped = {
            f.stem.removeprefix("oreBoulder_shadow_") for f in tex.glob("oreBoulder_shadow_*.png")
        }
        expect(shipped == set(ORES), "ores", set(ORES), shipped)
        glowing = {
            f.stem.removeprefix("oreBoulder_").removesuffix("_emissive")
            for f in tex.glob("oreBoulder_*_emissive.png")
        }
        expect(glowing == EMISSIVE_ORES, "emissive boulders", EMISSIVE_ORES, glowing)
        veins = self._wall_ore_sheets()

        for ore in ORES:
            self.save(self.sprite(f"lootsprite_{ore}Ore"), f"items/{ore}_ore/icon.png")
            self.save(self.sprite(f"lootsprite_{ore}Ore_small"), f"items/{ore}_ore/icon_small.png")

        for ore in ORES:
            d = f"boulders/{ore}_ore_boulder"
            self.copy(
                self.texture("oreBoulder" if ore == "copper" else f"oreBoulder_{ore}"),
                f"{d}/world.png",
            )
            self.copy(self.texture(f"oreBoulder_shadow_{ore}"), f"{d}/shadow.png")
            if ore in EMISSIVE_ORES:
                self.copy(self.texture(f"oreBoulder_{ore}_emissive"), f"{d}/world_emissive.png")
            self.save(self.sprite(f"lootsprite_{ore}OreBoulder"), f"{d}/icon.png")
            self.save(self.sprite(f"lootsprite_{ore}OreBoulder_small"), f"{d}/icon_small.png")

        for kind in ("front", "back"):
            debris = [
                f
                for f in sorted(tex.glob(f"oreBoulder_{kind}Debris*.png"))
                if not f.stem.endswith(MAP_SUFFIXES)
            ]
            if not debris:
                sys.exit(f"no oreBoulder_{kind}Debris textures in {tex}")
            for f in debris:
                biome = f.stem.removeprefix(f"oreBoulder_{kind}Debris").lstrip("_") or "default"
                self.copy(f, f"boulders/_debris/{kind}_{biome}.png")

        for d, strip in veins.items():
            self.save(strip, f"wall_ore/{d}/strip.png")
            for i in range(3):
                self.save(strip.crop((0, i * 16, 16, i * 16 + 16)), f"wall_ore/{d}/cell_{i}.png")

        for i in range(3):
            self.save(self.sprite(f"ore_blinking_{i}"), f"effects/ore_blinking_{i}.png")

    def _wall_ore_sheets(self) -> dict[str, Image.Image]:
        """Collect the ore column of every biome tileset, checked before anything is written."""
        seen: dict[str, Path] = {}
        strips: dict[str, Image.Image] = {}
        for f in sorted((self.assets / "Art/Tilesets").glob("*/*/*.png")):
            # The combined layout sheets; the per-layer `tileset_<Biome>_<layer>` files hold no ore.
            if (
                f.stem.startswith("tileset_")
                or "tileset" not in f.stem.lower()
                or f.stem.endswith(MAP_SUFFIXES)
            ):
                continue
            im = Image.open(f).convert("RGBA")
            if im.height != TILESET_HEIGHT:
                continue
            strip = im.crop(ORE_COLUMN)
            if not strip.getbbox():  # no veins: building, dungeon or ore-less biome sheets
                continue
            tileset, season = f.parts[-3], f.parts[-2]
            d = tileset + ("" if season == "NoSeason" else f"_{season}")
            # Two sheets for one tileset -- a map MAP_SUFFIXES does not know, or a second
            # colour sheet -- would let the later one silently overwrite the first.
            if d in seen:
                sys.exit(f"{f} and {seen[d]} both export to {d}")
            seen[d] = f
            strips[d] = strip
        expect(set(strips) == WALL_ORE_DIRS, "wall-ore tilesets", WALL_ORE_DIRS, set(strips))
        return strips


def expect(ok: bool, what: str, pinned: set[str], found: set[str]) -> None:
    """Abort when the game data no longer matches what this script was verified against."""
    if not ok:
        sys.exit(f"{what} changed: missing {sorted(pinned - found)}, new {sorted(found - pinned)}")


def main() -> None:
    """Parse the arguments and run the export."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("out", nargs="?", default="ore_sprites", type=Path)
    parser.add_argument("--resources", default=DEFAULT_RESOURCES, type=Path)
    args = parser.parse_args()
    assets = args.resources / "Assets"
    if not assets.is_dir():
        sys.exit(f"no AssetRipper export at {assets}")
    if args.out.exists() and any(args.out.iterdir()):
        sys.exit(f"{args.out} is not empty; move it away first")
    exporter = Exporter(assets, args.out)
    exporter.run()
    print(f"{exporter.written} files -> {args.out}")


if __name__ == "__main__":
    main()
