#!/usr/bin/env python3
"""Move one file's citations from absolute decompile lines onto symbol anchors.

`Pug.Other:370859` becomes
`Pug.Other:SmallTitleUIBackground:UpdateTextAndBackground:29`: the same line,
named by the element that contains it, so that a game update which does not
touch that element leaves the citation alone. The design and its reasoning are
`docs/specs/2026-10-10-symbol-anchored-citations-design.md`.

**One file at a time, and all of it or none of it.** A chapter written half in
one notation and half in the other has one snapshot key per citation either
way, so a partial migration is not a smaller version of a migration -- it is a
chapter nobody can reason about. Every condition that makes a citation unsafe
to move therefore refuses the whole file and names what to do about it.

**It does not make a citation correct.** The new form points exactly where the
old number pointed; if that was wrong, the result is wrong *and* reads as
though somebody had understood it, which is worse. That is why a chapter is
migrated only where a verification pass has worked it -- mechanically where the
pass has already run, and inside the pass otherwise. The round trip and the
recorded text are the two proofs available, and the report says which it had.

Usage:  uv run utils/anchor_citations.py <path> [--apply]
"""

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_citation_drift import DEFAULT_DECOMPILE
from check_citation_drift import DEFAULT_SNAPSHOT
from check_citation_drift import resolve
from check_citation_drift import source_for
from check_citation_drift import structure_for
from citation_notation import find
from citation_notation import render
from citation_notation import tier
from decompile_structure import describe
from decompile_structure import locate

CHAPTER_DIR = ("docs", "ck")


@dataclass(frozen=True)
class Rewrite:
    """One citation this file would re-spell, and how often it says it.

    Only citations that actually move are Rewrites. A line no type encloses
    keeps its absolute form and is reported as a note instead, so that
    "nothing to do here" is an empty list rather than a list of no-ops that
    every later caller has to filter.
    """

    token: str  # as the prose writes it today
    anchored: str  # what it becomes
    line: int  # the absolute line both forms resolve to
    occurrences: int  # how often `token` appears in this file


def is_chapter(path):
    """Whether this file is a handbook chapter, which decides what proof is required.

    Inside `docs/ck/` the drift gate guarantees a snapshot entry for every
    citation, so a missing one means the file is already in a state somebody
    has to look at. Outside it -- `docs/roadmap.md`, `CLAUDE.md` -- there was
    never going to be one, and the round trip is all there is. Both are
    legitimate; treating them alike is what would not be.

    Read off the two directory names rather than by comparing a repo-relative
    prefix against the path. That comparison is the bug `check_docs_wrapping`
    carries to this day -- `FROZEN` lists `"docs/specs/"` while the path it is
    matched against is relative to whatever root the caller handed in, so
    `--fix docs/` reformats the specs it is supposed to protect. Here the
    equivalent mistake is quieter: a relative `docs/ck` is never among an
    absolute path's parents, so every chapter would read as "not a chapter"
    and migrate without the snapshot entry it is required to have.
    """
    parent = Path(path).resolve().parent
    return (parent.parent.name, parent.name) == CHAPTER_DIR


def plan_file(path, decompile, recorded, structures=None):
    """What anchoring this file's citations would change: (rewrites, notes, refusals).

    `recorded` is the snapshot's `{token: [lines]}` mapping. Notes report a
    citation left as it is, with the reason; refusals report a citation that
    must not be moved, and one of them stops the whole file.

    Citations are visited once per unique token, in the order the file first
    writes them, because the file is rewritten per token and the count is what
    tells a later rewrite it reached all of them.
    """
    path = Path(path)
    structures = {} if structures is None else structures
    chapter = is_chapter(path)

    counts = Counter()
    first_seen = {}
    for number, line in enumerate(path.read_text().splitlines(), start=1):
        for token, citation in find(line):
            counts[token] += 1
            first_seen.setdefault(token, (citation, number))

    rewrites, notes, refusals = [], [], []
    for token, (citation, number) in first_seen.items():
        where = f"{path}:{number}  {token}"

        if tier(citation) != "absolute":
            # Already anchored, and skipped before anything else is asked of
            # it. Not merely a saved round trip: an anchored citation's
            # location is relative to its element, so every check below would
            # read it as an absolute line -- `Foo:Bar:3` would be measured
            # against line 3 of the file, whose recorded text does not match,
            # and the whole chapter would be refused on its second run.
            continue

        source = source_for(citation.assembly, decompile)
        if source is None:
            refusals.append(f"{where}  no decompiled file for {citation.assembly}")
            continue

        # The recorded text is checked before anything is proposed, because it
        # is a statement about the file rather than about the rewrite: a
        # citation whose recorded line has moved is drift nobody has read yet,
        # and re-keying it would carry that stale record onto a form which
        # names a class and a method and so reads as considered.
        if token in recorded:
            if recorded[token] != resolve(
                citation.assembly, citation.first, citation.last, decompile
            ):
                refusals.append(
                    f"{where}  recorded text no longer matches the line — "
                    "resolve the drift first (uv run utils/check_citation_drift.py)"
                )
                continue
        elif chapter:
            refusals.append(
                f"{where}  not in the snapshot — "
                "capture it first (uv run utils/check_citation_drift.py --capture)"
            )
            continue
        else:
            notes.append(f"{where}  no recorded text; the round trip is the only proof")

        if source.suffix != ".cs":
            notes.append(
                f"{where}  stays absolute: {citation.assembly} is not C#, "
                "so it has no elements to name"
            )
            continue

        structure = structure_for(source, structures)
        if structure is None:
            refusals.append(f"{where}  nothing is known about {source}")
            continue

        proposed = describe(structure, citation.first, citation.assembly, citation.last)
        landed = locate(structure, proposed)
        if landed != citation.first:
            refusals.append(
                f"{where}  {render(proposed)} resolves to line {landed}, not {citation.first}"
            )
            continue

        if tier(proposed) == "absolute":
            notes.append(f"{where}  stays absolute: no type encloses line {citation.first}")
            continue

        rewrites.append(Rewrite(token, render(proposed), citation.first, counts[token]))

    return tuple(rewrites), tuple(notes), tuple(refusals)


def anchored_already(path):
    """How many of this file's citations are already on a symbol.

    Counted so the report can tell a migrated file from one that never cited
    anything: both yield no rewrites, and a bare zero would make the check
    that a migration landed say nothing at all.
    """
    return sum(
        1
        for line in Path(path).read_text().splitlines()
        for _, citation in find(line)
        if tier(citation) != "absolute"
    )


def read_snapshot(path):
    """The snapshot document, or an empty one when the file is absent.

    Absent is not an error: a file outside `docs/ck/` has no entries to find,
    and `plan_file` already tells that apart from a chapter missing one.
    """
    path = Path(path)
    return json.loads(path.read_text()) if path.is_file() else {}


def main(argv=None):
    """Report what anchoring the named file would change; exit 1 if it must not be."""
    ap = argparse.ArgumentParser(description=(__doc__ or "").partition("\n")[0])
    ap.add_argument("path")
    ap.add_argument("--decompile", default=str(DEFAULT_DECOMPILE))
    ap.add_argument("--snapshot", default=str(DEFAULT_SNAPSHOT))
    args = ap.parse_args(argv)

    decompile = Path(args.decompile).expanduser()
    if not decompile.is_dir():
        print(f"decompile tree not found: {decompile}")
        return 1

    recorded = read_snapshot(args.snapshot).get("citations", {})
    rewrites, notes, refusals = plan_file(args.path, decompile, recorded)

    for rewrite in rewrites:
        repeated = "" if rewrite.occurrences == 1 else f"  ({rewrite.occurrences} occurrences)"
        print(f"  `{rewrite.token}` -> `{rewrite.anchored}`{repeated}")
    for line in notes + refusals:
        print(f"  {line}")

    if refusals:
        print(f"\n{args.path} is not anchored: {len(refusals)} citation(s) must not be moved")
        return 1
    print(
        f"\n{len(rewrites)} citation(s) to anchor, {len(notes)} kept as written, "
        f"{anchored_already(args.path)} already anchored"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
