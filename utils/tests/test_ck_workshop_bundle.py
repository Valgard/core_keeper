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

# What steam_bundle.build_bundle emits for a mod that has never been published:
# no file id, and therefore hidden. Paths are never opened on the dry-run path,
# so they need not exist.
GOLDEN = {
    "fileId": 0,
    "title": "Item Checklist",
    "description": "[b]Item Checklist[/b]",
    "tags": ["1.2.1.3", "Quality of Life", "Client", "Script"],
    "changelog": "- first release",
    "version": "1.0.0",
    "contentPath": "/nonexistent/build/ItemChecklist",
    "previewPath": "/nonexistent/build/preview.png",
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
    def test_a_new_item_reports_no_id_and_success(self, tool):
        done = run(tool, GOLDEN)
        assert done.returncode == 0
        assert result_line(done) == {
            "fileId": 0,
            "created": False,
            "success": True,
            # 0 because SteamClient.Init never ran; upload.sh reads that as
            # "no value to write" rather than as an owner of zero.
            "modOwner": 0,
        }

    def test_an_existing_item_echoes_its_id_back(self, tool):
        done = run(tool, {**GOLDEN, "fileId": 3210987654, "visibility": "unchanged"})
        assert done.returncode == 0
        assert result_line(done)["fileId"] == 3210987654

    def test_it_sends_nothing(self, tool):
        assert "nothing sent" in run(tool, GOLDEN).stderr


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
        # `null` parses, so the JSON guard lets it through; only the emptiness
        # check below it catches this one.
        done = run(tool, "null")
        assert done.returncode == 2

    @pytest.mark.parametrize("value", [None, ""])
    def test_content_path_missing_or_blank(self, tool, value):
        bundle = dict(GOLDEN)
        if value is None:
            del bundle["contentPath"]
        else:
            bundle["contentPath"] = value
        done = run(tool, bundle)
        assert done.returncode == 2
        assert "contentPath" in done.stderr


class TestVisibility:
    """The field where a silent default is a public Workshop item.

    Anything the tool does not recognise used to mean "leave visibility
    alone", which for an item being created that same second means Steam's
    own default: public, half-configured, in the catalogue. So the values it
    does not recognise are exactly the ones that must stop it.
    """

    def test_a_missing_key_is_refused(self, tool):
        bundle = dict(GOLDEN)
        del bundle["visibility"]
        done = run(tool, bundle)
        assert done.returncode == 2
        assert "visibility" in done.stderr

    @pytest.mark.parametrize("value", ["public", "Hidden", "", "unlisted"])
    def test_an_unrecognised_value_is_refused(self, tool, value):
        # "Hidden" among them on purpose: the comparison is case-sensitive, so
        # a producer that ever capitalised the value would have published one
        # public item per new mod, silently.
        done = run(tool, {**GOLDEN, "visibility": value})
        assert done.returncode == 2
        assert "visibility" in done.stderr

    def test_a_new_item_may_not_say_unchanged(self, tool):
        # hidden ⇔ fileId == 0, forwards: "unchanged" on an item that does not
        # exist yet is how it gets created public.
        done = run(tool, {**GOLDEN, "fileId": 0, "visibility": "unchanged"})
        assert done.returncode == 2

    def test_an_existing_item_may_not_say_hidden(self, tool):
        # And backwards: hiding a live item takes something out of the
        # catalogue that a person deliberately put there.
        done = run(tool, {**GOLDEN, "fileId": 3210987654, "visibility": "hidden"})
        assert done.returncode == 2
