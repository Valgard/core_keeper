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
    uv run utils/check_citation_drift.py --capture --game-version VERSION \
        [--decompile PATH] [repo-root]
    uv run utils/check_citation_drift.py [--decompile PATH] [repo-root]
"""

import argparse
import functools
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from citation_notation import find
from citation_notation import tier

# Backtick-delimited, because that is how every real citation is written and it
# is what separates `Pug.Other:441234` from prose like "roughly 124940". The
# assembly part allows dots (Pug.ECS.Components) but not spaces or colons.
# The `DedicatedServer/` prefix is anchored to that one literal string rather
# than opening the class to "/" in general — a general slash would also
# swallow a doc-to-doc line reference like `docs/ck/platforms.md:119`, which
# is not a citation at all.
CITATION = re.compile(r"`((?:DedicatedServer/)?[A-Za-z][A-Za-z0-9_.]*):(\d+)(?:-(\d+))?`")


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

# A citation can also name a file in an open-source dependency's own sources,
# which are checked out beside the decompile rather than inside it —
# `LocalizationModule.cs:132` is CoreLib's, not a decompiled assembly. Those
# resolve by searching the dependency clones, same as an asset name: the
# handbook states a filename, not a path.
SOURCE_EXTENSIONS = {".cs"}
SOURCE_CLONES = ("CoreLib-source-*",)


@functools.lru_cache(maxsize=4)
def _read_lines(path, size, mtime_ns):
    """Split one file, memoised on its identity. Call through `_lines_of`."""
    return Path(path).read_text(errors="replace").splitlines()


def _lines_of(path):
    """Every line of `path`, split once per file state rather than per citation.

    Measured, not guessed: without this, resolving the corpus read and split a
    16 MB file 914 times and spent 25 of its 29 seconds doing it -- 11 s in
    `read_text` and 14 s in `splitlines`. That cost predates symbol anchoring;
    the old resolver read the file per citation too, and nobody had profiled it.

    Keyed on size and mtime so a rewritten file is re-read, which is the same
    key `decompile_structure`'s disk cache uses and for the same reason: a
    stale answer about a file that moved is the one failure a cache here must
    not have. Bounded at four files, because `Pug.Other` alone is 460,000 lines
    and an unbounded store over 27 assemblies would hold hundreds of megabytes
    -- four is enough that the two copies of `Pug.Other`, which carry most of
    the corpus, stay resident while chapters interleave the rest.
    """
    stat = path.stat()
    return _read_lines(str(path), stat.st_size, stat.st_mtime_ns)


def _stripped_lines(path, first, last):
    """Read lines first..last from path, stripped.

    The shared tail of every resolution path below, once each has found which
    file to read.
    """
    return [line.strip() for line in _lines_of(path)[first - 1 : last]]


def source_for(assembly, decompile):
    """The file a citation's first field names, or None if it resolves to no file.

    `assembly` carries the whole name as the citation wrote it, so a
    `DedicatedServer/Pug.Other` citation needs no separate branch here — the
    embedded "/" makes the join below land in that tree's own subdirectory
    without anything having to notice. What does need its own branch is a
    name the decompile has nothing by: a recognised Unity asset extension
    sends the search into `Resources/Assets/` instead, by filename rather
    than by path, because a citation states the file's name, not which of the
    hundred type-named subdirectories under it holds that file. A `.cs` name
    is searched for the same way, one level further out, in the dependency
    clones that sit beside the decompiled assemblies. In both of those cases a
    name matching more than one file resolves to nothing rather than guessing
    which one the sentence means.

    This is the only path resolver. It used to be two: `resolve` below had all
    three branches while `relocate_citations` carried a copy with two, and a
    measurement taken through the short one put `LocalizationModule.cs` in the
    wrong anchor tier. One function, so there is nothing to keep in step.
    """
    source = Path(decompile) / f"{assembly}.decompiled.cs"
    if source.is_file():
        return source

    if Path(assembly).suffix in ASSET_EXTENSIONS:
        matches = sorted(Path(decompile, "Resources", "Assets").rglob(assembly))
        if len(matches) == 1:
            return matches[0]

    if Path(assembly).suffix in SOURCE_EXTENSIONS:
        matches = sorted(
            match
            for pattern in SOURCE_CLONES
            for clone in Path(decompile).glob(pattern)
            for match in clone.rglob(assembly)
        )
        if len(matches) == 1:
            return matches[0]

    return None


def resolve(assembly, first, last, decompile):
    """Return the stripped text of lines first..last, or None if unresolvable.

    Stripped, because leading whitespace is the one part of a decompiled line
    that changes for reasons having nothing to do with the code — a nesting
    level added around it moves every line inside without altering what any of
    them says. Comparing stripped text keeps the report about the statement.

    Which file those lines come from is `source_for`'s question, not this one's.
    """
    source = source_for(assembly, decompile)
    return _stripped_lines(source, first, last) if source is not None else None


def key_of(assembly, first, last):
    """Render a citation the way the prose writes it, so a report is greppable."""
    return f"{assembly}:{first}" if first == last else f"{assembly}:{first}-{last}"


def resolve_citation(citation, decompile, structures=None):
    """The stripped text a Citation points at, or None when it no longer resolves.

    `structures` is a caller-owned `{assembly: Structure | None}` cache. Pass
    one when resolving many citations: `structure_of` keeps a cache on disk, but
    it still decodes a 62,000-element entry on every call, and doing that once
    per citation took this checker from near-instant to 29 s over the corpus.
    The cache belongs to the caller rather than to `structure_of` on purpose --
    memoising inside it would make three of its own tests unable to fail, since
    they corrupt the entry on disk and call it again to prove it re-parses.

    None is the outcome absolute line numbers cannot produce and the reason for
    the whole change: a renamed or removed member stops resolving and says so,
    where a line number goes on pointing at whatever moved into its place.

    An absolute-tier citation reads its lines directly and needs no structure at
    all, which is what keeps the escape hatch and every unmigrated chapter
    working -- and what makes a `.prefab` citation resolvable, since it has no
    elements to name.

    `decompile_structure` is imported here rather than at module level on
    purpose: `check_citation_style` imports `DEFAULT_DECOMPILE` from this
    module, and its syntactic half has to run in a mod repository where neither
    `tree-sitter` nor a decompile exists. A module-level import would drag the
    parser into every one of those checkouts.
    """
    from decompile_structure import locate
    from decompile_structure import structure_of

    source = source_for(citation.assembly, decompile)
    if source is None:
        return None
    if tier(citation) == "absolute":
        return _stripped_lines(source, citation.first, citation.last)

    if structures is None:
        structures = {}
    if citation.assembly not in structures:
        structures[citation.assembly] = structure_of(source)
    structure = structures[citation.assembly]
    if structure is None:
        return None
    line = locate(structure, citation)
    if line is None:
        return None
    return _stripped_lines(source, line, line + citation.last - citation.first)


def collect(root, decompile):
    """Resolve every citation in docs/ck/: the corpus, the failures, and every key seen.

    That third value — seen, resolvable or not — is what lets a caller tell
    "unresolvable right now" apart from "not cited anywhere any more": a
    citation whose assembly disappeared is still sitting in the handbook, so
    it belongs in `seen` even though it never makes it into `corpus`.

    Chapters are read directly from docs/ck rather than from `git ls-files`,
    unlike check_docs_links: the handbook is one directory of tracked files,
    and reaching for git here would buy nothing while making the function need
    a repository to run at all.
    """
    corpus, problems, seen = {}, [], set()
    structures = {}  # one decode per assembly, not one per citation
    for chapter in sorted((Path(root) / "docs" / "ck").glob("*.md")):
        for number, line in enumerate(chapter.read_text().splitlines(), start=1):
            for token, citation in find(line):
                seen.add(token)
                # Two ways a citation can fail to resolve, and they are not the
                # same thing. A name the decompile has no file for is a broken
                # citation and goes in `problems`, as it always has. A file that
                # exists but no longer holds the named symbol is the new third
                # outcome: it belongs in the corpus as None, so that compare()
                # can tell "stopped resolving" from "never recorded".
                if source_for(citation.assembly, decompile) is None:
                    problems.append(f"{chapter.name}:{number}  {token}  no decompiled assembly")
                    continue
                corpus[token] = resolve_citation(citation, decompile, structures)
    return corpus, sorted(problems), seen


def render(lines):
    """One readable form for a resolved citation, including the empty case."""
    return " / ".join(lines) if lines else "(past end of file)"


def compare(corpus, snapshot, cited):
    """Report drift between the corpus and the snapshot, in three distinct shapes.

    A citation whose recorded line text no longer matches what is there now, a
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
        if lines is None:
            # The outcome that does not exist under absolute line numbers.
            # Deliberately not "not in the snapshot": the two prescribe
            # opposite actions, and reporting a rename as a missing capture
            # would invite writing the vanished symbol in as though it were
            # fine.
            problems.append(f"{key}  no longer resolves — the class or member was renamed")
        elif key not in snapshot:
            problems.append(f"{key}  not in the snapshot — run --capture")
        elif snapshot[key] != lines:
            problems.append(f"{key}  was: {render(snapshot[key])}  now: {render(lines)}")
    problems += [f"{key}  no longer cited anywhere" for key in snapshot if key not in cited]
    return sorted(problems)


DEFAULT_DECOMPILE = Path.home() / "Projects/checkouts/CoreKeeperDecompile"
DEFAULT_SNAPSHOT = Path(__file__).resolve().parent / "ck-citation-snapshot.json"


def main(argv):
    """Parse args and run the capture or compare mode the module docstring describes.

    The exit code tracks whether the requested action could run, not whether it
    found drift: a missing decompile tree or a missing snapshot is 1, and so is
    a compare that turns up problems — but a capture always returns 0, even when
    it leaves unresolved citations behind. Those are a handbook defect to fix,
    not a reason to refuse recording what did resolve.
    """
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
        # A citation that does not resolve is left out rather than recorded as
        # null. Written in, it would compare equal to itself on every later run
        # and so be confirmed forever -- the snapshot records what a line says,
        # and "nothing" is not something a line can say. They are reported
        # below with the rest.
        resolved = {key: lines for key, lines in corpus.items() if lines is not None}
        problems += [
            f"{key}  no longer resolves — not captured" for key in corpus if corpus[key] is None
        ]
        Path(args.snapshot).write_text(
            json.dumps(
                {"citations": resolved, "game_version": args.game_version},
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        print(
            f"captured {len(resolved)} citation(s) at game version "
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
