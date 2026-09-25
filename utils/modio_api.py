"""Shared mod.io access for the tools in this directory that talk to it directly.

Two tools read the same three values out of the SDK's own mod.io config asset
before every fetch: mod_source.py to resolve a mod's identity, steam_backfill.py
to mirror a mod's release history into its Steam Workshop item. Until this
module existed, each kept its own copy of that config read and of the curl
fetch mod.io actually answers (docs/ck/publishing.md -- mod.io returns a 403 to
urllib and the data to curl). Neither tool is the other's foundation -- one is
a lookup tool, the other a run-once backfill -- so neither should host the
other's copy; this is the one place both import from instead.
"""

import re
import subprocess
from pathlib import Path

# Read out of the SDK's own mod.io config asset; the same three values drive
# every fetch a tool in this directory makes against mod.io.
MODIO_CONFIG = "Assets/Resources/mod.io/config.asset"
SERVER_URL = re.compile(r"^\s*serverURL:\s*(\S+)\s*$", re.MULTILINE)
GAME_ID = re.compile(r"^\s*gameId:\s*(\d+)\s*$", re.MULTILINE)
GAME_KEY = re.compile(r"^\s*gameKey:\s*(\S+)\s*$", re.MULTILINE)

# A single mod's own id, out of its `unity/<Mod>/Editor/<Mod>_modio.asset` --
# a different file from the three above, and the authority on which published
# mod a repository is. Here because both tools read it and had the same
# expression twice; each builds that path its own way, so only the pattern is
# shared.
MODIO_ID = re.compile(r"^\s*modId:\s*(\d+)\s*$", re.MULTILINE)


def modio_config(sdk_path: Path) -> tuple[str, int, str]:
    """(serverURL, gameId, gameKey) out of the SDK's mod.io config asset."""
    text = (sdk_path / MODIO_CONFIG).read_text(encoding="utf-8")
    server, game, key = (
        SERVER_URL.search(text),
        GAME_ID.search(text),
        GAME_KEY.search(text),
    )
    if not (server and game and key):
        raise ValueError(f"{sdk_path / MODIO_CONFIG} has no serverURL/gameId/gameKey")
    return server.group(1), int(game.group(1)), key.group(1)


def curl(url: str, dest: Path | None = None) -> bytes:
    """Fetch a URL with curl.

    curl rather than urllib, and not out of preference: mod.io answers urllib
    with a 403 and curl with the data (docs/ck/publishing.md).

    `dest`, when given, is passed to curl as `-o` so the response is written
    straight to disk rather than held in memory -- steam_backfill.py's release
    downloads are the multi-megabyte case this exists for; mod_source.py never
    passes it. mod.io's game key travels in the URL's query string, so a
    failure is reported against `url.split('?')[0]` only, never the full URL:
    the key must never reach a log line or an exception message.
    """
    command = ["curl", "-sSfL"]
    if dest is not None:
        command += ["-o", str(dest)]
    command.append(url)
    completed = subprocess.run(command, capture_output=True, check=False)
    if completed.returncode != 0:
        raise ValueError(
            f"curl failed ({completed.returncode}) for {url.split('?')[0]}: "
            f"{completed.stderr.decode().strip()}"
        )
    return completed.stdout
