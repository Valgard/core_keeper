#!/usr/bin/env python3
"""Import a decompiled Core Keeper vanilla prefab into a mod's `unity/` tree,
made SDK/Editor-usable.

The AssetRipper Resources export (see the `reference_ck_assetripper_resources_unpack`
memory) is a read-only data dump: its prefabs reference game classes under
AssetRipper's *per-assembly* export GUIDs, which the SDK doesn't know -> "Missing
Script" if imported raw. This tool copies a prefab + its transitive asset
dependencies and remaps EVERY `m_Script` assembly-GUID from the AssetRipper GUID
to *this* SDK clone's real DLL GUID. The class fileIDs are portable MD4 hashes,
so they are left untouched. Asset deps (sprites/textures/materials/shaders) keep
their GUIDs (copying the file makes the ref resolve).

Usage:
    import_vanilla_prefab.py <PrefabName|path/to.prefab> <dest-dir>

Example:
    import_vanilla_prefab.py UISettings mod-settings-menu/unity/ModSettingsMenu/_vanilla_ref
"""
import os
import re
import shutil
import sys

RES = os.path.expanduser("~/Projects/checkouts/CoreKeeperDecompile/Resources")
SDK = os.path.expanduser("~/Projects/private/core_keeper/CoreKeeperModSDK")
GUID_RE = re.compile(r"guid: ([a-f0-9]{32})")
# Unity built-in / AssetRipper placeholder GUIDs: never copy, never remap.
BUILTIN = {
    "0000000000000000f000000000000000",
    "0000000000000000e000000000000000",
    "0000000deadbeef15deadf00d0000000",
}


def build_assembly_map():
    """AssetRipper assembly-GUID -> this SDK clone's DLL GUID.

    Returns (remap, ar_guid2asm): remap is only the entries where the SDK has a
    matching DLL; ar_guid2asm is the full AssetRipper guid->assembly-name table
    (used to flag script refs whose assembly is absent from the SDK).
    """
    ar_guid2asm = {}
    with open(os.path.join(RES, "guid_to_assembly.txt")) as fh:
        for line in fh:
            if line.startswith("#") or not line.strip():
                continue
            g, asm = line.split(None, 1)
            ar_guid2asm[g] = asm.strip()

    asm2sdk = {}
    for root, _, files in os.walk(os.path.join(SDK, "Assets")):
        for f in files:
            if f.endswith(".dll.meta"):
                asm = f[: -len(".dll.meta")]
                with open(os.path.join(root, f)) as fh:
                    for line in fh:
                        if line.startswith("guid:"):
                            asm2sdk[asm] = line.split()[1]
                            break

    remap = {g: asm2sdk[asm] for g, asm in ar_guid2asm.items() if asm in asm2sdk}
    return remap, ar_guid2asm


def index_meta():
    """guid -> asset file path, from every .meta under the Resources export."""
    idx = {}
    for root, _, files in os.walk(RES):
        for f in files:
            if not f.endswith(".meta"):
                continue
            mp = os.path.join(root, f)
            try:
                with open(mp, errors="ignore") as fh:
                    for line in fh:
                        if line.startswith("guid:"):
                            idx[line.split()[1]] = mp[:-5]
                            break
            except OSError:
                pass
    return idx


def guids_in(path):
    try:
        with open(path, errors="ignore") as fh:
            return set(GUID_RE.findall(fh.read()))
    except OSError:
        return set()


def locate(name):
    if os.path.isfile(name):
        return name
    want = name if name.endswith(".prefab") else name + ".prefab"
    for root, _, files in os.walk(os.path.join(RES, "Assets")):
        if os.path.basename(want) in files:
            return os.path.join(root, os.path.basename(want))
    return None


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    name, dest = sys.argv[1], sys.argv[2]

    remap, ar_guid2asm = build_assembly_map()
    script_guids = set(ar_guid2asm)
    meta_idx = index_meta()

    start = locate(name)
    if not start:
        print(f"prefab '{name}' not found under {RES}/Assets")
        sys.exit(1)

    # Transitive ASSET hull: walk guid refs, follow only asset guids (skip script
    # + builtin). Script refs get remapped in place, not copied.
    seen = {start}
    assets = set()
    queue = [start]
    while queue:
        cur = queue.pop()
        for g in guids_in(cur):
            if g in BUILTIN or g in script_guids:
                continue
            tgt = meta_idx.get(g)
            if tgt and tgt not in seen:
                seen.add(tgt)
                assets.add(tgt)
                queue.append(tgt)

    to_copy = [start] + sorted(assets)
    for src in to_copy:
        rel = src[len(RES) + 1:]
        dst = os.path.join(dest, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        if os.path.exists(src + ".meta"):
            shutil.copy2(src + ".meta", dst + ".meta")

    # Remap script assembly-GUIDs in every copied text asset.
    remapped_refs = 0
    remapped_files = 0
    missing = {}
    for src in to_copy:
        dst = os.path.join(dest, src[len(RES) + 1:])
        txt = open(dst, errors="ignore").read()
        n = 0
        for ar_g, sdk_g in remap.items():
            if ar_g in txt:
                n += txt.count(ar_g)
                txt = txt.replace(ar_g, sdk_g)
        if n:
            open(dst, "w").write(txt)
            remapped_refs += n
            remapped_files += 1
        for g in guids_in(dst):
            if g in script_guids and g not in remap:
                missing[ar_guid2asm[g]] = g

    print(f"imported {os.path.basename(start)} -> {dest}")
    print(f"  files copied: {len(to_copy)} ({len(assets)} asset deps)")
    print(f"  script GUIDs remapped: {remapped_refs} refs in {remapped_files} files")
    if missing:
        print(f"  WARNING: {len(missing)} referenced assemblies are NOT in the SDK "
              f"(these will still be Missing Script):")
        for asm, g in sorted(missing.items()):
            print(f"    - {asm} ({g})")
    else:
        print("  all referenced script assemblies resolved to SDK DLLs")


if __name__ == "__main__":
    main()
