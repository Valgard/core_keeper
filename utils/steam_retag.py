#!/usr/bin/env python3
"""Set the tags on this family's Steam Workshop items, and change nothing else.

**Why tags need a path of their own.** The game's `SteamWorkshopLoader` judges a
subscribed item's compatibility by its tags, exactly as the mod.io loader does
by a profile's (`steam_bundle.version_tags`). A wrong tag set is therefore not
cosmetic: an item without a version tag is refused in every game build. Fixing
that through `utils/upload.sh --steam-only` would upload a build nobody asked
to ship and append a change-history entry no API can remove. This sends
`SetItemTags` alone, through `ck-workshop --tags-only`.

**The tag set is derived, never typed.** `steam_bundle.tag_bundle` uses the
function a publish uses, so a retag and the next release send the same set.
It is sent whole — SetItemTags replaces rather than adds — which is also what
removes a stale value.

**Verification reads the public Web API, not the tool's success code.** Steam
drops an unknown tag value without a word, and `SubmitItemUpdate` reports
success for an update that lost one. `GetPublishedFileDetails` needs no key and
no Steam session, so what it lists is what a subscriber's client will see.

Usage:

    utils/steam_retag.py [mod ...]              # compare live tags with the derived set
    utils/steam_retag.py --execute <mod> ...    # send the ones that differ, then verify
"""

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import steam_bundle
import steam_identity
from steam_backfill import direnv_env
from steam_backfill import mod_repositories
from steam_backfill import run_ck_workshop

DETAILS_URL = "https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/"

# The Web API can answer from a cache for a short while after an update. A
# mismatch is re-read this many times before it is reported, so a lag is not
# mistaken for a dropped tag.
VERIFY_ATTEMPTS = 6
VERIFY_INTERVAL = 5


def live_tags(file_id: int) -> list[str]:
    """The tags a Workshop item carries right now, from the public Web API."""
    body = urllib.parse.urlencode({"itemcount": 1, "publishedfileids[0]": file_id}).encode()
    with urllib.request.urlopen(DETAILS_URL, body, timeout=30) as response:
        payload = json.load(response)
    # A response in another shape is an unreadable answer, not a crash: the
    # caller treats ValueError as "this mod failed" and moves on to the next.
    try:
        details = payload["response"]["publishedfiledetails"][0]
    except (KeyError, IndexError, TypeError) as err:
        raise ValueError(f"Workshop item {file_id}: unexpected Web API response ({err!r})") from err
    # result 1 is k_EResultOK. Anything else is an item the API will not
    # describe — deleted, banned, or an id that was never an item.
    if details.get("result") != 1:
        raise ValueError(
            f"Workshop item {file_id} could not be read (result {details.get('result')})"
        )
    return [tag["tag"] for tag in details.get("tags", [])]


def tag_changes(wanted: list[str], live: list[str]) -> tuple[list[str], list[str]]:
    """(to add, to remove), compared without case.

    Without case because Steam's own tag matching ignores it and so does the
    loader's `Asset`/`Script (Elevated Access)` check; a difference in case alone
    is not worth a submit.
    """
    live_folded = {tag.casefold() for tag in live}
    wanted_folded = {tag.casefold() for tag in wanted}
    return (
        [tag for tag in wanted if tag.casefold() not in live_folded],
        [tag for tag in live if tag.casefold() not in wanted_folded],
    )


def verify(file_id: int, wanted: list[str]) -> list[str]:
    """What the item still lacks after the update — empty when it took.

    Only the missing side is reported. A tag left over would be a failed
    replacement, which SetItemTags does not do; a tag missing is the documented
    way Steam loses one.

    A failed read is retried like a mismatch, since both can be a moment of lag.
    If no read succeeded at all, the last error is raised: that is "unknown",
    and must not come back as the empty list that means "confirmed".
    """
    missing: list[str] | None = None
    error: Exception | None = None
    for attempt in range(VERIFY_ATTEMPTS):
        try:
            missing, _ = tag_changes(wanted, live_tags(file_id))
        except (ValueError, OSError) as err:
            error = err
        else:
            if not missing:
                return []
        if attempt + 1 < VERIFY_ATTEMPTS:
            time.sleep(VERIFY_INTERVAL)
    if missing is None:
        raise error
    return missing


def report_after_failure(file_id: int, wanted: list[str]) -> None:
    """Say what a failed or interrupted update left on the item.

    ck-workshop can fail after Steam accepted the tags — a lost connection
    while it waits for the answer — so its exit code does not tell whether the
    item changed. One read settles it for the operator.
    """
    try:
        missing, _ = tag_changes(wanted, live_tags(file_id))
    except (ValueError, OSError) as err:
        print(f"  ? the item could not be read back ({err}) — check it by hand")
        return
    if missing:
        print(f"  the item still lacks: {', '.join(missing)}")
    else:
        print("  the item carries the wanted tags anyway — the update went through")


def retag(repo: Path, utils_dir: Path, execute: bool, named: bool) -> int:
    """One mod: compare, and with `execute` send and verify. Returns an exit code.

    `named` is whether the operator asked for this mod. A mod with no Workshop
    item is skipped quietly in the overview, which walks every repository, but
    is an error when named — then the id has gone missing, and "skipped" with
    exit 0 would hide it.
    """
    env = direnv_env(repo)
    mod_name = env.get("MOD_NAME", "")
    identity = steam_identity.asset_path(repo, mod_name)
    if mod_name and not named:
        # Raises for an asset that exists but cannot be read as one, so only a
        # genuinely unpublished mod reaches the quiet skip below.
        steam_identity.ensure_recognizable(identity)
        if not steam_identity.read_file_id(identity):
            print(f"\n{repo.name}: no Workshop item — skipped")
            return 0
    bundle = steam_bundle.tag_bundle(repo, env)
    live = live_tags(bundle["fileId"])
    add, remove = tag_changes(bundle["tags"], live)

    print(f"\n{repo.name} ({bundle['fileId']})")
    print(f"  live:   {', '.join(live) or '—'}")
    print(f"  wanted: {', '.join(bundle['tags'])}")
    if not add and not remove:
        print("  ✓ already current — nothing to send")
        return 0
    print(f"  + {', '.join(add) or '—'}")
    print(f"  - {', '.join(remove) or '—'}")

    args = ["--tags-only"] if execute else ["--tags-only", "--dry-run"]
    code, _ = run_ck_workshop(utils_dir, env, args, json.dumps(bundle), None)
    if code != 0:
        print(f"  ✗ ck-workshop exited {code}")
        if execute:
            report_after_failure(bundle["fileId"], bundle["tags"])
        return code
    if not execute:
        return 0

    try:
        missing = verify(bundle["fileId"], bundle["tags"])
    except (ValueError, OSError) as err:
        # Distinct from a failure before the send: Steam has accepted the
        # update, so re-running is safe, but nothing here confirms it took.
        print(f"  ✗ sent, but the item could not be read back ({err}) — check it by hand")
        return 1
    if missing:
        print(f"  ✗ sent, but the item does not carry: {', '.join(missing)}")
        return 1
    print("  ✓ tags updated and confirmed on the Workshop")
    return 0


def main(argv: list[str]) -> int:
    """CLI entry point. Without --execute nothing is sent."""
    parser = argparse.ArgumentParser(
        description="Set Steam Workshop tags without publishing a build."
    )
    parser.add_argument("mods", nargs="*", help="mod repository directories")
    parser.add_argument(
        "--execute", action="store_true", help="send the tags. Requires the mods to be named."
    )
    args = parser.parse_args(argv[1:])

    if args.execute and not args.mods:
        # The same guard steam_backfill.py has: a write to every public item
        # the family owns must not be one up-arrow away from a comparison run.
        parser.error("--execute needs the mods named explicitly")

    sys.stdout.reconfigure(line_buffering=True)

    utils_dir = Path(__file__).resolve().parent
    root = utils_dir.parent
    repos = (
        [Path(mod) if Path(mod).is_dir() else root / mod for mod in args.mods]
        if args.mods
        else mod_repositories(root)
    )

    status = 0
    for repo in repos:
        try:
            code = retag(repo, utils_dir, args.execute, named=bool(args.mods))
        except (ValueError, OSError) as err:
            print(f"\n{repo.name}: {err}", file=sys.stderr)
            code = 1
        status = status or code
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv))
