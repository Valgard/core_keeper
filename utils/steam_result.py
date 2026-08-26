"""Persist a Workshop item's id after ck-workshop has returned.

This runs on every publish, successful or not — Program.cs reports an item's
id even when the publish failed afterward, because CreateItem already ran by
then and the item exists on Steam regardless. Losing that id is precisely how
the NEXT run sees no local id (steam_identity.read_file_id), concludes the mod
has never been published, and creates a second public Workshop item that
nothing distinguishes from the first.

So the shape of this script is: say nothing and change nothing when no item
was created, write the id and explain what happened when one was, and fail
loudly when an id exists but cannot be stored — never quietly.

It lived as an inline heredoc in upload.sh, where the one piece of the Steam
stage with no test coverage was the piece deciding whether write_file_id (19
tests) is called at all. Moved out for the same reason register_build_path.py
is a file: a shell script cannot be handed a fixture.

Usage:
    steam_result.py <ck-workshop-output-file> <mod-repo-root>

with MOD_NAME set, and CK_STEAM_BUNDLE carrying the publish bundle — through
the environment rather than an argument because it holds the whole Workshop
description.
"""

import json
import os
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path

import steam_identity


def find_result(lines: Iterable[str]) -> dict | None:
    """The last of ck-workshop's result objects in its output, if any.

    Scanned from the end for a line that really is one, rather than taking the
    last '{'-prefixed line on faith. The stream carries the tool's stderr as
    well as its stdout, so a brace-leading diagnostic printed after the result
    — native Steamworks logging during Shutdown, say — would otherwise take
    its place and throw. Losing the line that way discards the id of an item
    that already exists, which is the one thing this step is for.
    """
    for line in reversed(list(lines)):
        if not line.strip().startswith("{"):
            continue
        try:
            candidate = json.loads(line)
        except ValueError:
            continue
        if isinstance(candidate, dict) and "fileId" in candidate:
            return candidate
    return None


def main(argv: list[str], env: Mapping[str, str] | None = None) -> int:
    env = os.environ if env is None else env

    if len(argv) != 3:
        print(
            f"usage: {Path(argv[0]).name} <ck-workshop-output-file> <mod-repo-root>",
            file=sys.stderr,
        )
        return 1

    mod_name = env.get("MOD_NAME")
    if not mod_name:
        print(
            "  ! MOD_NAME is not set — cannot locate the Steam asset.", file=sys.stderr
        )
        return 1

    try:
        with open(argv[1]) as stream:
            result = find_result(stream)
    except OSError as exc:
        # Non-zero, unlike the "nothing was created" exits below: those know
        # that there is no id, this one knows nothing at all. A non-zero exit
        # is also what keeps upload.sh from deleting the very file that may
        # still hold the id.
        print(f"  ! {argv[1]} could not be read: {exc}", file=sys.stderr)
        return 1

    if result is None:
        return 0  # ck-workshop crashed before it could report anything at all

    file_id = result["fileId"]
    if not file_id:
        return 0  # nothing was created on Steam — nothing to persist

    asset = steam_identity.asset_path(Path(argv[2]), mod_name)

    # The fields only the SDK window reads. Each falls back to None — leave
    # what is already there — rather than to a blank: modOwner is 0 whenever
    # Steam was not initialised, and a bundle that could not be parsed is no
    # reason to erase a path and a tag list that were right before this run.
    bundle = {}
    try:
        bundle = json.loads(env.get("CK_STEAM_BUNDLE") or "{}")
    except ValueError:
        pass

    try:
        steam_identity.write_file_id(
            asset,
            file_id,
            mod_owner=result.get("modOwner") or None,
            selected_path=bundle.get("contentPath") or None,
            tags=bundle.get("tags"),
        )
    except Exception as err:
        print(
            f"  ! Workshop item {file_id} is live, but its id could not be saved to {asset}: {err}",
            file=sys.stderr,
        )
        print(
            f"    Fix {asset} by hand — it needs a 'fileId:' line set to {file_id} — then re-run.",
            file=sys.stderr,
        )
        return 1

    if result["success"]:
        status = "created, hidden" if result["created"] else "updated"
        print(f"  Workshop item {file_id} ({status})")
    elif result["created"]:
        print(
            f"  Workshop item {file_id} was created despite the failed publish above — "
            "its id was saved so the next run reuses it instead of creating a duplicate.",
            file=sys.stderr,
        )
    else:
        print(
            f"  Workshop item {file_id} already existed — its id was (re-)saved, but "
            "the update itself failed (see above).",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
