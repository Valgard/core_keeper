"""Unit tests for mirroring a mod.io release history into a Workshop history.

Every decision here is made once and then cannot be taken back: the Workshop's
change history is append-only to every API, so a version submitted twice, or
submitted out of order, is corrected only by a human in a web form, one entry at
a time. That is why the tests below are about refusals — what the tool declines
to guess — far more than about what it produces.
"""

import json
import pathlib
import re

import pytest
import steam_backfill

MODFILE_A = {
    "id": 100,
    "version": "1.0.0",
    "date_added": 1000,
    "filesize": 4096,
    "changelog": "### Added\n- The first thing.",
    "filehash": {"md5": "aaa"},
    "download": {"binary_url": "https://example.invalid/files/100/download"},
}
MODFILE_B = {
    "id": 101,
    "version": "1.1.0",
    "date_added": 2000,
    "filesize": 8192,
    "changelog": "### Added\n- The second thing.",
    "filehash": {"md5": "bbb"},
    "download": {"binary_url": "https://example.invalid/files/101/download"},
}

ENTRIES = [
    ("1.1.0", "### Added\n- The second thing."),
    ("1.0.0", "### Added\n- The first thing."),
]


def _item(metadata, *, title="Some Mod", owner=76561197970776512):
    """What ck-workshop --read-item prints for a live item we own."""
    return {
        "fileId": 42,
        "result": "OK",
        "title": title,
        "owner": owner,
        "metadata": metadata,
        "metadataQueried": True,
    }


# --- pairing a modfile with the notes that belong to it ----------------------


def test_releases_come_back_oldest_first():
    """pair_releases reorders mod.io's newest-first listing to oldest-first.

    The order the submits happen in IS the order of the permanent
    history, so this is the one place that ordering can go wrong.
    """
    releases = steam_backfill.pair_releases([MODFILE_B, MODFILE_A], ENTRIES)

    assert [release.version for release in releases] == ["1.0.0", "1.1.0"]
    assert [release.modfile for release in releases] == [100, 101]


def test_each_release_carries_its_own_notes_not_the_newest():
    """Each release is paired with its own changelog entry, not with the newest one in the list."""
    releases = steam_backfill.pair_releases([MODFILE_A, MODFILE_B], ENTRIES)

    assert releases[0].changelog == "### Added\n- The first thing."
    assert releases[1].changelog == "### Added\n- The second thing."


def test_a_modfile_with_no_changelog_entry_is_refused():
    """A modfile with no matching CHANGELOG.md entry is refused.

    It never falls back to mod.io's own stored text — that field comes
    back HTML-escaped, and a fallback would ship escaped markup into a
    note no API can later edit.
    """
    with pytest.raises(ValueError, match=re.escape("1.1.0")):
        steam_backfill.pair_releases([MODFILE_A, MODFILE_B], ENTRIES[1:])


def test_a_changelog_entry_with_no_modfile_is_reported_not_submitted():
    """A changelog entry with no matching modfile is reported as unpublished.

    The two real cases: a version tagged locally before the mod existed
    on mod.io, and one written up but never released. Neither can become
    a history entry, but silence would read as a bug.
    """
    entries = [("2.0.0", "Unreleased."), *ENTRIES]

    releases = steam_backfill.pair_releases([MODFILE_A, MODFILE_B], entries)
    unpublished = steam_backfill.unpublished_versions([MODFILE_A, MODFILE_B], entries)

    assert [release.version for release in releases] == ["1.0.0", "1.1.0"]
    assert unpublished == ["2.0.0"]


def test_ties_on_date_are_broken_by_modfile_id():
    """Two modfiles with the same date_added are ordered by modfile id, not by listing order.

    Otherwise the resulting history order — which is not correctable
    through any API — would depend on whatever order the listing happened
    to return.
    """
    same = dict(MODFILE_B, date_added=MODFILE_A["date_added"])

    releases = steam_backfill.pair_releases([same, MODFILE_A], ENTRIES)

    assert [release.modfile for release in releases] == [100, 101]


# --- the progress record on the item -----------------------------------------


def test_the_record_round_trips():
    """The progress record round-trips through render_metadata and parse_metadata without loss."""
    releases = steam_backfill.pair_releases([MODFILE_A, MODFILE_B], ENTRIES)

    raw = steam_backfill.render_metadata(releases)

    assert steam_backfill.parse_metadata(raw) == [
        {"version": "1.0.0", "modfile": 100},
        {"version": "1.1.0", "modfile": 101},
    ]


def test_the_record_stays_well_under_steams_limit():
    """Even the family's longest history (16 versions) stays well under Steam's metadata limit.

    ck-workshop refuses a longer string rather than truncating it — a
    truncated record does not parse, and an unparseable record reads
    back as "unknown".
    """
    releases = [
        steam_backfill.Release(
            version=f"1.3.{n}",
            modfile=8000000 + n,
            date_added=n,
            size=0,
            md5="",
            url="",
            changelog="",
            modio_changelog="",
        )
        for n in range(16)
    ]

    assert len(steam_backfill.render_metadata(releases).encode()) < 1000


@pytest.mark.parametrize(
    "raw",
    [
        None,  # the query did not ask, or GetQueryUGCMetadata failed
        "",  # asked, and the item carries nothing
        "not json",
        "[]",  # JSON, but not an object
        json.dumps({"submitted": []}),  # no schema
        json.dumps({"schema": 1}),  # no submitted list
        json.dumps({"schema": 1, "submitted": [{"version": "1.0.0"}]}),  # no modfile
    ],
)
def test_anything_that_is_not_our_record_reads_as_unknown(raw):
    """Every unrecognisable shape of metadata reads as unknown, never as "nothing submitted yet".

    That distinction is a duplicated history entry per already-published
    version.
    """
    assert steam_backfill.parse_metadata(raw) is None


def test_a_newer_record_is_refused_rather_than_read_as_unknown():
    """A record with a schema newer than this tool understands is refused, not read as unknown.

    Reading it as unknown would lead to a re-submit that overwrites the
    newer record with an older tool's idea of what has been done.
    """
    raw = json.dumps({"schema": steam_backfill.SCHEMA + 1, "submitted": []})

    with pytest.raises(ValueError, match="newer"):
        steam_backfill.parse_metadata(raw)


# --- deciding what has already been submitted --------------------------------


def _releases():
    return steam_backfill.pair_releases([MODFILE_A, MODFILE_B], ENTRIES)


def test_no_workshop_item_means_nothing_has_been_submitted():
    """No Workshop item at all means nothing has been submitted yet.

    resume_state returns the empty set rather than erroring.
    """
    assert steam_backfill.resume_state(None, None, None, _releases()) == set()


def test_an_items_own_record_decides_what_is_done():
    """When the item carries its own progress record, that record decides what is done.

    Not an operator guess.
    """
    releases = _releases()
    raw = steam_backfill.render_metadata(releases[:1])

    assert steam_backfill.resume_state(42, _item(raw), None, releases) == {100}


def test_an_existing_item_with_no_record_is_refused():
    """An item that already exists but carries no progress record is refused, not assumed empty.

    It exists, so something submitted to it — the SDK window, an
    ordinary upload.sh publish, or a first backfill submit that failed
    after creating the item — and guessing "none" would duplicate every
    entry already there.
    """
    releases = _releases()

    with pytest.raises(ValueError, match="--assume-submitted"):
        steam_backfill.resume_state(42, _item(""), None, releases)


def test_the_operator_can_state_what_the_history_already_holds():
    """The operator's --assume-submitted list is accepted as the resume state.

    Only when the item has no record of its own.
    """
    releases = _releases()

    state = steam_backfill.resume_state(42, _item(""), ["1.0.0"], releases)

    assert state == {100}


def test_an_empty_assumption_is_a_statement_not_a_missing_one():
    """An empty --assume-submitted list states "the item's history is genuinely empty".

    A create that failed during the upload leaves exactly that state,
    and it must not be read as though the operator had not answered at
    all.
    """
    releases = _releases()

    assert steam_backfill.resume_state(42, _item(""), [], releases) == set()


def test_an_assumption_about_a_version_that_was_never_published_is_refused():
    """An --assume-submitted version that names no real release is refused.

    Not silently accepted.
    """
    releases = _releases()

    with pytest.raises(ValueError, match=re.escape("9.9.9")):
        steam_backfill.resume_state(42, _item(""), ["9.9.9"], releases)


def test_assuming_anything_without_an_item_is_refused():
    """An --assume-submitted list is refused when no Workshop item exists at all.

    Nothing can have been submitted to an item that is not there — taken
    at face value the assumption would skip versions that are genuinely
    missing.
    """
    with pytest.raises(ValueError, match="no Workshop item"):
        steam_backfill.resume_state(None, None, ["1.0.0"], _releases())


def test_a_read_that_did_not_ask_for_metadata_is_refused():
    """A read that never asked for metadata at all is refused.

    This is the documented Item.GetAsync trap: its null would otherwise
    read as "nothing recorded" for an item that has plenty recorded.
    """
    item = _item(None)
    del item["metadataQueried"]

    with pytest.raises(ValueError, match="metadata"):
        steam_backfill.resume_state(42, item, None, _releases())


def test_a_placeholder_response_is_refused():
    """A placeholder response (empty title, owner 0) is refused.

    Its null metadata measures a bulk query page's stand-in shape, not
    the actual item.
    """
    with pytest.raises(ValueError, match="placeholder"):
        steam_backfill.resume_state(42, _item("", title=""), None, _releases())


def test_an_unreadable_item_is_refused():
    """An item that could not be read at all is refused with its own message.

    Not conflated with a real item that simply carries no record.
    """
    with pytest.raises(ValueError, match="could not be read"):
        steam_backfill.resume_state(42, None, None, _releases())


# --- what is left to do ------------------------------------------------------


def test_pending_keeps_order_and_skips_what_is_recorded():
    """pending() keeps the releases' original submit order.

    It skips only the modfiles already recorded as done.
    """
    releases = _releases()

    assert steam_backfill.pending(releases, {100}) == releases[1:]


def test_pending_matches_on_modfile_id_not_on_version():
    """pending() matches done modfiles by id, not by version string.

    Two modfiles can share a version (a re-upload after a failed build),
    and keying on the version would skip the second as though it had
    already been submitted.
    """
    twin = dict(MODFILE_B, id=102, version="1.0.0", date_added=3000)
    releases = steam_backfill.pair_releases([MODFILE_A, MODFILE_B, twin], ENTRIES)

    assert [r.modfile for r in steam_backfill.pending(releases, {100})] == [101, 102]


def test_a_recorded_modfile_that_is_not_in_the_plan_is_reported():
    """A modfile the record claims is done but mod.io no longer lists is reported as unexpected.

    It changes nothing about what is left to submit, but the
    disagreement between record and listing (e.g. a deleted modfile) is
    worth surfacing rather than silently absorbing.
    """
    releases = _releases()

    assert steam_backfill.unexpected(releases, {100, 999}) == [999]


# --- how the two changelog texts differ, and why the repository wins ---------


def test_a_divergence_that_is_only_modio_escaping_is_named_as_such():
    """A divergence that disappears once mod.io's HTML escaping is undone is named as escaping only.

    Not as a real edit.
    """
    release = steam_backfill.Release(
        version="1.0.0",
        modfile=100,
        date_added=0,
        size=0,
        md5="",
        url="",
        changelog="Options -> Mod Settings & more",
        modio_changelog="Options -&gt; Mod Settings &amp; more",
    )

    assert steam_backfill.divergence(release) == "mod.io's HTML escaping only"


def test_a_real_edit_since_publishing_is_named_as_such():
    """A divergence that survives HTML-unescaping is named as a real edit.

    Not brushed aside as encoding noise.
    """
    release = steam_backfill.Release(
        version="1.0.0",
        modfile=100,
        date_added=0,
        size=0,
        md5="",
        url="",
        changelog="Shorter now.",
        modio_changelog="Longer, with a section that has since been dropped.",
    )

    assert steam_backfill.divergence(release) == "edited in the repository since"


def test_identical_texts_do_not_diverge():
    """Two identical changelog texts report no divergence.

    Not a false positive from the comparison logic.
    """
    release = steam_backfill.Release(
        version="1.0.0",
        modfile=100,
        date_added=0,
        size=0,
        md5="",
        url="",
        changelog="Same.",
        modio_changelog="Same.",
    )

    assert steam_backfill.divergence(release) is None


# --- the download URL --------------------------------------------------------


def test_the_game_key_is_appended_to_a_url_that_has_no_query():
    """The game key is appended with a leading `?`.

    The target URL has no query string yet.
    """
    assert (
        steam_backfill.download_url("https://x.invalid/download", "KEY")
        == "https://x.invalid/download?api_key=KEY"
    )


def test_the_game_key_joins_a_url_that_already_has_a_query():
    """The game key is joined with `&`, not `?`.

    The target URL already carries a query string.
    """
    assert (
        steam_backfill.download_url("https://x.invalid/download?a=1", "KEY")
        == "https://x.invalid/download?a=1&api_key=KEY"
    )


# --- the plan listing --------------------------------------------------------


def test_the_plan_shows_the_bbcode_note_that_will_be_submitted(capsys):
    """What the operator reads before an irreversible run is what goes out.

    A listing that showed the Markdown source would hide exactly the class of
    mistake a rehearsal exists to catch — and did: both publishing paths sent
    Markdown to a platform that renders BBCode, and every rehearsal of them
    looked right.
    """
    plan = steam_backfill.ModPlan(
        repo=pathlib.Path("/nowhere/some-mod"),
        mod_name="SomeMod",
        mod_id=1,
        env={},
        releases=_releases(),
        unpublished=[],
        file_id=None,
        done=set(),
        todo=_releases(),
    )

    steam_backfill.report(plan, None, brief=False)
    printed = capsys.readouterr().out

    assert "       | [h2]1.0.0[/h2]" in printed
    assert "       | [list]" in printed
    assert "- The first thing." not in printed
