"""Tests for check_citation_drift.

The cases are the citation forms the handbook actually contains, not invented
ones: the single-line majority, the range form, and — since 2026-09-01 — the
shapes it resolves beyond a plain assembly name: a `DedicatedServer/`
prefixed citation against that tree's own copy, an asset citation (`.prefab`)
found by name under `Resources/Assets/`, and — since 2026-09-22 — a `.cs`
citation naming a file in an open-source dependency's own clone, which sits
beside the decompile rather than inside it. What still resolves to
nothing is a citation naming neither shape: a bare `DedicatedServer:NNNN`
with no assembly named inside it, an asset name matching zero or more than
one file, and a doc-to-doc line reference that must never be mistaken for a
citation in the first place — the regression the `DedicatedServer/` prefix
regex change could have introduced.
"""

import json

import check_citation_drift as mod
import pytest


def test_extracts_a_single_line_citation():
    """A single-line citation's first and last line are the same number.

    The baseline shape every other extract() test varies from.
    """
    assert mod.extract("see `Pug.Other:441234` for the call") == [("Pug.Other", 441234, 441234)]


def test_extracts_a_range_citation_as_first_and_last():
    """A `first-last` range keeps both ends, not just the first number.

    The regex's optional group could otherwise drop the last one.
    """
    assert mod.extract("(`WorldGen:2836-2839`)") == [("WorldGen", 2836, 2839)]


def test_keeps_document_order_and_finds_every_occurrence():
    """Repeating a citation yields two entries in the order they appear, not one.

    A set-based implementation would silently collapse the duplicate and
    lose the second occurrence's position.
    """
    text = "`Pug.Base:1563` then `PugMod.Loader:783` then `Pug.Base:1563` again"
    assert mod.extract(text) == [
        ("Pug.Base", 1563, 1563),
        ("PugMod.Loader", 783, 783),
        ("Pug.Base", 1563, 1563),
    ]


def test_ignores_unity_fileid_which_is_not_a_citation():
    """`fileID: 11400000` is a Unity object id, not a source line.

    It appears throughout the handbook's YAML examples and has no
    backtick-delimited `Assembly:NNNN` shape, so it must not be mistaken for
    a citation.
    """
    assert mod.extract("`fileID: 11400000` and m_Name") == []


def test_ignores_a_bare_number_in_prose():
    """A bare number outside backticks is not a citation.

    Only the backtick-delimited `Assembly:NNNN` shape counts — a line count
    mentioned in prose must not match.
    """
    assert mod.extract("roughly 124940 lines in") == []


def test_extracts_a_dedicated_server_citation_with_its_prefix():
    """Pins that the `DedicatedServer/` prefix is captured as part of the assembly name.

    It is not stripped out or split into a separate group.
    """
    assert mod.extract("(`DedicatedServer/Pug.Other:263259-263262`)") == [
        ("DedicatedServer/Pug.Other", 263259, 263262)
    ]


def test_a_doc_to_doc_line_reference_is_not_mistaken_for_a_citation():
    """Guards against the regression a careless fix would introduce.

    Widening the assembly character class to allow "/" in general (rather
    than anchoring the `DedicatedServer/` prefix specifically) would also
    swallow a documentation cross-reference shaped like this one.
    """
    assert mod.extract("see `docs/ck/platforms.md:119` for the format") == []


def make_decompile(tmp_path, name, lines):
    """Build a decompile tree with one `<name>.decompiled.cs` file holding `lines`.

    `mkdir(exist_ok=True)` lets a caller invoke this more than once against
    the same `tmp_path` to add a second assembly to one tree.
    """
    tree = tmp_path / "decompile"
    tree.mkdir(exist_ok=True)
    (tree / f"{name}.decompiled.cs").write_text("\n".join(lines) + "\n")
    return tree


def test_resolves_a_single_line_to_its_stripped_text(tmp_path):
    """resolve() strips each returned line before comparing it.

    A decompiled file's leading indentation is not part of what a
    comparison sees.
    """
    tree = make_decompile(tmp_path, "Pug.Other", ["zero", "  public void Foo()", "two"])
    assert mod.resolve("Pug.Other", 2, 2, tree) == ["public void Foo()"]


def test_resolves_a_range_inclusive_of_both_ends(tmp_path):
    """A `first..last` range includes the last line, not just up to it.

    An off-by-one here would silently drop the final line of every
    multi-line citation.
    """
    tree = make_decompile(tmp_path, "WorldGen", ["a", "b", "c", "d", "e"])
    assert mod.resolve("WorldGen", 2, 4, tree) == ["b", "c", "d"]


def test_an_unknown_assembly_resolves_to_none(tmp_path):
    """Neither shape matches anything in this bare tree.

    No Resources/Assets subtree for the prefab name to be found under, and
    "DedicatedServer" alone (no assembly named inside it) is the pre-fix form
    that was never meant to resolve. Both must be reportable, distinguishable
    from an empty file.
    """
    tree = make_decompile(tmp_path, "Pug.Other", ["a"])
    assert mod.resolve("ControlMappingMenu.prefab", 2456, 2457, tree) is None
    assert mod.resolve("DedicatedServer", 263259, 263262, tree) is None


def test_resolves_a_dedicated_server_citation_from_its_own_tree(tmp_path):
    """The fix is entirely in extract()'s regex.

    The assembly string already carries the embedded "/", and Path's own join
    lands it in the right subdirectory with no extra branch in resolve()
    needed.
    """
    tree = tmp_path / "decompile"
    server = tree / "DedicatedServer"
    server.mkdir(parents=True)
    (server / "Pug.Other.decompiled.cs").write_text("a\nb\nc\n")
    assert mod.resolve("DedicatedServer/Pug.Other", 2, 2, tree) == ["b"]


def test_resolves_an_asset_citation_by_name_under_resources_assets(tmp_path):
    """A `.prefab` citation is found by filename anywhere under `Resources/Assets/`.

    It is found by filename, not by the path segments the citation omits.
    """
    tree = tmp_path / "decompile"
    gameobject = tree / "Resources" / "Assets" / "GameObject"
    gameobject.mkdir(parents=True)
    (gameobject / "ControlMappingMenu.prefab").write_text("a\nb\nc\nd\n")
    assert mod.resolve("ControlMappingMenu.prefab", 2, 3, tree) == ["b", "c"]


def test_an_asset_name_matching_two_files_resolves_to_none(tmp_path):
    """Never guess between them.

    Reported as unresolvable, the same as a citation that matches no file at all.
    """
    tree = tmp_path / "decompile"
    one = tree / "Resources" / "Assets" / "GameObject"
    two = tree / "Resources" / "Assets" / "Prefabs"
    one.mkdir(parents=True)
    two.mkdir(parents=True)
    (one / "Foo.prefab").write_text("a\n")
    (two / "Foo.prefab").write_text("b\n")
    assert mod.resolve("Foo.prefab", 1, 1, tree) is None


def test_an_unrecognised_asset_extension_is_not_searched_for(tmp_path):
    """`.prefab` is the only extension the handbook has cited by name-and-line so far.

    A name ending in something else must fall through to unresolvable
    rather than triggering a Resources/Assets search that was never asked
    for.
    """
    tree = tmp_path / "decompile"
    other = tree / "Resources" / "Assets" / "Material"
    other.mkdir(parents=True)
    (other / "Foo.mat").write_text("a\n")
    assert mod.resolve("Foo.mat", 1, 1, tree) is None


def test_a_line_past_the_end_yields_an_empty_list_not_a_crash(tmp_path):
    """A citation surviving a shrinking file is drift, not a crash.

    The compare step has to see "nothing there now" as a difference it can
    report.
    """
    tree = make_decompile(tmp_path, "Pug.Other", ["a", "b"])
    assert mod.resolve("Pug.Other", 900, 900, tree) == []


def write_chapter(root, name, text):
    """Write a handbook chapter at `docs/ck/<name>` under `root`, creating the tree if needed."""
    docs = root / "docs" / "ck"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / name).write_text(text)


def test_collects_every_citation_keyed_as_written(tmp_path):
    """collect() keys the corpus by the citation exactly as the prose writes it.

    It walks every chapter under docs/ck/, resolves each citation, and keys
    the corpus as (`Pug.Other:2`, `Pug.Other:3-4`) — not by chapter, line
    number, or some other identity two different citations might share.
    """
    tree = make_decompile(tmp_path, "Pug.Other", ["a", "b", "c", "d"])
    write_chapter(tmp_path, "one.md", "see `Pug.Other:2` and `Pug.Other:3-4`\n")

    corpus, problems, cited = mod.collect(tmp_path, tree)

    assert corpus == {"Pug.Other:2": ["b"], "Pug.Other:3-4": ["c", "d"]}
    assert problems == []
    assert cited == {"Pug.Other:2", "Pug.Other:3-4"}


def test_reports_an_unresolvable_citation_with_its_location(tmp_path):
    """An unresolvable citation is reported with its chapter, line number and text.

    The message says "no decompiled assembly" — and the citation is still
    recorded in `cited`, which is what lets compare() later tell a citation
    that vanished from the corpus apart from one that merely broke.
    """
    tree = make_decompile(tmp_path, "Pug.Other", ["a"])
    write_chapter(tmp_path, "ui.md", "line one\nsee `ControlMappingMenu.prefab:2456-2457`\n")

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
    """Two sentences may cite the same line.

    The snapshot is keyed by citation, so this is one entry, not a conflict.
    """
    tree = make_decompile(tmp_path, "Pug.Base", ["a", "b"])
    write_chapter(tmp_path, "one.md", "`Pug.Base:2`\n")
    write_chapter(tmp_path, "two.md", "also `Pug.Base:2`\n")

    corpus, problems, cited = mod.collect(tmp_path, tree)

    assert corpus == {"Pug.Base:2": ["b"]}
    assert problems == []
    assert cited == {"Pug.Base:2"}


def test_no_drift_reports_nothing():
    """Baseline: when the corpus matches the snapshot exactly, compare() reports nothing."""
    assert mod.compare({"Pug.Other:2": ["b"]}, {"Pug.Other:2": ["b"]}, {"Pug.Other:2"}) == []


def test_a_changed_line_is_reported_with_both_texts():
    """A citation whose text changed is reported with both the old and the new text.

    That is what makes the drift readable without opening the file.
    """
    problems = mod.compare({"Pug.Other:2": ["now()"]}, {"Pug.Other:2": ["then()"]}, {"Pug.Other:2"})
    assert len(problems) == 1
    assert "Pug.Other:2" in problems[0]
    assert "then()" in problems[0] and "now()" in problems[0]


def test_a_citation_missing_from_the_snapshot_is_reported_as_unrecorded():
    """A citation collect() resolved but the snapshot has never seen is reported as unrecorded.

    Distinct from a citation whose text changed.
    """
    problems = mod.compare({"Pug.Base:9": ["x"]}, {}, {"Pug.Base:9"})
    assert len(problems) == 1
    assert "not in the snapshot" in problems[0]


def test_a_snapshot_entry_no_longer_cited_is_reported_as_stale():
    """Not an error in the handbook — a sentence was removed or reworded.

    It is reported so --capture is a deliberate act rather than silent
    bookkeeping. `cited` is empty: the key is genuinely absent, not merely
    unresolvable.
    """
    problems = mod.compare({}, {"Pug.Base:9": ["x"]}, set())
    assert len(problems) == 1
    assert "no longer cited" in problems[0]


def test_an_unresolvable_citation_is_not_also_reported_as_uncited():
    """The case compare() used to get wrong.

    An assembly that disappears makes its citation unresolvable (so it never
    enters `corpus`), but the citation is still sitting right there in the
    handbook (so it is in `cited`). Reporting it as "no longer cited
    anywhere" would read as "stale snapshot entry, delete it" — which would
    erase the recorded text, the only thing left saying what the line used to
    hold.
    """
    problems = mod.compare({}, {"PugMod.Platform:2": ["old text"]}, {"PugMod.Platform:2"})
    assert problems == []


def test_a_line_that_vanished_reports_the_empty_side_readably():
    """A citation whose line ran past the end of a shrunk file renders readably.

    When the corpus side of a comparison is an empty list, compare()
    renders it as "(past end of file)" rather than an unreadable empty
    string.
    """
    problems = mod.compare({"Pug.Other:900": []}, {"Pug.Other:900": ["gone()"]}, {"Pug.Other:900"})
    assert len(problems) == 1
    assert "past end of file" in problems[0]


def test_capture_writes_a_snapshot_and_succeeds(tmp_path, capsys):
    """--capture end-to-end.

    It resolves the one citation in the chapter, writes it into the
    snapshot JSON's `citations` key, exits 0, and prints confirmation.
    """
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
    """--capture also records the `--game-version` value into the snapshot JSON.

    It echoes the value on stdout too, so a later compare run can report
    which game version the snapshot reflects.
    """
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
    """--game-version is required with --capture, not optional.

    A capture that silently recorded no version would reproduce the exact
    defect the flag exists to close.
    """
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
    """The default (compare) mode prints the game version recorded in the snapshot.

    That way a drift report says which build it is comparing against.
    """
    tree = make_decompile(tmp_path, "Pug.Other", ["a", "b"])
    write_chapter(tmp_path, "one.md", "`Pug.Other:2`\n")
    snapshot = tmp_path / "snap.json"
    snapshot.write_text(
        json.dumps({"citations": {"Pug.Other:2": ["b"]}, "game_version": "1.2.1.5-8be0"})
    )

    code = mod.main(["x", "--decompile", str(tree), "--snapshot", str(snapshot), str(tmp_path)])

    assert code == 0
    assert "1.2.1.5-8be0" in capsys.readouterr().out


def test_a_versionless_snapshot_is_handled_not_crashed(tmp_path, capsys):
    """A snapshot captured before --game-version existed has no `game_version` key.

    It must be usable, not fatal — handled with a message asking for a
    recapture, not a `KeyError`. The fix for a versionless snapshot is a
    recapture, not a traceback.
    """
    tree = make_decompile(tmp_path, "Pug.Other", ["a", "b"])
    write_chapter(tmp_path, "one.md", "`Pug.Other:2`\n")
    snapshot = tmp_path / "snap.json"
    snapshot.write_text(json.dumps({"citations": {"Pug.Other:2": ["b"]}}))

    code = mod.main(["x", "--decompile", str(tree), "--snapshot", str(snapshot), str(tmp_path)])

    assert code == 0
    assert "no recorded game version" in capsys.readouterr().out


def test_a_changed_line_makes_the_default_mode_fail(tmp_path, capsys):
    """End-to-end: a drifted line makes a plain (compare) run fail.

    After a capture, changing the decompiled line the snapshot recorded
    makes the run exit 1 and print the new text.
    """
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
    code = mod.main(["x", "--decompile", str(tree), "--snapshot", str(snapshot), str(tmp_path)])

    assert code == 1
    assert "CHANGED" in capsys.readouterr().out


def test_a_missing_snapshot_says_what_to_run_rather_than_crashing(tmp_path, capsys):
    """A snapshot path that does not exist yet fails informatively, not with a crash.

    Running without --capture against it prints "--capture" as the fix,
    rather than raising on the missing file.
    """
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
    """An unresolvable citation must fail the run even when nothing in the snapshot drifted.

    Otherwise it stays invisible forever, since it can never drift if it
    never resolved in the first place. The bare "DedicatedServer:NNNN" form
    (no assembly named inside it) stands in for "names something resolve()
    does not model"; it is the pre-fix shape, not one the handbook writes
    any more.
    """
    tree = make_decompile(tmp_path, "Pug.Other", ["a"])
    write_chapter(tmp_path, "m.md", "`DedicatedServer:263259-263262`\n")
    snapshot = tmp_path / "snap.json"
    snapshot.write_text(json.dumps({"citations": {}}))

    code = mod.main(["x", "--decompile", str(tree), "--snapshot", str(snapshot), str(tmp_path)])

    assert code == 1
    assert "no decompiled assembly" in capsys.readouterr().out


def test_an_assembly_that_disappears_is_not_also_reported_as_uncited(tmp_path, capsys):
    """Reproduces what a real game update produced.

    An assembly renamed out from under a citation makes it unresolvable, but
    the citation is still sitting right there in the handbook — it must not
    ALSO be reported as "no longer cited anywhere", which reads as "stale
    snapshot entry, clean it up with --capture" and would delete the only
    remaining record of what the line used to say.
    """
    tree = make_decompile(tmp_path, "Pug.Other", ["a"])
    write_chapter(tmp_path, "one.md", "`PugMod.Platform:2`\n")
    snapshot = tmp_path / "snap.json"
    snapshot.write_text(json.dumps({"citations": {"PugMod.Platform:2": ["old text"]}}))

    code = mod.main(["x", "--decompile", str(tree), "--snapshot", str(snapshot), str(tmp_path)])
    out = capsys.readouterr().out

    assert code == 1
    assert "no decompiled assembly" in out
    assert "no longer cited anywhere" not in out


class TestSourceCloneResolution:
    """A citation can name a file in an open-source dependency's own sources.

    Those sit beside the decompiled assemblies rather than among them, so they
    need their own lookup — and the handbook states a filename, not a path.
    """

    def _clone(self, tmp_path, rel, text):
        p = tmp_path / "CoreLib-source-4.0.5" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        return p

    def test_a_cs_file_in_a_source_clone_resolves(self, tmp_path):
        """A `.cs` citation resolves by searching the dependency clone's own tree.

        It searches recursively for that filename, the same way an asset
        citation searches `Resources/Assets/`.
        """
        self._clone(tmp_path, "Assets/CoreLib/LocalizationModule.cs", "a\nb\nc\n")
        assert mod.resolve("LocalizationModule.cs", 2, 2, tmp_path) == ["b"]

    def test_an_ambiguous_filename_resolves_to_nothing(self, tmp_path):
        """Two files of the same name cannot be told apart from a citation that gives only the name.

        resolve() reports this as unresolvable rather than guessing between them.
        """
        self._clone(tmp_path, "a/Thing.cs", "x\n")
        self._clone(tmp_path, "b/Thing.cs", "y\n")
        assert mod.resolve("Thing.cs", 1, 1, tmp_path) is None

    def test_an_absent_file_resolves_to_nothing(self, tmp_path):
        """A filename matching no file under any source clone resolves to None.

        The same outcome as an ambiguous match — both are simply
        "unresolvable" to a caller.
        """
        (tmp_path / "CoreLib-source-4.0.5").mkdir(parents=True)
        assert mod.resolve("Missing.cs", 1, 1, tmp_path) is None

    def test_a_decompiled_assembly_still_wins(self, tmp_path):
        """The decompiled-assembly path is tried first, before any source-clone search.

        A `.cs` file that happens to share the assembly's own name must not
        shadow it.
        """
        (tmp_path / "Pug.Other.decompiled.cs").write_text("real\n")
        assert mod.resolve("Pug.Other", 1, 1, tmp_path) == ["real"]
