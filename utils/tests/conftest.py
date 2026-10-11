"""Import the utils/ scripts, keep git off this repo, build .pixaki fixtures.

The test modules live in utils/tests/ but import the scripts under test from
utils/ one level up. pytest only puts the test file's own directory on
sys.path, so add its parent (utils/) here, once, for every test in this
directory. Deliberately no list of the scripts covered: this file said
"new_mod, pixaki_to_sheet, prefab_query" for as long as it took the next
suite to be added without it.
"""

import os
import pathlib
import sys
import zipfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(autouse=True)
def _isolate_git_env(monkeypatch):
    """Clear GIT_* so a test's git calls obey their own cwd.

    Inside a hook git exports GIT_DIR, GIT_INDEX_FILE and GIT_WORK_TREE, and
    those beat `cwd`. Several suites here run git against a directory: some read
    the sibling mod repos, others build a throwaway repository under tmp_path.
    Without this, the first kind answers from the committing repository -- no
    error, plausible output, wrong repo -- and the second kind *writes* there.
    That is not hypothetical: a test doing `git init` plus `git config user.*`
    once left this repository with `core.bare = true` and a repo-local identity,
    after which two commits went out under the wrong name.

    Autouse and in conftest rather than per call site, because the cost of
    forgetting it falls on whoever writes the *next* suite, not on the one that
    forgot. Production code cannot rely on this and scrubs on its own (see
    `patch_sdk.git_env`); here it only removes the ambient leak from the tests.
    """
    for name in [k for k in os.environ if k.startswith("GIT_")]:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(scope="session", autouse=True)
def _isolate_structure_cache(tmp_path_factory):
    """Keep `decompile_structure`'s cache out of the real `~/.cache`.

    Without this, every test that calls `structure_of` without an explicit
    `cache_dir` writes into the developer's own cache -- 115 of 140 entries
    there were test debris when this was found -- and, worse, reads from it.

    **Session scope and autouse, not function scope.** A first version of this
    was a function-scoped autouse fixture, and it did nothing for the suite
    that needed it most: pytest builds a module-scoped fixture before the
    function-scoped ones of the tests that use it, so
    `test_structure_corpus.py`'s `structures` fixture had already parsed all 27
    assemblies against the real cache before the env var was ever set.
    `--setup-show` prints the order plainly; what hid it from a count of cache
    entries is that a cache *hit* writes nothing, so the number does not move.

    The cost is that the corpus suite re-parses rather than reusing a warm
    cache -- around 13 s a run. That is the right price: this is the gate that
    licenses migrating an already-verified chapter without re-reading it, and
    the alternative is a gate that can validate changed extraction logic
    against entries the old logic wrote. `CACHE_FORMAT` is meant to catch that,
    but it only works if a human remembers to bump it, and the first edit to
    change `_member_name` after it existed did not.

    Autouse and in conftest for the same reason as `_isolate_git_env` above:
    the cost of forgetting it falls on whoever writes the *next* suite.
    """
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("CK_STRUCTURE_CACHE", str(tmp_path_factory.mktemp("ck-structure-cache")))
        yield


@pytest.fixture(scope="session")
def decompile():
    """The decompile checkout, or a loud skip.

    Shared by every suite that checks a claim against the real decompile, so
    there is one answer to "where is it" and one place that skips.
    """
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from check_citation_drift import DEFAULT_DECOMPILE

    path = pathlib.Path(str(DEFAULT_DECOMPILE)).expanduser()
    if not path.is_dir():
        pytest.skip(f"no decompile tree at {path} — this suite checks the real corpus")
    return path


_ABSOLUTE_LINES = {}


def _absolute_lines(decompile):
    """Absolute `(assembly, first, last)` per citation in docs/ck, and the misses.

    Returns `(spans, unresolved)`: the lines every citation points at, and the
    tokens no line could be found for.

    Collected with `citation_notation.find` rather than the old `CITATION`
    regex, which matters from the first migrated chapter onward: that regex
    cannot see a symbol-anchored citation, so a corpus built on it would
    quietly shrink as the migration progressed and every suite resting on it
    would test less without saying so.

    **And an anchored citation's own `first` is relative to its element, so it
    is resolved rather than taken at face value.** Reading `:38` of a member as
    line 38 of the file is not a small error: at the first migrated chapters it
    made the tier census report 79 absolute-tier citations against a bound of
    10, because a relative offset lands near the top of a 460,000-line file
    where no type encloses anything. Every suite here rests on these lines
    meaning what the handbook points at.

    A citation that no longer resolves is left out and **returned alongside**.
    Leaving it out is right -- there is no line to measure, and the drift gate
    has the recorded text to say what changed, where a fixture inventing a
    line would hide the only thing worth knowing. Returning it is what keeps
    that from being a silent shrink, which is the defect the paragraph above
    warns about for a different cause: the only other guard is a floor of 500
    on a corpus of 790, so every anchored citation could vanish and pass.
    """
    if decompile in _ABSOLUTE_LINES:
        # Three session fixtures ask for this, and parsing the cited
        # assemblies to resolve 243 anchored citations costs about 14 s each
        # time. Keyed on the tree, so a suite that ever measured two of them
        # would still get the right answer rather than the first one's.
        return _ABSOLUTE_LINES[decompile]

    from check_citation_drift import source_for
    from citation_notation import find
    from citation_notation import tier
    from decompile_structure import locate
    from decompile_structure import structure_of

    root = pathlib.Path(__file__).resolve().parents[2] / "docs" / "ck"
    structures, spans, unresolved = {}, set(), set()
    for chapter in sorted(root.glob("*.md")):
        for token, citation in find(chapter.read_text()):
            if tier(citation) == "absolute":
                spans.add((citation.assembly, citation.first, citation.last))
                continue
            if citation.assembly not in structures:
                path = source_for(citation.assembly, decompile)
                structures[citation.assembly] = structure_of(path) if path else None
            structure = structures[citation.assembly]
            start = locate(structure, citation) if structure else None
            if start is None:
                unresolved.add(token)
            else:
                spans.add((citation.assembly, start, start + citation.last - citation.first))
    _ABSOLUTE_LINES[decompile] = (spans, tuple(sorted(unresolved)))
    return _ABSOLUTE_LINES[decompile]


@pytest.fixture(scope="session")
def unresolved(decompile):
    """Every citation in `docs/ck/` that no longer resolves to a line.

    Empty today, and a test asserts that rather than leaving it implied --
    the corpus fixtures drop these, and a drop nobody counts is how a suite
    comes to test less than it claims.
    """
    return _absolute_lines(decompile)[1]


@pytest.fixture(scope="session")
def corpus(decompile):
    """Every unique `(assembly, absolute line)` the handbook cites.

    Unique by assembly and line, which is the base the design spec's figures
    use; the occurrence count is higher and the two must not be mixed. How the
    lines are arrived at, and why an anchored citation cannot be read at face
    value, is `_absolute_lines`.
    """
    return sorted({(assembly, first) for assembly, first, _ in _absolute_lines(decompile)[0]})


@pytest.fixture(scope="session")
def range_citations(decompile):
    """Every unique range citation the handbook carries, as (assembly, first, last).

    Shared rather than local to one suite because dropping the span is how a
    real defect got through: the `corpus` fixture keys on the first line alone,
    so a suite resting only on it cannot reach any code path that treats a
    range differently from a single line — and the style checker's structural
    half had exactly such a path, judging every range against the description
    of its first line.

    Absolute lines, for the reason `_absolute_lines` gives. The span's *length*
    survives either way, which is what makes this the quieter half of that
    defect: a suite resting on relative offsets would go on comparing spans
    correctly while measuring code nobody cites.
    """
    return sorted({span for span in _absolute_lines(decompile)[0] if span[1] != span[2]})


PIXAKI_FORMS = ("zip", "directory")

# What a real Pixaki export carries besides its files. A ZIP stores these as
# members of their own; a directory package cannot, and that gap is exactly the
# asymmetry pixaki_container documents -- so a fixture that omits them makes the
# two forms look more alike than they are, and the readers are never handed the
# one member shape they have to ignore.
PIXAKI_DIRECTORIES = (
    "cache/",
    "cache/keyframes/",
    "images/",
    "images/drawings/",
    "images/references/",
    "images/selections/",
)


def write_pixaki(path, members, form, directories=()):
    """Write {member path: bytes} to `path` as a .pixaki in the given `form`.

    The forms are the two packagings of one payload (docs/pixaki-format.md):
    "zip" is what Pixaki's Export produces, "directory" the native document
    package pulled straight out of iCloud. Every suite that reads a .pixaki
    needs to be able to build both, so the packing lives here once; the payload
    itself stays each suite's own business.

    `directories` are the trailing-slash names a real export stores as members
    of their own (PIXAKI_DIRECTORIES). They become archive entries in a ZIP and
    plain directories on disk in a package -- which is the point: the same
    argument produces the difference the two forms really have, instead of a
    fixture that hides it.

    An unknown form is rejected in the `else`, not by a guard above the
    branches: the tests this serves compare the two forms against each other, so
    a form that quietly built the same packaging twice would turn an equivalence
    test into one that can no longer fail. A guard checking PIXAKI_FORMS would
    let a third form added to that tuple -- but not here -- fall through to the
    directory branch and do exactly that.
    """
    if form == "zip":
        with zipfile.ZipFile(path, "w") as archive:
            for name in directories:
                archive.writestr(zipfile.ZipInfo(name), b"")
            for name, data in members.items():
                archive.writestr(name, data)
    elif form == "directory":
        root = pathlib.Path(path)
        root.mkdir(parents=True, exist_ok=True)  # else an empty payload writes nothing
        for name in directories:
            pathlib.Path(root, name).mkdir(parents=True, exist_ok=True)
        for name, data in members.items():
            member = pathlib.Path(root, name)
            member.parent.mkdir(parents=True, exist_ok=True)
            member.write_bytes(data)
    else:
        raise ValueError(f"unknown .pixaki packaging {form!r}, expected {PIXAKI_FORMS}")
    return path
