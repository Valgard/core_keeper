"""Open a .pixaki in either of its two packagings behind one small interface.

How the document left the iPad decides the form on disk: Pixaki's own Export
(then AirDrop) yields a ZIP archive, while pulling the document straight out of
iCloud yields the native package -- a directory, which the Finder still draws as
a single file. Both carry the same payload; docs/pixaki-format.md records how
that was verified.

`open_pixaki(path)` returns a context manager exposing the three members the
readers beside it use -- `namelist()`, `read(name)`, `open(name)` -- so neither
has to learn which form it was handed. For a ZIP that IS `zipfile.ZipFile`,
whose read surface the directory backend therefore mirrors rather than invents.

One asymmetry stays on purpose: a real Pixaki export stores directory entries,
the empty `images/references/` and `images/selections/` among them, and a
directory package cannot produce such an entry at all. Both readers pick members
by the `images/drawings/<uuid>.png` shape, which no directory entry matches, so
the difference never reaches them -- and hiding it would mean wrapping ZipFile
for nobody's benefit.
"""

import os
import zipfile


def _raise(error):
    """`os.walk`'s `onerror`, which defaults to ignoring a failed scan.

    Under that default an unreadable subtree drops out of the listing without a
    word: `load_pixaki` gets a drawings dict that is quietly short and the tool
    dies much later on a `KeyError` naming a bare cel UUID. An archive cannot
    fail that way -- the constructor throws, or the listing is complete -- so
    the failure is raised here instead of being carried forward as a gap."""
    raise error


def open_pixaki(path):
    """Return a ZipFile-like reader for a .pixaki in either packaging."""
    if os.path.isdir(path):
        return _DirectoryContainer(path)
    return zipfile.ZipFile(path)


class _DirectoryContainer:
    """`zipfile.ZipFile`'s read surface, backed by a directory on disk.

    Listing order is unspecified, exactly as it is for an archive (there it is
    insertion order); both readers key what they find by name.
    """

    def __init__(self, root):
        self._root = os.fspath(root)

    def namelist(self):
        """Every FILE below the root, as a '/'-joined path relative to it."""
        names = []
        for dirpath, _dirnames, filenames in os.walk(self._root, onerror=_raise):
            for filename in filenames:
                member = os.path.join(dirpath, filename)
                names.append(os.path.relpath(member, self._root).replace(os.sep, "/"))
        return names

    def read(self, name):
        with self.open(name) as handle:
            return handle.read()

    def open(self, name):
        return open(os.path.join(self._root, *name.split("/")), "rb")

    def close(self):
        """A no-op: the container itself holds nothing open.

        A handle from `open()` belongs to whoever asked for it, and closing the
        container does not reach it -- true of `ZipFile` as well, whose members
        stay readable after `close()` because they hold a reference to the
        archive's file object. So callers close what they open; here so both
        forms can be used alike."""

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.close()
        return False
