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
from pathlib import Path

FENCE = re.compile(r"^\s*(```|~~~)")
# A link is kept whole on one line for the sake of reading the source. The
# rendered output is fine either way — CommonMark allows a break inside link
# text — but an editor's source view stops highlighting a link it cannot see
# whole, so it reads as loose brackets while writing.
LINK = re.compile(r"\[[^\]]*\]\([^)\s]+\)", re.S)
# a bullet needs whitespace after the marker; "*emphasis*" starting a line is
# prose, and treating it as a list ends the paragraph where it should continue
BULLET = re.compile(r"^(\s*)([-*+]|\d+\.)(\s+)(.*)$")
GLUE = "\x00"  # stands in for a space inside a link while wrapping
# a token is "a link" even with trailing punctuation: "[x](y)," is still one
LINK_TOKEN = re.compile(r"\[[^\]]*\]\([^)\s]+\)[.,;:!?)\]]*$", re.S)
SPECIAL = ("#", "|", ">", "-", "*", "+", " ", "\t")
WIDE_WIDTH, NARROW_WIDTH = 88, 80
MIN_SAMPLE = 10  # prose lines needed before a file's own width is believed
OVERSHOOT = 12  # columns past target before a long line counts as a defect
SLACK = 18  # how far below target a line may sit before it looks broken


def glue_links(text):
    """Make every link one unbreakable token, without changing its length."""
    return LINK.sub(lambda m: m.group(0).replace(" ", GLUE), text)


def unglue(text):
    return text.replace(GLUE, " ")


def split_links(lines):
    """Links in these lines that straddle a break — the defect to remove."""
    joined = "\n".join(lines)
    return [m.group(0) for m in LINK.finditer(joined) if "\n" in m.group(0)]


def wrap_tokens(text, width, initial_indent="", subsequent_indent=""):
    """Greedy wrap in which a link never starts a line it did not have to.

    A generic wrapper moves an over-long token onto a line of its own. For a
    link that is the wrong call twice over: the previous line ends short *and*
    the link's line overshoots anyway. Here a link is appended to the line it
    began on — which may overshoot — and the break falls after it.
    """
    tokens = [unglue(x) for x in glue_links(text).split()]
    lines, cur, indent = [], [], initial_indent
    for token in tokens:
        if not cur:
            cur = [token]
            continue
        if len(indent) + len(" ".join(cur)) + 1 + len(token) <= width:
            cur.append(token)
            continue
        if LINK_TOKEN.match(token):
            cur.append(token)
            lines.append(indent + " ".join(cur))
            cur, indent = [], subsequent_indent
            continue
        lines.append(indent + " ".join(cur))
        cur, indent = [token], subsequent_indent
    if cur:
        lines.append(indent + " ".join(cur))
    return lines


def first_token(line):
    """The next unit a wrapper must place, links counted whole.

    Splitting on whitespace measures only a link's first word, so a line
    ending short to make room for one looks like a defect when it is the only
    possible break. The check has to tokenise the way the fixer does.
    """
    glued = glue_links(line).split()
    return unglue(glued[0]) if glued else ""


def is_prose(line):
    """A line of plain flowing text — not a heading, table, list or quote."""
    return (
        bool(line.strip())
        and not line.startswith(("#", "|", ">", " ", "\t"))
        and not BULLET.match(line)
    )


def list_items(lines):
    """Yield (first, end, indent, prefix) per list item plus its continuations.

    Links live in list items too, so leaving lists alone would make the gate
    block on something --fix cannot reach.
    """
    i, fence = 0, False
    while i < len(lines):
        if FENCE.match(lines[i]):
            fence = not fence
            i += 1
            continue
        m = None if fence else BULLET.match(lines[i])
        if not m:
            i += 1
            continue
        lead, mark, gap, _ = m.groups()
        cont = " " * (len(lead) + len(mark) + len(gap))
        j = i + 1
        while (
            j < len(lines)
            and lines[j].startswith(cont)
            and lines[j].strip()
            and not BULLET.match(lines[j])
            and not FENCE.match(lines[j])
        ):
            j += 1
        yield i, j, cont, f"{lead}{mark}{gap}"
        i = j


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
    for link in split_links(para):
        found.append((0, f"link split across lines: {' '.join(link.split())[:60]}"))
    for offset, line in enumerate(para):
        # long only counts when a break was actually available before the target
        # a line that overshoots because it ends on a link is correct by
        # construction — wrap_tokens put it there on purpose
        # a line that overshoots because it ends on a link is correct by
        # construction — wrap_tokens put it there on purpose
        if len(line) > width + OVERSHOOT and not LINK_TOKEN.search(line):
            head = line[: width + 1].rstrip()
            if " " in head[20:]:
                found.append((offset, f"{len(line)} columns, target {width}"))
    for offset, (line, nxt) in enumerate(zip(para, para[1:])):
        # a link belongs on the line it started on, however long that makes
        # it — so a line ending just before one is a break in the wrong place
        if LINK_TOKEN.match(first_token(nxt)):
            found.append((offset, "line ends where a link should have stayed"))
            continue
        # a line introducing a block ("as follows:") or closing a thought ends
        # short on purpose
        if line.rstrip().endswith((":", ".", "—")):
            continue
        # short only counts when the next word would have fit comfortably
        if (
            len(line) < width - SLACK
            and len(line) + 1 + len(first_token(nxt)) <= width - 2
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
            new = wrap_tokens(" ".join(x.strip() for x in para), width)
            if new != para:
                out.extend(lines[last:start])
                out.extend(new)
                last = end
                rewrapped += 1

    if fix and rewrapped:
        out.extend(lines[last:])
        lines = out

    # list items wrap separately: bullet and hanging indent must survive
    out, last, listed = [], 0, 0
    for first, end, cont, prefix in list_items(lines):
        item = lines[first:end]
        splits = split_links(item)
        if not splits and not any(
            len(x) > width + OVERSHOOT and not x.rstrip().endswith(")") for x in item
        ):
            continue
        for link in splits:
            problems.append(
                f"{display(path)}:{first + 1}  list item: {' '.join(link.split())[:60]}"
            )
        if not fix:
            continue
        # the bullet comes back via initial_indent; leaving it in the body
        # produced "- - text"
        body = " ".join(
            [item[0][len(prefix) :].strip()] + [x.strip() for x in item[1:]]
        )
        new = wrap_tokens(body, width, initial_indent=prefix, subsequent_indent=cont)
        if new != item:
            out.extend(lines[last:first])
            out.extend(new)
            last = end
            listed += 1

    if fix and listed:
        out.extend(lines[last:])
        lines = out

    if fix and (rewrapped or listed):
        path.write_text("\n".join(lines) + "\n")
    return problems, rewrapped + listed


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
