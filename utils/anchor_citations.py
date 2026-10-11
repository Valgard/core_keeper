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
    recorded: bool  # the snapshot holds this citation's line text, so two proofs exist


def is_chapter(path):
    """Whether this file is a handbook chapter, which decides what proof is required.

    Inside `docs/ck/` every citation is required to have a snapshot entry, so
    a missing one means the file is already in a state somebody has to look
    at. Required by the procedure rather than by a hook: `check_citation_drift`
    is not wired into pre-commit, so the requirement rests on the verification
    skill calling for a `--capture` and on this refusal. Outside `docs/ck/` --
    `docs/roadmap.md`, `CLAUDE.md` -- there was never going to be an entry,
    and the round trip is all there is. Both are legitimate; treating them
    alike is what would not be.

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

        rewrites.append(
            Rewrite(token, render(proposed), citation.first, counts[token], token in recorded)
        )

    return tuple(rewrites), tuple(notes), tuple(refusals)


def apply_rewrites(path, rewrites):
    """Rewrite every occurrence of each token in `path`; return how many were replaced.

    Matched with its backticks, which is what keeps one token from matching
    inside another: `Pug.Other:37085` is a prefix of `Pug.Other:370859`, and
    a replacement on the bare text would corrupt the longer citation while
    reporting success.

    Then the file is read back and every anchored form looked for. The
    wrapping gate now keeps a citation whole, so nothing should be able to
    produce a token the file cannot express -- but this is the step that
    would carry such a thing into a commit, and a citation with a line break
    inside it matches no pattern, so the failure would be silence in every
    other check at once.
    """
    path = Path(path)
    text = path.read_text()
    replaced = 0
    for rewrite in rewrites:
        old, new = f"`{rewrite.token}`", f"`{rewrite.anchored}`"
        replaced += text.count(old)
        text = text.replace(old, new)
    path.write_text(text)

    expected = sum(rewrite.occurrences for rewrite in rewrites)
    if replaced != expected:
        # What `occurrences` is for. A plan built against one revision of the
        # file and applied to another leaves some occurrences behind, and the
        # result is a file written half in each notation with one snapshot key
        # per citation -- the state this tool refuses a file to avoid.
        raise RuntimeError(
            f"{path}: replaced {replaced} occurrence(s) where the plan counted "
            f"{expected} — the file changed under the plan; re-run it"
        )

    written = {token for line in path.read_text().splitlines() for token, _ in find(line)}
    missing = [rewrite.anchored for rewrite in rewrites if rewrite.anchored not in written]
    if missing:
        raise RuntimeError(
            f"{path}: {len(missing)} citation(s) were written but cannot be found again, "
            f"starting with `{missing[0]}` — the file holds a form no checker can read"
        )
    return replaced


def repository_root(path):
    """The directory whose `docs/ck/` the snapshot describes, or None.

    Found by walking up from the file rather than taken from a flag. A
    `--root` defaulting to `.` was the first version of this, and the failure
    it produced is silent: run the documented command from any directory but
    the repository root and the chapter census comes back empty,
    `rekey_snapshot` reads that as "no chapter cites anything", and every
    record the file touched is deleted while the run prints "re-keyed".
    Measured on a copy of the real corpus -- 809 records in, 807 out, exit 0.

    An empty census is the house example of a silent zero, so it must not be
    reachable on a write path at all. None here is the caller's cue to refuse.
    """
    resolved = Path(path).resolve()
    for candidate in (resolved.parent, *resolved.parents):
        if (candidate / "docs" / "ck").is_dir():
            return candidate
    return None


def cited_tokens(root):
    """Every citation token the handbook's chapters still write.

    `docs/ck/` only, because that is what the snapshot records: a token cited
    solely in `docs/roadmap.md` has no entry to keep alive, and counting it
    here would keep a stale record indefinitely. Read with the same `find`
    that `check_citation_drift.collect` uses, so the two agree on what a
    citation is by construction rather than by two patterns kept in step.
    """
    return {
        token
        for chapter in sorted((Path(root) / "docs" / "ck").glob("*.md"))
        for line in chapter.read_text().splitlines()
        for token, _ in find(line)
    }


def rekey_snapshot(snapshot, rewrites, still_cited):
    """The snapshot with each rewritten citation's record under its new key.

    Both halves are decided against `still_cited` -- the chapters' citations
    as they stand *after* the prose was rewritten -- because the snapshot
    records the handbook and `check_citation_drift.compare` reports in both
    directions: a key no chapter cites is stale, and a cited citation with no
    key is uncaptured. So a record is added only once a chapter writes the
    anchored form, and removed only once no chapter writes the old one.

    The two cases that makes right are worth naming. 13 of the citations in
    the chapters migrated here are also cited in chapters that stay
    unmigrated, where moving the key would report the other chapter as
    uncaptured. And anchoring a file outside `docs/ck/` changes no chapter at
    all, so it must change no entry -- adding one would turn the gate red on
    the very commit that anchored it.

    The recorded text travels unchanged. Re-capturing instead would write
    what the line says now, which compares equal to itself forever, and so
    would hide a mis-anchoring behind fresh evidence.
    """
    citations = dict(snapshot.get("citations", {}))
    for rewrite in rewrites:
        if rewrite.token in citations and rewrite.anchored in still_cited:
            citations[rewrite.anchored] = citations[rewrite.token]
        if rewrite.token not in still_cited:
            citations.pop(rewrite.token, None)
    return {**snapshot, "citations": citations}


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
    """Report what anchoring the named file would change; with --apply, do it."""
    ap = argparse.ArgumentParser(description=(__doc__ or "").partition("\n")[0])
    ap.add_argument("path")
    ap.add_argument("--apply", action="store_true", help="write the file and the snapshot")
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
        unproven = (
            "" if rewrite.recorded else "  — no recorded text; the round trip is the only proof"
        )
        print(f"  `{rewrite.token}` -> `{rewrite.anchored}`{repeated}{unproven}")
    for line in notes + refusals:
        print(f"  {line}")

    if refusals:
        print(f"\n{args.path} is not anchored: {len(refusals)} citation(s) must not be moved")
        return 1

    if args.apply and rewrites:
        root = repository_root(args.path)
        if root is None:
            print(f"\nno docs/ck/ directory above {args.path} — cannot read the chapters")
            return 1
        snapshot = Path(args.snapshot)
        if not snapshot.is_file():
            # Absent is an ordinary answer when reading (a file outside
            # docs/ck has no records to find) and never one when writing: a
            # mistyped path would otherwise create a second snapshot and
            # report success, leaving the real one short of every record this
            # run should have moved into it.
            print(f"\nno snapshot at {snapshot} — a rekey needs the one the gate compares against")
            return 1

        # The prose first, then the snapshot. A prose write whose snapshot
        # write failed is reported by the drift gate on the next run, in both
        # of its directions; the reverse order leaves a snapshot naming
        # citations no file carries, which reads as a handbook that lost them.
        try:
            replaced = apply_rewrites(args.path, rewrites)
        except RuntimeError as problem:
            # A sentence and an exit code, as every sibling checker reports a
            # failure. The prose is already written at this point, which the
            # message has to say, because the repair is a rewrap rather than
            # a re-run.
            print(f"\n{problem}")
            return 1
        rekeyed = rekey_snapshot(read_snapshot(snapshot), rewrites, cited_tokens(root))
        snapshot.write_text(json.dumps(rekeyed, indent=2, sort_keys=True) + "\n")
        print(f"\nanchored {len(rewrites)} citation(s) in {replaced} place(s) in {args.path}")
        print(f"re-keyed {snapshot}: {len(rekeyed['citations'])} record(s)")
        return 0

    print(
        f"\n{len(rewrites)} citation(s) to anchor, {len(notes)} kept as written, "
        f"{anchored_already(args.path)} already anchored"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
