#!/usr/bin/env python3
"""Reject handbook line references that no tool can check.

A citation is only as useful as the tooling that can verify it, and two
notations the handbook used put references outside every check:

  `:419767`            the assembly inherited from an earlier sentence
  `Pug.Other` ~355773  the number outside the backticks

288 references were written the first way and about 20 the second, against 178
in the checkable form -- so most of the handbook's line references were never
verified by anything, and a major update invalidated them silently. They were
expanded once; this keeps the short forms from coming back, because the reason
they appeared is a good one and will recur: `(`:263245` client, `:263187`
server)` reads better than the full form, right up to the moment someone needs
to know whether it is still true.

The rule: every line reference carries its assembly, as `` `Assembly:line` `` or
`` `Assembly:first-last` ``.

**Two halves, because they need different things and run in different places.**
The syntactic half asks whether a reference is well-formed at all, needs
nothing but the text, and runs in every repository -- including the mod repos,
where decompile citations have sat unchecked because this script could not be
wired there. The structural half asks whether a well-formed citation is the
*best* form available, which takes the decompiled source and `tree-sitter`, and
runs wherever those are reachable. Where they are not, it says so and is
skipped.

**The structural findings report; they do not block.** This script runs over
the whole repository whenever any `.md` is staged, so a blocking structural
half would let one overload added by a game update stop every documentation
commit until somebody rewrote a citation that still resolves to the right
line. A gate that turns red on correct documentation teaches people to work
around it. Syntactic findings do block: a malformed citation is checkable by
nobody.

**What this deliberately does not flag.** A tilde followed by a number is
usually not a line reference at all -- `~1300-entity scan`, `~143 MB`, `~180
scene names`, `~135 lines` are quantities, and a checker that rejected those
would be wrong far more often than right. Only the two unambiguous shapes are
errors here; a bare `~124928` in prose is left to the reader.

Usage:  uv run utils/check_citation_style.py [root] [--decompile PATH]
"""

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_citation_drift import DEFAULT_DECOMPILE
from citation_notation import FINDER
from citation_notation import find
from citation_notation import parse
from citation_notation import render
from citation_notation import tier

# `:123` or `:123-145` -- a line reference with its assembly dropped.
BARE = re.compile(r"`:\d+(?:-\d+)?`")

# `Pug.Other` ~355773 -- assembly in backticks, number outside, optionally with
# a word like "decompiled" or "offset" in between.
TILDE_AFTER_ASSEMBLY = re.compile(
    r"`(?:DedicatedServer/)?[A-Za-z][A-Za-z0-9_.]*`"
    r"(?:[,\s]+(?:decompiled|decompile|offset|line|at)){0,3}[\s,]*~\s*`?:?\s*\d{3,}"
)

CHECKS = (
    (BARE, "line reference without its assembly", "write `Assembly:line`"),
    (
        TILDE_AFTER_ASSEMBLY,
        "line reference written with ~ outside the backticks",
        "write `Assembly:line`",
    ),
)


FENCE = re.compile(r"^\s*(```|~~~)")

# Paths this does not check, and why each is here. Found by widening the reach
# from `docs/ck/` to every markdown file, which surfaced 67 references in files
# that had never been in scope -- none of them a defect.
#
# `docs/specs/` is a record of what was decided, and a spec arguing about the
# notation quotes the banned forms to do it. The wrapping gate freezes the same
# directory for a related but different reason (reformatting edits the record),
# which is why this list is its own rather than an import: unfreezing one should
# not silently unfreeze the other.
#
# `.claude/` holds skills and agents, which *describe* the notation rather than
# use it. Two instances make the category plain: the ck-docs-review scoring
# fixtures contain deliberately planted bad citations and are half of a
# calibration instrument, and `ck-verify-chapter/SKILL.md` carries `:419767`
# inside the very sentence explaining why that form is refused. A chapter can
# put such an example in a fence; running prose cannot.
UNCHECKED = (
    "docs/specs/",
    ".claude/",
)


def unfenced_lines(path):
    """(number, text) for every line of `path` outside a fenced code block.

    Fenced code blocks are skipped, which is the difference between using a
    notation and showing one. A chapter that explains why the short form is
    unverifiable has to be able to display it, and the alternative -- a magic
    comment marking an exception -- would both drift during rewrapping and
    invite use as a way around the rule. A code fence cannot be missed by a
    reader either, which is what makes it a safe boundary.

    Shared by both halves rather than written twice, so the structural half
    inherits the boundary instead of growing its own version of it.
    """
    in_fence = False
    for number, line in enumerate(path.read_text().splitlines(), start=1):
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        if not in_fence:
            yield number, line


def syntactic_problems(path):
    """Every malformed reference in one file, as (line number, text, why, fix).

    Needs nothing but the text, so this is the half that runs in a mod
    repository. Three shapes: the two abbreviations the handbook banned, and a
    token that looks like a citation and does not parse -- a reversed range, a
    field the grammar has no place for. That last one reads `FINDER` directly
    rather than `find`, because `find` answers with citations and a malformed
    token is by definition not one.
    """
    found = []
    for number, line in unfenced_lines(path):
        for pattern, why, fix in CHECKS:
            for match in pattern.finditer(line):
                found.append((number, match.group(0), why, fix))
        for match in FINDER.finditer(line):
            if parse(match.group(1)) is None:
                found.append(
                    (
                        number,
                        match.group(0),
                        "citation token does not parse",
                        "write `Assembly:Class:member:line`, with first <= last",
                    )
                )
    return found


def structural_problems(path, decompile):
    """Every citation in `path` that is not the best form available.

    Takes the decompile, so the imports are inside the function: the syntactic
    half above has to run where neither `tree-sitter` nor a decompiled
    assembly exists, and a module-level import would make that impossible.

    `describe` decides what the best form is; nothing here re-decides it. The
    comparison is simply the citation against what `describe` writes for the
    line it resolves to, which is why a citation this reports is exactly a
    citation the migration would change.
    """
    from check_citation_drift import source_for
    from decompile_structure import describe
    from decompile_structure import locate
    from decompile_structure import structure_of

    found, structures = [], {}
    for number, line in unfenced_lines(path):
        for token, citation in find(line):
            assembly = citation.assembly
            if assembly not in structures:
                source = source_for(assembly, decompile)
                structures[assembly] = structure_of(source) if source is not None else None
            structure = structures[assembly]
            if structure is None:
                found.append(
                    (
                        number,
                        f"`{token}`",
                        f"not checked: no decompiled source for {assembly}",
                        "nothing to do unless the name is wrong",
                    )
                )
                continue

            resolved = locate(structure, citation)
            if resolved is None:
                found.append(
                    (
                        number,
                        f"`{token}`",
                        "does not resolve",
                        "the member was renamed or removed, or the form names more than one",
                    )
                )
                continue

            best = describe(structure, resolved, assembly)
            if best is None or render(best) == token:
                continue
            if tier(citation) == "absolute":
                named = best.type_name if best.member is None else f"{best.type_name}:{best.member}"
                found.append(
                    (
                        number,
                        f"`{token}`",
                        f"line is inside {named}, which the citation could name",
                        f"write `{render(best)}`",
                    )
                )
            else:
                found.append(
                    (
                        number,
                        f"`{token}`",
                        f"longer than necessary; `{render(best)}` says the same",
                        f"write `{render(best)}`",
                    )
                )
    return found


def markdown_files(root):
    """Every `*.md` under `root` that git would show, or a plain walk without git.

    Mirrors check_docs_wrapping's function of the same name, including why the
    `GIT_*` variables are stripped: a hook runs with `GIT_DIR` and
    `GIT_INDEX_FILE` set, and those outrank `-C`, so an inherited environment
    would list the hook's own repository no matter which root was asked for.

    The fallback is what the sibling does not have and this one needs: a root
    that is not a repository at all still has to be checkable, which is how the
    tests run and how a bare directory of documentation would.
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "ls-files",
                "--cached",
                "--others",
                "--exclude-standard",
                "*.md",
            ],
            capture_output=True,
            text=True,
            check=True,
            env=env,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        found = sorted(p for p in Path(root).rglob("*.md") if p.is_file())
        return [p for p in found if not str(p.relative_to(root)).startswith(UNCHECKED)]
    seen = dict.fromkeys(result.stdout.splitlines())
    return [
        Path(root) / line
        for line in seen
        if line and (Path(root) / line).is_file() and not line.startswith(UNCHECKED)
    ]


def main(argv=None):
    """Report unverifiable references across every markdown file under a root.

    Only the syntactic findings set the exit code. The structural ones are
    printed and deliberately do not, for the reason in this module's docstring:
    this runs repository-wide on any staged `.md`, and a structural finding
    means a citation could be written better, not that it is wrong.

    `argv` defaults to the command line, because the pre-commit hook invokes
    this with no arguments at all.
    """
    parser = argparse.ArgumentParser(description="Check handbook citation style.")
    parser.add_argument("root", nargs="?", default=".", help="repository or directory to check")
    parser.add_argument("--decompile", default=str(DEFAULT_DECOMPILE))
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    root = Path(args.root)
    files = markdown_files(root)
    if not files:
        print(f"no markdown files under {root} — nothing to check")
        return 0

    decompile = Path(args.decompile).expanduser()
    structural_ready = decompile.is_dir()

    blocking = structural = 0
    for path in files:
        for number, text, why, fix in syntactic_problems(path):
            blocking += 1
            print(f"{path}:{number}: {text}  — {why}; {fix}")
        if structural_ready:
            for number, text, why, fix in structural_problems(path, decompile):
                structural += 1
                print(f"{path}:{number}: {text}  — {why}; {fix}")

    if not structural_ready:
        print(f"structural checks skipped — no decompile tree at {decompile}")

    if blocking:
        print(f"\n{blocking} unverifiable line reference(s).")
        print("Every line reference must carry its assembly, or no checker can follow it.")
        return 1

    if structural:
        print(f"\n{structural} citation(s) could be anchored better — reported, not blocking.")
    print(f"OK — {len(files)} markdown file(s), every line reference carries its assembly")
    return 0


if __name__ == "__main__":
    sys.exit(main())
