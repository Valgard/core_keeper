#!/usr/bin/env python3
"""Record what every decompile citation in docs/ck/ points at, and notice when it moves.

A citation like `Pug.Other:441234` is a claim in its own right, and it is wrong
unless that exact line carries what the sentence says it shows. Line numbers
move with every Core Keeper update, so after one, every citation in the
handbook is suspect and nothing says which. Answering that by hand cost four
parallel verifiers across 175 references on 2026-08-22, to find six errors.

This script answers it in seconds, by storing the *text* of each cited line
rather than trusting the number. It does not check whether a statement is true
— no script can — it checks whether the ground under it moved. A citation
whose line still reads the same is not thereby correct; it is merely unchanged.

Two modes: --capture writes the snapshot, the default compares against it.
Capture deliberately requires a flag, so a drift run can never silently record
the drift as the new truth.

What it resolves a citation against, in order of attempt: a plain assembly
name in the client decompile (`Pug.Other:441234`); the same shape prefixed
`DedicatedServer/` against that tree's own copy of the assembly — a distinct
build kept separately, not a duplicate of the client's
(`DedicatedServer/Pug.Other:430189`); and a name ending in a recognised Unity
asset extension against `Resources/Assets/`, searched recursively
(`ControlMappingMenu.prefab:2456-2457`). A citation naming anything else is
reported rather than guessed at — and so is an asset name that matches more
than one file, rather than picking between them.

Usage:
    uv run utils/check_citation_drift.py --capture --game-version VERSION [--decompile PATH] [repo-root]
    uv run utils/check_citation_drift.py [--decompile PATH] [repo-root]
"""

import argparse
import json
import re
import sys
from pathlib import Path

# Backtick-delimited, because that is how every real citation is written and it
# is what separates `Pug.Other:441234` from prose like "roughly 124940". The
# assembly part allows dots (Pug.ECS.Components) but not spaces or colons.
# The `DedicatedServer/` prefix is anchored to that one literal string rather
# than opening the class to "/" in general — a general slash would also
# swallow a doc-to-doc line reference like `docs/ck/platforms.md:119`, which
# is not a citation at all.
CITATION = re.compile(
    r"`((?:DedicatedServer/)?[A-Za-z][A-Za-z0-9_.]*):(\d+)(?:-(\d+))?`"
)


def extract(text):
    """Return (assembly, first_line, last_line) per citation, in document order."""
    return [
        (m.group(1), int(m.group(2)), int(m.group(3) or m.group(2)))
        for m in CITATION.finditer(text)
    ]


# Unity asset extensions the handbook has actually cited by name-and-line so
# far. `.prefab` is the only one in use today
# (`ControlMappingMenu.prefab:2456-2457` in ui-framework.md) — extend this set
# the day a citation needs a second one, rather than pre-guessing which.
ASSET_EXTENSIONS = {".prefab"}


def _stripped_lines(path, first, last):
    """Read lines first..last from path, stripped — the shared tail of every
    resolution path below, once each has found which file to read."""
    lines = path.read_text(errors="replace").splitlines()
    return [line.strip() for line in lines[first - 1 : last]]


def resolve(assembly, first, last, decompile):
    """Return the stripped text of lines first..last, or None if unresolvable.

    Stripped, because leading whitespace is the one part of a decompiled line
    that changes for reasons having nothing to do with the code — a nesting
    level added around it moves every line inside without altering what any of
    them says. Comparing stripped text keeps the report about the statement.

    `assembly` carries the whole name as the citation wrote it, so a
    `DedicatedServer/Pug.Other` citation needs no separate branch here — the
    embedded "/" makes the join below land in that tree's own subdirectory
    without anything having to notice. What does need its own branch is a
    name the decompile has nothing by: a recognised Unity asset extension
    sends the search into `Resources/Assets/` instead, by filename rather
    than by path, because a citation states the file's name, not which of the
    hundred type-named subdirectories under it holds that file. A name
    matching more than one file there resolves to nothing rather than
    guessing which one the sentence means.
    """
    source = Path(decompile) / f"{assembly}.decompiled.cs"
    if source.is_file():
        return _stripped_lines(source, first, last)

    if Path(assembly).suffix in ASSET_EXTENSIONS:
        matches = sorted(Path(decompile, "Resources", "Assets").rglob(assembly))
        if len(matches) == 1:
            return _stripped_lines(matches[0], first, last)

    return None


def key_of(assembly, first, last):
    """Render a citation the way the prose writes it, so a report is greppable."""
    return f"{assembly}:{first}" if first == last else f"{assembly}:{first}-{last}"


def collect(root, decompile):
    """Resolve every citation in docs/ck/, returning the corpus, the failures,
    and the set of every citation key seen — resolvable or not.

    That third set is what lets a caller tell "unresolvable right now" apart
    from "not cited anywhere any more": a citation whose assembly disappeared
    is still sitting in the handbook, so it belongs in `seen` even though it
    never makes it into `corpus`.

    Chapters are read directly from docs/ck rather than from `git ls-files`,
    unlike check_docs_links: the handbook is one directory of tracked files,
    and reaching for git here would buy nothing while making the function need
    a repository to run at all.
    """
    corpus, problems, seen = {}, [], set()
    for chapter in sorted((Path(root) / "docs" / "ck").glob("*.md")):
        for number, line in enumerate(chapter.read_text().splitlines(), start=1):
            for assembly, first, last in extract(line):
                key = key_of(assembly, first, last)
                seen.add(key)
                lines = resolve(assembly, first, last, decompile)
                if lines is None:
                    problems.append(
                        f"{chapter.name}:{number}  {key}  no decompiled assembly"
                    )
                else:
                    corpus[key] = lines
    return corpus, sorted(problems), seen


def render(lines):
    """One readable form for a resolved citation, including the empty case."""
    return " / ".join(lines) if lines else "(past end of file)"


def compare(corpus, snapshot, cited):
    """Report drift between the corpus and the snapshot, in three distinct shapes:
    a citation whose recorded line text no longer matches what is there now, a
    citation the snapshot has never seen, and a snapshot entry for a citation
    that has genuinely dropped out of the handbook.

    That last shape is judged against `cited` — every citation key collect()
    saw, resolvable or not — rather than against `corpus`. A citation whose
    assembly disappeared is unresolvable, so it is absent from `corpus`, but
    it is still sitting in the handbook and must not also be reported as
    stale: that reads as "delete this snapshot entry", which would erase the
    one thing still recording what the line used to say.
    """
    problems = []
    for key, lines in corpus.items():
        if key not in snapshot:
            problems.append(f"{key}  not in the snapshot — run --capture")
        elif snapshot[key] != lines:
            problems.append(
                f"{key}  was: {render(snapshot[key])}  now: {render(lines)}"
            )
    problems += [
        f"{key}  no longer cited anywhere" for key in snapshot if key not in cited
    ]
    return sorted(problems)


DEFAULT_DECOMPILE = Path.home() / "Projects/checkouts/CoreKeeperDecompile"
DEFAULT_SNAPSHOT = Path(__file__).resolve().parent / "ck-citation-snapshot.json"


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("root", nargs="?", default=".")
    parser.add_argument("--capture", action="store_true", help="record, do not compare")
    parser.add_argument(
        "--game-version",
        help="game version this capture reflects, e.g. 1.2.1.5-8be0 (required with --capture)",
    )
    parser.add_argument("--decompile", default=str(DEFAULT_DECOMPILE))
    parser.add_argument("--snapshot", default=str(DEFAULT_SNAPSHOT))
    args = parser.parse_args(argv[1:])

    if args.capture and not args.game_version:
        # Required rather than optional: a capture that silently records no
        # version reproduces the exact defect this argument exists to close.
        parser.error("--capture requires --game-version (e.g. 1.2.1.5-8be0)")

    decompile = Path(args.decompile).expanduser()
    if not decompile.is_dir():
        print(f"decompile tree not found: {decompile}")
        return 1

    corpus, problems, cited = collect(Path(args.root), decompile)

    if args.capture:
        Path(args.snapshot).write_text(
            json.dumps(
                {"citations": corpus, "game_version": args.game_version},
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        print(
            f"captured {len(corpus)} citation(s) at game version "
            f"{args.game_version} to {args.snapshot}"
        )
        # Unresolvable citations are still reported, but capture succeeds: they
        # are a handbook defect to fix, not a reason to refuse to record what
        # did resolve.
        for problem in problems:
            print(f"  {problem}")
        return 0

    snapshot_file = Path(args.snapshot)
    if not snapshot_file.is_file():
        print(f"no snapshot at {snapshot_file} — run with --capture first")
        return 1
    snapshot_data = json.loads(snapshot_file.read_text())
    game_version = snapshot_data.get("game_version")
    if game_version:
        print(f"comparing against snapshot captured at game version {game_version}")
    else:
        # A snapshot captured before this flag existed. Say so rather than
        # crashing on a missing key — the fix is a recapture, not a traceback.
        print(
            "snapshot has no recorded game version "
            "(captured before --game-version was required) — recapture to add one"
        )
    problems += compare(corpus, snapshot_data["citations"], cited)

    if problems:
        print(f"{len(problems)} problem(s):")
        for problem in problems:
            print(f"  {problem}")
        return 1
    print(f"OK — {len(corpus)} citation(s), every cited line unchanged")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
