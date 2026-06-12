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
