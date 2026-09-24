#!/usr/bin/env python3
"""Find where a drifted decompile citation's line moved to, after a game update.

`check_citation_drift.py` answers "which citations no longer point at what they
used to". After a major update that is most of them -- 160 of 173 for
1.2.1.5 -> 1.3.0.2 -- and re-reading all of them by hand is the cost that makes
line citations look like a bad idea in the first place.

Most of that work is mechanical, because the snapshot recorded the *text* of
every cited line. If that exact text still exists somewhere in the same
assembly, the statement is undisturbed and only the number moved: a search
finds it. What is left over is the interesting part -- citations whose text is
genuinely gone, meaning the code changed and the sentence built on it needs a
human.

So this splits the 160 into "renumber these" and "read these", and only the
second is real work.

**A relocated citation is not thereby correct.** It points at the same text it
pointed at before, which restores the ground under the sentence; it does not
establish that the sentence was right. That is what the chapter verification
programme is for. What this rules out is the other failure: a citation that
silently points at unrelated code because everything below an edit shifted.

Usage:
    uv run utils/relocate_citations.py                  # report only
    uv run utils/relocate_citations.py --apply          # rewrite docs/ck/
    uv run utils/relocate_citations.py --only Pug.Base  # one assembly at a time
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_citation_drift import ASSET_EXTENSIONS
from check_citation_drift import CITATION
from check_citation_drift import DEFAULT_DECOMPILE
from check_citation_drift import DEFAULT_SNAPSHOT
from check_citation_drift import key_of


def source_for(assembly, decompile):
    """The file a citation's assembly name refers to, or None.

    Mirrors resolve()'s lookup rules -- a plain or DedicatedServer/-prefixed
    assembly name is a path, a recognised asset extension is a filename to
    search for under Resources/Assets/ -- but returns the path rather than the
    lines, because relocation has to read the whole file, not a slice of it.
    """
    direct = Path(decompile) / f"{assembly}.decompiled.cs"
    if direct.is_file():
        return direct
    if Path(assembly).suffix in ASSET_EXTENSIONS:
        matches = sorted(Path(decompile, "Resources", "Assets").rglob(assembly))
        if len(matches) == 1:
            return matches[0]
    return None


def find_sequence(haystack, needle):
    """Every 1-based start line where `needle` appears as consecutive lines.

    Both sides are already stripped, for the same reason resolve() strips:
    indentation moves when a nesting level is added around code that did not
    otherwise change, and that is not the kind of drift worth reporting.
    """
    if not needle:
        return []
    first = needle[0]
    n = len(needle)
    return [
        i + 1 for i, line in enumerate(haystack) if line == first and haystack[i : i + n] == needle
    ]


def relocate(old_lines, old_first, source, anchors=None):
    """Where the recorded text now lives: (new_first, verdict, detail).

    `anchors` is a sorted list of (old_line, new_line) pairs from citations in
    the same assembly that relocated unambiguously. They turn the weakest case
    into the strongest one: text like `{` or `return true;` occurs thousands of
    times, so matching on it alone settles nothing, but insertions and deletions
    are local, and between two neighbouring anchors the offset barely moves.
    A candidate sitting where the surrounding code went is the right one; the
    rest are elsewhere in the file entirely.
    """
    lines = [line.strip() for line in source.read_text(errors="replace").splitlines()]
    hits = find_sequence(lines, old_lines)

    if not hits:
        return None, "gone", "recorded text no longer present"
    if len(hits) == 1:
        return hits[0], "moved" if hits[0] != old_first else "unchanged", ""

    if anchors:
        expected = expected_position(old_first, anchors)
        if expected is not None:
            near = sorted(hits, key=lambda h: abs(h - expected))
            # Accept only when the best candidate is unambiguously nearer than
            # the next one AND lands where the anchors say -- otherwise the
            # anchors did not actually decide it, and a guess wearing a
            # confident verdict is worse than an honest "ambiguous".
            decisive = len(near) == 1 or abs(near[0] - expected) * 4 <= abs(near[1] - expected)
            if decisive and abs(near[0] - expected) <= ANCHOR_TOLERANCE:
                verdict = "moved" if near[0] != old_first else "unchanged"
                return (
                    near[0],
                    verdict,
                    f"{len(hits)} matches, placed by neighbouring anchors",
                )

    # Several matches: prefer the one nearest where the citation used to sit.
    # A file grows and shrinks around a statement, so the old line number is a
    # weak signal -- good enough to pick between candidates, never good enough
    # to accept one on its own, which is why the count travels with it.
    best = min(hits, key=lambda h: abs(h - old_first))
    return best, "ambiguous", f"{len(hits)} matches, nearest to the old position"


# How far a candidate may sit from where the anchors say the code went. Wide
# enough to absorb a few lines added inside the enclosing method, narrow enough
# that a match elsewhere in a 460,000-line file never qualifies.
ANCHOR_TOLERANCE = 400


def expected_position(old_line, anchors):
    """Interpolate where `old_line` should have landed, from surrounding anchors."""
    below = [a for a in anchors if a[0] <= old_line]
    above = [a for a in anchors if a[0] > old_line]
    if below and above:
        lo, hi = below[-1], above[0]
        span = hi[0] - lo[0]
        if span == 0:
            return lo[1]
        frac = (old_line - lo[0]) / span
        return round(lo[1] + frac * (hi[1] - lo[1]))
    if below:
        lo = below[-1]
        return lo[1] + (old_line - lo[0])
    if above:
        hi = above[0]
        return hi[1] - (hi[0] - old_line)
    return None


def rewrite_chapter(path, mapping):
    """Replace every citation in one chapter per `mapping`; return the count."""
    text = path.read_text()
    changed = 0

    def repl(m):
        nonlocal changed
        assembly, first = m.group(1), int(m.group(2))
        last = int(m.group(3) or m.group(2))
        new_first = mapping.get(key_of(assembly, first, last))
        if new_first is None:
            return m.group(0)
        changed += 1
        span = last - first
        new_last = new_first + span
        body = f"{assembly}:{new_first}" if span == 0 else f"{assembly}:{new_first}-{new_last}"
        return f"`{body}`"

    new_text = CITATION.sub(repl, text)
    if changed:
        path.write_text(new_text)
    return changed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root", nargs="?", default=".")
    ap.add_argument("--decompile", default=str(DEFAULT_DECOMPILE))
    ap.add_argument("--snapshot", default=str(DEFAULT_SNAPSHOT))
    ap.add_argument("--only", help="restrict to citations of this assembly")
    ap.add_argument("--apply", action="store_true", help="rewrite the chapters")
    args = ap.parse_args()

    snapshot = json.loads(Path(args.snapshot).read_text())
    recorded = snapshot["citations"]

    # Which citations are actually in the handbook, and where.
    cited = {}
    for chapter in sorted((Path(args.root) / "docs" / "ck").glob("*.md")):
        for m in CITATION.finditer(chapter.read_text()):
            assembly, first = m.group(1), int(m.group(2))
            last = int(m.group(3) or m.group(2))
            cited.setdefault(key_of(assembly, first, last), []).append(chapter.name)

    # Two passes. The first settles every citation whose recorded text occurs
    # exactly once; the second reuses those as anchors, which is what makes a
    # citation on `{` placeable at all.
    sources = {}
    work = []
    for key, chapters in sorted(cited.items()):
        assembly, _, span = key.partition(":")
        old_first = int(span.split("-")[0])
        if args.only and assembly != args.only:
            continue
        if key not in recorded:
            work.append((key, chapters, assembly, old_first, "unrecorded"))
            continue
        if assembly not in sources:
            sources[assembly] = source_for(assembly, args.decompile)
        if sources[assembly] is None:
            work.append((key, chapters, assembly, old_first, "unresolvable"))
            continue
        work.append((key, chapters, assembly, old_first, None))

    first_pass = {}
    for key, _chapters, assembly, old_first, problem in work:
        if problem:
            continue
        new_first, verdict, _d = relocate(recorded[key], old_first, sources[assembly])
        if verdict in ("moved", "unchanged"):
            first_pass.setdefault(assembly, []).append((old_first, new_first))
    for pairs in first_pass.values():
        pairs.sort()

    results = []
    for key, chapters, assembly, old_first, problem in work:
        if problem == "unrecorded":
            results.append((key, chapters, None, "unrecorded", "not in the snapshot"))
            continue
        if problem == "unresolvable":
            results.append((key, chapters, None, "unresolvable", "no such assembly"))
            continue
        new_first, verdict, detail = relocate(
            recorded[key], old_first, sources[assembly], first_pass.get(assembly)
        )
        results.append((key, chapters, new_first, verdict, detail))

    by_verdict = {}
    for r in results:
        by_verdict.setdefault(r[3], []).append(r)

    order = ["unchanged", "moved", "ambiguous", "gone", "unresolvable", "unrecorded"]
    print(f"{len(results)} citations examined\n")
    for verdict in order:
        rows = by_verdict.get(verdict, [])
        if rows:
            print(f"  {verdict:<13} {len(rows):>4}")
    print()

    for verdict in ("gone", "ambiguous", "unresolvable", "unrecorded"):
        rows = by_verdict.get(verdict, [])
        if not rows:
            continue
        print(f"=== {verdict} — needs a human ===")
        for key, chapters, new_first, _v, detail in rows:
            where = ", ".join(sorted(set(chapters)))
            moved = f" -> {new_first}" if new_first else ""
            print(f"  {key}{moved}  [{where}]  {detail}")
        print()

    moved = by_verdict.get("moved", [])
    if args.apply:
        mapping = {key: new for key, _c, new, _v, _d in moved}
        total = 0
        for chapter in sorted((Path(args.root) / "docs" / "ck").glob("*.md")):
            total += rewrite_chapter(chapter, mapping)
        print(f"rewrote {total} citation(s) across docs/ck/")
        print("Re-run check_citation_drift.py --capture once the rest is settled.")
    elif moved:
        print(f"{len(moved)} citation(s) can be renumbered mechanically — pass --apply.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
