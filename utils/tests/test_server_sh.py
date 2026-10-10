"""Argument handling of utils/server.sh, exercised through `start --dry-run`.

Nothing here launches a server: a dry run validates and prints the cxstart
command line, then stops. Every test points the script at a scratch server
directory, so neither the result nor the value lists depend on what is installed
on the machine running the suite.
"""

import shlex
import subprocess
import time
from itertools import pairwise
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "server.sh"

# A cut-down ARGUMENTS.txt in the shape the server ships it: "## <Title>"
# sections, values as "- Name" or "- Name: description", LF line endings.
ARGUMENTS_TXT = """\
## World Mode

Possible values are:
- Normal: Face balanced monsters.
- Hard: Tackle tougher monsters.
- Creative: Set your imagination free.

## Season

Possible values are:
- None
- Easter
- CherryBlossom

## Activate Content Bundles

Possible values are:
- GuaranteedOases: missing: Menu/ContentBundleGuaranteedOasesDesc
- BiomeStatues: missing: Menu/ContentBundleBiomeStatuesDesc

## Platform

Possible values are:
- Steam
- GOG
"""

CK_ENV = (
    "CK_SERVER_WORLD",
    "CK_SERVER_PORT",
    "CK_SERVER_PASSWORD",
    "CK_SERVER_MAXPLAYERS",
    "CK_SERVER_PLATFORM",
    "CK_SERVER_DIR",
    "CK_BOTTLE_NAME",
    "CK_BOTTLE_PATH",
    "CK_CXSTART",
    "CK_WINE_USER",
)

# Stands in for cxstart on the paths that launch: records the arguments it was
# given and writes the GameInfo.txt the script waits for, as the server would.
CXSTART_STUB = """\
#!/bin/bash
printf '%s\\n' "$@" > "$STUB_LOG"
printf 'Allowed platforms: Steam\\n' > "$CK_SERVER_DIR/GameInfo.txt"
"""

# The pattern server.sh recognises a running server by.
PROC_PATTERN = "CoreKeeperServer.exe"


def real_server_running():
    """Tell whether a real dedicated server is up, which would steer start elsewhere."""
    return (
        subprocess.run(["pgrep", "-f", PROC_PATTERN], capture_output=True, check=False).returncode
        == 0
    )


@pytest.fixture
def server_dir(tmp_path):
    """A scratch server install holding nothing but ARGUMENTS.txt."""
    d = tmp_path / "server"
    d.mkdir()
    (d / "ARGUMENTS.txt").write_text(ARGUMENTS_TXT)
    return d


@pytest.fixture
def run(tmp_path, server_dir, monkeypatch):
    """Run server.sh against the scratch install, with no CK_* leaking in from .envrc."""
    for name in CK_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CK_BOTTLE_PATH", str(tmp_path / "bottle"))
    monkeypatch.setenv("CK_SERVER_DIR", str(server_dir))

    def _run(*args, **env):
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        return subprocess.run(
            ["bash", str(SCRIPT), *args], capture_output=True, text=True, check=False
        )

    return _run


def server_argv(result):
    """Return the arguments a dry run would hand to CoreKeeperServer.exe."""
    assert result.returncode == 0, result.stderr
    words = shlex.split(result.stdout)
    exe = next(i for i, w in enumerate(words) if w.endswith("CoreKeeperServer.exe"))
    return words[exe + 1 :]


def value_of(argv, flag):
    """Return the value following a server flag."""
    return argv[argv.index(flag) + 1]


def test_defaults_match_the_previous_fixed_launch(run):
    """With no options and no CK_SERVER_* set, only the built-in defaults are sent."""
    argv = server_argv(run("start", "--dry-run"))
    assert argv == [
        "-batchmode", "-logfile", "CoreKeeperServerLog.txt",
        "-world", "0", "-maxplayers", "8",
        "-port", "27015", "-allowonlyplatform", "Steam",
    ]  # fmt: skip


def test_options_reach_the_server_with_its_own_flag_names(run):
    """Each option is translated to the flag spelling ARGUMENTS.txt documents."""
    argv = server_argv(
        run(
            "start", "-n", "-w", "3", "--world-name", "My Server", "--seed=Nice World",
            "--mode", "Hard", "--season", "Easter", "--game-id", "WH3rhzuk5TfbA4jFuZPg7SmbCHES",
            "--max-players", "4", "--password", "secret", "--ip", "10.0.0.5",
            "--hashed-seed", "42", "--activate-all-content",
        )
    )  # fmt: skip
    pairs = dict(pairwise(argv))
    assert pairs["-world"] == "3"
    assert pairs["-worldname"] == "My Server"
    assert pairs["-worldseed"] == "Nice World"
    assert pairs["-hashedworldseed"] == "42"
    assert pairs["-worldmode"] == "Hard"
    assert pairs["-season"] == "Easter"
    assert pairs["-gameid"] == "WH3rhzuk5TfbA4jFuZPg7SmbCHES"
    assert pairs["-maxplayers"] == "4"
    assert pairs["-password"] == "secret"
    assert pairs["-ip"] == "10.0.0.5"
    assert "-activateallcontent" in argv


def test_an_option_overrides_its_environment_default(run):
    """A CK_SERVER_* value is a default, and the option wins over it."""
    argv = server_argv(run("start", "-n", "--world", "5", CK_SERVER_WORLD="2"))
    assert value_of(argv, "-world") == "5"


def test_no_port_and_all_platforms_drop_their_flags(run):
    """The two negative options remove the flags their defaults would add."""
    argv = server_argv(run("start", "-n", "--no-port", "--all-platforms"))
    assert "-port" not in argv
    assert "-allowonlyplatform" not in argv


def test_values_are_matched_case_insensitively_and_sent_in_canonical_spelling(run):
    """A lower-case value is accepted and forwarded as ARGUMENTS.txt spells it."""
    argv = server_argv(
        run("start", "-n", "--mode", "hard", "--season", "cherryblossom", "--platform", "gog")
    )
    assert value_of(argv, "-worldmode") == "Hard"
    assert value_of(argv, "-season") == "CherryBlossom"
    assert value_of(argv, "-allowonlyplatform") == "GOG"


def test_content_bundles_are_validated_one_by_one(run):
    """Every bundle in the list is checked, not just the list as a whole."""
    argv = server_argv(run("start", "-n", "--activate-content", "guaranteedoases,BiomeStatues"))
    assert value_of(argv, "-activatecontent") == "GuaranteedOases,BiomeStatues"

    result = run("start", "-n", "--activate-content", "GuaranteedOases,Nope")
    assert result.returncode == 1
    assert "'Nope'" in result.stderr


def test_arguments_after_double_dash_pass_through_verbatim(run):
    """Anything after `--` reaches the server untouched, even option look-alikes."""
    argv = server_argv(run("start", "-n", "--", "-custom", "--world", "x y"))
    assert argv[-3:] == ["-custom", "--world", "x y"]


def test_without_arguments_txt_values_pass_through_unchecked_with_a_warning(run, server_dir):
    """With no value list the value is forwarded, and the skipped check is announced."""
    (server_dir / "ARGUMENTS.txt").unlink()
    result = run("start", "-n", "--mode", "Whatever")
    assert value_of(server_argv(result), "-worldmode") == "Whatever"
    assert "cannot check --mode" in result.stderr


def test_a_renamed_section_is_treated_like_a_missing_list(run, server_dir):
    """An update renaming a section must not turn validation off silently."""
    (server_dir / "ARGUMENTS.txt").write_text(
        ARGUMENTS_TXT.replace("## World Mode", "## Game Mode")
    )
    result = run("start", "-n", "--mode", "Hrad")
    assert "cannot check --mode: no '## World Mode' list" in result.stderr


@pytest.mark.parametrize(
    ("args", "flag", "value"),
    [
        (["--world", "0"], "-world", "0"),
        (["--world", "29"], "-world", "29"),
        (["--port", "1"], "-port", "1"),
        (["--port", "65535"], "-port", "65535"),
        (["--hashed-seed", "0"], "-hashedworldseed", "0"),
        (["--hashed-seed", "4294967295"], "-hashedworldseed", "4294967295"),
        (["--game-id", "A" * 15], "-gameid", "A" * 15),
        (["--game-id", "z" * 28], "-gameid", "z" * 28),
        (["--password", "p" * 28], "-password", "p" * 28),
        (["-p", "7778"], "-port", "7778"),
    ],
)
def test_values_at_the_edge_of_their_range_are_accepted(run, args, flag, value):
    """The documented limits are inclusive, so the boundary values themselves must pass."""
    assert value_of(server_argv(run("start", "-n", *args)), flag) == value


def test_an_existing_macos_data_path_is_forwarded(run, tmp_path):
    """A valid data path reaches the server; dropping it would write into the shared world."""
    saves = tmp_path / "saves"
    saves.mkdir()
    assert value_of(server_argv(run("start", "-n", "--data-path", str(saves))), "-datapath") == str(
        saves
    )


def test_a_windows_data_path_is_forwarded_as_it_is(run):
    """A Windows path cannot be checked from macOS, so it passes untouched."""
    assert (
        value_of(server_argv(run("start", "-n", "--data-path", "C:/Saves")), "-datapath")
        == "C:/Saves"
    )


@pytest.mark.parametrize("var", ["CK_SERVER_PORT", "CK_SERVER_PLATFORM"])
def test_an_empty_environment_value_drops_its_flag(run, var):
    """Empty means relay only or every platform, as documented, not the built-in default."""
    argv = server_argv(run("start", "-n", **{var: ""}))
    flag = {"CK_SERVER_PORT": "-port", "CK_SERVER_PLATFORM": "-allowonlyplatform"}[var]
    assert flag not in argv


@pytest.mark.parametrize(
    ("args", "env", "message"),
    [
        (["--world", "30"], {}, "world index must be 0-29"),
        ([], {"CK_SERVER_WORLD": "abc"}, "world index must be 0-29"),
        (["--port", "70000"], {}, "port must be 1-65535"),
        (["--max-players", "0"], {}, "max players must be a positive number"),
        (["--password", "x" * 29], {}, "longer than 28"),
        (["--hashed-seed", "4294967296"], {}, "hashed seed must be"),
        (["--game-id", "short"], {}, "game ID must be"),
        (["--game-id", "WH3rhzuk5TfbA4jFuZPg7SmbCHE0"], {}, "game ID must be"),
        (["--mode", "Brutal"], {}, "valid: Normal Hard Creative"),
        (["--timeout", "0"], {}, "timeout must be"),
        (["--data-path", "/does/not/exist/anywhere"], {}, "is not an existing directory"),
        (["--data-path", "/etc/hosts"], {}, "is not an existing directory"),
        (["--data-path", "saves"], {}, "must be an absolute macOS path"),
        (["--data-path=~/saves"], {}, "must be an absolute macOS path"),
        (["--activate-content", ","], {}, "names no bundle"),
        (["--port"], {}, "--port needs a value"),
        (["--port="], {}, "--port needs a non-empty value"),
        (["--no-relink=1"], {}, "--no-relink takes no value"),
        (["--bogus"], {}, "unknown option: --bogus"),
    ],
)
def test_bad_input_is_refused_before_anything_runs(run, args, env, message):
    """A bad option or CK_SERVER_* value stops the run with a reason and prints no command."""
    result = run("start", "-n", *args, **env)
    assert result.returncode == 1
    assert message in result.stderr
    assert result.stdout == ""


@pytest.mark.parametrize(
    ("args", "warning"),
    [
        (["--no-port", "--ip", "10.0.0.5"], "--ip has no effect without a port"),
        (["--no-port", "--platform", "GOG"], "--platform has no effect without a port"),
        (["--seed", "a", "--hashed-seed", "1"], "--hashed-seed is ignored when --seed is set"),
    ],
)
def test_ineffective_combinations_warn_and_are_still_forwarded(run, args, warning):
    """Options the server would ignore are harmless, so they warn instead of failing."""
    result = run("start", "-n", *args)
    assert warning in result.stderr
    assert server_argv(result)


def test_the_platform_default_alone_does_not_warn_without_a_port(run):
    """Only an explicit --platform warns; the default would nag on every relay start."""
    result = run("start", "-n", "--no-port")
    assert "WARNING" not in result.stderr


def test_start_help_lists_the_values_from_arguments_txt(run):
    """The help text shows the value lists of the installed server, not a hardcoded copy."""
    result = run("start", "--help")
    assert result.returncode == 0
    assert "Normal Hard Creative" in result.stdout
    assert "GuaranteedOases BiomeStatues" in result.stdout


@pytest.mark.parametrize("args", [["--help"], ["-h"], ["help"]])
def test_global_help(run, args):
    """Every common spelling of help prints the command overview and succeeds."""
    result = run(*args)
    assert result.returncode == 0
    assert "Commands:" in result.stdout


def test_no_command_prints_usage_and_fails(run):
    """A bare invocation is a usage error, so the overview goes to stderr."""
    result = run()
    assert result.returncode == 1
    assert "Commands:" in result.stderr


@pytest.mark.parametrize("command", ["stop", "status", "log", "relink"])
def test_commands_without_options_refuse_trailing_arguments(run, command):
    """A start option given to another command is refused, not silently dropped."""
    result = run(command, "--world", "3")
    assert result.returncode == 1
    assert f"'{command}' takes no arguments" in result.stderr


def test_unknown_command(run):
    """An unknown command names itself in the error."""
    result = run("frobnicate")
    assert result.returncode == 1
    assert "unknown command: frobnicate" in result.stderr


def test_status_shows_server_notes_but_not_the_paste_block(run, server_dir):
    """Status keeps whatever the server wrote, except the paste block it replaces."""
    # The note line stands in for whatever the server writes about a bad
    # argument; its exact wording is not known here, which is why status lists
    # everything except the paste block rather than an allowlist of lines.
    (server_dir / "GameInfo.txt").write_text(
        "Allowed platforms: Steam\n"
        "Some note about an ignored argument\n"
        "Port: 27015\n"
        "Password: pw\n"
        "Local IP: 10.0.0.2\n"
        "\n"
        'Paste to ip-field in "join via IP" menu to easily fill all values\n'
        "10.0.0.2;27015;;pw\n"
    )
    out = run("status").stdout
    assert "Some note about an ignored argument" in out
    assert "Paste to" not in out
    assert "Join via IP:  10.0.0.2;27015;;pw" in out
    assert out.count(";;") == 1


def test_status_keeps_a_password_line_that_contains_the_paste_separator(run, server_dir):
    """The paste block is dropped by position, so a password holding ';;' still shows."""
    (server_dir / "GameInfo.txt").write_text(
        "Password: a;;b\n"
        "\n"
        'Paste to ip-field in "join via IP" menu to easily fill all values\n'
        "10.0.0.2;27015;;a;;b\n"
    )
    assert "Password: a;;b" in run("status").stdout


def test_a_missing_bottle_is_reported_instead_of_exiting_silently(run):
    """Regression: without the bottle's LocalLow directory the script died without a message."""
    result = run("relink")
    assert result.returncode == 1
    assert "server mod dir not found" in result.stderr


def test_relink_warns_when_the_client_loader_config_is_missing(run, tmp_path, server_dir):
    """Without the loader config the version filter is off, which must not go unmentioned."""
    (server_dir / "CoreKeeperServer_Data" / "StreamingAssets" / "Mods").mkdir(parents=True)
    (tmp_path / "bottle" / "drive_c" / "users" / "Public" / "mod.io" / "5289" / "mods").mkdir(
        parents=True
    )
    result = run("relink")
    assert "client loader config not found" in result.stderr


@pytest.fixture
def launchable(tmp_path, server_dir, monkeypatch):
    """Make start's launch path runnable: a stub cxstart, an exe and an empty mod setup."""
    if real_server_running():
        pytest.skip("a real dedicated server is running; start would take the already-running path")
    stub = tmp_path / "cxstart"
    stub.write_text(CXSTART_STUB)
    stub.chmod(0o755)
    (server_dir / "CoreKeeperServer.exe").touch()
    (server_dir / "CoreKeeperServer_Data" / "StreamingAssets" / "Mods").mkdir(parents=True)
    (tmp_path / "bottle" / "drive_c" / "users" / "Public" / "mod.io" / "5289" / "mods").mkdir(
        parents=True
    )
    log = tmp_path / "stub.log"
    monkeypatch.setenv("STUB_LOG", str(log))
    return {"CK_CXSTART": str(stub)}, log


def test_start_launches_with_the_options_and_relinks_first(run, launchable):
    """A real start hands the options to cxstart and reconciles the mod links before that."""
    env, log = launchable
    result = run("start", "--world", "4", **env)
    assert result.returncode == 0, result.stderr
    assert "-world\n4\n" in log.read_text()
    # The scratch cache has no state.json, so the relink fails — loudly, and the start goes on.
    assert "mod links not reconciled" in result.stderr


def test_no_relink_skips_the_reconciliation(run, launchable):
    """--no-relink starts with the links as they are, without touching them."""
    env, log = launchable
    result = run("start", "--no-relink", **env)
    assert result.returncode == 0, result.stderr
    assert log.exists()
    assert "mod links" not in result.stderr


@pytest.fixture
def fake_running_server():
    """A process whose command line matches the pattern server.sh treats as a running server."""
    if real_server_running():
        pytest.skip("a real dedicated server is running")
    proc = subprocess.Popen(["bash", "-c", f"exec -a {PROC_PATTERN} sleep 60"])
    try:
        # Popen returns before the exec renames the process; wait until pgrep sees it.
        deadline = time.monotonic() + 5
        while not real_server_running():
            assert time.monotonic() < deadline, "fake server process never became visible to pgrep"
            time.sleep(0.05)
        yield proc
    finally:
        proc.kill()
        proc.wait()


def test_start_options_fail_while_the_server_already_runs(run, launchable, fake_running_server):
    """Options that cannot be applied are an error, so a caller does not test the wrong setup."""
    env, log = launchable
    result = run("start", "--world", "3", **env)
    assert result.returncode == 1
    assert "options not applied" in result.stderr
    assert not log.exists()


def test_a_plain_start_while_running_just_reports_it(run, launchable, fake_running_server):
    """Without options there is nothing to lose, so an already running server is success."""
    env, log = launchable
    result = run("start", **env)
    assert result.returncode == 0
    assert "Server already running" in result.stdout
    assert not log.exists()
