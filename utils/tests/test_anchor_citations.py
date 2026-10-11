"""Tests for anchor_citations.

The cases are the shapes `docs/ck/` actually holds: the member-tier majority,
the two fallback tiers, a range, a token cited more than once in one file, and
the four states that make a file unsafe to migrate. Nothing here is invented
-- the expected citation strings were read out of `describe` against the
fixture below, not written from the grammar, because a test asserting a
guessed anchor fails for the wrong reason.

The fixture is small on purpose. What makes an anchor right is a property of
the structure layer, which `test_structure_corpus.py` measures against all
27 real assemblies; what is measured here is the decision this module makes
on top of it -- migrate, keep, or refuse.
"""

import json
import re

import anchor_citations as mod
import pytest

# Lines 1-12, with one of each tier reachable:
#   3  a namespace-level delegate -- no enclosing type, so absolute
#   4  the class declaration      -- inside a type, inside no member
#   8  a statement in Bar         -- member tier, relative line 3
SOURCE = (
    "namespace Pug.Other\n"
    "{\n"
    "\tpublic delegate void Ready();\n"
    "\tpublic class Foo\n"
    "\t{\n"
    "\t\tpublic void Bar()\n"
    "\t\t{\n"
    "\t\t\tint x = 1;\n"
    "\t\t\tint y = 2;\n"
    "\t\t}\n"
    "\t}\n"
    "}\n"
)


def make_decompile(tmp_path, name="Pug.Other", source=SOURCE):
    """Write `source` as a decompiled assembly and return the tree it sits in.

    Same shape as the helper in test_check_citation_drift.py: call it twice
    with the same tmp_path to put a second assembly in one tree.
    """
    tree = tmp_path / "decompile"
    tree.mkdir(exist_ok=True)
    (tree / f"{name}.decompiled.cs").write_text(source)
    return tree


def make_file(tmp_path, text, name="docs/notes.md"):
    """Write a markdown file; `name` decides whether it counts as a chapter."""
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


@pytest.fixture
def recorded():
    """A snapshot mapping covering every citation the fixtures below use.

    The text is what the fixture's lines say, stripped, exactly as
    check_citation_drift records it.
    """
    return {
        "Pug.Other:3": ["public delegate void Ready();"],
        "Pug.Other:4": ["public class Foo"],
        "Pug.Other:8": ["int x = 1;"],
        "Pug.Other:8-9": ["int x = 1;", "int y = 2;"],
    }


class TestTiers:
    """Which tier a line lands in, and what the file then says instead."""

    def test_an_absolute_citation_becomes_its_member_anchor(self, tmp_path, recorded):
        """The ordinary case, 93 % of the corpus: a line inside a member."""
        tree = make_decompile(tmp_path)
        path = make_file(tmp_path, "the call `Pug.Other:8` does it\n")

        rewrites, notes, refusals = mod.plan_file(path, tree, recorded)

        assert refusals == ()
        assert notes == ()
        assert [(r.token, r.anchored, r.line, r.occurrences) for r in rewrites] == [
            ("Pug.Other:8", "Pug.Other:Foo:Bar:3", 8, 1)
        ]

    def test_a_line_inside_a_type_but_no_member_becomes_the_type_anchor(self, tmp_path, recorded):
        """56 citations in the corpus have no member to name. The type is the fallback."""
        tree = make_decompile(tmp_path)
        path = make_file(tmp_path, "declared at `Pug.Other:4`\n")

        rewrites, _, refusals = mod.plan_file(path, tree, recorded)

        assert refusals == ()
        assert [r.anchored for r in rewrites] == ["Pug.Other:Foo:1"]

    def test_a_line_no_type_encloses_stays_absolute(self, tmp_path, recorded):
        """The escape hatch: reported with its reason, never refused, never rewritten.

        Five citations in `harmony-and-ecs` are this case, all at namespace
        level in `Unity.Entities`. Refusing the file over one would make the
        escape hatch unmigratable, and rewriting it is impossible -- the
        grammar reads `Assembly:member:N` back as the type tier.
        """
        tree = make_decompile(tmp_path)
        path = make_file(tmp_path, "the delegate `Pug.Other:3`\n")

        rewrites, notes, refusals = mod.plan_file(path, tree, recorded)

        assert refusals == ()
        assert rewrites == ()
        assert len(notes) == 1
        assert "Pug.Other:3" in notes[0]
        assert "no type encloses" in notes[0]

    def test_a_range_keeps_both_ends_relative_to_its_element(self, tmp_path, recorded):
        """132 citations in the corpus are ranges; an end dropped here is silent."""
        tree = make_decompile(tmp_path)
        path = make_file(tmp_path, "both lines `Pug.Other:8-9`\n")

        rewrites, _, refusals = mod.plan_file(path, tree, recorded)

        assert refusals == ()
        assert [r.anchored for r in rewrites] == ["Pug.Other:Foo:Bar:3-4"]


class TestOccurrences:
    """A token appears as often as it appears, and the plan has to say so."""

    def test_every_occurrence_of_a_repeated_token_is_counted(self, tmp_path, recorded):
        """`harmony-and-ecs` holds 170 occurrences of 150 tokens.

        One Rewrite per unique token, carrying the count -- so a later rewrite
        of one occurrence that left the others behind is visible as a
        mismatch rather than as a chapter quietly written in two notations.
        """
        tree = make_decompile(tmp_path)
        path = make_file(
            tmp_path,
            "first `Pug.Other:8`, then `Pug.Other:4`, then `Pug.Other:8` again\n",
        )

        rewrites, _, refusals = mod.plan_file(path, tree, recorded)

        assert refusals == ()
        assert [(r.token, r.occurrences) for r in rewrites] == [
            ("Pug.Other:8", 2),
            ("Pug.Other:4", 1),
        ]


class TestRefusals:
    """The four states in which a citation must not be moved, each stopping the file."""

    def test_a_citation_whose_recorded_text_moved_is_refused(self, tmp_path, recorded):
        """Re-keying a stale record would carry it onto an authoritative-looking form.

        The spec's own boundary: this makes citations durable, not correct. A
        record that no longer matches the line is drift nobody has read, and
        the anchored form names a class and a method, so it reads as
        considered where the bare number read as written down.
        """
        tree = make_decompile(tmp_path)
        path = make_file(tmp_path, "the call `Pug.Other:8` does it\n")
        recorded["Pug.Other:8"] = ["int x = 99;"]

        rewrites, _, refusals = mod.plan_file(path, tree, recorded)

        assert rewrites == ()
        assert len(refusals) == 1
        assert "recorded text no longer matches" in refusals[0]
        assert "check_citation_drift" in refusals[0]

    def test_a_chapter_citation_with_no_snapshot_entry_is_refused(self, tmp_path):
        """Inside docs/ck the drift gate guarantees one, so its absence is a defect."""
        tree = make_decompile(tmp_path)
        path = make_file(tmp_path, "the call `Pug.Other:8`\n", name="docs/ck/a.md")

        rewrites, _, refusals = mod.plan_file(path, tree, {})

        assert rewrites == ()
        assert len(refusals) == 1
        assert "not in the snapshot" in refusals[0]

    def test_a_file_outside_docs_ck_anchors_on_the_round_trip_alone(self, tmp_path):
        """docs/roadmap.md has no snapshot by design, and the report says so.

        The same empty mapping that stops a chapter is the normal state here,
        so the difference has to be visible: one proof was available instead
        of two, and a reader of the report is told which.

        It rides on the rewrite rather than in the notes, because the citation
        *is* rewritten -- a note would be counted as "kept as written", which
        is how the report once claimed two kept citations out of four, none of
        which was kept.
        """
        tree = make_decompile(tmp_path)
        path = make_file(tmp_path, "the call `Pug.Other:8`\n", name="docs/roadmap.md")

        rewrites, notes, refusals = mod.plan_file(path, tree, {})

        assert refusals == ()
        assert notes == ()
        assert [(r.anchored, r.recorded) for r in rewrites] == [("Pug.Other:Foo:Bar:3", False)]

    def test_a_citation_naming_no_decompiled_file_is_refused(self, tmp_path, recorded):
        """An assembly the decompile has nothing by is a broken citation, not a tier."""
        tree = make_decompile(tmp_path)
        path = make_file(tmp_path, "the call `Pug.Nothing:8`\n")

        rewrites, _, refusals = mod.plan_file(path, tree, recorded)

        assert rewrites == ()
        assert "no decompiled file" in refusals[0]

    def test_a_round_trip_that_lands_elsewhere_refuses_the_whole_file(
        self, tmp_path, recorded, monkeypatch
    ):
        """One citation the tool cannot place stops the file, not just that citation.

        The guard exists for a defect in this tooling rather than in the
        handbook, so the only way to exercise it is to inject one: `locate`
        is made to answer with a line `describe` did not mean. Two prototypes
        failed silently and in opposite directions while this was designed,
        which is why the round trip is checked per citation and not sampled.
        """
        tree = make_decompile(tmp_path)
        path = make_file(tmp_path, "one `Pug.Other:8`, two `Pug.Other:4`\n")
        monkeypatch.setattr(mod, "locate", lambda structure, citation: 999)

        rewrites, _, refusals = mod.plan_file(path, tree, recorded)

        assert rewrites == ()
        assert len(refusals) == 2
        assert "resolves to line 999" in refusals[0]


class TestIdempotence:
    """A file already anchored is left alone, so a second run costs nothing."""

    def test_an_already_anchored_citation_yields_no_rewrite(self, tmp_path):
        """Re-running the tool is a no-op, so no second pass can churn the snapshot.

        And more than a convenience: an anchored citation's location is
        relative to its element, so treating it as an absolute line would
        describe some unrelated line near the top of the file -- and then
        refuse the whole chapter, because the recorded text of the citation
        would not match what that line says.
        """
        tree = make_decompile(tmp_path)
        path = make_file(tmp_path, "the call `Pug.Other:Foo:Bar:3` does it\n")

        rewrites, notes, refusals = mod.plan_file(
            path, tree, {"Pug.Other:Foo:Bar:3": ["int x = 1;"]}
        )

        assert (rewrites, notes, refusals) == ((), (), ())


def make_snapshot(tmp_path, recorded):
    """Write a snapshot document the CLI can read, with a game version like the real one."""
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps({"citations": recorded, "game_version": "1.3.0.6-6e73"}))
    return path


class TestCli:
    """The report a reader acts on: what moves, what stays, and what stops the file."""

    def test_it_reports_each_rewrite_and_exits_zero(self, tmp_path, recorded, capsys):
        """Both forms on one line, so the report can be read against the diff afterwards."""
        tree = make_decompile(tmp_path)
        path = make_file(tmp_path, "the call `Pug.Other:8` twice: `Pug.Other:8`\n")
        snapshot = make_snapshot(tmp_path, recorded)

        code = mod.main([str(path), "--decompile", str(tree), "--snapshot", str(snapshot)])

        out = capsys.readouterr().out
        assert code == 0
        assert "`Pug.Other:8` -> `Pug.Other:Foo:Bar:3`" in out
        assert "2 occurrences" in out
        assert "1 citation(s) to anchor" in out

    def test_it_exits_one_and_names_the_reason_when_the_file_is_refused(
        self, tmp_path, recorded, capsys
    ):
        """A refusal is an instruction, so the exit code and the text both have to carry it."""
        tree = make_decompile(tmp_path)
        path = make_file(tmp_path, "the call `Pug.Other:8`\n")
        recorded["Pug.Other:8"] = ["int x = 99;"]
        snapshot = make_snapshot(tmp_path, recorded)

        code = mod.main([str(path), "--decompile", str(tree), "--snapshot", str(snapshot)])

        out = capsys.readouterr().out
        assert code == 1
        assert "is not anchored" in out
        assert "recorded text no longer matches" in out

    def test_it_distinguishes_an_anchored_file_from_one_with_no_citations(
        self, tmp_path, recorded, capsys
    ):
        """Having nothing to do has two causes, and the report tells them apart.

        A migrated chapter and a file that never cited anything both yield no
        rewrites. The migration tasks read this line to confirm a migration
        landed, so a bare zero would make that check meaningless.
        """
        tree = make_decompile(tmp_path)
        path = make_file(tmp_path, "the call `Pug.Other:Foo:Bar:3` does it\n")
        snapshot = make_snapshot(tmp_path, {"Pug.Other:Foo:Bar:3": ["int x = 1;"]})

        code = mod.main([str(path), "--decompile", str(tree), "--snapshot", str(snapshot)])

        out = capsys.readouterr().out
        assert code == 0
        assert "0 citation(s) to anchor" in out
        assert "1 already anchored" in out

    def test_a_citation_with_no_recorded_text_is_not_counted_as_kept(self, tmp_path, capsys):
        """It is rewritten, so counting it as kept contradicts the line above it.

        Measured on the file the plan chose to exercise this path --
        `docs/roadmap.md`, 2 of whose 4 citations have no snapshot record --
        the run printed "4 citation(s) to anchor, 2 kept as written" from four
        citations of which none was kept. The summary exists so that "nothing
        to do" is distinguishable from "not looked at"; two citations counted
        twice under contradictory labels is the same defect one layer in.
        """
        tree = make_decompile(tmp_path)
        path = make_file(tmp_path, "the call `Pug.Other:8` and `Pug.Other:4`\n")

        code = mod.main([str(path), "--decompile", str(tree), "--snapshot", str(tmp_path / "none")])

        out = capsys.readouterr().out
        assert code == 0
        assert "2 citation(s) to anchor, 0 kept as written" in out
        assert "the round trip is the only proof" in out

    def test_a_missing_decompile_tree_is_reported_rather_than_traced(self, tmp_path, capsys):
        """The same shape as the sibling checkers: a missing tree is exit 1 with a sentence."""
        path = make_file(tmp_path, "the call `Pug.Other:8`\n")

        code = mod.main([str(path), "--decompile", str(tmp_path / "absent")])

        assert code == 1
        assert "decompile tree not found" in capsys.readouterr().out


class TestApply:
    """Writing the prose, and the one shape of replacement that is safe."""

    def test_applying_rewrites_replaces_every_occurrence(self, tmp_path):
        """Every occurrence, and matched with its backticks.

        The backticks are what keep one token from matching inside another:
        `Pug.Other:37085` is a prefix of `Pug.Other:370859`, and replacing
        the bare text would corrupt the longer citation while reporting
        success.
        """
        path = make_file(
            tmp_path, "see `Pug.Other:37085`, `Pug.Other:370859` and `Pug.Other:37085`\n"
        )
        rewrites = (
            mod.Rewrite("Pug.Other:37085", "Pug.Other:Foo:Bar:1", 37085, 2, True),
            mod.Rewrite("Pug.Other:370859", "Pug.Other:Foo:Baz:9", 370859, 1, True),
        )

        replaced = mod.apply_rewrites(path, rewrites)

        assert replaced == 3
        assert path.read_text() == (
            "see `Pug.Other:Foo:Bar:1`, `Pug.Other:Foo:Baz:9` and `Pug.Other:Foo:Bar:1`\n"
        )

    def test_a_count_that_does_not_match_the_plan_is_an_error(self, tmp_path):
        """What `occurrences` is documented to catch, now actually compared.

        The field's docstring says it makes a partial rewrite "visible as a
        mismatch", and nothing compared it: `apply_rewrites` returned the
        count, `main` printed it, and the post-condition only asked whether
        each anchored token was findable at least once. A plan built against
        one revision of a file and applied to another is the case that
        produces it.
        """
        path = make_file(tmp_path, "the call `Pug.Other:8` once\n")

        with pytest.raises(RuntimeError, match="the plan counted 3"):
            mod.apply_rewrites(
                path, (mod.Rewrite("Pug.Other:8", "Pug.Other:Foo:Bar:3", 8, 3, True),)
            )

    def test_a_token_that_does_not_land_in_the_file_is_an_error(self, tmp_path, monkeypatch):
        """The post-condition for the hazard the wrapping gate now prevents.

        This is the step that would carry a citation the file cannot express
        into a commit, so what was written is read back and checked rather
        than assumed. Exercised by making the written token unfindable, since
        no input can produce that state once `check_docs_wrapping` keeps a
        citation whole.
        """
        path = make_file(tmp_path, "see `Pug.Other:8`\n")
        monkeypatch.setattr(mod, "find", lambda line: [])

        with pytest.raises(RuntimeError, match=re.escape("Pug.Other:Foo:Bar:3")):
            mod.apply_rewrites(
                path, (mod.Rewrite("Pug.Other:8", "Pug.Other:Foo:Bar:3", 8, 1, True),)
            )


class TestRekey:
    """The snapshot after a migration: every record kept, under whichever key cites it."""

    def test_the_recorded_text_travels_to_the_new_key_unchanged(self):
        """The snapshot keeps recording what the line said, not what it says now.

        Re-capturing instead would write the current text under the new key,
        which compares equal to itself forever -- and so would hide a
        mis-anchoring behind fresh evidence. Carrying the old record across
        is the check that the new form points at the claim that was read.
        """
        snapshot = {"citations": {"Pug.Other:8": ["int x = 1;"]}, "game_version": "1.3.0.6-6e73"}
        rewrites = (mod.Rewrite("Pug.Other:8", "Pug.Other:Foo:Bar:3", 8, 1, True),)

        after = mod.rekey_snapshot(snapshot, rewrites, {"Pug.Other:Foo:Bar:3"})

        assert after["citations"] == {"Pug.Other:Foo:Bar:3": ["int x = 1;"]}

    def test_it_keeps_a_token_another_chapter_still_cites(self):
        """Both keys exist afterwards, carrying the same record.

        13 of the three target chapters' citations are also cited in chapters
        that stay unmigrated. Moving the key would leave the drift gate
        reporting the unmigrated chapter's citation as uncaptured, which
        reads as an instruction to capture what is already recorded.
        """
        snapshot = {"citations": {"Pug.Other:8": ["int x = 1;"]}}
        rewrites = (mod.Rewrite("Pug.Other:8", "Pug.Other:Foo:Bar:3", 8, 1, True),)

        after = mod.rekey_snapshot(snapshot, rewrites, {"Pug.Other:8", "Pug.Other:Foo:Bar:3"})

        assert after["citations"] == {
            "Pug.Other:8": ["int x = 1;"],
            "Pug.Other:Foo:Bar:3": ["int x = 1;"],
        }

    def test_it_adds_no_key_for_a_citation_no_chapter_carries(self):
        """Anchoring a file outside docs/ck changes no snapshot entry at all.

        The snapshot records the handbook, and `check_citation_drift.compare`
        reports any key no chapter cites as stale. So adding a key for
        `docs/roadmap.md` would turn the gate red on the very commit that
        anchored it, and dropping the old one would do the same from the other
        side -- the chapter that still cites it would read as uncaptured.
        """
        snapshot = {"citations": {"Pug.Other:8": ["int x = 1;"]}}
        rewrites = (mod.Rewrite("Pug.Other:8", "Pug.Other:Foo:Bar:3", 8, 1, True),)

        after = mod.rekey_snapshot(snapshot, rewrites, {"Pug.Other:8"})

        assert after["citations"] == {"Pug.Other:8": ["int x = 1;"]}

    def test_the_game_version_survives_the_rekey(self):
        """`verify_status` reads it to name the current build when no decompile is present."""
        snapshot = {"citations": {"Pug.Other:8": ["int x = 1;"]}, "game_version": "1.3.0.6-6e73"}
        rewrites = (mod.Rewrite("Pug.Other:8", "Pug.Other:Foo:Bar:3", 8, 1, True),)

        after = mod.rekey_snapshot(snapshot, rewrites, {"Pug.Other:Foo:Bar:3"})

        assert after["game_version"] == "1.3.0.6-6e73"


class TestCitedTokens:
    """What the handbook still writes, which is what decides the pruning."""

    def test_it_reads_every_chapter_and_nothing_else(self, tmp_path):
        """docs/ck only: the snapshot records the handbook, so only it votes.

        A token cited solely in `docs/roadmap.md` has no snapshot entry to
        keep alive, and counting it here would keep a stale record forever.
        """
        make_file(tmp_path, "a `Pug.Other:8` here\n", name="docs/ck/one.md")
        make_file(tmp_path, "b `Pug.Base:12` there\n", name="docs/ck/two.md")
        make_file(tmp_path, "c `WorldGen:3` elsewhere\n", name="docs/roadmap.md")

        assert mod.cited_tokens(tmp_path) == {"Pug.Other:8", "Pug.Base:12"}


class TestApplyIsAtomic:
    """A refused file is untouched on disk, in both places."""

    def test_nothing_is_written_when_the_file_is_refused(self, tmp_path, recorded):
        """Neither the prose nor the snapshot.

        A refusal means a citation must not move; writing the others anyway
        would leave the chapter in two notations, which is the state this
        tool exists to avoid rather than a partial success.
        """
        tree = make_decompile(tmp_path)
        path = make_file(
            tmp_path, "the call `Pug.Other:8` and `Pug.Nothing:3`\n", name="docs/ck/a.md"
        )
        before = path.read_text()
        snapshot = make_snapshot(tmp_path, recorded)
        snapshot_before = snapshot.read_text()

        code = mod.main(
            [str(path), "--apply", "--decompile", str(tree), "--snapshot", str(snapshot)]
        )

        assert code == 1
        assert path.read_text() == before
        assert snapshot.read_text() == snapshot_before

    def test_apply_writes_both_the_chapter_and_the_snapshot(self, tmp_path, recorded):
        """End to end through the flag, which is the half that is easiest to omit.

        The spec says as much about its own acceptance test: the risk is not
        that `describe` names the wrong element but that the value it returns
        does not survive being written into a chapter and read back out. Here
        that means three things at once -- the prose carries the anchored
        form, the snapshot's record moved to the new key, and the old key is
        gone because no chapter cites it any more.
        """
        tree = make_decompile(tmp_path)
        path = make_file(tmp_path, "the call `Pug.Other:8` does it\n", name="docs/ck/a.md")
        snapshot = make_snapshot(tmp_path, recorded)

        code = mod.main(
            [str(path), "--apply", "--decompile", str(tree), "--snapshot", str(snapshot)]
        )

        assert code == 0
        assert path.read_text() == "the call `Pug.Other:Foo:Bar:3` does it\n"
        citations = json.loads(snapshot.read_text())["citations"]
        assert citations["Pug.Other:Foo:Bar:3"] == ["int x = 1;"]
        assert "Pug.Other:8" not in citations

    def test_a_rekey_reads_the_chapters_of_the_file_s_own_repository(
        self, tmp_path, recorded, monkeypatch
    ):
        """Not the ones under the working directory, which is how records were lost.

        `--root` defaulted to `.`, so the documented command run from any
        other directory globbed `./docs/ck/*.md`, found nothing, and handed
        `rekey_snapshot` an empty census as the authoritative answer: nothing
        is cited, therefore every record this file touched is stale. Measured
        on a copy of the real corpus before the fix -- 809 records in, 807
        out, prose rewritten, exit 0, and the message said "re-keyed".

        Worse than a red gate. The recorded text is the only proof that the
        anchored form points at the line the claim was weighed against, and
        once it is gone the repair a reader reaches for is `--capture`, which
        writes what the line says now. An empty census is the house example
        of a silent zero and must not be a legitimate answer on a write path.
        """
        tree = make_decompile(tmp_path)
        path = make_file(tmp_path, "the call `Pug.Other:8`\n", name="docs/ck/a.md")
        snapshot = make_snapshot(tmp_path, recorded)
        monkeypatch.chdir(tmp_path / "docs")

        code = mod.main(
            [str(path), "--apply", "--decompile", str(tree), "--snapshot", str(snapshot)]
        )

        assert code == 0
        citations = json.loads(snapshot.read_text())["citations"]
        assert citations["Pug.Other:Foo:Bar:3"] == ["int x = 1;"]

    def test_a_file_with_no_repository_above_it_is_refused_rather_than_rekeyed(
        self, tmp_path, recorded, capsys
    ):
        """No `docs/ck/` above the file means no census can be taken.

        The alternative is to take one anyway and get an empty answer, which
        is the defect above. A refusal costs a message; guessing costs the
        snapshot.
        """
        tree = make_decompile(tmp_path)
        path = make_file(tmp_path, "the call `Pug.Other:8`\n", name="loose/a.md")
        snapshot = make_snapshot(tmp_path, recorded)
        before = snapshot.read_text()

        code = mod.main(
            [str(path), "--apply", "--decompile", str(tree), "--snapshot", str(snapshot)]
        )

        assert code == 1
        assert "no docs/ck" in capsys.readouterr().out
        assert snapshot.read_text() == before

    def test_nothing_is_written_without_apply(self, tmp_path, recorded):
        """The default is a report: the flag is what authorises a write."""
        tree = make_decompile(tmp_path)
        path = make_file(tmp_path, "the call `Pug.Other:8`\n")
        before = path.read_text()
        snapshot = make_snapshot(tmp_path, recorded)

        mod.main([str(path), "--decompile", str(tree), "--snapshot", str(snapshot)])

        assert path.read_text() == before


class TestRelocateCoexistence:
    """An anchored citation is invisible to the transitional renumbering tool."""

    def test_an_anchored_citation_is_not_touched_by_relocate_citations(self):
        """`check_citation_drift.CITATION` requires digits straight after the assembly.

        So an anchored citation matches nothing there, and the tool that
        renumbers absolute citations after a game update leaves it alone --
        which is what lets the two notations coexist while ten chapters are
        still unmigrated. Pinned rather than assumed: a widened pattern would
        read the `:3` of a member anchor as an absolute line and rewrite it.
        """
        from check_citation_drift import extract

        text = "see `Pug.Other:Foo:Bar:29` and `Pug.Other:370859`"

        assert extract(text) == [("Pug.Other", 370859, 370859)]
