#!/usr/bin/env python3
"""Report what a Core Keeper update breaks in this repository's mods.

A game update does not announce what it broke. The mods bind to game internals
by name, and a renamed or removed member is a *compile* error rather than a
misbehaviour, because a mod ships C# source that Roslyn compiles at load time --
so one vanished member drops the whole mod, not just the patch that named it.
This compares two decompiled states and says which mods are affected.

Three vectors, because each one finds what the others cannot:

**Targets.** Does the patched member still exist under that name? Catches an
outright rename.

**Signatures.** A member can keep its name while its declaration changes. The
target check would call that "ok"; Harmony would not bind.

**Types.** A patch target can survive while a helper type used inside the patch
body is removed -- which is exactly how 1.3.0.2 broke three mods here while
their Harmony targets all still existed. It also covers the mods that use no
Harmony at all and bind through ECS component structs instead.

**Every vector is calibrated against the OLD state, and that is the point.** A
target that cannot be found in the old state either is a miss in this script,
not a breaking change. Those are reported separately and never counted as
findings -- without that, a parser bug reads as a broken mod and sends you
hunting through code that is fine. A run whose "unresolved" count is zero is
one whose findings can be trusted.

Known limits, so the green result is not read for more than it says:

- **It proves nothing about behaviour.** A member can keep its name and
  signature and do something different inside. Only a build and a play session
  answer that.
- It does not check ECS component *fields*, ObjectID values, prefab or UI
  hierarchies, or anything living in an AssetBundle rather than in source.
- Identifiers are matched by name, so ambiguity is resolved in the mod's favour:
  every name a mod declares itself -- type, property, field or method -- is
  excluded before the comparison. item-checklist declares `Mode` and the game
  dropped an enum of that name; without this the tool would report it at every
  future run. The cost is that a mod naming a member after a game type it really
  does use would hide a genuine finding.

Usage:
    uv run utils/check_game_update_impact.py                  # newest two states
    uv run utils/check_game_update_impact.py --old <dir> --new <dir>
    uv run utils/check_game_update_impact.py --mod item-checklist

Decompiled states are looked for in $CK_DECOMPILE_ROOT (default
~/Projects/checkouts), in directories named CoreKeeperDecompile-<version>-<hash>.
Exits non-zero when a finding is reported.
"""

import argparse
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DECOMPILE_ROOT = Path(os.environ.get("CK_DECOMPILE_ROOT", Path.home() / "Projects/checkouts"))
STATE_DIR = re.compile(r"^CoreKeeperDecompile-(\d+(?:\.\d+)*)-(\w+)$")

# Directories under the repo root that are not mods.
NOT_A_MOD = {
    "CoreKeeperModSDK",
    "utils",
    "docs",
    "sources",
    "unity",
    "CoreKeeperModDocs",
}

TYPE_DECL = re.compile(
    r"^\s*(?:public|internal|private|protected|sealed|abstract|static|partial|readonly|unsafe|\s)*"
    r"(?:class|struct|interface|enum)\s+(\w+)"
)
# Any name the mod declares itself -- property, field, method. A mod's own
# `public SortMode Mode` must not make the removal of the game enum `Mode` look
# like this mod's problem. Ambiguous names belong to the mod, not to the game.
MEMBER_DECL = re.compile(
    r"^\s*(?:\[[^\]]*\]\s*)*"
    r"(?:(?:public|private|protected|internal|static|readonly|override|virtual|abstract|sealed|"
    r"async|const|partial|extern|new|unsafe)\s+)+"
    r"[\w<>\[\],.?]+\s+(\w+)\s*(?:[{;=(]|=>)"
)
NAMEOF = re.compile(r"nameof\s*\(\s*([A-Z]\w*)\s*\.\s*(\w+)\s*\)")
HARMONY_TARGET = re.compile(
    r"HarmonyPatch\s*\(\s*typeof\s*\(\s*([\w.]+)\s*\)\s*,\s*(?:\"([^\"]+)\"|nameof\s*\(\s*[\w.]*?(\w+)\s*\))"
)
BURST = re.compile(r"DisableBurstForSystem(?:AndJobs)?\s*<\s*([\w.]+)\s*>")
# A type reference stands on its own; `model.Mode` and `ModConfig.Mode` are member
# access and must not be read as a reference to the game enum `Mode`. Requiring the
# identifier not to follow a dot costs only nested types, which fall with their
# outer type anyway and are reported through it.
IDENTIFIER = re.compile(r"(?<![.\w])([A-Z][A-Za-z0-9_]{2,})\b")


def version_key(name: str) -> tuple:
    m = STATE_DIR.match(name)
    return tuple(int(p) for p in m.group(1).split(".")) if m else ()


def find_states() -> list[Path]:
    """Decompiled states, oldest first."""
    if not DECOMPILE_ROOT.is_dir():
        return []
    dirs = [d for d in DECOMPILE_ROOT.iterdir() if d.is_dir() and STATE_DIR.match(d.name)]
    return sorted(dirs, key=lambda d: version_key(d.name))


def strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", "", text)


def mod_dirs(only: str | None) -> list[Path]:
    out = []
    for d in sorted(REPO.iterdir()):
        if not d.is_dir() or d.name in NOT_A_MOD or d.name.startswith("."):
            continue
        if not (d / "unity").is_dir():
            continue
        if only and d.name != only:
            continue
        out.append(d)
    return out


def mod_sources(mod: Path):
    for cs in sorted(mod.rglob("*.cs")):
        if "/.worktrees/" in str(cs):
            continue
        try:
            yield cs, cs.read_text(errors="replace")
        except OSError:
            continue


def scan_mod(mod: Path) -> dict:
    """Collect what this mod binds to, and what it declares itself."""
    members: set[tuple[str, str]] = set()
    burst: set[str] = set()
    own_names: set[str] = set()
    identifiers: set[str] = set()
    for cs, text in mod_sources(mod):
        code = strip_comments(text)
        for m in TYPE_DECL.finditer(code):
            own_names.add(m.group(1))
        for line in code.splitlines():
            m = MEMBER_DECL.match(line)
            if m:
                own_names.add(m.group(1))
        for m in BURST.finditer(code):
            burst.add(m.group(1).split(".")[-1])
        for m in NAMEOF.finditer(code):
            members.add((m.group(1), m.group(2)))
        for m in HARMONY_TARGET.finditer(code):
            members.add((m.group(1).split(".")[-1], m.group(2) or m.group(3)))
        if "/Editor/" not in str(cs):
            identifiers |= set(IDENTIFIER.findall(code))
    return {
        "members": members,
        "burst": burst,
        "own_names": own_names,
        "identifiers": identifiers,
    }


def declared_types(state: Path) -> set[str]:
    names: set[str] = set()
    for f in state.glob("*.decompiled.cs"):
        try:
            for line in f.read_text(errors="replace").splitlines():
                m = TYPE_DECL.match(line)
                if m:
                    names.add(m.group(1))
        except OSError:
            continue
    return names


def member_declarations(
    state: Path, pairs: set[tuple[str, str]]
) -> dict[tuple[str, str], set[str]]:
    """Declaration lines for each Type.Member, found inside the type's body."""
    by_type: dict[str, set[str]] = {}
    for t, mem in pairs:
        by_type.setdefault(t, set()).add(mem)
    out: dict[tuple[str, str], set[str]] = {}
    for f in sorted(state.glob("*.decompiled.cs")):
        try:
            lines = f.read_text(errors="replace").splitlines()
        except OSError:
            continue
        for i, line in enumerate(lines):
            m = TYPE_DECL.match(line)
            if not m or m.group(1) not in by_type:
                continue
            tname = m.group(1)
            depth, j, started, body = 0, i, False, []
            while j < len(lines) and j < i + 40000:
                depth += lines[j].count("{") - lines[j].count("}")
                started = started or "{" in lines[j]
                body.append(lines[j])
                if started and depth <= 0:
                    break
                j += 1
            for mem in by_type[tname]:
                # A declaration carries a return type or modifier before the name.
                # Requiring one keeps a bare call site -- `HideAllInventoryAndCraftingUI();`
                # sits in the same type body -- from being compared as a declaration,
                # which would both mislead the report and corrupt the signature check.
                pat = re.compile(
                    rf"^\s*[\w<>\[\],.?]+(?:\s+[\w<>\[\],.?]+)*\s+{re.escape(mem)}\s*[(<=;{{]"
                )
                for b in body:
                    if pat.match(b) and not b.lstrip().startswith(
                        ("return ", "if ", "while ", "var ", "new ")
                    ):
                        out.setdefault((tname, mem), set()).add(
                            re.sub(r"\s+", " ", b).strip().rstrip("{").strip()
                        )
    return out


def best(declarations: set[str]) -> str:
    """The fullest declaration, chosen deterministically.

    A type body can yield several matching lines (an overload, a partial). Picking
    from the set directly makes the report differ between runs on the same input.
    """
    return max(sorted(declarations), key=len)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--old", type=Path, help="decompiled state before the update")
    ap.add_argument("--new", type=Path, help="decompiled state after the update")
    ap.add_argument("--mod", help="restrict to one mod directory")
    args = ap.parse_args()

    old, new = args.old, args.new
    if not (old and new):
        states = find_states()
        if len(states) < 2:
            print(
                f"Need two decompiled states in {DECOMPILE_ROOT}; found {len(states)}.",
                file=sys.stderr,
            )
            print(
                "Name them CoreKeeperDecompile-<version>-<hash>, or pass --old/--new.",
                file=sys.stderr,
            )
            return 2
        old, new = old or states[-2], new or states[-1]
    for label, state in (("--old", old), ("--new", new)):
        if not state.is_dir():
            print(f"{label}: not a directory: {state}", file=sys.stderr)
            return 2
    print(f"alt: {old.name}\nneu: {new.name}\n")

    mods = {m.name: scan_mod(m) for m in mod_dirs(args.mod)}
    if not mods:
        print("Keine Mod-Verzeichnisse gefunden.", file=sys.stderr)
        return 2

    all_pairs = set().union(*(v["members"] for v in mods.values())) if mods else set()
    old_members = member_declarations(old, all_pairs)
    new_members = member_declarations(new, all_pairs)
    old_types, new_types = declared_types(old), declared_types(new)
    vanished_types = old_types - new_types

    findings: dict[str, list[str]] = {}
    unresolved: list[str] = []
    checked = 0

    for name, info in sorted(mods.items()):
        hits: list[str] = []
        for pair in sorted(info["members"]):
            label = f"{pair[0]}.{pair[1]}"
            o, n = old_members.get(pair), new_members.get(pair)
            if not o:
                unresolved.append(f"{name}: {label}")
                continue
            checked += 1
            if not n:
                hits.append(f"Member entfällt:   {label}  ({best(o)})")
            elif not (o & n):
                hits.append(
                    f"Signatur ändert:   {label}\n      alt: {best(o)}\n      neu: {best(n)}"
                )
        for t in sorted(info["burst"]):
            if t in old_types:
                checked += 1
                if t not in new_types:
                    hits.append(f"Burst-System weg:  {t}")
            else:
                unresolved.append(f"{name}: {t} (Burst-Ziel)")
        # Types the mod references but does not declare itself.
        referenced = (info["identifiers"] & old_types) - info["own_names"]
        checked += len(referenced)
        for t in sorted(referenced & vanished_types):
            hits.append(f"Typ entfällt:      {t}")
        if hits:
            findings[name] = hits

    print(f"{'MOD':<34} BEFUND")
    print("-" * 78)
    for name in sorted(mods):
        if name in findings:
            print(f"{name:<34} {len(findings[name])} Fund(e)")
            for h in findings[name]:
                print(f"    - {h}")
        else:
            print(f"{name:<34} ok")

    print(f"\ngeprüfte Bindungen: {checked}   betroffene Mods: {len(findings)}")
    if unresolved:
        print(
            f"\n⚠ im ALTEN Stand nicht auflösbar ({len(unresolved)}) — Parser-Lücke, KEIN Befund:"
        )
        for u in unresolved[:20]:
            print(f"    {u}")
        print("  Solange hier etwas steht, ist das Ergebnis oben unvollständig.")
    else:
        print("im alten Stand nicht auflösbar: 0 — die Befunde oben sind belastbar.")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
