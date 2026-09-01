"""Tests for check_citation_drift.

The cases are the citation forms the handbook actually contains, not invented
ones: the single-line majority, the range form, and — since 2026-09-01 — the
three shapes it resolves beyond a plain assembly name: a `DedicatedServer/`
prefixed citation against that tree's own copy, and an asset citation
(`.prefab`) found by name under `Resources/Assets/`. What still resolves to
nothing is a citation naming neither shape: a bare `DedicatedServer:NNNN`
with no assembly named inside it, an asset name matching zero or more than
one file, and a doc-to-doc line reference that must never be mistaken for a
citation in the first place — the regression the `DedicatedServer/` prefix
regex change could have introduced.
"""

import json

import pytest

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


def test_extracts_a_dedicated_server_citation_with_its_prefix():
    assert mod.extract("(`DedicatedServer/Pug.Other:263259-263262`)") == [
        ("DedicatedServer/Pug.Other", 263259, 263262)
    ]


def test_a_doc_to_doc_line_reference_is_not_mistaken_for_a_citation():
    # The regression a careless fix would introduce: widening the assembly
    # character class to allow "/" in general (rather than anchoring the
    # `DedicatedServer/` prefix specifically) would also swallow a
    # documentation cross-reference shaped like this one.
    assert mod.extract("see `docs/ck/platforms.md:119` for the format") == []


def make_decompile(tmp_path, name, lines):
    tree = tmp_path / "decompile"
    tree.mkdir(exist_ok=True)
    (tree / f"{name}.decompiled.cs").write_text("\n".join(lines) + "\n")
    return tree


def test_resolves_a_single_line_to_its_stripped_text(tmp_path):
    tree = make_decompile(tmp_path, "Pug.Other", ["zero", "  public void Foo()", "two"])
    assert mod.resolve("Pug.Other", 2, 2, tree) == ["public void Foo()"]


def test_resolves_a_range_inclusive_of_both_ends(tmp_path):
    tree = make_decompile(tmp_path, "WorldGen", ["a", "b", "c", "d", "e"])
    assert mod.resolve("WorldGen", 2, 4, tree) == ["b", "c", "d"]


def test_an_unknown_assembly_resolves_to_none(tmp_path):
    # Neither shape matches anything in this bare tree — no Resources/Assets
    # subtree for the prefab name to be found under, and "DedicatedServer"
    # alone (no assembly named inside it) is the pre-fix form that was never
    # meant to resolve. Both must be reportable, distinguishable from an
    # empty file.
    tree = make_decompile(tmp_path, "Pug.Other", ["a"])
    assert mod.resolve("ControlMappingMenu.prefab", 2456, 2457, tree) is None
    assert mod.resolve("DedicatedServer", 263259, 263262, tree) is None


def test_resolves_a_dedicated_server_citation_from_its_own_tree(tmp_path):
    # The fix is entirely in extract()'s regex: assembly already carries the
    # embedded "/", and Path's own join lands it in the right subdirectory
    # with no extra branch in resolve() needed.
    tree = tmp_path / "decompile"
    server = tree / "DedicatedServer"
    server.mkdir(parents=True)
    (server / "Pug.Other.decompiled.cs").write_text("a\nb\nc\n")
    assert mod.resolve("DedicatedServer/Pug.Other", 2, 2, tree) == ["b"]


def test_resolves_an_asset_citation_by_name_under_resources_assets(tmp_path):
    tree = tmp_path / "decompile"
    gameobject = tree / "Resources" / "Assets" / "GameObject"
    gameobject.mkdir(parents=True)
    (gameobject / "ControlMappingMenu.prefab").write_text("a\nb\nc\nd\n")
    assert mod.resolve("ControlMappingMenu.prefab", 2, 3, tree) == ["b", "c"]


def test_an_asset_name_matching_two_files_resolves_to_none(tmp_path):
    # Never guess between them — reported as unresolvable, the same as a
    # citation that matches no file at all.
    tree = tmp_path / "decompile"
    one = tree / "Resources" / "Assets" / "GameObject"
    two = tree / "Resources" / "Assets" / "Prefabs"
    one.mkdir(parents=True)
    two.mkdir(parents=True)
    (one / "Foo.prefab").write_text("a\n")
    (two / "Foo.prefab").write_text("b\n")
    assert mod.resolve("Foo.prefab", 1, 1, tree) is None


def test_an_unrecognised_asset_extension_is_not_searched_for(tmp_path):
    # ".prefab" is the only extension the handbook has cited so far — a name
    # ending in something else must fall through to unresolvable rather than
    # triggering a Resources/Assets search that was never asked for.
    tree = tmp_path / "decompile"
    other = tree / "Resources" / "Assets" / "Material"
    other.mkdir(parents=True)
    (other / "Foo.mat").write_text("a\n")
    assert mod.resolve("Foo.mat", 1, 1, tree) is None


def test_a_line_past_the_end_yields_an_empty_list_not_a_crash(tmp_path):
    # A citation surviving a shrinking file is drift, not a crash: the compare
    # step has to see "nothing there now" as a difference it can report.
    tree = make_decompile(tmp_path, "Pug.Other", ["a", "b"])
    assert mod.resolve("Pug.Other", 900, 900, tree) == []


def write_chapter(root, name, text):
    docs = root / "docs" / "ck"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / name).write_text(text)


def test_collects_every_citation_keyed_as_written(tmp_path):
    tree = make_decompile(tmp_path, "Pug.Other", ["a", "b", "c", "d"])
    write_chapter(tmp_path, "one.md", "see `Pug.Other:2` and `Pug.Other:3-4`\n")

    corpus, problems, cited = mod.collect(tmp_path, tree)

    assert corpus == {"Pug.Other:2": ["b"], "Pug.Other:3-4": ["c", "d"]}
    assert problems == []
    assert cited == {"Pug.Other:2", "Pug.Other:3-4"}


def test_reports_an_unresolvable_citation_with_its_location(tmp_path):
    tree = make_decompile(tmp_path, "Pug.Other", ["a"])
    write_chapter(
        tmp_path, "ui.md", "line one\nsee `ControlMappingMenu.prefab:2456-2457`\n"
    )

    corpus, problems, cited = mod.collect(tmp_path, tree)

    assert corpus == {}
    assert len(problems) == 1
    assert "ui.md:2" in problems[0]
    assert "ControlMappingMenu.prefab:2456-2457" in problems[0]
    assert "no decompiled assembly" in problems[0]
    # Unresolvable, but still seen — this is what lets compare() tell a
    # citation that vanished apart from one that merely broke.
    assert cited == {"ControlMappingMenu.prefab:2456-2457"}


def test_the_same_citation_twice_collapses_to_one_entry(tmp_path):
    # Two sentences may cite the same line; the snapshot is keyed by citation,
    # so this is one entry, not a conflict.
    tree = make_decompile(tmp_path, "Pug.Base", ["a", "b"])
    write_chapter(tmp_path, "one.md", "`Pug.Base:2`\n")
    write_chapter(tmp_path, "two.md", "also `Pug.Base:2`\n")

    corpus, problems, cited = mod.collect(tmp_path, tree)

    assert corpus == {"Pug.Base:2": ["b"]}
    assert problems == []
    assert cited == {"Pug.Base:2"}


def test_no_drift_reports_nothing():
    assert (
        mod.compare({"Pug.Other:2": ["b"]}, {"Pug.Other:2": ["b"]}, {"Pug.Other:2"})
        == []
    )


def test_a_changed_line_is_reported_with_both_texts():
    problems = mod.compare(
        {"Pug.Other:2": ["now()"]}, {"Pug.Other:2": ["then()"]}, {"Pug.Other:2"}
    )
    assert len(problems) == 1
    assert "Pug.Other:2" in problems[0]
    assert "then()" in problems[0] and "now()" in problems[0]


def test_a_citation_missing_from_the_snapshot_is_reported_as_unrecorded():
    problems = mod.compare({"Pug.Base:9": ["x"]}, {}, {"Pug.Base:9"})
    assert len(problems) == 1
    assert "not in the snapshot" in problems[0]


def test_a_snapshot_entry_no_longer_cited_is_reported_as_stale():
    # Not an error in the handbook — a sentence was removed or reworded. It is
    # reported so --capture is a deliberate act rather than silent bookkeeping.
    # `cited` is empty: the key is genuinely absent, not merely unresolvable.
    problems = mod.compare({}, {"Pug.Base:9": ["x"]}, set())
    assert len(problems) == 1
    assert "no longer cited" in problems[0]


def test_an_unresolvable_citation_is_not_also_reported_as_uncited():
    # The case compare() used to get wrong: an assembly that disappears makes
    # its citation unresolvable (so it never enters `corpus`), but the
    # citation is still sitting right there in the handbook (so it is in
    # `cited`). Reporting it as "no longer cited anywhere" would read as
    # "stale snapshot entry, delete it" — which would erase the recorded text,
    # the only thing left saying what the line used to hold.
    problems = mod.compare(
        {}, {"PugMod.Platform:2": ["old text"]}, {"PugMod.Platform:2"}
    )
    assert problems == []


def test_a_line_that_vanished_reports_the_empty_side_readably():
    problems = mod.compare(
        {"Pug.Other:900": []}, {"Pug.Other:900": ["gone()"]}, {"Pug.Other:900"}
    )
    assert len(problems) == 1
    assert "past end of file" in problems[0]


def test_capture_writes_a_snapshot_and_succeeds(tmp_path, capsys):
    tree = make_decompile(tmp_path, "Pug.Other", ["a", "b"])
    write_chapter(tmp_path, "one.md", "`Pug.Other:2`\n")
    snapshot = tmp_path / "snap.json"

    code = mod.main(
        [
            "x",
            "--capture",
            "--game-version",
            "1.2.1.5-8be0",
            "--decompile",
            str(tree),
            "--snapshot",
            str(snapshot),
            str(tmp_path),
        ]
    )

    assert code == 0
    assert json.loads(snapshot.read_text())["citations"] == {"Pug.Other:2": ["b"]}
    assert "captured" in capsys.readouterr().out


def test_capture_stores_the_game_version(tmp_path, capsys):
    tree = make_decompile(tmp_path, "Pug.Other", ["a", "b"])
    write_chapter(tmp_path, "one.md", "`Pug.Other:2`\n")
    snapshot = tmp_path / "snap.json"

    code = mod.main(
        [
            "x",
            "--capture",
            "--game-version",
            "1.2.1.5-8be0",
            "--decompile",
            str(tree),
            "--snapshot",
            str(snapshot),
            str(tmp_path),
        ]
    )

    assert code == 0
    assert json.loads(snapshot.read_text())["game_version"] == "1.2.1.5-8be0"
    assert "1.2.1.5-8be0" in capsys.readouterr().out


def test_capture_without_game_version_is_rejected(tmp_path):
    # Required, not optional: a capture that silently records no version
    # reproduces the exact defect --game-version exists to close.
    tree = make_decompile(tmp_path, "Pug.Other", ["a"])
    write_chapter(tmp_path, "one.md", "`Pug.Other:1`\n")
    snapshot = tmp_path / "snap.json"

    with pytest.raises(SystemExit):
        mod.main(
            [
                "x",
                "--capture",
                "--decompile",
                str(tree),
                "--snapshot",
                str(snapshot),
                str(tmp_path),
            ]
        )


def test_compare_prints_the_recorded_game_version(tmp_path, capsys):
    tree = make_decompile(tmp_path, "Pug.Other", ["a", "b"])
    write_chapter(tmp_path, "one.md", "`Pug.Other:2`\n")
    snapshot = tmp_path / "snap.json"
    snapshot.write_text(
        json.dumps(
            {"citations": {"Pug.Other:2": ["b"]}, "game_version": "1.2.1.5-8be0"}
        )
    )

    code = mod.main(
        ["x", "--decompile", str(tree), "--snapshot", str(snapshot), str(tmp_path)]
    )

    assert code == 0
    assert "1.2.1.5-8be0" in capsys.readouterr().out


def test_a_versionless_snapshot_is_handled_not_crashed(tmp_path, capsys):
    # A snapshot captured before --game-version existed. It must be usable,
    # not fatal — the fix is a recapture, not a traceback.
    tree = make_decompile(tmp_path, "Pug.Other", ["a", "b"])
    write_chapter(tmp_path, "one.md", "`Pug.Other:2`\n")
    snapshot = tmp_path / "snap.json"
    snapshot.write_text(json.dumps({"citations": {"Pug.Other:2": ["b"]}}))

    code = mod.main(
        ["x", "--decompile", str(tree), "--snapshot", str(snapshot), str(tmp_path)]
    )

    assert code == 0
    assert "no recorded game version" in capsys.readouterr().out


def test_a_changed_line_makes_the_default_mode_fail(tmp_path, capsys):
    tree = make_decompile(tmp_path, "Pug.Other", ["a", "b"])
    write_chapter(tmp_path, "one.md", "`Pug.Other:2`\n")
    snapshot = tmp_path / "snap.json"
    mod.main(
        [
            "x",
            "--capture",
            "--game-version",
            "1.2.1.5-8be0",
            "--decompile",
            str(tree),
            "--snapshot",
            str(snapshot),
            str(tmp_path),
        ]
    )

    (tree / "Pug.Other.decompiled.cs").write_text("a\nCHANGED\n")
    code = mod.main(
        ["x", "--decompile", str(tree), "--snapshot", str(snapshot), str(tmp_path)]
    )

    assert code == 1
    assert "CHANGED" in capsys.readouterr().out


def test_a_missing_snapshot_says_what_to_run_rather_than_crashing(tmp_path, capsys):
    tree = make_decompile(tmp_path, "Pug.Other", ["a", "b"])
    write_chapter(tmp_path, "one.md", "`Pug.Other:2`\n")

    code = mod.main(
        [
            "x",
            "--decompile",
            str(tree),
            "--snapshot",
            str(tmp_path / "nope.json"),
            str(tmp_path),
        ]
    )

    assert code == 1
    assert "--capture" in capsys.readouterr().out


def test_an_unresolvable_citation_fails_even_when_nothing_drifted(tmp_path, capsys):
    # Otherwise an unresolvable citation stays invisible forever: it never
    # drifts, because it never resolved in the first place. The bare
    # "DedicatedServer:NNNN" form stands in for "names something the checker
    # does not model" — it is the pre-fix shape, not the one the handbook
    # writes any more.
    tree = make_decompile(tmp_path, "Pug.Other", ["a"])
    write_chapter(tmp_path, "m.md", "`DedicatedServer:263259-263262`\n")
    snapshot = tmp_path / "snap.json"
    snapshot.write_text(json.dumps({"citations": {}}))

    code = mod.main(
        ["x", "--decompile", str(tree), "--snapshot", str(snapshot), str(tmp_path)]
    )

    assert code == 1
    assert "no decompiled assembly" in capsys.readouterr().out


def test_an_assembly_that_disappears_is_not_also_reported_as_uncited(tmp_path, capsys):
    # Reproduces what a real game update produced: an assembly renamed out
    # from under a citation makes it unresolvable, but the citation is still
    # sitting right there in the handbook — it must not ALSO be reported as
    # "no longer cited anywhere", which reads as "stale snapshot entry, clean
    # it up with --capture" and would delete the only remaining record of
    # what the line used to say.
    tree = make_decompile(tmp_path, "Pug.Other", ["a"])
    write_chapter(tmp_path, "one.md", "`PugMod.Platform:2`\n")
    snapshot = tmp_path / "snap.json"
    snapshot.write_text(json.dumps({"citations": {"PugMod.Platform:2": ["old text"]}}))

    code = mod.main(
        ["x", "--decompile", str(tree), "--snapshot", str(snapshot), str(tmp_path)]
    )
    out = capsys.readouterr().out

    assert code == 1
    assert "no decompiled assembly" in out
    assert "no longer cited anywhere" not in out
