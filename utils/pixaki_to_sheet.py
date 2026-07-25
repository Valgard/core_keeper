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

_CONFIG_DEFAULTS = {"exclude": [], "sliced": [], "borderOverride": [],
                    "rename": {}, "pad": {}, "internalIds": {},
                    "sheetWidth": 128, "gutter": 2, "guid": None}


def load_config(pixaki_path):
    """Load the sibling <name>.json sprite-def config for a .pixaki file.

    Missing keys fall back to _CONFIG_DEFAULTS; a missing .json raises
    FileNotFoundError."""
    cfg_path = os.path.splitext(pixaki_path)[0] + ".json"
    if not os.path.exists(cfg_path):
        raise FileNotFoundError(f"sprite-def config not found next to the .pixaki: {cfg_path}")
    data = json.load(open(cfg_path))
    c = dict(_CONFIG_DEFAULTS); c.update(data)
    c["exclude"] = set(c["exclude"])
    c["sliced"] = set(c["sliced"])
    c["borderOverride"] = {(b["name"], b["w"], b["h"]): tuple(b["border"]) for b in c["borderOverride"]}
    c["pad"] = {k: (v["w"], v["h"], (tuple(v["anchor"]) if isinstance(v["anchor"], list) else v["anchor"]))
                for k, v in c["pad"].items()}
    return c


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


def internal_id(name, pins=None):
    """Stable signed-32-bit int from the final sprite name.

    If pins is provided and contains name, return pins[name].
    Otherwise, return SHA1(name) as a signed 32-bit int."""
    if pins and name in pins:
        return pins[name]
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
# (base_name, final_w, final_h) -> explicit border, overriding the SLICED default.
# Folds back the user's manual Sprite-Editor border tweaks so a re-generate
# reproduces the hand-tuned sheet.
BORDER_OVERRIDE = {
    ("Window", 16, 16): (4, 4, 4, 4),
    ("Entry Selected", 8, 8): (3, 3, 3, 3),       # corner selection marker (3px L-corners)
    ("Entry Toggled", 10, 10): (4, 4, 4, 4),      # Iter-40 ItemRow tracked marker: 10x10, 4px L-corner brackets

    ("Scrollbar Selector", 4, 8): (1, 3, 1, 3),   # vertical 3px ends
    ("Caret", 2, 8): (0, 1, 0, 1),                # 1px top/bottom only
    ("Checkbox empty", 6, 6): (1, 1, 1, 1),       # thin box frame
}

# Manual Sprite-Editor renames, folded back in. Keyed by the auto-disambiguated
# name (base + ' WxH'); applied AFTER naming so the size-disambiguation of
# same-named layers stays intact. The internalID follows the FINAL name (the
# prefab refs were updated to match — see docs).
RENAME = {
    "Entry Background 8x1": "Option Background 8x8",
    "Panel": "Option Panel",
    # Iter-40: the ItemRow tracked-marker is a NEW 10x10 toggled frame, distinct from the
    # existing 8x8 "Entry Toggled" (which keeps its name + internalID 853627131, used elsewhere).
    # Both Pixaki layers are named "Entry Toggled"; assign_names size-disambiguates them, then
    # these renames give the 8x8 back its original name and the 10x10 its own sprite name.
    "Entry Toggled 8x8": "Entry Toggled",
    "Entry Toggled 10x10": "ItemRow Entry Toggled",
}
# Pad a sub-cell layer up to its full grid cell, anchoring the drawn content.
# Keyed by the disambiguated (pre-rename) name. The option separator is a 1px
# line drawn at the bottom of an 8x8 grid cell (the sprites live on a notional
# grid; this one is sub-cell and must be padded to the cell for 9-slicing).
PAD = {
    "Entry Background 8x1": (8, 8, "bottom"),
    # Unknown-item icon: pad the 6x11 "?" up to a 16x16 icon slot (item icons are
    # 16x16), placed at offset (left 5, top 3) -> horizontally centred, top-biased.
    "Unknown Object": (16, 16, (5, 3)),
}


def _pad(img, target_w, target_h, anchor):
    """Return img on a transparent target_w x target_h canvas. anchor is
    'bottom' (centred x, bottom y), a (left, top) offset tuple, or top-left."""
    canvas = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
    if anchor == "bottom":
        canvas.alpha_composite(img, ((target_w - img.width) // 2, target_h - img.height))
    elif isinstance(anchor, tuple):
        canvas.alpha_composite(img, anchor)
    else:  # top-left
        canvas.alpha_composite(img, (0, 0))
    return canvas


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


def build_sheet(pixaki_path, out_png, template_meta, guid=None):
    """Build the sheet PNG + .meta. Returns (mapping name->internalID, guid).
    guid: force the sheet GUID (so prefab refs stay valid); else derive from path."""
    doc, drawings = load_pixaki(pixaki_path)
    layers = collect_layers(doc, EXCLUDE_TOP)
    distinct, name_to_key = dedup(layers, drawings)
    # base name per key = first layer that produced it (recompute the key per
    # layer; name_to_key is lossy when one name maps to several distinct keys,
    # e.g. the 8x8/6x6 sort-icon size pairs)
    key_base = {}
    for layer in layers:
        key = pixel_key(_normalize(layer, drawings))
        key_base.setdefault(key, layer.name)
    items = [(k, img, w, h, key_base[k]) for (k, img, w, h) in distinct]
    names = assign_names(items)                       # {key: disambiguated name}
    # Fold in manual Sprite-Editor edits: pad sub-cell sprites up to their grid
    # cell (PAD, keyed by disambiguated name), then apply renames (RENAME).
    # internalID follows the FINAL (renamed) name.
    img_by_key, size_by_key = {}, {}
    for (k, img, w, h, _) in items:
        if names[k] in PAD:
            tw, th, anchor = PAD[names[k]]
            img = _pad(img, tw, th, anchor)
            w, h = tw, th
        img_by_key[k], size_by_key[k] = img, (w, h)
    names = {k: RENAME.get(v, v) for k, v in names.items()}
    items.sort(key=lambda it: names[it[0]])           # deterministic order
    placements, sw, sh = pack([(k, img_by_key[k], *size_by_key[k]) for (k, _, _, _, _) in items])
    sheet = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
    placed_named = []
    for key, x, y_bl, w, h in placements:
        top = sh - y_bl - h
        sheet.alpha_composite(img_by_key[key], (x, top))
        nm = names[key]
        placed_named.append(dict(
            name=nm, internal_id=internal_id(nm),
            x=x, y=y_bl, w=w, h=h,
            border=border_for(key_base[key], w, h),   # BASE name + final size
        ))
    sheet.save(out_png)
    new_guid = guid or hashlib.sha1(out_png.encode()).hexdigest()[:32]
    with open(out_png + ".meta", "w") as f:
        f.write(render_meta(template_meta, new_guid, placed_named))
    mapping = {s["name"]: s["internal_id"] for s in placed_named}
    return mapping, new_guid


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pixaki")
    ap.add_argument("out_png")
    ap.add_argument("--meta-template", required=True)
    ap.add_argument("--mapping-out", default=None)
    ap.add_argument("--guid", default=None, help="force sheet GUID (else derived from out path)")
    a = ap.parse_args()
    mapping, guid = build_sheet(a.pixaki, a.out_png, a.meta_template, guid=a.guid)
    if a.mapping_out:
        with open(a.mapping_out, "w") as f:
            json.dump({"guid": guid, "name_to_internal_id": mapping}, f, indent=1)
    print(f"sheet guid {guid}, {len(mapping)} distinct sprites")
    for nm in sorted(mapping):
        print(f"  {nm}: {mapping[nm]}")


if __name__ == "__main__":
    main()
