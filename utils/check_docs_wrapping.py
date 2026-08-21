#!/usr/bin/env python3
"""Check (and optionally fix) line wrapping in this repository's Markdown.

Editing prose by pattern lengthens a line without rewrapping the paragraph it
sits in. The result is invisible to a link checker and to a formatter, but it
accumulates: one substitution left a 142-column line in a file wrapped at 80.

Two things this does NOT do, both learned the hard way:

**It does not impose a width.** Each file is measured against the width it
already uses, taken from its own 90th percentile. Two chapters here are written
at ~88 columns and the rest at 80; forcing one number on all of them would
rewrite hundreds of untouched lines to satisfy a convention nobody agreed on.

**It does not flag a line for being short.** A break is only a defect if a
better one was available — a long code span or link simply cannot be split, and
a paragraph that ends at column 60 because the next token is 25 characters wide
is correctly wrapped. A first version of this check compared against a flat 80
and reported 763 findings, essentially none of them real.

Usage:
    uv run utils/check_docs_wrapping.py [--fix] [path ...]
"""

import re
import subprocess
import sys
import textwrap
from pathlib import Path

FENCE = re.compile(r"^\s*(```|~~~)")
SPECIAL = ("#", "|", ">", "-", "*", "+", " ", "\t")
WIDE_WIDTH, NARROW_WIDTH = 88, 80
MIN_SAMPLE = 10  # prose lines needed before a file's own width is believed
OVERSHOOT = 12  # columns past target before a long line counts as a defect
SLACK = 18  # how far below target a line may sit before it looks broken


def is_prose(line):
    """A line of plain flowing text — not a heading, table, list or quote."""
    return (
        bool(line.strip())
        and not line.startswith(SPECIAL)
        and not re.match(r"^\d+\.", line)
    )


def target_width(lines):
    """The width this file already uses, so a fix does not restyle it.

    Measured by the median, not a high percentile: the defects being looked for
    are over-long lines, and a percentile lets them raise the very width they
    are measured against. In a short file that is circular — one 200-column
    line would declare the file "wide" and be left alone.
    """
    lengths = sorted(len(l) for l in lines[body_start(lines) :] if is_prose(l))
    # too few lines to infer anything: keep the default rather than let two
    # lines vote on a house style
    if len(lengths) < MIN_SAMPLE:
        return NARROW_WIDTH
    median = lengths[len(lengths) // 2]
    return WIDE_WIDTH if median > 81 else NARROW_WIDTH


def body_start(lines):
    """Skip YAML front matter — it is data, and its lines are not prose."""
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                return i + 1
    return 0


def paragraphs(lines):
    """Yield (start, end) for each run of prose outside code fences."""
    i, fence = body_start(lines), False
    while i < len(lines):
        if FENCE.match(lines[i]):
            fence = not fence
            i += 1
            continue
        if fence or not is_prose(lines[i]):
            i += 1
            continue
        start = i
        # FENCE must be checked here too: a fence line starts with a backtick,
        # which is not a special leading character, so a paragraph running into
        # one would swallow it — and a rewrap would then destroy the code block.
        while i < len(lines) and is_prose(lines[i]) and not FENCE.match(lines[i]):
            i += 1
        yield start, i


def defects(para, width):
    """Reasons this paragraph is mis-wrapped; empty means it is fine."""
    found = []
    for offset, line in enumerate(para):
        # long only counts when a break was actually available before the target
        if len(line) > width + OVERSHOOT:
            head = line[: width + 1].rstrip()
            if " " in head[20:]:
                found.append((offset, f"{len(line)} columns, target {width}"))
    for offset, (line, nxt) in enumerate(zip(para, para[1:])):
        # a line introducing a block ("as follows:") or closing a thought ends
        # short on purpose
        if line.rstrip().endswith((":", ".", "—")):
            continue
        # short only counts when the next word would have fit comfortably
        if (
            len(line) < width - SLACK
            and len(line) + 1 + len(nxt.split()[0]) <= width - 2
        ):
            found.append((offset, f"breaks at {len(line)}, target {width}"))
    return found


def process(path, fix):
    lines = path.read_text().splitlines()
    width = target_width(lines)
    problems, rewrapped, out, last = [], 0, [], 0

    for start, end in paragraphs(lines):
        para = lines[start:end]
        if len(para) < 2:
            continue
        found = defects(para, width)
        if not found:
            continue
        for offset, why in found:
            problems.append(f"{display(path)}:{start + offset + 1}  {why}")
        if fix:
            new = textwrap.wrap(
                " ".join(x.strip() for x in para),
                width=width,
                break_long_words=False,
                break_on_hyphens=False,
            )
            if new != para:
                out.extend(lines[last:start])
                out.extend(new)
                last = end
                rewrapped += 1

    if fix and rewrapped:
        out.extend(lines[last:])
        path.write_text("\n".join(out) + "\n")
    return problems, rewrapped


# Frozen by intent: a design spec records what was decided at a point in time.
# Reformatting one rewrites history for no reader's benefit.
FROZEN = ("docs/specs/",)


def display(path):
    try:
        return str(path.resolve().relative_to(Path(__file__).resolve().parent.parent))
    except ValueError:
        return str(path)


def markdown_files(root):
    env_keys = [k for k in __import__("os").environ if not k.startswith("GIT_")]
    env = {k: __import__("os").environ[k] for k in env_keys}
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
    seen = dict.fromkeys(result.stdout.splitlines())
    return [
        root / line
        for line in seen
        if line and (root / line).is_file() and not line.startswith(FROZEN)
    ]


def main(argv):
    fix = "--fix" in argv
    args = [a for a in argv[1:] if not a.startswith("--")]
    root = Path(__file__).resolve().parent.parent
    files = [Path(a) for a in args] if args else markdown_files(root)

    problems, rewrapped, checked = [], 0, 0
    for f in sorted(files):
        p, r = process(f, fix)
        problems += p
        rewrapped += r
        checked += 1

    if fix:
        print(f"rewrapped {rewrapped} paragraph(s) across {checked} file(s)")
        return 0
    if problems:
        print(f"{len(problems)} mis-wrapped line(s):")
        for p in problems:
            print(f"  {p}")
        print("\nfix with: uv run utils/check_docs_wrapping.py --fix")
        return 1
    print(f"OK — {checked} Markdown files, wrapping consistent")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
