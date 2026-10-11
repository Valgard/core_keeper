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

    found, sources, structures = [], {}, {}
    for number, line in unfenced_lines(path):
        for token, citation in find(line):
            assembly = citation.assembly
            if assembly not in sources:
                sources[assembly] = source_for(assembly, decompile)
                structures[assembly] = (
                    structure_of(sources[assembly]) if sources[assembly] is not None else None
                )
            structure = structures[assembly]
            if structure is None:
                # Two facts, not one, and only the second occurs in the real
                # corpus: both prefab citations resolve to a file that is right
                # there and simply is not C#. Collapsing them printed a message
                # about a missing source that was false every time, with advice
                # that sent the reader looking for the file. Same None-versus-()
                # rule the structure layer keeps, one level up.
                if sources[assembly] is None:
                    why = f"not checked: nothing named {assembly} in the decompile"
                    fix = "check the name, or add the assembly to the decompile"
                else:
                    why = f"not checked: {assembly} is not C#, so it has no elements to name"
                    fix = "nothing to do — a line is the only anchor such a file has"
                found.append((number, f"`{token}`", why, fix))
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

            # The whole span, not just its first line. Describing one end names
            # whatever element holds that line, which for a range crossing out
            # of it is a different element entirely: `ScriptableData:34-45`
            # spans three field declarations, and describing line 34 alone
            # advised `...:m_guid:1` -- a field, with the range thrown away.
            # 133 of the corpus's 894 findings were that mistake.
            best = describe(
                structure, resolved, assembly, last=resolved + citation.last - citation.first
            )
            if best is None or render(best) == token:
                continue
            if tier(citation) == "absolute":
                # `best` is a member or type citation here -- an absolute one
                # renders identically to the token and was filtered above -- but
                # guard anyway: writing the word "None" into a finding tells a
                # reader nothing and happened once already, from the range
                # defect this same function used to have.
                if best.type_name is None:
                    named = "an element the structure layer could not name"
                elif best.member is None:
                    named = best.type_name
                else:
                    named = f"{best.type_name}:{best.member}"
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


def structural_available(decompile):
    """(ready, reason) — whether the structural half can run in this checkout.

    Two conditions, not one. The decompile has to be there, and `tree-sitter`
    has to be importable: a mod repository can have the first without the
    second, and a bare `import` would then end the run with a traceback and a
    non-zero exit — a blocking structural half, which is the one thing this
    design rules out. Checked once in `main` rather than per file, so the
    reason is stated once too.
    """
    if not Path(decompile).is_dir():
        return False, f"no decompile tree at {decompile}"
    try:
        import decompile_structure  # noqa: F401
    except ImportError as exc:
        return False, f"tree-sitter is not installed here ({exc})"
    return True, ""


def _repo_relative(root):
    """A function turning a path into one relative to the repository, if there is one.

    `UNCHECKED` lists repository-relative prefixes, and `git ls-files -C root`
    reports paths relative to `root` — so the two only agree when `root` *is*
    the repository. Pass a subdirectory and every exclusion silently misses,
    which for a blocking gate means turning red on the files it exists to leave
    alone. `CLAUDE.md` records the same defect in `check_docs_wrapping --fix
    docs/`, where it rewrote eight frozen specs; here it is cheaper to fix than
    to document.
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    try:
        top = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
            env=env,
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return lambda path: str(Path(path).relative_to(root))

    toplevel = Path(top).resolve()
    return lambda path: str(Path(path).resolve().relative_to(toplevel))


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
    relative = _repo_relative(root)
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
        found = [Path(root) / line for line in dict.fromkeys(result.stdout.splitlines()) if line]
    except (subprocess.CalledProcessError, FileNotFoundError):
        found = sorted(Path(root).rglob("*.md"))
    return [p for p in found if p.is_file() and not relative(p).startswith(UNCHECKED)]


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
    structural_ready, skip_reason = structural_available(decompile)

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
        print(f"structural checks skipped — {skip_reason}")

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
