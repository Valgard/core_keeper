"""Tests for ck-workshop's bundle contract, driven through the real tool.

`--dry-run` returns before `SteamClient.Init`, so everything between reading
stdin and the result line — parsing the bundle, every guard that rejects one,
and the shape of what upload.sh then parses back — runs with no Steam client,
no native library and no account. That is the whole seam this suite covers;
the Steamworks calls past that point stay untested on purpose, which is why
the contract in front of them is worth pinning down.

The tool is invoked as a subprocess rather than reimplemented, for the same
reason test_check_docs_links.py runs the real script: a hand-rolled model of
the parser would agree with itself while disagreeing with what upload.sh
actually pipes into.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

UTILS = Path(__file__).resolve().parent.parent
PROJECT = UTILS / "ck-workshop"
SDK_PATH = UTILS.parent / "CoreKeeperModSDK"
PLUGINS = SDK_PATH / "Assets" / "Plugins" / "CoreKeeperModSDK"


@pytest.fixture(scope="module")
def preview(tmp_path_factory):
    """A file for previewPath to name, because the tool checks that one exists.

    Its contents are never read here — nothing on the dry-run path opens it,
    and Steam is what would eventually reject a preview it does not like. What
    is being exercised is the existence check, so an existing file is the whole
    of what this has to be.
    """
    path = tmp_path_factory.mktemp("preview") / "preview.png"
    path.write_bytes(b"not really a png")
    return path


@pytest.fixture
def golden(preview):
    """What steam_bundle.build_bundle emits for a mod never published before:
    no file id, and therefore hidden.

    contentPath is never opened on the dry-run path and so need not exist;
    previewPath is, which is the asymmetry the fixture above exists for. A
    fresh dict per test, so a test that mutates it cannot reach the next one.
    """
    return {
        "fileId": 0,
        "title": "Item Checklist",
        "description": "[b]Item Checklist[/b]",
        "tags": ["1.2.1.3", "Quality of Life", "Client", "Script"],
        "changelog": "- first release",
        "version": "1.0.0",
        "contentPath": "/nonexistent/build/ItemChecklist",
        "previewPath": str(preview),
        "visibility": "hidden",
        "dependencies": [],
    }


@pytest.fixture(scope="module")
def tool():
    """Build ck-workshop once and return the argv that runs it.

    Skips rather than fails when the toolchain or the SDK clone is absent —
    both are this machine's setup, not something the suite can arrange — but a
    build that is present and broken fails loudly, which is the case worth
    hearing about.
    """
    if shutil.which("dotnet") is None:
        pytest.skip("dotnet is not installed")
    for name in ("Facepunch.Steamworks.Posix.dll", "libsteam_api.dylib"):
        if not (PLUGINS / name).is_file():
            pytest.skip(
                f"{name} is not in the SDK clone — see utils/fetch_steam_lib.sh"
            )

    # -getProperty:TargetPath builds and then reports the assembly's exact
    # path, so the configuration and target framework never have to be guessed
    # at here — they live in the csproj, and a change there cannot silently
    # leave this suite running a stale binary from a path it hardcoded.
    built = subprocess.run(
        [
            "dotnet",
            "build",
            str(PROJECT),
            "-v",
            "q",
            "--nologo",
            "-getProperty:TargetPath",
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "SDK_PATH": str(SDK_PATH)},
    )
    assert built.returncode == 0, (
        f"ck-workshop did not build:\n{built.stdout}\n{built.stderr}"
    )
    return ["dotnet", built.stdout.strip(), "--dry-run"]


def run(tool, bundle):
    """Feed `bundle` (a dict, or raw text) to the tool and return the result."""
    text = bundle if isinstance(bundle, str) else json.dumps(bundle)
    return subprocess.run(tool, input=text, capture_output=True, text=True)


def result_line(completed):
    """The last '{'-prefixed stdout line, parsed — what upload.sh reads back.

    Scanned from the end the way upload.sh scans it, so a diagnostic that ever
    starts with a brace cannot make this suite disagree with the consumer.
    """
    for line in reversed(completed.stdout.splitlines()):
        if line.strip().startswith("{"):
            return json.loads(line)
    raise AssertionError(
        f"no result line on stdout:\n{completed.stdout}\n{completed.stderr}"
    )


class TestAcceptedBundle:
    def test_a_new_item_reports_no_id_and_success(self, tool, golden):
        done = run(tool, golden)
        assert done.returncode == 0
        assert result_line(done) == {
            "fileId": 0,
            "created": False,
            "success": True,
            # 0 because SteamClient.Init never ran; upload.sh reads that as
            # "no value to write" rather than as an owner of zero.
            "modOwner": 0,
        }

    def test_an_existing_item_echoes_its_id_back(self, tool, golden):
        done = run(tool, {**golden, "fileId": 3210987654, "visibility": "unchanged"})
        assert done.returncode == 0
        assert result_line(done)["fileId"] == 3210987654

    def test_it_sends_nothing(self, tool, golden):
        assert "nothing sent" in run(tool, golden).stderr


class TestUnusableBundle:
    """Everything that must exit 2 — the code upload.sh already treats as fatal."""

    def test_stdin_that_is_not_json(self, tool):
        done = run(tool, "not json at all")
        assert done.returncode == 2
        assert "not valid JSON" in done.stderr

    def test_empty_stdin(self, tool):
        done = run(tool, "")
        assert done.returncode == 2

    def test_json_null(self, tool):
        # `null` is valid JSON, so it gets past the parse and deserialises to a
        # null bundle. Only the emptiness check after it catches this one.
        done = run(tool, "null")
        assert done.returncode == 2

    @pytest.mark.parametrize("value", [None, ""])
    def test_content_path_missing_or_blank(self, tool, golden, value):
        bundle = dict(golden)
        if value is None:
            del bundle["contentPath"]
        else:
            bundle["contentPath"] = value
        done = run(tool, bundle)
        assert done.returncode == 2
        assert "contentPath" in done.stderr


class TestRequiredFields:
    """The fields that reach the Steamworks API, checked before they do.

    The csproj disables nullable annotations, so nothing in the C# says which
    of these may be absent — the only thing keeping a null out of a Workshop
    item is the discipline of a producer written in another language.
    """

    @pytest.mark.parametrize("field", ["title", "description", "changelog"])
    def test_a_missing_field_is_named(self, tool, golden, field):
        bundle = dict(golden)
        del bundle[field]
        done = run(tool, bundle)
        assert done.returncode == 2
        assert field in done.stderr

    @pytest.mark.parametrize("field", ["title", "description", "changelog"])
    def test_an_explicit_null_is_refused_too(self, tool, golden, field):
        # A JSON null and an absent key are the same thing on this side, and
        # both are a producer that stopped supplying a value.
        done = run(tool, {**golden, field: None})
        assert done.returncode == 2
        assert field in done.stderr

    def test_a_blank_title_is_refused(self, tool, golden):
        # Blank only counts as missing where blank is itself a wrong item, and
        # an untitled entry in the Workshop catalogue is one.
        done = run(tool, {**golden, "title": "   "})
        assert done.returncode == 2
        assert "title" in done.stderr

    @pytest.mark.parametrize("field", ["description", "changelog"])
    def test_an_empty_one_is_accepted(self, tool, golden, field):
        # Neither is refused when empty: an empty description makes a sparse
        # item rather than a broken one, and steam_bundle.parse_changelog
        # genuinely returns "" for a version heading with nothing under it.
        assert run(tool, {**golden, field: ""}).returncode == 0


class TestVisibility:
    """The field where a silent default is a public Workshop item.

    Anything the tool does not recognise used to mean "leave visibility
    alone", which for an item being created that same second means Steam's
    own default: public, half-configured, in the catalogue. So the values it
    does not recognise are exactly the ones that must stop it.
    """

    def test_a_missing_key_is_refused(self, tool, golden):
        bundle = dict(golden)
        del bundle["visibility"]
        done = run(tool, bundle)
        assert done.returncode == 2
        assert "visibility" in done.stderr

    @pytest.mark.parametrize("value", ["public", "Hidden", "", "unlisted"])
    def test_an_unrecognised_value_is_refused(self, tool, golden, value):
        # "Hidden" among them on purpose: the comparison is case-sensitive, so
        # a producer that ever capitalised the value would have published one
        # public item per new mod, silently.
        done = run(tool, {**golden, "visibility": value})
        assert done.returncode == 2
        assert "visibility" in done.stderr

    def test_a_new_item_may_not_say_unchanged(self, tool, golden):
        # hidden ⇔ fileId == 0, forwards: "unchanged" on an item that does not
        # exist yet is how it gets created public.
        done = run(tool, {**golden, "fileId": 0, "visibility": "unchanged"})
        assert done.returncode == 2

    def test_an_existing_item_may_not_say_hidden(self, tool, golden):
        # And backwards: hiding a live item takes something out of the
        # catalogue that a person deliberately put there.
        done = run(tool, {**golden, "fileId": 3210987654, "visibility": "hidden"})
        assert done.returncode == 2


class TestPreview:
    """The field whose absence used to publish an item with no preview at all.

    `if (File.Exists(previewPath))` with no else read a missing key, a typo and
    a preview that was never written as the same instruction: send no preview,
    say nothing. The result is a live catalogue entry with a placeholder where
    its logo belongs — and the Steam side has no metadata-only publish path
    (see docs/publishing.md), so correcting it afterwards costs a whole
    Workshop update, where refusing here costs nothing at all.

    Checked on the dry run too, which is why these tests can see it. A
    rehearsal that passed while the real run would go out without a preview
    would not be a rehearsal.
    """

    def test_a_missing_key_is_refused(self, tool, golden):
        bundle = dict(golden)
        del bundle["previewPath"]
        done = run(tool, bundle)
        assert done.returncode == 2
        assert "previewPath" in done.stderr

    @pytest.mark.parametrize("value", [None, "", "   "])
    def test_a_blank_value_is_refused(self, tool, golden, value):
        done = run(tool, {**golden, "previewPath": value})
        assert done.returncode == 2
        assert "previewPath" in done.stderr

    def test_a_path_that_names_no_file_is_refused(self, tool, golden):
        # What a present-and-non-blank check alone would still let through, and
        # the case that actually happens: the producer derives the preview into
        # a scratch directory that a trap removes, so the path is spelled
        # perfectly and the file is simply not there any more.
        done = run(tool, {**golden, "previewPath": "/nonexistent/preview.png"})
        assert done.returncode == 2
        assert "/nonexistent/preview.png" in done.stderr


class TestDependencies:
    """Entries on their way to AddDependency, checked before they get there.

    steam_bundle.py cannot emit any of the refusals below — it resolves an id
    or reports None for the whole list — so this guards a bundle assembled by
    hand or by some later producer. It is worth guarding because neither
    failure announces itself: AddDependency(0) asks Steam about an item that
    cannot exist, and a nameless entry empties the one log line on which a
    dependency's severity is visible while the log is still on screen.
    """

    def test_an_entry_with_no_file_id_is_refused(self, tool, golden):
        entry = {"name": "CoreLib", "fileId": 0, "required": True}
        done = run(tool, {**golden, "dependencies": [entry]})
        assert done.returncode == 2
        assert "CoreLib" in done.stderr

    def test_an_absent_file_id_is_refused_as_well(self, tool, golden):
        # An absent key deserialises to 0, so it is the same AddDependency(0)
        # arriving by a different route — and the likelier of the two.
        done = run(tool, {**golden, "dependencies": [{"name": "CoreLib"}]})
        assert done.returncode == 2
        assert "CoreLib" in done.stderr

    @pytest.mark.parametrize("name", [None, "", "  "])
    def test_an_entry_with_no_name_is_refused(self, tool, golden, name):
        entry = {"name": name, "fileId": 3000000001, "required": False}
        done = run(tool, {**golden, "dependencies": [entry]})
        assert done.returncode == 2
        # Named by its id, because the name is the thing that is missing.
        assert "3000000001" in done.stderr

    def test_a_null_entry_is_refused(self, tool, golden):
        done = run(tool, {**golden, "dependencies": [None]})
        assert done.returncode == 2
        assert "dependencies" in done.stderr

    def test_a_resolved_entry_is_accepted(self, tool, golden):
        entry = {"name": "CoreLib", "fileId": 3000000001, "required": True}
        assert run(tool, {**golden, "dependencies": [entry]}).returncode == 0

    def test_null_is_accepted_because_it_means_unknown(self, tool, golden):
        # What steam_bundle emits when it could not resolve every declared
        # dependency. Program.cs early-returns on it and syncs nothing, which
        # is the point: a list it cannot complete would remove what it cannot
        # name. Refusing null here would turn that safeguard into an abort.
        assert run(tool, {**golden, "dependencies": None}).returncode == 0

    def test_an_empty_list_is_accepted(self, tool, golden):
        # "Declares none, so remove anything stale" — a complete picture, and a
        # different claim from the null above.
        assert run(tool, {**golden, "dependencies": []}).returncode == 0


class TestDependencyPlan:
    """What the dry run says it would do with dependencies.

    The sync itself runs after SubmitAsync and so needs a live Steam session,
    a published item and a real failure; none of that is reachable from a
    test. What IS reachable is the plan the dry run states beforehand — the
    list an operator reads before a real publish, and the exit code a sync
    that could not run would produce, which comes out of the same
    DependencyDecision.ExitCodeFor the live path ends on.

    The decision table itself is tested directly, in C#, by
    utils/ck-workshop-tests — see test_ck_workshop_severity.py. These cover
    the reporting around it.
    """

    def test_each_dependency_is_listed_with_its_file_id(self, tool, golden):
        # The id, not just the name: it is what actually gets attached, and
        # what a wrong entry in steam-dependencies.json would show up as. A
        # name alone cannot be checked against the Workshop by eye.
        deps = [{"name": "CoreLib", "fileId": 3673516180, "required": True}]
        err = run(tool, {**golden, "dependencies": deps}).stderr
        assert "CoreLib" in err
        assert "3673516180" in err
        assert "required" in err

    def test_it_says_what_it_cannot_show_not_merely_that_something_is_missing(
        self, tool, golden
    ):
        # Without this the list reads as the whole plan, and it is not: the
        # sync is a full one, so it also removes what the live item carries and
        # the bundle does not name. Naming the removals specifically is the
        # point — "some things cannot be previewed" would not warn anyone.
        deps = [{"name": "CoreLib", "fileId": 3673516180, "required": True}]
        err = run(tool, {**golden, "dependencies": deps}).stderr
        assert "remove any dependency the item carries that is not listed" in err
        assert "cannot be previewed" in err

    def test_a_required_dependency_takes_the_louder_code(self, tool, golden):
        # 9 rather than 7 whenever ANY declared dependency is required: the
        # two cost a subscriber different things, and a mod that does not run
        # is the expensive one to miss.
        deps = [
            {"name": "ModSettingsMenu", "fileId": 3000000002, "required": False},
            {"name": "CoreLib", "fileId": 3000000001, "required": True},
        ]
        err = run(tool, {**golden, "dependencies": deps}).stderr
        assert "exit 9" in err
        assert "CoreLib" in err

    def test_only_optional_dependencies_take_the_quieter_code(self, tool, golden):
        deps = [{"name": "ModSettingsMenu", "fileId": 3000000002, "required": False}]
        err = run(tool, {**golden, "dependencies": deps}).stderr
        assert "exit 7" in err
        assert "exit 9" not in err

    def test_an_empty_list_is_still_a_sync_that_could_fail(self, tool, golden):
        # Declaring none is an instruction to remove what is stale, so the
        # query can still fail — and with nothing required, quietly.
        err = run(tool, {**golden, "dependencies": []}).stderr
        assert "exit 7" in err

    def test_an_unresolved_list_plans_no_sync_at_all(self, tool, golden):
        # null is "unknown, change nothing". There is no failure code to
        # report because there is no sync, and saying one would invite the
        # reader to expect an attempt.
        err = run(tool, {**golden, "dependencies": None}).stderr
        assert "exit 9" not in err
        assert "exit 7" not in err
        assert "skipped" in err.lower()
