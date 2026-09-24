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

**What this deliberately does not flag.** A tilde followed by a number is
usually not a line reference at all -- `~1300-entity scan`, `~143 MB`, `~180
scene names`, `~135 lines` are quantities, and a checker that rejected those
would be wrong far more often than right. Only the two unambiguous shapes are
errors here; a bare `~124928` in prose is left to the reader.

Usage:  uv run utils/check_citation_style.py [root]
"""

import re
import sys
from pathlib import Path

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


def problems_in(path):
    """Every offending reference in one file, as (line number, text, why, fix).

    Fenced code blocks are skipped, which is the difference between using a
    notation and showing one. A chapter that explains why the short form is
    unverifiable has to be able to display it, and the alternative -- a magic
    comment marking an exception -- would both drift during rewrapping and
    invite use as a way around the rule. A code fence cannot be missed by a
    reader either, which is what makes it a safe boundary.
    """
    found = []
    in_fence = False
    for number, line in enumerate(path.read_text().splitlines(), start=1):
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        for pattern, why, fix in CHECKS:
            for m in pattern.finditer(line):
                found.append((number, m.group(0), why, fix))
    return found


def main():
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    chapters = sorted((root / "docs" / "ck").glob("*.md"))
    if not chapters:
        print("no docs/ck chapters found — nothing to check")
        return 0

    total = 0
    for chapter in chapters:
        for number, text, why, fix in problems_in(chapter):
            total += 1
            print(f"{chapter}:{number}: {text}  — {why}; {fix}")

    if total:
        print(f"\n{total} unverifiable line reference(s).")
        print("Every line reference must carry its assembly, or no checker can follow it.")
        return 1

    print(f"OK — {len(chapters)} chapters, every line reference carries its assembly")
    return 0


if __name__ == "__main__":
    sys.exit(main())
