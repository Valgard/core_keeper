#!/usr/bin/env python3
"""Report which docs/ck/ chapters are verified, and against what.

The ck-verify-chapter skill keeps no register file: a chapter's verification
state is its newest `docs(ck): verify <chapter> against <build>` commit. Such a
commit vouches for two things together, and this script checks both:

- **the text as of that commit.** Any line changed since -- committed or not --
  was never seen by the pass. One changed line makes a chapter partial; there
  is no threshold.
- **the build in its subject line.** If its first three parts differ from the
  current build, the verdict is void even with not one line changed. If only
  the fourth part (or the hash) differs, it stands, except for the claims whose
  cited lines `relocate_citations.py` can no longer find.

The current build is read from the decompile checkout's README heading, the
same string the skill tells a pass to put in its commit, and falls back to the
citation snapshot's `game_version`. `--build` overrides both.

`index.md` and `README.md` are left out, as `check_docs_links.py` leaves them out
of its chapter list: one routes to the chapters, the other introduces them.

Usage:
    uv run utils/verify_status.py                   # every chapter
    uv run utils/verify_status.py --build 1.3.0.5-cb48

Always exits 0 -- this is a report, not a gate.
"""

import argparse
import difflib
import itertools
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from citation_notation import find

DEFAULT_DECOMPILE = Path.home() / "Projects/checkouts/CoreKeeperDecompile"
DEFAULT_SNAPSHOT = Path(__file__).resolve().parent / "ck-citation-snapshot.json"
NOT_CHAPTERS = ("README.md", "index.md")

SUBJECT = re.compile(r"^docs\(ck\): verify (?P<chapter>\S+?)(?:\.md)? against (?P<build>\S+)$")
BUILD = re.compile(r"^(\d+)\.(\d+)\.(\d+)\.(\d+)(?:-\w+)?$")
README_HEADING = re.compile(r"^#\s.*`(\d+\.\d+\.\d+\.\d+-\w+)`", re.MULTILINE)


@dataclass(frozen=True)
class Verification:
    """A chapter's newest verification commit, and how far its text moved since."""

    chapter: str
    commit: str
    build: str
    added: int
    deleted: int


@dataclass(frozen=True)
class Status:
    """One chapter's state under the skill's rule."""

    state: str  # verified | hotfix | partial | unverified
    detail: str


def parse_subject(subject):
    """(chapter, build) from a verification commit subject, or None for any other commit."""
    m = SUBJECT.match(subject)
    return (m["chapter"], m["build"]) if m else None


def parse_build(build):
    """The four numeric parts of a build string; the hash, if any, is dropped."""
    m = BUILD.match(build)
    if not m:
        raise ValueError(f"not a four-part build: {build!r}")
    return tuple(int(part) for part in m.groups())


def classify(verification, current):
    """Apply the skill's rule: the text as of the commit, against the build it names."""
    if verification is None:
        return Status("unverified", "never verified")
    v = verification
    if parse_build(v.build)[:3] != parse_build(current)[:3]:
        return Status("unverified", f"verified against {v.build}, current build is {current}")
    hotfix = v.build != current
    if v.added or v.deleted:
        detail = f"+{v.added}/-{v.deleted} lines since {v.commit}"
        if hotfix:
            detail += f"; also a hotfix since ({v.build} -> {current})"
        return Status("partial", detail)
    if hotfix:
        return Status(
            "hotfix",
            f"{v.build} -> {current}: re-check claims relocate_citations.py cannot place",
        )
    return Status("verified", f"{v.build} at {v.commit}")


def _git(root, *args):
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    ).stdout


CITATION_PLACEHOLDER = "\x00citation\x00"


def normalise(text):
    """`text` with every citation replaced by one placeholder.

    So that a renumbered citation is not a change and a *migrated* one is not
    either: both notations collapse to the same string. The second half matters
    as much as the first -- without it the migration commit reads as prose and
    fells the tick of every chapter it touches, which is the failure this whole
    change exists to remove, reintroduced by the step meant to carry it.

    Substitutes the tokens `citation_notation.find` returns rather than a
    pattern of its own, so this and the checkers agree on what a citation is by
    construction instead of by two regexes kept in step.

    Transitional, with the same planned end of life as `relocate_citations.py`:
    once every chapter is anchored on a symbol, a hotfix rewrites no citation
    and there is nothing left to normalise away.
    """
    for token, _ in find(text):
        text = text.replace(f"`{token}`", CITATION_PLACEHOLDER)
    return text


def changed_lines(root, commit, chapter):
    """(added, deleted) between the chapter at `commit` and in the working tree.

    Normalised on both sides, which is why this cannot be `git diff --numstat`:
    that counts lines of the text as written, and the whole point is to compare
    something else. A chapter that did not exist at `commit` counts as nothing,
    which is the behaviour the numstat call had for the same case.
    """
    path = f"docs/ck/{chapter}.md"
    try:
        before = _git(root, "show", f"{commit}:{path}")
    except subprocess.CalledProcessError:
        # Absent from that commit, so every line it has now was written after
        # the verification. NOT (0, 0): an earlier version returned that and
        # claimed parity with `git diff --numstat`, which is false in exactly
        # this case -- numstat reported the file as wholly added and printed
        # `partial`, while (0, 0) prints `verified`. The two fail on different
        # things: numstat cannot see an untracked file, `git show` cannot see a
        # path the commit did not have.
        before = ""
    current = Path(root, path)
    after = current.read_text() if current.is_file() else ""

    diff = difflib.unified_diff(
        normalise(before).splitlines(), normalise(after).splitlines(), n=0, lineterm=""
    )
    # The two file headers are skipped by position, not by prefix. `---` is
    # ordinary Markdown, and with the diff's own marker in front such a line
    # reads as `----` -- a prefix test discards it as a header and the change
    # vanishes. The direction is the dangerous one: it *under*-counts, and
    # `classify` has no threshold, so a chapter with real prose edits would
    # read as verified. `unified_diff` emits those two lines only when there is
    # a hunk at all, so slicing an empty diff is still empty.
    added = deleted = 0
    for line in itertools.islice(diff, 2, None):
        if line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            deleted += 1
    return (added, deleted)


def latest_verifications(root):
    """{chapter: Verification} for every chapter with a verification commit, newest one each."""
    found = {}
    log = _git(root, "log", "--format=%h%x00%s", "--grep=^docs(ck): verify ")
    for line in log.splitlines():
        commit, _, subject = line.partition("\0")
        parsed = parse_subject(subject)
        if not parsed or parsed[0] in found:
            continue
        chapter, build = parsed
        # Against the working tree, not HEAD: an uncommitted edit is unverified too.
        added, deleted = changed_lines(root, commit, chapter)
        found[chapter] = Verification(chapter, commit, build, added, deleted)
    return found


def current_build(decompile, snapshot):
    """The build the decompile checkout is of, else the one the citation snapshot was taken at."""
    readme = Path(decompile) / "README.md"
    if readme.is_file():
        m = README_HEADING.search(readme.read_text())
        if m:
            return m[1], f"{readme} heading"
    if Path(snapshot).is_file():
        version = json.loads(Path(snapshot).read_text()).get("game_version")
        if version:
            return version, f"{snapshot} game_version"
    return None, None


def main(argv=None):
    """Print one line per chapter: state, name, and why."""
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("root", nargs="?", default=".")
    ap.add_argument(
        "--build", help="current build, e.g. 1.3.0.5-cb48 (default: read from the decompile)"
    )
    ap.add_argument("--decompile", default=str(DEFAULT_DECOMPILE))
    ap.add_argument("--snapshot", default=str(DEFAULT_SNAPSHOT))
    args = ap.parse_args(argv)

    root = Path(args.root)
    build, source = (
        (args.build, "--build")
        if args.build
        else current_build(Path(args.decompile).expanduser(), args.snapshot)
    )
    if not build:
        print(
            "current build unknown: no decompile README and no snapshot game_version; pass --build"
        )
        return 0
    print(f"current build {build} (from {source})\n")

    verifications = latest_verifications(root)
    chapters = sorted(
        p.stem for p in (root / "docs" / "ck").glob("*.md") if p.name not in NOT_CHAPTERS
    )
    for name in sorted(set(verifications) - set(chapters)):
        print(f"note: verification commit names {name!r}, not a chapter (renamed, or a typo?)")

    statuses = {name: classify(verifications.get(name), build) for name in chapters}
    width = max(map(len, chapters), default=0)
    for state in ("verified", "hotfix", "partial", "unverified"):
        for name in chapters:
            if statuses[name].state == state:
                print(f"{state:<10}  {name:<{width}}  {statuses[name].detail}")

    partial = [n for n in chapters if statuses[n].state == "partial"]
    if partial:
        # Names the raw diff deliberately, with a word about why its numbers
        # will be larger: the counts above are taken after normalising the
        # citations away, and a reader who ran the plain command and saw +92/-31
        # against a reported +61/-0 would reasonably think one of them lying.
        print("\nunverified hunks: git diff <commit> -- docs/ck/<chapter>.md")
        print("(that diff counts renumbered citations too; the figures above do not)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
