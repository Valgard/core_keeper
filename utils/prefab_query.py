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
  prefab_query.py <prefab> tree [Name]        # GO parent/child hierarchy (from Name, else all roots)
"""
import re
import sys
import yaml

CLASS = {  # the handful of Unity class IDs this project authors
    "1": "GameObject", "4": "Transform", "65": "BoxCollider",
    "114": "MonoBehaviour", "212": "SpriteRenderer",
}
_HEADER = re.compile(r"!u!(\d+)\s+&(\d+)")


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
    return [str(c["component"]["fileID"]) for c in body["GameObject"].get("m_Component", [])]


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
        cgo = str(objs[ct][1]["Transform"]["m_GameObject"]["fileID"])
        out.append(cgo)
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


def print_tree(objs, fid, depth=0):
    cid, body = objs.get(fid, (None, None))
    go = (body or {}).get("GameObject", {}) if body else {}
    name = go.get("m_Name") or "(unnamed)"
    mark = "" if go.get("m_IsActive", 1) else "  [inactive]"
    print("  " * depth + f"- {name}{mark}")
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
        ccid = objs.get(c, ('?',))[0]
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
    else:
        print("unknown command", cmd)


if __name__ == "__main__":
    main()
