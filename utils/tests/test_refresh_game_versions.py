"""Unit tests for the version-list refresh report.

Only the comparing is tested; fetching is a thin wrapper nobody can assert
against without a network. That is also where the value is: the report exists
because neither feed can be trusted on its own, and the rules for saying so are
the part that can be wrong.
"""

import pytest

import refresh_game_versions as rg


def test_a_build_only_steam_knows_is_reported_as_missing():
    report = rg.compare(known=["1.2.1.5"], steam={"1.2.1.6": "2026-07-01"}, modio=[])

    assert "1.2.1.6" in report.missing


def test_a_build_only_modio_knows_is_reported_too():
    """Steam drops day-one hotfixes that never got their own post, so mod.io is
    not merely a cross-check -- it contributes builds of its own."""
    report = rg.compare(known=["1.2.1.5"], steam={}, modio=["1.1.0.1"])

    assert "1.1.0.1" in report.missing


def test_spellings_that_differ_only_in_padding_are_the_same_build():
    """Steam titles it `0.7.4.0`, mod.io tags it `0.7.4` — the same build."""
    report = rg.compare(
        known=["0.7.4.0"], steam={"0.7.4.0": "2024-03-08"}, modio=["0.7.4"]
    )

    assert not report.missing


def test_a_version_in_two_far_apart_entries_is_flagged_as_a_suspected_typo():
    """`Hotfix 0.7.5.1` appears twice: 2024-03-11, between 0.7.4.0 and 0.7.4.2,
    and 2024-06-05 where it belongs. The first is a mistyped 0.7.4.1, and no
    rule short of reading the dates can tell -- so it is reported, not fixed."""
    report = rg.compare(
        known=[],
        steam={},
        modio=[],
        duplicates={"0.7.5.1": ["2024-03-11", "2024-06-05"]},
    )

    assert "0.7.5.1" in report.suspects


def test_a_list_that_matches_both_feeds_reports_nothing():
    report = rg.compare(
        known=["1.2.1.5"], steam={"1.2.1.5": "2026-06-08"}, modio=["1.2.1.5"]
    )

    assert not report.missing and not report.suspects


def test_a_missing_build_keeps_the_date_steam_gave_it():
    """`missing` holds the padded spelling while `steam` is keyed by the raw
    title, and either side can be the short one — mod.io writes `0.7.4`, Steam
    writes `0.7.5` for what the list calls `0.7.5.0`. Looking the date up by the
    raw key reported such builds as mod.io-only, losing the release date, which
    is the one thing that resolves a mistyped title."""
    report = rg.compare(known=[], steam={"0.7.5": "2024-06-05"}, modio=[])

    assert report.dates["0.7.5.0"] == "2024-06-05"


def _event(gid, name, day, kind=rg.EVENT_SMALL_UPDATE):
    """One store event, with the two fields the parser reads."""
    import datetime

    stamp = int(
        datetime.datetime.fromisoformat(day)
        .replace(tzinfo=datetime.timezone.utc)
        .timestamp()
    )
    return {
        "gid": gid,
        "event_name": name,
        "event_type": kind,
        "rtime32_start_time": stamp,
    }


def test_major_updates_are_parsed_too_not_only_small_ones():
    """The reason this module reads store events instead of GetNewsForApp: the
    news API tags small updates and leaves major ones untagged, so filtering it
    by tags=patchnotes drops every major release -- 1.2.0.3 among them."""
    versions, _ = rg.parse_events(
        [
            _event(
                1,
                "1.2.0.3 Major Update - Void & Voltage",
                "2026-02-25",
                rg.EVENT_MAJOR_UPDATE,
            )
        ]
    )

    assert "1.2.0.3" in versions


def test_events_that_are_not_updates_are_ignored():
    versions, _ = rg.parse_events(
        [_event(1, "Core Keeper 2026 Roadmap: 1.3 and beyond", "2026-01-01", 28)]
    )

    assert versions == {}


def test_the_same_version_on_two_days_is_recorded_as_a_duplicate():
    events = [
        _event(1, "Hotfix 0.7.5.1", "2024-03-11"),
        _event(2, "Hotfix 0.7.5.1", "2024-06-05"),
    ]

    versions, duplicates = rg.parse_events(events)

    assert duplicates["0.7.5.1"] == ["2024-03-11", "2024-06-05"]
    assert versions["0.7.5.1"] == "2024-03-11", "the earliest sighting wins"


def test_a_bare_two_segment_number_in_a_title_is_not_a_version():
    """'1.3 and beyond' or 'we fixed 3.2 million bugs' must not become builds."""
    versions, _ = rg.parse_events([_event(1, "Patch 1.3 is live", "2026-01-01")])

    assert versions == {}


def test_a_mod_io_answer_without_the_version_group_is_an_error_not_an_empty_list():
    """An expired game key answers with a well-formed JSON error object, which
    has no tag_options — returning [] for that reported 'mod.io knows no
    versions', and the run then ended with 'both feeds agree'."""
    with pytest.raises(RuntimeError, match="Game Version"):
        rg.version_tags({"error": {"code": 401, "message": "api key not found"}})


def test_the_version_group_is_read_when_it_is_there():
    game = {
        "tag_options": [
            {"name": "Type", "tags": ["Visual"]},
            {"name": "Game Version", "tags": ["1.2.1.5", "not-a-version"]},
        ]
    }

    assert rg.version_tags(game) == ["1.2.1.5"]
