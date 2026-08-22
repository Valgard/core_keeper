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

One asymmetry is deliberate. A real export stores six directory members of its
own -- `cache/`, `cache/keyframes/`, `images/`, `images/drawings/`,
`images/references/`, `images/selections/`. A package has those directories on
disk and `os.walk` duly reports them, but this backend lists files, so nothing
here answers to them. Neither way of hiding that is worth taking: synthesising
the entries would put members in a listing that no package stores, and dropping
them from the archive's would mean wrapping ZipFile instead of handing back the
real one.

The difference reaches neither reader, though for two different reasons, which
is worth stating because the wrong one invites a wrong conclusion:
`pixaki_to_sheet` scans `namelist()` and keeps only `images/drawings/*.png`, so
a directory entry is filtered out; `pixaki_to_glyphs` never enumerates at all
and opens each member by the exact name its `document.json` names.
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
    """Return a reader for a .pixaki in either packaging, as a context manager.

    What it guarantees is `namelist()`, `read(name)` and `open(name)`, and no
    more: the archive branch hands back the real `zipfile.ZipFile`, so reaching
    past those three works on every export and fails on the first package."""
    if os.path.isdir(path):
        return _DirectoryContainer(path)
    return zipfile.ZipFile(path)


class _DirectoryContainer:
    """The three members the readers use, backed by a directory on disk.

    Not a ZipFile stand-in beyond those and the context-manager protocol:
    `infolist()`, `getinfo()`, `extractall()` and the rest are absent here and
    present on the other branch, so a call reaching for one of them passes every
    archive and falls over on the first package.

    Listing order is arbitrary, and NOT arbitrary in the same way an archive's
    is: a ZIP lists its central directory, so one file always reads back in the
    order it was written, while `os.walk` follows the filesystem. Nothing may
    rely on it; both readers key what they find by name.
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
        return open(self._member_path(name), "rb")

    def _member_path(self, name):
        """The file a member name refers to, refusing to leave the package.

        An archive needs no such check: `ZipFile` resolves a name against its
        own namespace, where '..' matches nothing and an absolute name is just
        a name. Joining onto a real directory walks out, which would leave this
        backend strictly MORE permissive than the one it stands in for.

        Splitting on '/' rather than passing the name whole is part of the same
        guard: `os.path.join(root, '/etc/passwd')` discards the root, while
        joining the segments keeps it. It is also the exact inverse of what
        `namelist()` does on the way out."""
        member = os.path.abspath(os.path.join(self._root, *name.split("/")))
        root = os.path.abspath(self._root)
        if os.path.commonpath((root, member)) != root:
            raise ValueError(f"member {name!r} resolves outside the package")
        return member

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
