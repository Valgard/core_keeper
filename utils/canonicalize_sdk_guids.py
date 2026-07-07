#!/usr/bin/env python3
"""Pin the Core Keeper SDK's game-DLL .meta GUIDs to a committed snapshot.

Why: `CoreKeeperModSDK/Assets/Plugins/CoreKeeper/*.dll.meta` GUIDs are generated
locally by Unity during "Update Game Files" -> different on every machine / every
re-setup (the .meta files are untracked). Mod prefabs that reference game scripts
(PugText, UIScrollWindow, RadicalMenuOption, ...) bind to these GUIDs, so a fresh
SDK makes already-committed prefabs show "Missing Script".

Rather than remapping the *committed, stable* mod prefabs on every new machine,
this pins the *volatile* SDK GUIDs back to the canonical values the mod code
already expects. Safe: inside the SDK, only each `.dll.meta` references its own
GUID (game prefabs live in resources.assets; SDK assets reference game code by
asmdef name, not GUID) — verified 2026-07-07.

Snapshot lives at `utils/sdk-dll-guids.json` (commit it — it's the canonical map).

Usage:
  canonicalize_sdk_guids.py snapshot   # save current SDK DLL GUIDs as canonical
  canonicalize_sdk_guids.py check      # report drift vs snapshot (no changes)
  canonicalize_sdk_guids.py apply      # pin SDK DLL GUIDs to snapshot (new-mac setup)
"""
import json
import os
import re
import sys

SDK = os.path.expanduser("~/Projects/private/core_keeper/CoreKeeperModSDK")
PLUGINS = os.path.join(SDK, "Assets/Plugins/CoreKeeper")
SNAP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sdk-dll-guids.json")
GUID_LINE = re.compile(r"^guid: ([a-f0-9]{32})$", re.M)


def current():
    """dll filename ('X.dll') -> current guid, for every *.dll.meta in the plugins dir."""
    out = {}
    if not os.path.isdir(PLUGINS):
        print(f"SDK plugins dir not found: {PLUGINS}")
        sys.exit(1)
    for f in sorted(os.listdir(PLUGINS)):
        if f.endswith(".dll.meta"):
            mo = GUID_LINE.search(open(os.path.join(PLUGINS, f)).read())
            if mo:
                out[f[:-5]] = mo.group(1)  # strip ".meta" -> "X.dll"
    return out


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    cur = current()

    if cmd == "snapshot":
        json.dump(cur, open(SNAP, "w"), indent=2, sort_keys=True)
        print(f"snapshot: saved {len(cur)} DLL GUIDs -> {SNAP}")
        return

    if not os.path.exists(SNAP):
        print(f"no snapshot at {SNAP} — run 'snapshot' first")
        sys.exit(1)
    want = json.load(open(SNAP))
    drift = {k: (cur.get(k), v) for k, v in want.items() if cur.get(k) != v}
    missing = [k for k in want if k not in cur]

    if cmd == "check":
        print(f"snapshot: {len(want)} DLLs | drifted: {len(drift)} | missing in SDK: {len(missing)}")
        for k, (c, w) in list(drift.items())[:30]:
            print(f"  {k}: SDK={c} -> canonical={w}")
        if missing:
            print("  missing:", ", ".join(missing[:10]))
        return

    if cmd == "apply":
        n = 0
        for dll, (c, w) in drift.items():
            if c is None:
                continue  # DLL absent in this SDK — nothing to pin
            p = os.path.join(PLUGINS, dll + ".meta")
            txt = open(p).read()
            new = GUID_LINE.sub(f"guid: {w}", txt, count=1)
            if new != txt:
                open(p, "w").write(new)
                n += 1
        print(f"apply: pinned {n} DLL GUID(s) to canonical")
        if n:
            print("NEXT: delete CoreKeeperModSDK/Library/SourceAssetDB (+ Bee, ScriptAssemblies)")
            print("      then reopen the Editor so Unity reimports against the pinned GUIDs.")
        return

    print(__doc__)


if __name__ == "__main__":
    main()
