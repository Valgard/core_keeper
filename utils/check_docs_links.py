#!/usr/bin/env python3
"""Check every relative Markdown link and anchor in this repository.

A broken anchor is the quietest documentation defect there is: the file still
renders, the link is still blue, it just lands nowhere. It happens whenever a
heading is reworded, which is why docs/ck/ carries the rule that headings are
never renamed — this script is that rule, enforced.

Scope is the repository's own tracked and untracked-but-not-ignored Markdown,
taken from `git ls-files`. That matters here: the SDK clone and every mod repo
sit inside this one as separate repositories, so a plain directory walk would
reach thousands of foreign files. It is the same reasoning that makes
.csharpierignore an allowlist.

Checked per file: relative links resolve to an existing file; `#anchors` match a
heading in the target; no two headings in one file produce the same anchor; code
fences are balanced. Plus one rule for the handbook: every chapter under docs/ck
is linked from its index.md, so a new chapter cannot be added and left
unreachable.

Usage:
    uv run utils/check_docs_links.py [repo-root]
"""

import os
import re
import subprocess
import sys
from pathlib import Path

FENCE = re.compile(r"^\s*(```|~~~)")
HEADING = re.compile(r"^#+\s+(.*)$")
# [^\]] spans newlines on purpose: a link whose text is wrapped across two lines
# is valid Markdown, and a line-wise matcher silently skips it.
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")


def anchor(heading):
    """Slugify a heading the way GitHub does."""
    s = re.sub(r"[`*_]", "", heading.strip().lower())
    s = re.sub(r"[^a-z0-9 -]", "", s)
    return s.replace(" ", "-")  # every space becomes a hyphen, runs included


def heading_anchors(text):
    """The anchor each heading in this (already fence-masked) text produces."""
    anchors = set()
    for line in text.splitlines():
        match = HEADING.match(line)
        if match:
            anchors.add(anchor(match.group(1)))
    return anchors


def mask_fences(text):
    """Blank out fenced blocks, keeping the line count so numbers stay true."""
    out, inside = [], False
    for line in text.splitlines():
        if FENCE.match(line):
            inside = not inside
            out.append("")
        else:
            out.append("" if inside else line)
    return "\n".join(out), inside


def markdown_files(root):
    """Tracked and untracked-but-not-ignored *.md, so foreign repositories
    nested here are never reached.

    Returns (existing, missing). A tracked file that is gone from the working
    tree is a finding, not a crash: that is exactly the state of a deleted .md
    at the moment the commit hook runs.
    """
    # GIT_DIR and GIT_INDEX_FILE outrank -C, and a hook runs with both set:
    # inherited, this would list the hook's repository no matter which root
    # was asked for. Strip them so -C means what it says.
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    # --others --exclude-standard adds files that are not tracked yet but are
    # not ignored either: a chapter written and not yet staged is exactly the
    # file most likely to carry a broken link, and skipping it reported OK.
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
    tracked = [
        root / line for line in dict.fromkeys(result.stdout.splitlines()) if line
    ]
    return [p for p in tracked if p.is_file()], [p for p in tracked if not p.is_file()]


def check(files, root):
    """Return a list of human-readable problems; empty means everything holds."""
    problems, headings, masked = [], {}, {}

    for path in files:
        text, unclosed = mask_fences(path.read_text())
        masked[path] = text
        if unclosed:
            problems.append(f"{path.relative_to(root)}  unclosed code fence")
        seen = {}
        for number, line in enumerate(text.splitlines(), 1):
            match = HEADING.match(line)
            if not match:
                continue
            slug = anchor(match.group(1))
            if slug in seen:
                problems.append(
                    f"{path.relative_to(root)}:{number}  duplicate heading "
                    f"anchor '{slug}' (also line {seen[slug]})"
                )
            seen[slug] = number
        headings[path] = set(seen)

    known = {p.resolve(): a for p, a in headings.items()}
    for path in files:
        text = masked[path]
        for match in LINK.finditer(text):
            target = match.group(1)
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            number = text[: match.start()].count("\n") + 1
            where = f"{path.relative_to(root)}:{number}"
            file_part, _, frag = target.partition("#")
            if not file_part:
                if frag and frag not in headings[path]:
                    problems.append(f"{where}  no such anchor -> #{frag}")
                continue
            dest = (path.parent / file_part).resolve()
            if not dest.exists():
                problems.append(f"{where}  no such file -> {target}")
            elif frag:
                if dest in known:
                    target_anchors = known[dest]
                else:
                    # the scope rule governs which files are *checked*, not
                    # which are resolvable as link targets: a target that
                    # exists on disk but sits outside scope (gitignored, say)
                    # still gets its headings parsed here, on demand
                    target_text, _ = mask_fences(dest.read_text())
                    target_anchors = heading_anchors(target_text)
                if frag not in target_anchors:
                    problems.append(f"{where}  no such anchor -> {target}")

    problems.extend(check_handbook_complete(files, root))
    return problems


def check_handbook_complete(files, root):
    """Every docs/ck chapter must be reachable from index.md.

    index.md is the entry point and carries the chapter list; README.md
    describes the work and deliberately does not enumerate it. So the
    completeness rule belongs to the index alone — requiring it of both would
    force the duplicate list that separating them was meant to avoid.
    """
    docs = root / "docs" / "ck"
    index = docs / "index.md"
    if not index.exists():
        return []
    # mask_fences so a filename merely shown in a code block (a directory
    # listing, say) does not count as a link to it
    text, _ = mask_fences(index.read_text())
    linked = {match.group(1).partition("#")[0] for match in LINK.finditer(text)}
    return [
        f"docs/ck/index.md  does not link chapter {f.name}"
        for f in files
        if f.parent == docs
        and f.name not in ("README.md", "index.md")
        and f.name not in linked
    ]


def main(argv):
    root = Path(argv[1] if len(argv) > 1 else ".").resolve()
    files, missing = markdown_files(root)
    problems = [f"{p.relative_to(root)}  tracked but not on disk" for p in missing]
    problems += check(files, root)
    if problems:
        print(f"{len(problems)} problem(s):")
        for problem in problems:
            print(f"  {problem}")
        return 1
    total = sum(len(LINK.findall(mask_fences(f.read_text())[0])) for f in files)
    print(f"OK — {len(files)} Markdown files, {total} links, all resolve")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
