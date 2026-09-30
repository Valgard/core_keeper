"""Unit tests for the tag-only Workshop update driver.

The Steamworks call and the Web API read stay untested here, as they do for
every other Steam tool in this directory; what is pinned down is the decision
around them — what counts as a change, and what the CLI refuses.
"""

import io
import json

import pytest
import steam_retag


def test_identical_sets_need_no_submit():
    """Order is irrelevant to a tag set, so a reordering must not trigger a write."""
    assert steam_retag.tag_changes(
        ["1.3.0", "Library", "Script"], ["Script", "Library", "1.3.0"]
    ) == ([], [])


def test_case_alone_is_not_a_change():
    """Steam matches tags without case; a submit for a case difference changes nothing."""
    assert steam_retag.tag_changes(["Quality of Life"], ["quality of life"]) == ([], [])


def test_the_missing_version_tag_is_what_gets_added():
    """The defect this tool exists for: every category present, the version absent."""
    add, remove = steam_retag.tag_changes(
        ["1.3.0", "Visual", "Library", "Client", "Script"],
        ["Visual", "Library", "Client", "Script"],
    )
    assert add == ["1.3.0"]
    assert remove == []


def test_a_stale_value_is_reported_for_removal():
    """SetItemTags replaces the set, so a value no longer derived is dropped, and should be said."""
    _, remove = steam_retag.tag_changes(["1.3.0", "Script"], ["1.3.0", "Script", "Asset"])
    assert remove == ["Asset"]


def test_execute_needs_the_mods_named(capsys):
    """A write to every public item must not be one up-arrow away from a comparison run."""
    with pytest.raises(SystemExit):
        steam_retag.main(["steam_retag.py", "--execute"])
    assert "named explicitly" in capsys.readouterr().err


BUNDLE = {"fileId": 3791299348, "tags": ["1.3.0", "Library", "Script"]}


@pytest.fixture
def seams(monkeypatch):
    """Replace every seam that reaches outside the process, and record the calls.

    What is left under test is retag's own control flow: which arguments reach
    ck-workshop, whether verify runs, and which exit code comes back.
    """
    calls = {"ck": [], "verify": 0, "reports": 0}
    state = {"live": ["Library", "Script"], "ck_code": 0, "missing": []}

    monkeypatch.setattr(steam_retag, "direnv_env", lambda repo: {"MOD_NAME": "ModSettingsMenu"})
    monkeypatch.setattr(steam_retag.steam_bundle, "tag_bundle", lambda repo, env: dict(BUNDLE))
    monkeypatch.setattr(steam_retag, "live_tags", lambda file_id: list(state["live"]))

    def fake_ck(utils_dir, env, args, stdin, tee_to):
        calls["ck"].append(args)
        return state["ck_code"], ""

    def fake_verify(file_id, wanted):
        calls["verify"] += 1
        return state["missing"]

    def fake_report(file_id, wanted):
        calls["reports"] += 1

    monkeypatch.setattr(steam_retag, "run_ck_workshop", fake_ck)
    monkeypatch.setattr(steam_retag, "verify", fake_verify)
    monkeypatch.setattr(steam_retag, "report_after_failure", fake_report)
    return calls, state


def test_without_execute_nothing_is_sent(seams, tmp_path):
    """The overview runs this for every public item; a lost --dry-run would write to all of them."""
    calls, _ = seams
    assert steam_retag.retag(tmp_path, tmp_path, execute=False, named=True) == 0
    assert calls["ck"] == [["--tags-only", "--dry-run"]]
    assert calls["verify"] == 0


def test_execute_sends_and_verifies(seams, tmp_path):
    """The success line may only follow a read-back, never the tool's exit code alone."""
    calls, _ = seams
    assert steam_retag.retag(tmp_path, tmp_path, execute=True, named=True) == 0
    assert calls["ck"] == [["--tags-only"]]
    assert calls["verify"] == 1


def test_a_current_item_is_not_touched(seams, tmp_path):
    """Equal sets mean no submit at all, not a submit that changes nothing."""
    calls, state = seams
    state["live"] = ["script", "1.3.0", "Library"]
    assert steam_retag.retag(tmp_path, tmp_path, execute=True, named=True) == 0
    assert calls["ck"] == []


def test_a_tag_steam_did_not_keep_fails_the_mod(seams, tmp_path):
    """ck-workshop reports success for an update that lost a value; only the read-back sees it."""
    _, state = seams
    state["missing"] = ["1.3.0"]
    assert steam_retag.retag(tmp_path, tmp_path, execute=True, named=True) == 1


def test_a_failed_send_reports_what_the_item_now_carries(seams, tmp_path):
    """Exit 5 or 6 can come after Steam accepted the tags, so the item is read once more."""
    calls, state = seams
    state["ck_code"] = 6
    assert steam_retag.retag(tmp_path, tmp_path, execute=True, named=True) == 6
    assert calls["reports"] == 1
    assert calls["verify"] == 0


def test_an_unpublished_mod_is_skipped_only_in_the_overview(seams, monkeypatch, tmp_path):
    """Unnamed, a mod with no item is expected; named, its id has gone missing."""
    calls, _ = seams
    monkeypatch.setattr(steam_retag.steam_identity, "ensure_recognizable", lambda asset: None)
    monkeypatch.setattr(steam_retag.steam_identity, "read_file_id", lambda asset: None)
    assert steam_retag.retag(tmp_path, tmp_path, execute=False, named=False) == 0
    assert calls["ck"] == []


def test_verify_waits_out_a_lagging_read(monkeypatch):
    """A cached answer first, the updated one next: that is success, not a dropped tag."""
    answers = iter([["Library"], ["1.3.0", "Library"]])
    monkeypatch.setattr(steam_retag, "live_tags", lambda file_id: next(answers))
    monkeypatch.setattr(steam_retag.time, "sleep", lambda seconds: None)
    assert steam_retag.verify(1, ["1.3.0", "Library"]) == []


def test_verify_reports_what_stays_missing(monkeypatch):
    """Every attempt short of the tag: the missing value comes back, not an empty list."""
    monkeypatch.setattr(steam_retag, "live_tags", lambda file_id: ["Library"])
    monkeypatch.setattr(steam_retag.time, "sleep", lambda seconds: None)
    assert steam_retag.verify(1, ["1.3.0", "Library"]) == ["1.3.0"]


def test_verify_never_turns_unreadable_into_confirmed(monkeypatch):
    """No successful read means unknown, and the empty list means confirmed."""

    def unreachable(file_id):
        raise OSError("no route")

    monkeypatch.setattr(steam_retag, "live_tags", unreachable)
    monkeypatch.setattr(steam_retag.time, "sleep", lambda seconds: None)
    with pytest.raises(OSError):
        steam_retag.verify(1, ["1.3.0"])


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"response": {}},
        {"response": {"publishedfiledetails": []}},
        {"response": {"publishedfiledetails": [{"result": 9}]}},
    ],
)
def test_an_unusable_web_api_answer_is_a_value_error(monkeypatch, payload):
    """main() catches ValueError per mod; anything else would stop the remaining mods."""
    monkeypatch.setattr(
        steam_retag.urllib.request,
        "urlopen",
        lambda *a, **k: _Response(json.dumps(payload).encode()),
    )
    with pytest.raises(ValueError):
        steam_retag.live_tags(1)


def test_an_item_without_tags_reads_as_none(monkeypatch):
    """The API omits the key for an untagged item; that is an empty set, not an error."""
    payload = {"response": {"publishedfiledetails": [{"result": 1}]}}
    monkeypatch.setattr(
        steam_retag.urllib.request,
        "urlopen",
        lambda *a, **k: _Response(json.dumps(payload).encode()),
    )
    assert steam_retag.live_tags(1) == []


def test_one_failing_mod_does_not_stop_the_rest(monkeypatch, tmp_path):
    """The first failure's code is reported, and every named mod is still attempted."""
    seen = []

    def fake_retag(repo, utils_dir, execute, named):
        seen.append(repo.name)
        if repo.name == "a":
            raise ValueError("broken")
        return 0

    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    monkeypatch.setattr(steam_retag, "retag", fake_retag)
    assert steam_retag.main(["steam_retag.py", str(tmp_path / "a"), str(tmp_path / "b")]) == 1
    assert seen == ["a", "b"]
