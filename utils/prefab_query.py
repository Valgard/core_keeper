#!/usr/bin/env python3
"""Reliable Unity prefab/scene YAML inspection.

Unity YAML is multi-document with a per-file `%TAG !u! tag:unity3d.com,2011:`
directive and `--- !u!<classID> &<fileID>` document headers. Standard YAML
parsers (PyYAML/yq) trip over the `!u!` tag handle on documents 2..N because the
%TAG directive only applies to the first document. This module sidesteps that:
it splits documents on the `--- ` marker, parses the `!u!<classID> &<fileID>`
header itself, and feeds only the (standard-YAML) body to PyYAML.

Result: a dict `fileID -> (classID, body)` you can query without brittle
grep/awk/sed tracing of fileID references.

CLI:
  prefab_query.py <prefab> dump-go <Name>     # a GameObject's components + children (+ sprites)
  prefab_query.py <prefab> names              # all named GameObjects (name -> fileID)
  prefab_query.py <prefab> sprite <fileID>    # the m_Sprite of a SpriteRenderer fileID
  prefab_query.py <prefab> tree [Name]        # GO hierarchy + component types + active flag
  prefab_query.py <prefab> verify             # orphans / broken m_Script / dangling refs (exit 1 if any)
"""

import glob
import os
import re
import struct
import sys
import yaml

CLASS = {  # the handful of Unity class IDs this project authors
    "1": "GameObject",
    "4": "Transform",
    "65": "BoxCollider",
    "114": "MonoBehaviour",
    "212": "SpriteRenderer",
}
# Core Keeper game-DLL scripts, keyed by the m_Script fileID — a stable,
# install-independent hash of the class: the first 4 bytes (LE, signed int32) of
# MD4("s\0\0\0" + namespace + className). All of these live in the global
# namespace. Values were derived by that hash and cross-checked against the
# classes' actual placement in this repo's prefabs. Mod scripts all share fileID
# 11500000 and are told apart by guid instead, so they fall back to a short guid
# in comp_label. To add more: hash the class name (see the
# script-fileid-derivation memory) — do NOT eyeball it.
SCRIPT_FILEID = {
    # Text
    "1873953792": "PugText",
    "1139742956": "PugTextEffectMenuOption",
    "1793966478": "PugTextEffectJuicyAppear",
    # Layout / structure
    "-2136513284": "LinearLayoutUIComponent",
    "-601971722": "WrapperUIComponent",
    "-1334111655": "InheritPlacementFromUIComponent",
    # Scrolling
    "197547074": "UIScrollWindow",
    "-277093456": "ScrollBar",
    "-1490357010": "ScrollBarHandle",
    # UI elements / misc
    "-685432232": "BlockingUIElement",
    "-1087151945": "CharacterMarkBlinker",
    # Item / object authoring (non-UI; appears in item prefabs)
    "244469479": "InventoryItemAuthoring",
    "318086258": "ObjectAuthoring",
}
_HEADER = re.compile(r"!u!(-?\d+)\s+&(-?\d+)")


def _md4(msg):
    """Pure-Python MD4 (RFC 1320) — OpenSSL 3 disables hashlib's md4."""

    def lrot(x, n):
        x &= 0xFFFFFFFF
        return ((x << n) | (x >> (32 - n))) & 0xFFFFFFFF

    ml = len(msg) * 8
    msg = msg + b"\x80"
    while len(msg) % 64 != 56:
        msg += b"\x00"
    msg += struct.pack("<Q", ml)

    a, b, c, d = 0x67452301, 0xEFCDAB89, 0x98BADCFE, 0x10325476
    for off in range(0, len(msg), 64):
        X = list(struct.unpack("<16I", msg[off : off + 64]))
        aa, bb, cc, dd = a, b, c, d

        def F(x, y, z):
            return (x & y) | (~x & z)

        def G(x, y, z):
            return (x & y) | (x & z) | (y & z)

        def H(x, y, z):
            return x ^ y ^ z

        for i in (0, 4, 8, 12):
            a = lrot(a + F(b, c, d) + X[i], 3)
            d = lrot(d + F(a, b, c) + X[i + 1], 7)
            c = lrot(c + F(d, a, b) + X[i + 2], 11)
            b = lrot(b + F(c, d, a) + X[i + 3], 19)
        for i in (0, 1, 2, 3):
            a = lrot(a + G(b, c, d) + X[i] + 0x5A827999, 3)
            d = lrot(d + G(a, b, c) + X[i + 4] + 0x5A827999, 5)
            c = lrot(c + G(d, a, b) + X[i + 8] + 0x5A827999, 9)
            b = lrot(b + G(c, d, a) + X[i + 12] + 0x5A827999, 13)
        for i in (0, 2, 1, 3):
            a = lrot(a + H(b, c, d) + X[i] + 0x6ED9EBA1, 3)
            d = lrot(d + H(a, b, c) + X[i + 8] + 0x6ED9EBA1, 9)
            c = lrot(c + H(d, a, b) + X[i + 4] + 0x6ED9EBA1, 11)
            b = lrot(b + H(c, d, a) + X[i + 12] + 0x6ED9EBA1, 15)

        a = (a + aa) & 0xFFFFFFFF
        b = (b + bb) & 0xFFFFFFFF
        c = (c + cc) & 0xFFFFFFFF
        d = (d + dd) & 0xFFFFFFFF
    return struct.pack("<4I", a, b, c, d)


def fileid(name, namespace=""):
    """Unity script fileID: signed int32 of the first 4 bytes of
    MD4("s\\0\\0\\0" + namespace + className)."""
    data = b"s\x00\x00\x00" + (namespace + name).encode("utf-8")
    return struct.unpack("<i", _md4(data)[:4])[0]


_SCRIPT_ROOTS = frozenset({"MonoBehaviour", "ScriptableObject"})


def is_component(name, base_of, _seen=None):
    """True iff name transitively derives from MonoBehaviour/ScriptableObject."""
    if name in _SCRIPT_ROOTS:
        return True
    _seen = _seen if _seen is not None else set()
    if name in _seen or name not in base_of:
        return False
    _seen.add(name)
    base = base_of[name]
    return bool(base) and is_component(base, base_of, _seen)


_NS_RE = re.compile(r"^\s*namespace\s+([A-Za-z_][\w.]*)")
_DECL_RE = re.compile(
    r"^\s*(?:\[[^\]]*\]\s*)*"
    r"(?:public|internal|private|protected|sealed|abstract|static|partial|unsafe|new|\s)*"
    r"\bclass\s+([A-Za-z_]\w*)(?:<[^>]*>)?"
    r"(?:\s*:\s*([A-Za-z_][\w.]*))?"
)


def parse_decompile(decomp_dir):
    """Scan *.decompiled.cs -> (base_of, ns_of). Tracks the current namespace
    via brace depth; records each class's first base token and namespace."""
    base_of, ns_of = {}, {}
    for path in sorted(glob.glob(os.path.join(decomp_dir, "*.decompiled.cs"))):
        stack, depth, pending = [], 0, None
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                m = _NS_RE.match(line)
                if m:
                    pending = m.group(1)
                d = _DECL_RE.match(line)
                if d:
                    name = d.group(1)
                    cur_ns = stack[-1][0] if stack else ""
                    base_of.setdefault(name, d.group(2))
                    ns_of.setdefault(name, cur_ns)
                for _ in range(line.count("{")):
                    depth += 1
                    if pending is not None:
                        stack.append((pending, depth))
                        pending = None
                for _ in range(line.count("}")):
                    if stack and stack[-1][1] == depth:
                        stack.pop()
                    depth -= 1
    return base_of, ns_of


def build_script_ids(base_of, ns_of):
    """{str(fileID): className} for MonoBehaviour/ScriptableObject-derived types.
    Raises ValueError listing every colliding pair on a hash collision."""
    out, collisions = {}, []
    for name in sorted(base_of):
        if not is_component(name, base_of):
            continue
        fid = str(fileid(name, ns_of.get(name, "")))
        if fid in out:
            collisions.append((fid, out[fid], name))
        else:
            out[fid] = name
    if collisions:
        body = "\n".join(f"  {fid}: {a} vs {b}" for fid, a, b in collisions)
        raise ValueError(f"fileID hash collisions:\n{body}")
    return out


def load(path):
    """Return {fileID(str): (classID(str), body(dict))}."""
    text = open(path).read()
    objs = {}
    for chunk in re.split(r"^--- ", text, flags=re.M)[1:]:
        header, _, body = chunk.partition("\n")
        m = _HEADER.search(header)
        if not m:
            continue
        classid, fid = m.group(1), m.group(2)
        try:
            d = yaml.safe_load(body)
        except yaml.YAMLError:
            d = None
        objs[fid] = (classid, d)
    return objs


def _go_name(body):
    return (body or {}).get("GameObject", body).get("m_Name") if body else None


def go_name(objs, fid):
    cid, body = objs.get(fid, (None, None))
    if cid == "1" and body:
        return body["GameObject"].get("m_Name", "")
    return None


def find_go(objs, name):
    for fid, (cid, body) in objs.items():
        if cid == "1" and body and body["GameObject"].get("m_Name") == name:
            return fid
    return None


def components(objs, go_fid):
    cid, body = objs[go_fid]
    return [
        str(c["component"]["fileID"]) for c in body["GameObject"].get("m_Component", [])
    ]


def transform_of(objs, go_fid):
    for c in components(objs, go_fid):
        if objs.get(c, (None,))[0] == "4":
            return c
    return None


def children(objs, go_fid):
    t = transform_of(objs, go_fid)
    if not t:
        return []
    body = objs[t][1]["Transform"]
    kids = body.get("m_Children") or []
    out = []
    for k in kids:
        ct = str(k["fileID"])
        node = objs.get(ct)
        if not node or not node[1]:
            continue  # dangling child transform — skip (verify reports it separately)
        cgo = node[1].get("Transform", {}).get("m_GameObject", {}).get("fileID")
        if cgo is not None:
            out.append(str(cgo))
    return out


def roots(objs):
    """GameObject fileIDs whose transform has no parent (m_Father fileID 0)."""
    out = []
    for fid, (cid, body) in objs.items():
        if cid != "1" or not body:
            continue
        t = transform_of(objs, fid)
        if not t:
            continue
        father = objs[t][1]["Transform"].get("m_Father", {}).get("fileID")
        if str(father) == "0":
            out.append(fid)
    return out


def comp_label(objs, comp_fid):
    """Human-readable type for a component fileID: the Unity class name, or for a
    MonoBehaviour the resolved CK script name (else a short guid)."""
    cid, body = objs.get(comp_fid, (None, None))
    if cid != "114":
        return CLASS.get(cid, f"class{cid}")
    sc = (body or {}).get("MonoBehaviour", {}).get("m_Script", {}) if body else {}
    return (
        SCRIPT_FILEID.get(str(sc.get("fileID")))
        or f"MonoBehaviour[{str(sc.get('guid', ''))[:8]}]"
    )


def print_tree(objs, fid, depth=0):
    cid, body = objs.get(fid, (None, None))
    go = (body or {}).get("GameObject", {}) if body else {}
    name = go.get("m_Name") or "(unnamed)"
    mark = "" if go.get("m_IsActive", 1) else "  [inactive]"
    comps = [
        comp_label(objs, c)
        for c in components(objs, fid)
        if objs.get(c, (None,))[0] != "4"
    ]  # skip the implicit Transform
    ctext = f"  :: {', '.join(comps)}" if comps else ""
    print("  " * depth + f"- {name}{mark}{ctext}")
    for cgo in children(objs, fid):
        print_tree(objs, cgo, depth + 1)


def sprite_of(objs, go_fid):
    """The m_Sprite guid:fileID of the SpriteRenderer on this GO, if any."""
    for c in components(objs, go_fid):
        cid, body = objs.get(c, (None, None))
        if cid == "212" and body:
            s = body["SpriteRenderer"].get("m_Sprite", {})
            return f"fileID:{s.get('fileID')} guid:{s.get('guid')}"
    return None


def dump_go(objs, name):
    fid = find_go(objs, name)
    if not fid:
        print(f"GameObject '{name}' not found")
        return
    cid, body = objs[fid]
    go = body["GameObject"]
    print(f"{name}  (fileID {fid})  active={go.get('m_IsActive')}")
    for c in components(objs, fid):
        ccid = objs.get(c, ("?",))[0]
        line = f"  - {CLASS.get(ccid, ccid)}"
        if ccid == "212":
            line += f"   sprite={sprite_of(objs, fid)}"
        if ccid == "114":
            sc = objs[c][1]["MonoBehaviour"].get("m_Script", {})
            line += f"   script-guid={sc.get('guid')}"
        print(line)
    print("  children:")
    for cgo in children(objs, fid):
        print(f"    - {go_name(objs, cgo) or '(?)':18} sprite={sprite_of(objs, cgo)}")


def verify(objs):
    """Integrity checks: orphan GameObjects (unreachable from any root), broken
    m_Script refs (fileID 0), and dangling component/child fileIDs (referenced but
    absent from the file). Prints findings; returns the problem count (0 == clean)."""
    problems = 0

    # 1. Reachability from root transforms (children() already skips dangling refs).
    reachable = set()
    stack = list(roots(objs))
    while stack:
        go = stack.pop()
        if go in reachable:
            continue
        reachable.add(go)
        stack.extend(children(objs, go))
    orphans = [
        fid
        for fid, (cid, body) in objs.items()
        if cid == "1" and body and fid not in reachable
    ]
    if orphans:
        print(f"ORPHAN GameObjects (unreachable from any root): {len(orphans)}")
        for fid in orphans:
            print(f"  - {go_name(objs, fid) or '(unnamed)'}  (fileID {fid})")
        problems += len(orphans)

    # 2. Broken MonoBehaviour script references.
    broken = [
        fid
        for fid, (cid, body) in objs.items()
        if cid == "114"
        and body
        and str((body.get("MonoBehaviour") or {}).get("m_Script", {}).get("fileID"))
        == "0"
    ]
    if broken:
        print(f"BROKEN script refs (m_Script fileID 0): {len(broken)}")
        for fid in broken:
            print(f"  - MonoBehaviour fileID {fid}")
        problems += len(broken)

    # 3. Dangling references: component / m_Children fileIDs not present in the file.
    dangling = []
    for fid, (cid, body) in objs.items():
        if not body:
            continue
        if cid == "1":
            for c in body["GameObject"].get("m_Component", []):
                cf = str(c["component"]["fileID"])
                if cf != "0" and cf not in objs:
                    dangling.append((fid, "component", cf))
        elif cid == "4":
            for k in body["Transform"].get("m_Children") or []:
                kf = str(k["fileID"])
                if kf != "0" and kf not in objs:
                    dangling.append((fid, "m_Children", kf))
    if dangling:
        print(f"DANGLING references (fileID absent from file): {len(dangling)}")
        for owner, kind, ref in dangling:
            print(f"  - {kind} {ref}  <- referenced by fileID {owner}")
        problems += len(dangling)

    if problems == 0:
        print("OK — no orphans, broken script refs, or dangling references.")
    return problems


def main():
    path, cmd = sys.argv[1], sys.argv[2]
    objs = load(path)
    if cmd == "names":
        for fid, (cid, body) in objs.items():
            if cid == "1":
                n = body["GameObject"].get("m_Name", "")
                if n:
                    print(f"{fid}\t{n}")
    elif cmd == "dump-go":
        dump_go(objs, sys.argv[3])
    elif cmd == "sprite":
        print(sprite_of(objs, sys.argv[3]))
    elif cmd == "tree":
        if len(sys.argv) > 3:
            fid = find_go(objs, sys.argv[3])
            if not fid:
                print(f"GameObject '{sys.argv[3]}' not found")
                return
            print_tree(objs, fid)
        else:
            for r in roots(objs):
                print_tree(objs, r)
    elif cmd == "verify":
        sys.exit(1 if verify(objs) else 0)
    else:
        print("unknown command", cmd)


if __name__ == "__main__":
    main()
