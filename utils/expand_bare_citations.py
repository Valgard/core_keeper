#!/usr/bin/env python3
"""Rewrite the handbook's short-form line references into full citations.

A line reference written as `:419767` inherits its assembly from the last full
citation nearby, which reads well and is invisible to every tool: the drift
checker's pattern requires `Assembly:line`, so 288 of the handbook's ~498 line
references stood outside it entirely. After a major update they are as wrong as
the ones that are checked, and nothing says so.

This expands them once, so that a single notation remains and the existing
checker covers all of it. `check_citation_style.py` then keeps the short form
from coming back.

**The inheritance is not purely mechanical, which is why the server cases are
listed by hand.** The handbook's own convention says an unmarked citation is the
client build and a server citation says so in prose -- and prose is where a
script goes wrong: `API.Server.World (`ModAPIServer.World`, `:392317`)` mentions
"Server" as part of an identifier, not as a build. Reading that as the server
tree would point a correct citation at unrelated code. Five references are
genuinely server-side; every one of them was read in context first.

Run once, then delete. Kept in the repository only so the next person can see
what was done to 288 lines of prose, and check it.

Usage:  uv run utils/expand_bare_citations.py [--apply] [root]
"""

import argparse
import re
import sys
from pathlib import Path

FULL = re.compile(r"`((?:DedicatedServer/)?[A-Za-z][A-Za-z0-9_.]*):(\d+)(?:-(\d+))?`")
# The span form `:1376-1386` is as common as the single one and was missed on
# the first pass, which is what the style gate then reported: a checker that
# only ever confirms what the writer already thought of is not a checker.
BARE = re.compile(r"`:(\d+)(?:-(\d+))?`")
TOKEN = re.compile(r"`(?:(?:DedicatedServer/)?[A-Za-z][A-Za-z0-9_.]*)?:\d+(?:-\d+)?`")

# (chapter, line number in the file as it stands now, referenced number) whose
# assembly is NOT the inherited one. Each was read in its sentence first.
OVERRIDES = {
    ("harmony-and-ecs.md", 15, 2656): "DedicatedServer/Pug.Other",
    ("harmony-and-ecs.md", 310, 263271): "DedicatedServer/Pug.Other",
    ("harmony-and-ecs.md", 312, 263187): "DedicatedServer/Pug.Other",
    ("harmony-and-ecs.md", 314, 270188): "DedicatedServer/Pug.Other",
    ("harmony-and-ecs.md", 371, 2914): "DedicatedServer/Pug.Other",
}

# A bare reference standing before any full citation in its chapter has nothing
# to inherit from. Each such passage does name its assembly -- just in a form no
# pattern catches: `Pug.Other` ~355773 puts the number outside the backticks,
# and `extension methods in `PugMod.SDK.Runtime` (`:602`, `:642`)` names it as
# plain prose. Read out of those passages rather than inferred:
#
#   ui-framework.md    `UIMouse.UpdateMouseUIInput()` (`Pug.Other` ~355773)
#   sandbox.md         "extension methods in `PugMod.SDK.Runtime` (`:602`, `:642`)"
#   troubleshooting.md "`unsupportedModsToLoad` is `PugMod.Loader`'s config list (`:1070`)"
#
# The middle one is why this list is read and not guessed: sandbox.md is the
# chapter about Trivial.CodeSecurity, so that is the assembly a reasonable guess
# lands on, and the sentence says otherwise.
CHAPTER_DEFAULT_BEFORE_FIRST = {
    "ui-framework.md": "Pug.Other",
    "sandbox.md": "PugMod.SDK.Runtime",
    "troubleshooting.md": "PugMod.Loader",
}


OLD_CHECKOUT = Path.home() / "Projects/checkouts/CoreKeeperDecompile-1.2.1.5-8be0"
CLIENT_DEFAULT = "Pug.Other"
_sizes = {}


def assembly_length(asm):
    """Line count of an assembly in the checkout the references were written for."""
    if asm not in _sizes:
        p = OLD_CHECKOUT / f"{asm}.decompiled.cs"
        _sizes[asm] = sum(1 for _ in p.open(errors="replace")) if p.is_file() else None
    return _sizes[asm]


def fits(asm, number):
    """Whether that assembly can hold that line at all."""
    n = assembly_length(asm)
    return n is not None and number <= n


def expand(chapter_path, apply):
    """Return (expansions, unresolved) for one chapter, optionally rewriting it.

    Inheritance carries an assembly forward until the next full citation, which
    is wrong wherever the prose cites a small assembly and then returns to
    Pug.Other without naming it again -- the anchor can be 441 lines back, and by
    then it is a fiction. Those are caught rather than trusted: a line number
    past the end of the inherited assembly cannot be that assembly's, so it falls
    back to the client default the handbook documents.

    That check found 31 of the 288, all in Pug.Other, and each was verified
    against the old checkout by reading the line: `BucketSlot` (`:310153`) is
    `public class BucketSlot : PlaceObjectSlot`, Backspace (`:269628`) is
    `if (IsKeyDown(KeyCode.Backspace))`, and so on for all 31. The bound is what
    makes a silent mis-inheritance loud.
    """
    name = chapter_path.name
    lines = chapter_path.read_text().splitlines(keepends=True)
    current = None
    expansions, unresolved = [], []

    for idx, line in enumerate(lines):
        n = idx + 1
        out, pos = [], 0
        for m in TOKEN.finditer(line):
            tok = m.group(0)
            full = FULL.fullmatch(tok)
            if full:
                current = full.group(1)
                continue
            bare = BARE.fullmatch(tok)
            if not bare:
                continue
            num = int(bare.group(1))
            end = bare.group(2)
            span = f"{num}-{end}" if end else f"{num}"
            override = OVERRIDES.get((name, n, num))
            asm = override or current or CHAPTER_DEFAULT_BEFORE_FIRST.get(name)
            how = "override" if override else "inherited"
            if asm is None:
                unresolved.append((n, num))
                continue
            # Bound-check the far end too: a span reaching past the file is the
            # same mis-inheritance, and only its last line shows it.
            probe = int(end) if end else num
            if not override and not fits(asm, probe):
                if not fits(CLIENT_DEFAULT, probe):
                    unresolved.append((n, num))
                    continue
                asm, how = CLIENT_DEFAULT, "bounds-corrected"
            out.append((m.start(), m.end(), f"`{asm}:{span}`"))
            expansions.append((n, num, asm, how))

        if out and apply:
            rebuilt = []
            for start, end, repl in out:
                rebuilt.append(line[pos:start])
                rebuilt.append(repl)
                pos = end
            rebuilt.append(line[pos:])
            lines[idx] = "".join(rebuilt)

    if apply and expansions:
        chapter_path.write_text("".join(lines))
    return expansions, unresolved


def main():
    """Report (or, with --apply, rewrite) every chapter's bare citations.

    Dry-run by default, matching every other checker/fixer pair in this
    directory — seeing the plan before anything is rewritten matters more here
    than anywhere else, since a bad expansion turns a merely-unverified
    citation into a wrong one. The exit code follows `unresolved_all`, not
    `total`: a run that found nothing left to expand is success even when
    `--apply` was never passed.
    """
    ap = argparse.ArgumentParser()
    ap.add_argument("root", nargs="?", default=".")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    total, by_asm, unresolved_all, overrides = 0, {}, [], 0
    for chapter in sorted((Path(args.root) / "docs" / "ck").glob("*.md")):
        exps, unres = expand(chapter, args.apply)
        total += len(exps)
        overrides += sum(1 for e in exps if e[3] == "override")
        for _n, _num, asm, _how in exps:
            by_asm[asm] = by_asm.get(asm, 0) + 1
        unresolved_all += [(chapter.name, n, num) for n, num in unres]

    print(f"{total} bare reference(s) expanded, {overrides} by explicit override")
    for asm, n in sorted(by_asm.items(), key=lambda kv: -kv[1]):
        print(f"  {asm:<32}{n:>5}")
    if unresolved_all:
        print(f"\n{len(unresolved_all)} could not be resolved:")
        for c, n, num in unresolved_all:
            print(f"  {c}:{n}  `:{num}`")
    if not args.apply:
        print("\nreport only — pass --apply to rewrite")
    return 1 if unresolved_all else 0


if __name__ == "__main__":
    sys.exit(main())
