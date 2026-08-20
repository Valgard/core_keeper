"""Compare `ck-game-versions.json` against Steam and mod.io, and report.

Reports, never writes. The titles both feeds are built from are typed by hand
and contain errors — `Hotfix 0.7.5.1` was posted on 2024-03-11 between 0.7.4.0
and 0.7.4.2, where only the date says it is a mistyped 0.7.4.1. Resolving that
took a second source and a look at the calendar; a script that wrote the file
would have invented a build and hidden a real one.

Neither feed is complete on its own, in different ways:

  * Steam's update feed misses 0.7.5.4, 1.0.0.1 and 1.1.0.1 — builds that
    shipped without their own post, two of them the `.1` right after a `.0`
    release, i.e. day-one hotfixes folded into the launch notes. It misses
    0.7.4.1 for a different reason: its post exists, mistyped, as above.
  * mod.io's Game Version tags miss the builds named in
    CK_MODIO_VERSION_UNLISTED — the parent `.envrc.example` is where that list
    is kept, and the only place the numbers are written down — and start at
    0.6.3.0, the build the Mod SDK shipped with.

Usage:
    python3 utils/refresh_game_versions.py
"""

import datetime
import json
import os
import pathlib
import re
import subprocess
import sys
import urllib.parse
from dataclasses import dataclass, field

# Store events rather than the news API: `GetNewsForApp` reports major updates
# with no tag at all, so filtering it by `tags=patchnotes` silently drops every
# major release (1.2.0.3 "Void & Voltage" among them). The event types are the
# same split the store page's `?updates=true` filter uses.
STEAM_APP_ID = 1621690
EVENT_SMALL_UPDATE = 12
EVENT_MAJOR_UPDATE = 14

# English, pinned: the localised titles carry *different version numbers*, not
# just translated words. The German feed calls 0.7.3.1 "0.7.3" and 0.4.6
# "0.4.5" — parsing whatever language the environment happens to ask for would
# make the result depend on who ran it.
STEAM_EVENTS_URL = (
    "https://store.steampowered.com/events/ajaxgetpartnereventspageable/"
    f"?clan_accountid=0&appid={STEAM_APP_ID}&l=english&count=50&offset="
)

MODIO_GAME_URL = "https://g-5289.modapi.io/v1/games/5289?api_key="
TAG_GROUP_GAME_VERSION = "Game Version"

VERSION_IN_TITLE = re.compile(r"\b(\d+\.\d+(?:\.\d+){1,3})\b")

# The feed is a few hundred events; this only bounds a runaway loop.
MAX_PAGES = 40

# A build seen in two entries more than this far apart is not one release
# announced twice. Steam's archive is immutable, so 0.7.5.1 is reported on
# every run, forever — a *second* suspect is the signal, not the first.
TYPO_GAP_DAYS = 30  # 0.7.5.1's real gap is 86 days; same-day pairs are two
# releases sharing a number (0.7.3, 2024-01-31), not a mistake.


@dataclass
class Report:
    missing: list = field(default_factory=list)
    suspects: list = field(default_factory=list)
    # Keyed by the canonical spelling, because `missing` is: Steam writes
    # `0.7.4` where the list writes `0.7.4.0`, and a lookup by the raw title
    # silently reported every three-segment build as mod.io-only.
    dates: dict = field(default_factory=dict)


def norm(version):
    """Canonical form: at least four segments, compared as integers."""
    parts = [int(x) for x in version.split(".")]
    while len(parts) < 4:
        parts.append(0)
    return tuple(parts)


def fmt(parts):
    return ".".join(str(x) for x in parts)


def compare(known, steam, modio, duplicates=None):
    """What the file does not have, and what neither feed can decide."""
    have = {norm(v) for v in known}
    seen = {norm(v) for v in list(steam) + list(modio)}

    report = Report()
    report.missing = [fmt(v) for v in sorted(seen - have)]
    report.dates = {fmt(norm(v)): day for v, day in steam.items()}
    for version, dates in sorted((duplicates or {}).items()):
        if _spread_days(dates) > TYPO_GAP_DAYS:
            report.suspects.append(version)
    return report


def _spread_days(dates):
    parsed = sorted(datetime.date.fromisoformat(d) for d in dates)
    return (parsed[-1] - parsed[0]).days


def _get(url):
    """Fetch via system curl.

    The per-app firewall on this machine blocks Python's own sockets (urllib
    gets a 403 that looks like the server's) and Homebrew's curl, so
    /usr/bin/curl is the one client that reaches out.
    """
    # --fail-with-body, because plain `curl -sS` exits 0 on every HTTP status and
    # hands the error body to json.loads. Both APIs answer errors with
    # well-formed JSON, so the parse succeeds and the failure arrives disguised
    # as data: an empty tag list, an empty first page.
    done = subprocess.run(
        ["/usr/bin/curl", "-sS", "--fail-with-body", "--max-time", "30", url],
        capture_output=True,
        text=True,
        check=False,  # the status is read below, with the body in the message
    )
    if done.returncode != 0:
        raise RuntimeError(
            f"curl exit {done.returncode} for {url}: "
            f"{done.stderr.strip() or done.stdout[:200]}"
        )
    return json.loads(done.stdout)


def fetch_steam_updates():
    """{version: earliest date} and {version: [dates]} from the store's updates."""
    events, offset = {}, 0
    for _ in range(MAX_PAGES):
        page = _get(STEAM_EVENTS_URL + str(offset)).get("events") or []
        if not page:
            break
        before = len(events)
        for event in page:
            gid = event.get("gid")
            if not gid:
                raise RuntimeError(
                    f"Steam event without a gid at offset {offset}: "
                    f"{event.get('event_name')!r}"
                )
            events[gid] = event
        # The dict is keyed by gid so overlapping pages are harmless -- which is
        # also what would make a feed that ignores `offset` invisible: the loop
        # would run forever while the result stopped growing.
        if len(events) == before:
            raise RuntimeError(
                f"offset={offset} returned {len(page)} events, all already seen — "
                "the feed is ignoring the offset parameter"
            )
        offset += 50
    else:
        raise RuntimeError(
            f"stopped after {MAX_PAGES} pages ({len(events)} events) without "
            "reaching the end of the feed"
        )
    if not events:
        raise RuntimeError(
            "Steam's update feed returned nothing at all — an HTTP error answers "
            "like this too, and an empty first page is indistinguishable from the "
            "end of the feed"
        )
    return parse_events(events.values())


def parse_events(events):
    """({version: earliest date}, {version: [dates]}) from store events.

    Split out of the fetching so the two rules that carry the module can be
    tested: which event types count as an update -- the reason this reads store
    events rather than the news API at all -- and what makes a repeated version
    a duplicate.
    """
    versions, seen_at = {}, {}
    for event in events:
        if event.get("event_type") not in (EVENT_SMALL_UPDATE, EVENT_MAJOR_UPDATE):
            continue
        stamp = event.get("rtime32_start_time")
        if not stamp:
            # Defaulting to 0 would date the event to 1970; because the earliest
            # sighting wins, that fabricated date would beat the real one and
            # then surface as a "mistyped title" suspect -- a script built to
            # find hand-typed errors manufacturing one of its own.
            print(
                f"  ! skipping {event.get('event_name', '?')!r}: no release date",
                file=sys.stderr,
            )
            continue
        # UTC explicitly: a local-time conversion moves a release across the
        # date line for anyone in the wrong zone, and these dates are compared.
        day = datetime.datetime.fromtimestamp(stamp, tz=datetime.UTC).date().isoformat()
        for version in VERSION_IN_TITLE.findall(event.get("event_name", "")):
            seen_at.setdefault(version, []).append(day)
            if version not in versions or day < versions[version]:
                versions[version] = day
    duplicates = {v: sorted(set(d)) for v, d in seen_at.items() if len(set(d)) > 1}
    return versions, duplicates


def fetch_modio_tags(game_key):
    return version_tags(_get(MODIO_GAME_URL + urllib.parse.quote(game_key)))


def version_tags(game):
    """The Game Version vocabulary, or an error naming what came back instead."""
    groups = {g.get("name") for g in game.get("tag_options", [])}
    if TAG_GROUP_GAME_VERSION not in groups:
        raise RuntimeError(
            f"mod.io returned no '{TAG_GROUP_GAME_VERSION}' tag group "
            f"(got {sorted(g for g in groups if g)}) — an expired gameKey answers "
            "like this too; check Assets/Resources/mod.io/config.asset"
        )
    for group in game["tag_options"]:
        if group.get("name") == TAG_GROUP_GAME_VERSION:
            return [t for t in group.get("tags", []) if re.fullmatch(r"\d+(\.\d+)+", t)]
    return []


def read_game_key():
    """The read-only mod.io game key, from the SDK clone rather than inlined."""
    sdk = os.environ.get("SDK_PATH")
    if not sdk:
        sys.exit("SDK_PATH is not set — source the mod's .envrc first")
    config = pathlib.Path(sdk) / "Assets/Resources/mod.io/config.asset"
    text = config.read_text() if config.is_file() else ""
    # [ \t] rather than \s: `\s*` spans newlines, so a blank `gameKey:` captured
    # the next YAML key ("serverURL:") and the not-found guard never fired.
    match = re.search(r"gameKey:[ \t]*([A-Za-z0-9]{8,})[ \t]*$", text, re.MULTILINE)
    if not match:
        sys.exit(
            f"gameKey in {config} is empty or malformed"
            if "gameKey:" in text
            else f"no gameKey field in {config}"
        )
    return match.group(1)


def main():
    path = pathlib.Path(__file__).with_name("ck-game-versions.json")
    doc = json.loads(path.read_text())
    steam, duplicates = fetch_steam_updates()
    modio = fetch_modio_tags(read_game_key())

    # Below the SDK build nothing can carry a mod, so a "missing" one there is
    # noise -- the file starts at 0.6.3.0 for the same reason.
    floor = min(norm(v) for v in doc["versions"])
    steam = {v: d for v, d in steam.items() if norm(v) >= floor}
    modio = [v for v in modio if norm(v) >= floor]

    report = compare(doc["versions"], steam, modio, duplicates)
    if report.missing:
        print("Not in ck-game-versions.json:")
        for version in report.missing:
            print(f"  {version:10} {report.dates.get(version, 'mod.io tag only')}")
    if report.suspects:
        print("\nSame version in entries far apart — check for a mistyped title:")
        for version in report.suspects:
            print(f"  {version:10} {', '.join(duplicates[version])}")
    if not report.missing and not report.suspects:
        print(f"{len(doc['versions'])} versions, both feeds agree.")
        return 0
    # Non-zero so the report can gate something; the findings are printed
    # either way.
    return 1


if __name__ == "__main__":
    sys.exit(main())
