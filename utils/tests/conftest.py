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


def write_pixaki(path, members, form):
    """Write {member path: bytes} to `path` as a .pixaki in the given `form`.

    The forms are the two packagings of one payload (docs/pixaki-format.md):
    "zip" is what Pixaki's Export produces, "directory" the native document
    package pulled straight out of iCloud. Every suite that reads a .pixaki
    needs to be able to build both, so the packing lives here once; the payload
    itself stays each suite's own business.

    An unknown form is rejected rather than treated as a directory, because the
    tests this serves compare the two forms against each other: a typo'd form
    would quietly build the same packaging twice and turn an equivalence test
    into one that can no longer fail.
    """
    if form not in PIXAKI_FORMS:
        raise ValueError(f"unknown .pixaki packaging {form!r}, expected {PIXAKI_FORMS}")
    if form == "zip":
        with zipfile.ZipFile(path, "w") as archive:
            for name, data in members.items():
                archive.writestr(name, data)
        return path
    for name, data in members.items():
        member = pathlib.Path(path, name)
        member.parent.mkdir(parents=True, exist_ok=True)
        member.write_bytes(data)
    return path
