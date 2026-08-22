"""Unit tests for pixaki_container (the ZIP-or-directory adapter).

Every assertion runs against BOTH packagings through one parametrised fixture
-- the executable form of the claim in docs/pixaki-format.md that the two forms
carry the same payload.
"""

import json
import os

import pytest
from conftest import PIXAKI_FORMS, write_pixaki
from pixaki_container import open_pixaki

PAYLOAD = {
    "metadata.json": b'{"size": [8, 8]}',
    "document.json": b'{"sprites": []}',
    "images/drawings/D1.png": b"\x89PNG\r\n\x1a\n-not-a-real-png",
}


@pytest.fixture(params=PIXAKI_FORMS)
def container(request, tmp_path):
    """The same payload, once per packaging."""
    path = write_pixaki(tmp_path / f"m-{request.param}.pixaki", PAYLOAD, request.param)
    if request.param == "directory":
        # Pixaki leaves these two empty; a directory package cannot carry an
        # empty directory into namelist(), and nothing may pretend otherwise.
        (path / "images" / "references").mkdir(parents=True, exist_ok=True)
        (path / "images" / "selections").mkdir(parents=True, exist_ok=True)
    return path


def test_namelist_lists_the_payload_files_as_relative_posix_paths(container):
    # Exact equality, not containment: it also pins that the two empty
    # directories above produce no entries.
    with open_pixaki(container) as c:
        assert sorted(c.namelist()) == sorted(PAYLOAD)


def test_read_returns_the_stored_bytes(container):
    with open_pixaki(container) as c:
        assert c.read("images/drawings/D1.png") == PAYLOAD["images/drawings/D1.png"]


def test_open_returns_a_binary_stream(container):
    with open_pixaki(container) as c:
        with c.open("document.json") as handle:
            assert json.load(handle) == {"sprites": []}


def test_open_pixaki_accepts_a_path_object_as_well_as_a_string(container):
    # The tools hand it argparse strings, the tests hand it pathlib paths.
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
