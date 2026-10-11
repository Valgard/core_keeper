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
        detail = f"+{v.added}/-{v.deleted} words since {v.commit}"
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


def changed_words(root, commit, chapter):
    """(added, deleted) words between the chapter at `commit` and in the working tree.

    Normalised on both sides, which is why this cannot be `git diff
    --numstat`: that counts lines of the text as written, and the whole point
    is to compare something else.

    **Words rather than lines, because anchoring a chapter's citations forces
    a rewrap.** An anchored citation runs some 40 characters longer than the
    absolute number it replaces, so every paragraph holding one overflows the
    width its file is written at and the wrapping gate rewraps it. Measured on
    `harmony-and-ecs` against its verification commit `4bad12e`, in both units
    so that neither figure is compared with the other's:

        prose written since the pass      61/0 lines      557/0 words
        the anchoring and its rewrap     370/301 lines      0/0 words
        what the tool would report       429/299 lines    557/0 words

    Seven times the real figure, line-wise, from a change in which no word
    moved. Word-wise a single changed word is still counted and the comparison
    has no opinion about where the breaks fall.

    It also retires a hazard rather than fixing it. The line version parsed
    unified-diff output and had to skip the two file headers by position,
    because a Markdown `---` with a diff marker in front reads as `----` and
    a prefix test discarded it -- undercounting, in a function whose caller
    has no threshold. There is no diff text here to mistake anything in.

    A chapter that did not exist at `commit` counts as wholly added, which is
    what the numstat call did for that case.
    """
    path = f"docs/ck/{chapter}.md"
    # Two questions, asked separately, because only one of the answers is
    # harmless. Is the commit readable at all -- a mistyped or
    # garbage-collected one raises here -- and then, does it carry this path.
    # A single `except` around `git show` could not tell them apart, so an
    # unreadable commit read as a chapter wholly written since its
    # verification: a large figure under a confident label, with no relation
    # to any prose.
    _git(root, "rev-parse", "--verify", "--quiet", f"{commit}^{{commit}}")
    absent = subprocess.run(
        ["git", "cat-file", "-e", f"{commit}:{path}"], cwd=root, capture_output=True
    ).returncode
    # A path the commit did not carry counts as "" -- every word the chapter
    # has now was written after the verification. NOT (0, 0): an earlier
    # version returned that and claimed parity with `git diff --numstat`,
    # which is false in exactly this case -- numstat reported the file as
    # wholly added and printed `partial`, while (0, 0) prints `verified`. The
    # two fail on different things: numstat cannot see an untracked file,
    # `git show` cannot see a path the commit did not have.
    before = "" if absent else _git(root, "show", f"{commit}:{path}")
    current = Path(root, path)
    after = current.read_text() if current.is_file() else ""

    # autojunk off, which is load-bearing rather than cautious. It discards
    # elements appearing in over 1 % of a sequence longer than 200, and a
    # chapter is 13,000 words of which "the" is far more than 1 %. Measured:
    # a one-word insertion between 400 occurrences of one word reports
    # (201, 200) with the default and (1, 0) with it off. Identical input is
    # (0, 0) either way, so the migration's own zero was never at risk -- the
    # figure a reader judges by was, and an ordinary edit reading as a
    # rewrite is the quiet version of the defect this all exists to remove.
    # It costs about 215 ms against about 37 ms on the largest chapter,
    # medians over repeated runs rather than one reading of each.
    matcher = difflib.SequenceMatcher(
        None, normalise(before).split(), normalise(after).split(), autojunk=False
    )
    added = deleted = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ("replace", "delete"):
            deleted += i2 - i1
        if tag in ("replace", "insert"):
            added += j2 - j1
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
        added, deleted = changed_words(root, commit, chapter)
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
    ap = argparse.ArgumentParser(description=(__doc__ or "").partition("\n\n")[0])
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
        # will not match. The counts above are words, taken after normalising
        # the citations away; the plain command counts lines of the text as
        # written. For `harmony-and-ecs` against its verification commit that
        # is 452/322 lines raw against a reported 557/0 words, and the
        # asymmetry runs the way a reader does not expect: the reported figure
        # is the *larger* one, because a line holds several words. Two things
        # are folded away rather than one -- renumbered or re-anchored
        # citations, and the rewrap that anchoring forces, in which no word
        # moves at all.
        print("\nunverified hunks: git diff <commit> -- docs/ck/<chapter>.md")
        print("(that diff counts lines, citations and rewrapping; the figures above count words)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
