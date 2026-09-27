"""Runs utils/publish-helper-tests, so the pytest gate covers CLIPublishHelper too.

CLIPublishHelper runs inside Unity against the live mod.io plugin, so almost
none of it can be tested here. The exception is GameVersionTags, the rule that
decides which Game Version tag a shipped build is published under: it sits
after the file's `#endif` and uses no Unity or mod.io type, so the test project
compiles the helper as it stands and exercises that rule directly.

Driven from pytest for the reason test_ck_workshop_severity.py gives: the
repository has one hook that runs a test suite, and a second gate would have to
be remembered separately. Unlike that project, this one needs no SDK clone —
nothing it compiles references Steamworks — so dotnet is the only precondition.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parent.parent / "publish-helper-tests"


def test_the_game_version_tag_rule_holds():
    """`dotnet test` over utils/publish-helper-tests must pass."""
    if shutil.which("dotnet") is None:
        pytest.skip("dotnet is not installed")

    done = subprocess.run(
        ["dotnet", "test", str(PROJECT), "-v", "q", "--nologo"],
        capture_output=True,
        text=True,
        check=False,  # the status is asserted below, with the output attached
    )

    assert done.returncode == 0, f"publish-helper-tests failed:\n{done.stdout}\n{done.stderr}"
