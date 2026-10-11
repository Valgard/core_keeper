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
        """
        tree = make_decompile(tmp_path)
        path = make_file(tmp_path, "the call `Pug.Other:8`\n", name="docs/roadmap.md")

        rewrites, notes, refusals = mod.plan_file(path, tree, {})

        assert refusals == ()
        assert [r.anchored for r in rewrites] == ["Pug.Other:Foo:Bar:3"]
        assert any("the round trip is the only proof" in note for note in notes)

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

    def test_a_missing_decompile_tree_is_reported_rather_than_traced(self, tmp_path, capsys):
        """The same shape as the sibling checkers: a missing tree is exit 1 with a sentence."""
        path = make_file(tmp_path, "the call `Pug.Other:8`\n")

        code = mod.main([str(path), "--decompile", str(tmp_path / "absent")])

        assert code == 1
        assert "decompile tree not found" in capsys.readouterr().out
