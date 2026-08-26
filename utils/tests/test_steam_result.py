"""Unit tests for persisting a Workshop item's id after ck-workshop returns.

This is the step that decides whether write_file_id is called at all, and every
way it can decide wrong ends the same way: an item exists on Steam, its id
exists nowhere locally, and the next publish creates a second public item that
nothing distinguishes from the first. So the branches are enumerated here one
by one rather than sampled — including the ones whose whole content is "do
nothing", because doing nothing is only correct when nothing was created.
"""

import json
import shutil
import subprocess

import pytest
import steam_identity
import steam_result

MOD = "DisableDurability"

ASSET = """%YAML 1.1
%TAG !u! tag:unity3d.com,2011:
--- !u!114 &11400000
MonoBehaviour:
  m_Name: DisableDurability_Steam
  fileId: 3790345467
  modOwner: 10000000000000000
  modName: Disable Durability
  selectedPath: /old/path/DisableDurability
  tags:
  - Client
  - Script
"""

BUNDLE = json.dumps(
    {"contentPath": "/builds/DisableDurability", "tags": ["Client", "Script"]}
)


def result_line(file_id, *, created, success, mod_owner=10000000000000000):
    """One of ck-workshop's result objects, as EmitResult writes it."""
    return json.dumps(
        {
            "fileId": file_id,
            "created": created,
            "success": success,
            "modOwner": mod_owner,
        }
    )


@pytest.fixture
def scenario(tmp_path):
    """Build a repo root plus a result file, and return a runner over both.

    Mirrors what upload.sh hands the script: two positional arguments and the
    three environment variables, with the asset where a real mod repo keeps it.
    """

    def build(stream, *, asset_text=ASSET, bundle=BUNDLE):
        asset = steam_identity.asset_path(tmp_path, MOD)
        asset.parent.mkdir(parents=True, exist_ok=True)
        if asset_text is not None:
            asset.write_text(asset_text)
        result = tmp_path / "result.txt"
        result.write_text(stream)

        env = {"MOD_NAME": MOD, "CK_STEAM_BUNDLE": bundle}
        code = steam_result.main(
            ["steam_result.py", str(result), str(tmp_path)], env=env
        )
        return code, asset

    return build


# --- 1-3: nothing was created, so nothing may be written -------------------


def test_an_empty_result_file_is_not_an_error(scenario, capsys):
    # ck-workshop crashed before it could report anything at all. Nothing was
    # created, so there is nothing to lose and nothing to say.
    code, asset = scenario("")

    assert code == 0
    assert steam_identity.read_file_id(asset) == 3790345467
    assert capsys.readouterr() == ("", "")


def test_a_stream_with_no_json_line_is_not_an_error(scenario, capsys):
    code, asset = scenario("  Title:   Disable Durability\nSteamworks: something\n")

    assert code == 0
    assert steam_identity.read_file_id(asset) == 3790345467
    assert capsys.readouterr() == ("", "")


def test_a_zero_file_id_persists_nothing(scenario, capsys):
    # The tool reports fileId 0 when it never got as far as creating an item.
    code, asset = scenario(result_line(0, created=False, success=False) + "\n")

    assert code == 0
    assert asset.read_text() == ASSET  # untouched, not merely unchanged in id
    assert capsys.readouterr() == ("", "")


# --- 4-6: an item exists on Steam, so its id must reach the asset ----------


def test_a_successful_creation_writes_the_id_and_reports_it(scenario, capsys):
    code, asset = scenario(
        "  Item:    new (hidden)\n"
        + result_line(4242424242, created=True, success=True)
        + "\n",
        asset_text=None,
    )

    assert code == 0
    assert steam_identity.read_file_id(asset) == 4242424242
    out, err = capsys.readouterr()
    assert "Workshop item 4242424242 (created, hidden)" in out
    assert err == ""


def test_a_successful_update_reports_updated(scenario, capsys):
    code, asset = scenario(result_line(3790345467, created=False, success=True) + "\n")

    assert code == 0
    assert steam_identity.read_file_id(asset) == 3790345467
    assert "Workshop item 3790345467 (updated)" in capsys.readouterr().out


def test_an_id_created_before_a_failed_publish_is_still_saved(scenario, capsys):
    # CreateItem already ran, so the item is live whether or not the rest of
    # the publish was. This is the branch the duplicate hazard lives in.
    code, asset = scenario(result_line(4242424242, created=True, success=False) + "\n")

    assert code == 0
    assert steam_identity.read_file_id(asset) == 4242424242
    out, err = capsys.readouterr()
    assert "created despite the failed publish" in err
    assert "instead of creating a duplicate" in err
    assert out == ""


def test_a_failed_update_re_saves_the_id_and_says_so(scenario, capsys):
    code, asset = scenario(result_line(3790345467, created=False, success=False) + "\n")

    assert code == 0
    assert steam_identity.read_file_id(asset) == 3790345467
    out, err = capsys.readouterr()
    assert "already existed" in err
    assert "the update itself failed" in err
    assert out == ""


# --- 7-9: the ways the surrounding data can be wrong -----------------------


def test_an_unparsable_bundle_still_saves_the_id(scenario, capsys):
    # The bundle only carries the fields the SDK window reads. Failing to parse
    # it must not cost the id, and must not blank out a path and a tag list
    # that were right before this run.
    code, asset = scenario(
        result_line(4242424242, created=False, success=True) + "\n",
        bundle="{not json at all",
    )

    assert code == 0
    assert steam_identity.read_file_id(asset) == 4242424242
    text = asset.read_text()
    assert "selectedPath: /old/path/DisableDurability" in text
    assert "tags:\n  - Client\n  - Script\n" in text
    assert "Workshop item 4242424242 (updated)" in capsys.readouterr().out


def test_a_refused_asset_exits_1_with_both_guidance_lines(scenario, capsys):
    code, asset = scenario(
        result_line(4242424242, created=True, success=True) + "\n",
        asset_text="this is not a Steam asset at all\n",
    )

    assert code == 1
    err = capsys.readouterr().err
    # The id itself has to appear in both lines: by the time anyone reads this
    # the tool's own output has scrolled past, and this is what they retype.
    assert "Workshop item 4242424242 is live" in err
    assert f"Fix {asset} by hand" in err
    assert "'fileId:' line set to 4242424242" in err


def test_a_stray_brace_line_after_the_result_does_not_displace_it(scenario, capsys):
    # The stream carries ck-workshop's stderr too, so a brace-leading
    # diagnostic printed after the result — native Steamworks logging during
    # Shutdown, say — must not be mistaken for the result and throw.
    code, asset = scenario(
        result_line(4242424242, created=False, success=True)
        + "\n{ Steamworks shutdown trace\n"
    )

    assert code == 0
    assert steam_identity.read_file_id(asset) == 4242424242
    assert "Workshop item 4242424242 (updated)" in capsys.readouterr().out


def test_a_later_json_object_without_a_fileId_does_not_displace_it(scenario):
    # Same hazard, one step subtler: valid JSON, wrong object.
    code, asset = scenario(
        result_line(4242424242, created=False, success=True)
        + "\n"
        + json.dumps({"progress": 100})
        + "\n"
    )

    assert code == 0
    assert steam_identity.read_file_id(asset) == 4242424242


# --- the parts upload.sh supplies -----------------------------------------


def test_the_bundle_fills_the_fields_only_the_sdk_window_reads(scenario):
    code, asset = scenario(result_line(4242424242, created=True, success=True) + "\n")

    assert code == 0
    text = asset.read_text()
    assert "modOwner: 10000000000000000" in text
    assert "selectedPath: /builds/DisableDurability" in text


def test_a_zero_mod_owner_leaves_the_stored_one_alone(scenario):
    # modOwner is 0 whenever Steam was not initialised. Writing that would
    # erase a value the SDK window needs and this run simply does not know.
    code, asset = scenario(
        result_line(4242424242, created=False, success=True, mod_owner=0) + "\n"
    )

    assert code == 0
    assert "modOwner: 10000000000000000" in asset.read_text()


# --- the asset this run brought into existence ----------------------------


needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


@needs_git
def test_an_asset_created_by_this_run_is_flagged_as_untracked(tmp_path, capsys):
    # The moment docs/publishing.md is actually about: "Commit it once, right
    # after the first Steam publish." check_prerequisites cannot cover this —
    # it ran before the file existed — so the warning has to happen here or
    # nowhere, and here the file holds a brand-new public item's only id.
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    asset = steam_identity.asset_path(tmp_path, MOD)
    asset.parent.mkdir(parents=True)
    result = tmp_path / "result.txt"
    result.write_text(result_line(4242424242, created=True, success=True) + "\n")

    code = steam_result.main(
        ["steam_result.py", str(result), str(tmp_path)],
        env={"MOD_NAME": MOD, "CK_STEAM_BUNDLE": BUNDLE},
    )

    assert code == 0
    assert steam_identity.read_file_id(asset) == 4242424242
    err = capsys.readouterr().err
    assert "not tracked by git" in err
    assert f"git add {asset}" in err


@needs_git
def test_an_asset_that_already_existed_is_not_flagged_again(tmp_path, capsys):
    # check_prerequisites already said it this run, before the mod.io release.
    # Saying it twice per publish is how it stops being read at all.
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    asset = steam_identity.asset_path(tmp_path, MOD)
    asset.parent.mkdir(parents=True)
    asset.write_text(ASSET)
    result = tmp_path / "result.txt"
    result.write_text(result_line(4242424242, created=False, success=True) + "\n")

    code = steam_result.main(
        ["steam_result.py", str(result), str(tmp_path)],
        env={"MOD_NAME": MOD, "CK_STEAM_BUNDLE": BUNDLE},
    )

    assert code == 0
    assert "not tracked by git" not in capsys.readouterr().err


def test_an_unreadable_result_file_reports_rather_than_traces(tmp_path, capsys):
    code = steam_result.main(
        ["steam_result.py", str(tmp_path / "absent.txt"), str(tmp_path)],
        env={"MOD_NAME": MOD},
    )

    # Non-zero, unlike branches 1-3: those establish that nothing was created,
    # while this one establishes nothing at all — the id may be sitting in a
    # file we could not open, and upload.sh keeps that file on a non-zero exit.
    assert code == 1
    assert "could not be read" in capsys.readouterr().err


def test_a_missing_mod_name_reports_rather_than_traces(tmp_path, capsys):
    result = tmp_path / "result.txt"
    result.write_text(result_line(42, created=True, success=True) + "\n")

    code = steam_result.main(["steam_result.py", str(result), str(tmp_path)], env={})

    assert code == 1
    assert "MOD_NAME" in capsys.readouterr().err


def test_wrong_arguments_report_rather_than_trace(capsys):
    assert steam_result.main(["steam_result.py"], env={}) == 1
    assert "usage:" in capsys.readouterr().err
