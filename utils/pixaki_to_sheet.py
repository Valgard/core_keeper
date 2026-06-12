"""Generate a Core Keeper mod sprite sheet (PNG + .meta) from a Pixaki file.

Iter-12 of the ItemChecklist mod: replaces the Item-Browser placeholder sprites
with original pixel art authored in Pixaki. Extracts the visible named layers,
dedups them by pixel hash, packs them into one sheet, and emits a Unity
sprite-sheet .png.meta with deterministic internalIDs.

Usage:
    python3 pixaki_to_sheet.py <file.pixaki> <out.png> --meta-template <ui_classic.png.meta>
"""
import json
import zipfile
import io
import hashlib
import argparse
import os
from dataclasses import dataclass
from PIL import Image

EXCLUDE_TOP = {"Outsorted", "Background", "Search Field Complete", "Dropdown Complete"}


@dataclass
class Layer:
    name: str
    drawing_id: str
    w: int
    h: int


def collect_layers(doc, exclude_top):
    """Return the visible, named, drawing-bearing layers, skipping the
    excluded top-level groups and any hidden layer."""
    sp = doc["sprites"][0]
    cel_size = {c["identifier"]: tuple(c["frame"][1])
                for c in sp.get("cels", []) if c.get("frame")}
    out = []

    def walk(node, top_excluded):
        if isinstance(node, dict):
            excl = top_excluded
            clips = node.get("clips")
            if clips and not excl and node.get("isVisible", True):
                for cl in clips:
                    it = cl.get("itemIdentifier")
                    if it in cel_size:
                        w, h = cel_size[it]
                        out.append(Layer(node.get("name"), it, w, h))
            for k, v in node.items():
                if isinstance(v, (list, dict)) and k != "name":
                    walk(v, excl)
        elif isinstance(node, list):
            for v in node:
                walk(v, top_excluded)

    # top-level layers: a name in exclude_top marks that whole subtree excluded
    for top in sp.get("layers", []):
        nm = top.get("name") if isinstance(top, dict) else None
        walk(top, bool(nm and nm in exclude_top))
    return out


def load_pixaki(path):
    """Return (document.json dict, {drawing_uuid: RGBA Image})."""
    with zipfile.ZipFile(path) as z:
        doc = json.loads(z.read("document.json"))
        drawings = {}
        for n in z.namelist():
            if n.startswith("images/drawings/") and n.endswith(".png"):
                uid = os.path.basename(n)[:-4]
                drawings[uid] = Image.open(io.BytesIO(z.read(n))).convert("RGBA")
    return doc, drawings


def _normalize(layer, drawings):
    """Return an RGBA image of exactly (layer.w, layer.h), top-left anchored."""
    src = drawings[layer.drawing_id]
    if src.size == (layer.w, layer.h):
        return src
    canvas = Image.new("RGBA", (layer.w, layer.h), (0, 0, 0, 0))
    canvas.alpha_composite(src, (0, 0))
    return canvas


def pixel_key(img):
    return hashlib.sha1(img.tobytes()).hexdigest() + f"_{img.width}x{img.height}"


def dedup(layers, drawings):
    """Return (distinct: list[(key, img, w, h)], name_to_key: dict)."""
    distinct = {}
    name_to_key = {}
    for layer in layers:
        img = _normalize(layer, drawings)
        key = pixel_key(img)
        distinct.setdefault(key, (key, img, layer.w, layer.h))
        name_to_key[layer.name] = key
    return list(distinct.values()), name_to_key


def assign_names(items):
    """items: list of (key, img_or_None, w, h, base_name).
    Returns {key: final_name}; appends ' WxH' when a base name repeats."""
    from collections import Counter
    base_counts = Counter(base for (_, _, _, _, base) in items)
    out = {}
    for key, _img, w, h, base in items:
        out[key] = f"{base} {w}x{h}" if base_counts[base] > 1 else base
    return out


def internal_id(name):
    """Stable signed-32-bit int from the final sprite name."""
    digest = hashlib.sha1(name.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "little", signed=True)


def pack(sprites, sheet_w=128, gutter=2):
    """sprites: list of (key, img_or_None, w, h) in the caller's deterministic order.
    Returns (placements: list of (key, x, y_bottomleft, w, h), sheet_w, sheet_h)."""
    cur_x, row_h, top = gutter, 0, gutter
    placed_top = []     # (key, x, top, w, h)
    for key, _img, w, h in sprites:
        if cur_x + w + gutter > sheet_w:
            top += row_h + gutter
            cur_x, row_h = gutter, 0
        placed_top.append((key, cur_x, top, w, h))
        cur_x += w + gutter
        row_h = max(row_h, h)
    sheet_h = top + row_h + gutter
    placements = [(key, x, sheet_h - t - h, w, h) for (key, x, t, w, h) in placed_top]
    return placements, sheet_w, sheet_h


# Base names that are 9-sliced chrome (default border {1,1,1,1} unless overridden).
SLICED = {
    "Entry Background", "Entry Toggled", "Entry Selected", "Field Background",
    "Dropdown Background", "Button Background", "Panel", "Rarity Border",
    "Scrollbar Background", "Scrollbar Handler", "Scrollbar Highlight", "Scrollbar Selector",
}
# (base_name, w, h) -> explicit border, overriding the SLICED default.
BORDER_OVERRIDE = {
    ("Window", 16, 16): (4, 4, 4, 4),
    ("Entry Background", 8, 1): (1, 0, 1, 0),   # option divider, horizontal-only
}


def border_for(name, w, h):
    """Border (left, bottom, right, top) for a sprite given its BASE name + size."""
    if (name, w, h) in BORDER_OVERRIDE:
        return BORDER_OVERRIDE[(name, w, h)]
    if name in SLICED:
        return (1, 1, 1, 1)
    return (0, 0, 0, 0)   # icons, caret, checkbox glyphs = simple


def _sprite_id(name):
    """Deterministic 32-hex per-sub-sprite spriteID (Unity's 128-bit handle)."""
    return hashlib.md5(name.encode("utf-8")).hexdigest()


def _sprite_block(s):
    left, bot, right, top = s["border"]
    return (
        "    - serializedVersion: 2\n"
        f"      name: {s['name']}\n"
        "      rect:\n"
        "        serializedVersion: 2\n"
        f"        x: {s['x']}\n"
        f"        y: {s['y']}\n"
        f"        width: {s['w']}\n"
        f"        height: {s['h']}\n"
        "      alignment: 0\n"
        "      pivot: {x: 0.5, y: 0.5}\n"
        f"      border: {{x: {left}, y: {bot}, z: {right}, w: {top}}}\n"
        "      customData: \n"
        "      outline: []\n"
        "      physicsShape: []\n"
        "      tessellationDetail: 0\n"
        "      bones: []\n"
        f"      spriteID: {_sprite_id(s['name'])}\n"
        f"      internalID: {s['internal_id']}\n"
        "      vertices: []\n"
        "      indices: \n"
        "      edges: []\n"
        "      weights: []\n"
    )


def render_meta(template_meta_path, new_guid, placements_named):
    """Reuse the template header/tail verbatim; replace guid + the whole
    spriteSheet block. placements_named: list of dict(name, internal_id, x, y,
    w, h, border)."""
    import re
    tpl = open(template_meta_path).read()
    head, rest = tpl.split("  spriteSheet:\n", 1)
    _, tail = rest.split("  mipmapLimitGroupName:", 1)
    tail = "  mipmapLimitGroupName:" + tail
    head = re.sub(r"^guid: [0-9a-f]{32}", f"guid: {new_guid}", head, count=1, flags=re.M)
    ordered = sorted(placements_named, key=lambda s: s["name"])
    sprites = "".join(_sprite_block(s) for s in ordered)
    name_table = "".join(f"      {s['name']}: {s['internal_id']}\n" for s in ordered)
    sheet = (
        "  spriteSheet:\n"
        "    serializedVersion: 2\n"
        "    sprites:\n"
        f"{sprites}"
        "    outline: []\n"
        "    customData: \n"
        "    physicsShape: []\n"
        "    bones: []\n"
        "    spriteID: 5e97eb03825dee720800000000000000\n"
        "    internalID: 0\n"
        "    vertices: []\n"
        "    indices: \n"
        "    edges: []\n"
        "    weights: []\n"
        "    secondaryTextures: []\n"
        "    spriteCustomMetadata:\n"
        "      entries: []\n"
        "    nameFileIdTable:\n"
        f"{name_table}"
    )
    return head + sheet + tail
