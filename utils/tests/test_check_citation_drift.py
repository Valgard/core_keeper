"""Tests for check_citation_drift.

The cases are the citation forms the handbook actually contains, counted on
2026-08-31, not invented ones: the single-line majority, the range form, the
prefab citation that names no assembly, and the DedicatedServer citation that
names a tree instead of one.
"""

import check_citation_drift as mod


def test_extracts_a_single_line_citation():
    assert mod.extract("see `Pug.Other:441234` for the call") == [
        ("Pug.Other", 441234, 441234)
    ]


def test_extracts_a_range_citation_as_first_and_last():
    assert mod.extract("(`WorldGen:2836-2839`)") == [("WorldGen", 2836, 2839)]


def test_keeps_document_order_and_finds_every_occurrence():
    text = "`Pug.Base:1563` then `PugMod.Loader:783` then `Pug.Base:1563` again"
    assert mod.extract(text) == [
        ("Pug.Base", 1563, 1563),
        ("PugMod.Loader", 783, 783),
        ("Pug.Base", 1563, 1563),
    ]


def test_ignores_unity_fileid_which_is_not_a_citation():
    # `fileID: 11400000` appears in YAML examples throughout the handbook and
    # is a Unity object id, not a source line. It has no backtick-delimited
    # Assembly:NNNN shape, and must not be mistaken for one.
    assert mod.extract("`fileID: 11400000` and m_Name") == []


def test_ignores_a_bare_number_in_prose():
    assert mod.extract("roughly 124940 lines in") == []
