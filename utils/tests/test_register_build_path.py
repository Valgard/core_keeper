"""Unit tests for registering a build path in the SDK's ModPaths asset.

The asset is Unity's, not ours, and the Editor reads it back -- so the tests that
matter are the ones about leaving it intact: everything outside the one list must
survive byte-for-byte, and the list itself must keep the shape the SDK's own
`AddPath` produces (five entries, oldest dropped).

The ordering test looks pedantic and is not. The Steam Workshop tab selects with
`LastOrDefault`, so among several paths ending in the same mod name the *last*
one wins -- re-registering has to move an entry to the end rather than leave it
where it was, or a stale sibling keeps winning after a fresh build.
"""

import register_build_path as rbp

HEADER = """%YAML 1.1
%TAG !u! tag:unity3d.com,2011:
--- !u!114 &11400000
MonoBehaviour:
  m_ObjectHideFlags: 0
  m_Script: {fileID: 11500000, guid: 103cec58589bd164cace4f80bcb67dcf, type: 3}
  m_Name: ModPaths
  m_EditorClassIdentifier: """


def asset(*paths, empty_form=False):
    if empty_form:
        return HEADER + "\n  latestBuildOrInstallPaths: []\n"
    body = "\n  latestBuildOrInstallPaths:"
    for p in paths:
        body += f"\n  - {p}"
    return HEADER + body + "\n"


def paths_in(text):
    _, _, paths, _ = rbp.split_list(text.splitlines())
    return paths


def test_adds_to_an_empty_list_written_as_inline_brackets():
    text, _ = rbp.register(asset(empty_form=True), "/builds/DisableDurability")

    assert paths_in(text) == ["/builds/DisableDurability"]


def test_appends_to_an_existing_list():
    text, _ = rbp.register(asset("/builds/FasterTalents"), "/builds/DisableDurability")

    assert paths_in(text) == ["/builds/FasterTalents", "/builds/DisableDurability"]


def test_registering_the_same_path_twice_does_not_duplicate_it():
    once, _ = rbp.register(asset(), "/builds/DisableDurability")
    twice, message = rbp.register(once, "/builds/DisableDurability")

    assert paths_in(twice) == ["/builds/DisableDurability"]
    assert message == "already registered"


def test_reregistering_moves_the_path_last_so_LastOrDefault_finds_it():
    start = asset("/builds/DisableDurability", "/builds/FasterTalents")

    text, _ = rbp.register(start, "/builds/DisableDurability")

    assert paths_in(text) == ["/builds/FasterTalents", "/builds/DisableDurability"]


def test_the_list_is_capped_at_five_and_drops_the_oldest():
    text = asset(*[f"/builds/Mod{i}" for i in range(5)])

    text, message = rbp.register(text, "/builds/Fresh")

    assert paths_in(text) == [
        "/builds/Mod1",
        "/builds/Mod2",
        "/builds/Mod3",
        "/builds/Mod4",
        "/builds/Fresh",
    ]
    assert "Mod0" in message


def test_everything_outside_the_list_is_left_untouched():
    start = asset("/builds/FasterTalents")

    text, _ = rbp.register(start, "/builds/DisableDurability")

    assert text.startswith(HEADER)
    assert "guid: 103cec58589bd164cace4f80bcb67dcf" in text
    assert text.count("latestBuildOrInstallPaths:") == 1


def test_a_path_needing_yaml_quoting_survives_a_round_trip():
    # Not hypothetical: a volume or mod named with a colon reaches us verbatim
    # from MOD_INSTALL_PATH, and unquoted it would parse as a mapping.
    weird = "/builds/Odd: Name"

    text, _ = rbp.register(asset(), weird)

    assert paths_in(text) == [weird]
    assert "'/builds/Odd: Name'" in text


def test_an_asset_without_the_field_is_reported_rather_than_guessed_at():
    try:
        rbp.register(HEADER + "\n", "/builds/DisableDurability")
    except LookupError as exc:
        assert "latestBuildOrInstallPaths" in str(exc)
    else:
        raise AssertionError("a missing field must not be silently invented")


def test_a_missing_asset_file_never_fails_the_build(tmp_path, capsys):
    code = rbp.main(
        ["register_build_path.py", str(tmp_path / "absent.asset"), "/builds/X"]
    )

    assert code == 0
    assert "not updated" in capsys.readouterr().err


def test_wrong_arguments_never_fail_the_build(capsys):
    code = rbp.main(["register_build_path.py"])

    assert code == 0
    assert "usage" in capsys.readouterr().err


def test_main_writes_the_file(tmp_path):
    target = tmp_path / "ModPaths.asset"
    target.write_text(asset("/builds/FasterTalents"))

    rbp.main(["register_build_path.py", str(target), "/builds/DisableDurability"])

    assert paths_in(target.read_text()) == [
        "/builds/FasterTalents",
        "/builds/DisableDurability",
    ]
