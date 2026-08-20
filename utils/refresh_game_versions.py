"""Compare `ck-game-versions.json` against Steam and mod.io, and report.

Reports, never writes. The titles both feeds are built from are typed by hand
and contain errors — `Hotfix 0.7.5.1` was posted on 2024-03-11 between 0.7.4.0
and 0.7.4.2, where only the date says it is a mistyped 0.7.4.1. Resolving that
took a second source and a look at the calendar; a script that wrote the file
would have invented a build and hidden a real one.

Neither feed is complete on its own, in different ways:

  * Steam's update feed misses builds that shipped without their own post —
    0.7.4.1, 0.7.5.4, 1.0.0.1 and 1.1.0.1, three of them the `.1` right after
    a `.0` release, i.e. day-one hotfixes folded into the launch notes.
  * mod.io's Game Version tags miss builds nobody tagged (1.0.0.7, 1.0.0.12,
    1.2.1.2) and start at 0.6.3.0, the build the Mod SDK shipped with.

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

VERSION_IN_TITLE = re.compile(r"\b(\d+\.\d+(?:\.\d+){1,3})\b")

# A build seen in two entries more than this far apart is not a repost.
TYPO_GAP_DAYS = 30


@dataclass
class Report:
    missing: list = field(default_factory=list)
    suspects: list = field(default_factory=list)


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
    done = subprocess.run(
        ["/usr/bin/curl", "-sS", url], capture_output=True, text=True, check=True
    )
    return json.loads(done.stdout)


def fetch_steam_updates():
    """{version: iso-date} and {version: [dates]} from the store's update feed."""
    events, offset = {}, 0
    while True:
        page = _get(STEAM_EVENTS_URL + str(offset)).get("events") or []
        if not page:
            break
        for event in page:
            events[event.get("gid")] = event
        offset += 50

    versions, seen_at = {}, {}
    for event in events.values():
        if event.get("event_type") not in (EVENT_SMALL_UPDATE, EVENT_MAJOR_UPDATE):
            continue
        # UTC explicitly: a local-time conversion moves a release across the
        # date line for anyone in the wrong zone, and these dates are compared.
        day = (
            datetime.datetime.fromtimestamp(
                event.get("rtime32_start_time", 0), tz=datetime.UTC
            )
            .date()
            .isoformat()
        )
        for version in VERSION_IN_TITLE.findall(event["event_name"]):
            seen_at.setdefault(version, []).append(day)
            if version not in versions or day < versions[version]:
                versions[version] = day
    duplicates = {v: d for v, d in seen_at.items() if len(d) > 1}
    return versions, duplicates


def fetch_modio_tags(game_key):
    game = _get(MODIO_GAME_URL + urllib.parse.quote(game_key))
    for group in game.get("tag_options", []):
        if group.get("name") == "Game Version":
            return [t for t in group["tags"] if re.fullmatch(r"\d+(\.\d+)+", t)]
    return []


def read_game_key():
    """The read-only mod.io game key, from the SDK clone rather than inlined."""
    sdk = os.environ.get("SDK_PATH")
    if not sdk:
        sys.exit("SDK_PATH is not set — source the mod's .envrc first")
    config = pathlib.Path(sdk) / "Assets/Resources/mod.io/config.asset"
    match = re.search(
        r"gameKey:\s*(\S+)", config.read_text() if config.is_file() else ""
    )
    if not match:
        sys.exit(f"no gameKey in {config}")
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
            print(f"  {version:10} {steam.get(version, 'mod.io tag only')}")
    if report.suspects:
        print("\nSame version in entries far apart — check for a mistyped title:")
        for version in report.suspects:
            print(f"  {version:10} {', '.join(duplicates[version])}")
    if not report.missing and not report.suspects:
        print(f"{len(doc['versions'])} versions, both feeds agree.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
