"""Make the utils/ scripts importable, and build .pixaki fixtures in both forms.

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

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
