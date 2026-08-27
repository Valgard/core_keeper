"""Runs ck-workshop's own C# tests, so the pytest gate covers them too.

utils/ck-workshop-tests holds the only unit tests in this repository that are
not Python: DependencyDecision decides which exit code a publish ends with,
and that decision is the single part of the dependency path reachable without
creating or modifying a real Workshop item — everything around it sits behind
SteamClient.Init and a successful SubmitAsync.

Those tests are therefore worth running on every commit, and the repository
has exactly one hook that runs a test suite (`pytest (utils)` in
.pre-commit-config.yaml). Rather than add a second gate that would have to be
remembered separately, this drives `dotnet test` from inside the first one —
the same shape test_ck_workshop_bundle.py already uses to drive `dotnet
build`.

The assertion is deliberately thin: a failing C# test fails here with its own
output attached. Restating any of its cases in Python would create a second
copy of the decision table, which is precisely what DependencyDecision exists
to prevent.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

UTILS = Path(__file__).resolve().parent.parent
PROJECT = UTILS / "ck-workshop-tests"
SDK_PATH = UTILS.parent / "CoreKeeperModSDK"
PLUGINS = SDK_PATH / "Assets" / "Plugins" / "CoreKeeperModSDK"


def test_the_dependency_decision_table_holds():
    """`dotnet test` over utils/ck-workshop-tests must pass.

    Skips on the same two conditions as the sibling suite, and for the same
    reason: the toolchain and the SDK clone are this machine's setup, not
    something the tests can arrange. The Steamworks assembly is needed even
    though no test touches it — the project under test references it, so
    without it nothing compiles.
    """
    if shutil.which("dotnet") is None:
        pytest.skip("dotnet is not installed")
    for name in ("Facepunch.Steamworks.Posix.dll", "libsteam_api.dylib"):
        if not (PLUGINS / name).is_file():
            pytest.skip(
                f"{name} is not in the SDK clone — see utils/fetch_steam_lib.sh"
            )

    done = subprocess.run(
        ["dotnet", "test", str(PROJECT), "-v", "q", "--nologo"],
        capture_output=True,
        text=True,
        env={**os.environ, "SDK_PATH": str(SDK_PATH)},
    )

    assert done.returncode == 0, (
        f"ck-workshop-tests failed:\n{done.stdout}\n{done.stderr}"
    )
