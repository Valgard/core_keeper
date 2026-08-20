"""Unit tests for the version-list refresh report.

Only the comparing is tested; fetching is a thin wrapper nobody can assert
against without a network. That is also where the value is: the report exists
because neither feed can be trusted on its own, and the rules for saying so are
the part that can be wrong.
"""

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
    report = rg.compare(
        known=["0.7.4.0"], steam={"0.7.4": "2024-03-08"}, modio=["0.7.4"]
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
    """Steam titles are three-segment as often as four, and `missing` holds the
    padded spelling. Looking the date up by the raw key silently reported every
    such build as mod.io-only — losing the release date, which is the one thing
    that resolves a mistyped title."""
    report = rg.compare(known=[], steam={"0.7.4": "2024-03-08"}, modio=[])

    assert report.dates["0.7.4.0"] == "2024-03-08"
