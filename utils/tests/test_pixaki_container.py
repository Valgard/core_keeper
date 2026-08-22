"""Unit tests for pixaki_container (the ZIP-or-directory adapter).

Whatever takes the `container` fixture runs against BOTH packagings, which is
the executable form of the claim in docs/pixaki-format.md that the two forms
carry the same payload. Where they are meant to DIFFER, the test takes
`packaging` too and asserts each side -- an asymmetry that is pinned stays
deliberate, while one that merely happens is indistinguishable from a bug.
"""

import json
import os

import pytest
from conftest import PIXAKI_DIRECTORIES, PIXAKI_FORMS, write_pixaki
from pixaki_container import open_pixaki

PAYLOAD = {
    "metadata.json": b'{"size": [8, 8]}',
    "document.json": b'{"sprites": []}',
    "images/drawings/D1.png": b"\x89PNG\r\n\x1a\n-not-a-real-png",
}


@pytest.fixture(params=PIXAKI_FORMS)
def packaging(request):
    return request.param


@pytest.fixture
def container(packaging, tmp_path):
    """The same payload, once per packaging -- with the directory members a
    real export carries, so the two forms differ here the way they really do."""
    return write_pixaki(
        tmp_path / f"m-{packaging}.pixaki",
        PAYLOAD,
        packaging,
        directories=PIXAKI_DIRECTORIES,
    )


def test_namelist_lists_every_file_and_only_an_archive_its_directories(
    container, packaging
):
    """The one place the two forms are meant to disagree, asserted on purpose.

    An earlier version demanded the SAME listing from both and passed only
    because the fixture stored no directory members at all -- it quietly
    encoded an unrealistic archive and claimed a symmetry pixaki_container's
    own docstring denies. Pinning the difference makes it deliberate: the
    readers must cope with entries a package can never produce."""
    with open_pixaki(container) as c:
        names = sorted(c.namelist())
    if packaging == "zip":
        assert names == sorted([*PAYLOAD, *PIXAKI_DIRECTORIES])
    else:
        assert names == sorted(PAYLOAD)


def test_a_missing_member_raises_each_backend_s_own_error(container, packaging):
    """The forms deliberately do not agree here either. Pinning it keeps the
    difference intentional rather than incidental: a later `except KeyError`
    would run green against every archive and fall over on the first package."""
    with open_pixaki(container) as c:
        with pytest.raises(KeyError if packaging == "zip" else FileNotFoundError):
            c.read("images/drawings/nope.png")


def test_a_member_name_cannot_read_outside_the_package(container, packaging):
    """An archive gets this for free -- `ZipFile` resolves a name against its
    own namespace, where '..' matches nothing -- while joining onto a real
    directory walks straight out of the package. Left alone, the adapter would
    be strictly MORE permissive than the thing it replaces, which is a poor
    property for a class that claims to mirror it.

    The name is not always the tool's own, either: pixaki_to_glyphs builds it
    from a cel identifier inside document.json, i.e. out of the very file being
    read."""
    (container.parent / "outside.txt").write_bytes(b"not part of the package")
    with open_pixaki(container) as c:
        with pytest.raises(KeyError if packaging == "zip" else ValueError):
            c.read("../outside.txt")


def test_open_pixaki_fails_loudly_on_a_path_that_does_not_exist(tmp_path):
    """Guards the dispatch itself. `if not os.path.isfile(path)` reads like a
    harmless rewrite of `if os.path.isdir(path)` and passes the whole suite --
    but under it a mistyped path becomes an EMPTY container (os.walk on a
    missing root yields nothing at all), and the failure then surfaces later,
    somewhere else, and says less."""
    with pytest.raises(FileNotFoundError):
        open_pixaki(tmp_path / "nope.pixaki")


def test_read_returns_the_stored_bytes(container):
    with open_pixaki(container) as c:
        assert c.read("images/drawings/D1.png") == PAYLOAD["images/drawings/D1.png"]


def test_open_returns_a_binary_stream(container):
    with open_pixaki(container) as c:
        with c.open("document.json") as handle:
            # b"{", not "{": json.load takes a text stream just as happily, so
            # opening in text mode passed this test until the bytes were named.
            assert handle.read(1) == b"{"
        with c.open("document.json") as handle:
            assert json.load(handle) == {"sprites": []}


def test_open_pixaki_accepts_a_path_object_as_well_as_a_string(container):
    # The tools hand it argparse strings, the tests hand it pathlib paths. Both
    # spelled out here: the Path half used to be covered only incidentally, by
    # the other tests happening to pass the fixture through unconverted.
    with open_pixaki(container) as c:
        assert c.read("metadata.json") == PAYLOAD["metadata.json"]
    with open_pixaki(str(container)) as c:
        assert c.read("metadata.json") == PAYLOAD["metadata.json"]


def test_namelist_raises_rather_than_dropping_an_unreadable_subtree(tmp_path):
    """`os.walk`'s default is to ignore scan errors, which makes a whole
    unreadable subtree vanish from the listing without a word. `load_pixaki`
    would then return a drawings dict that is quietly short, and the tool dies
    much later on a bare `KeyError: '<uuid>'` that names neither a file nor a
    cause. A ZIP cannot fail this way -- either the constructor throws or the
    listing is complete -- so the backend has to raise here to keep the
    docstring's "every FILE below the root" true."""
    package = write_pixaki(tmp_path / "m.pixaki", PAYLOAD, "directory")
    unreadable = package / "images" / "drawings"
    os.chmod(unreadable, 0o000)
    try:
        with open_pixaki(package) as container:
            with pytest.raises(PermissionError):
                container.namelist()
    finally:
        os.chmod(unreadable, 0o755)  # else tmp_path cleanup fails


def test_write_pixaki_rejects_an_unknown_packaging(tmp_path):
    # Guards the equivalence tests in the two tool suites: a typo'd form that
    # silently fell through to "directory" would have them compare a packaging
    # with itself, and they could no longer fail.
    with pytest.raises(ValueError, match="unknown .pixaki packaging 'dir'"):
        write_pixaki(tmp_path / "m.pixaki", PAYLOAD, "dir")
