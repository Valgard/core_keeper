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


@pytest.fixture(scope="session")
def corpus():
    """Every unique `(assembly, first line)` the handbook cites.

    Unique by assembly and line, which is the base the design spec's figures
    use; the occurrence count is higher and the two must not be mixed.

    Collected with `citation_notation.find` rather than the old `CITATION`
    regex, which matters from the first migrated chapter onward: that regex
    cannot see a symbol-anchored citation, so a corpus built on it would
    quietly shrink as the migration progressed and every suite resting on it
    would test less without saying so.
    """
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from citation_notation import find

    root = pathlib.Path(__file__).resolve().parents[2] / "docs" / "ck"
    cited = {
        (citation.assembly, citation.first)
        for chapter in sorted(root.glob("*.md"))
        for _, citation in find(chapter.read_text())
    }
    return sorted(cited)


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
