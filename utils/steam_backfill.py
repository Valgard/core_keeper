#!/usr/bin/env python3
"""Mirror a mod's mod.io release history into its Steam Workshop change history.

Each mod here has a release history on mod.io — every version it ever published,
with the build that shipped and the notes that went with it. Its Workshop item
has one entry, for whatever version happened to be current when it was first
published there. This puts the rest of them in, oldest first, so the two
platforms tell the same story.

**A tool of its own, and deliberately not a mode of `utils/upload.sh`.** That
script publishes *a* release: one version, one build, the one it was just handed.
Everything here is the opposite shape — an old version, a build fetched from
mod.io rather than made, and a run that spans many submits and can be
interrupted in the middle of them. Folding that into the publish path would
leave a permanent second mode in the one script whose failures are the most
expensive, to serve something that runs once per mod and then never again.

**Nothing about this is reversible.** A Workshop item's change history is
append-only to every API — `SubmitItemUpdate` appends, nothing names an entry,
and only the web UI can edit or delete one (`docs/ck/steam-workshop.md`). So the
order in which the submits happen *is* the order of the history, forever, and a
version submitted twice is corrected by hand, one web form at a time. Three
consequences shape the whole file:

- Versions go out oldest first, and a failure stops that mod rather than
  skipping ahead. An entry out of order is not fixable from here.
- Every bundle is validated before the first one is sent. `--execute` runs the
  same rehearsal the default run does, in full, and only then starts
  submitting: a bundle that turns out to be unusable at version 7 of 16 is a
  bad thing to discover with six entries already published.
- Nothing is guessed. Where the tool cannot know something — above all how many
  entries an item's history already holds — it refuses and says what to pass.

**The progress record lives on the item, not in a local file.** A Workshop item
carries a publisher-only Metadata string, and `ck-workshop` writes this tool's
record into it *in the same submit as the content it describes*. A local file
can disagree with reality in both directions; the direction that costs something
is "the upload succeeded, the file write did not", because the next run then
re-submits an entry that cannot be deleted. Metadata cannot drift that way, and
it survives a fresh checkout or another machine.

The trap that goes with it is documented and guarded here rather than trusted:
a query fills `Item.Metadata` only when it asked, so an unasked query returns
null — and null read as "nothing recorded yet" is exactly the bug this design
exists to avoid. `resume_state` therefore treats every unreadable answer, and
every item whose record is absent, as *unknown* and refuses.

Usage:

    utils/steam_backfill.py [mod ...]              # rehearse; nothing is sent
    utils/steam_backfill.py --execute <mod> ...    # rehearse, then submit

With no mod named it rehearses every mod repository it finds, which is the
overview: which are ready, which are waiting on a dependency's Workshop id, and
what each would submit. `--execute` requires the mods to be named, so a run that
writes 49 permanent history entries cannot be started by pressing up-arrow.
"""

import argparse
import dataclasses
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import zipfile
from pathlib import Path

import steam_bundle
import steam_changenote
import steam_identity
import steam_result

# The record's own version. Bumped only when its shape changes in a way an
# older reader would misunderstand; `parse_metadata` refuses anything higher
# rather than treating it as unreadable, because "unreadable" leads to a
# re-submit that would overwrite a newer tool's progress.
SCHEMA = 1
TOOL = "steam_backfill"

# Same guard as utils/upload.sh puts on its own ck-workshop call: Facepunch's
# submit loop can spin indefinitely on a stalled connection.
CK_WORKSHOP_TIMEOUT = 600

MODIO_CONFIG = "Assets/Resources/mod.io/config.asset"
MODIO_ID = re.compile(r"^\s*modId:\s*(\d+)\s*$", re.MULTILINE)
GAME_KEY = re.compile(r"^\s*gameKey:\s*(\S+)\s*$", re.MULTILINE)
GAME_ID = re.compile(r"^\s*gameId:\s*(\d+)\s*$", re.MULTILINE)
SERVER_URL = re.compile(r"^\s*serverURL:\s*(\S+)\s*$", re.MULTILINE)


@dataclasses.dataclass(frozen=True)
class Release:
    """One published version: what mod.io holds, paired with the notes for it.

    `modfile` — mod.io's own id for the uploaded build — is the identity, not
    `version`. Two modfiles can carry the same version string (a re-upload of a
    release whose first attempt was wrong), and a record keyed on the version
    would then skip the second as though it had already been submitted.
    """

    version: str
    modfile: int
    date_added: int
    size: int
    md5: str
    url: str
    # From the repository's CHANGELOG.md — see `divergence` for why that and
    # not the copy mod.io stores.
    changelog: str
    modio_changelog: str


# --- pairing -----------------------------------------------------------------


def pair_releases(
    modfiles: list[dict], entries: list[tuple[str, str]]
) -> list[Release]:
    """Every modfile with the changelog entry that belongs to it, oldest first.

    Sorted by mod.io's own `date_added`, with the modfile id breaking a tie:
    the listing arrives newest-first, and the order the submits happen in is the
    order of the history, permanently. Two builds stamped the same second would
    otherwise be ordered by whatever the listing happened to return.

    A modfile with no changelog entry raises rather than falling back to the
    changelog mod.io stores for it. That field comes back HTML-escaped — `->`
    reads as `-&gt;` — so a fallback would put escaped markup into a change note
    that no API can edit afterwards. Unescaping it would be a guess about text
    that may have contained an entity to begin with.
    """
    bodies: dict[str, str] = {}
    for version, body in entries:
        # First wins: a changelog with the same version twice is malformed, and
        # the topmost entry is the one every other reader here takes.
        bodies.setdefault(version, body)

    out = []
    for modfile in sorted(modfiles, key=lambda m: (m["date_added"], m["id"])):
        version = modfile["version"]
        if version not in bodies:
            raise ValueError(
                f"modfile {modfile['id']} publishes version {version!r}, which has no "
                "'## [x.y.z]' entry in CHANGELOG.md — a Workshop change note cannot be "
                "invented, and mod.io's own copy comes back HTML-escaped"
            )
        out.append(
            Release(
                version=version,
                modfile=modfile["id"],
                date_added=modfile["date_added"],
                size=modfile["filesize"],
                md5=(modfile.get("filehash") or {}).get("md5", ""),
                url=modfile["download"]["binary_url"],
                changelog=bodies[version],
                modio_changelog=(modfile.get("changelog") or "").strip(),
            )
        )
    return out


def unpublished_versions(
    modfiles: list[dict], entries: list[tuple[str, str]]
) -> list[str]:
    """Changelog versions mod.io has no modfile for, in changelog order.

    Reported, never submitted: with no build behind it there is nothing to
    upload, and a history entry whose content is some other version's is worse
    than a missing one. Both real cases are legitimate — a version tagged
    locally before the mod existed on mod.io, and one written up but never
    released — which is exactly why they get a line rather than silence.
    """
    published = {modfile["version"] for modfile in modfiles}
    return [version for version, _ in entries if version not in published]


def divergence(release: Release) -> str | None:
    """How this version's two changelog texts differ, or None if they agree.

    They can differ two ways and the difference matters, because the repository's
    text is the one that gets sent — the same source `utils/upload.sh` publishes
    from, so a backfilled entry and the next ordinary release read alike:

    - **mod.io's HTML escaping.** Its API returns the stored changelog escaped,
      so `->` and `&` come back as `-&gt;` and `&amp;`. Nothing was edited; the
      platform is answering in a different dialect.
    - **A real edit since publishing.** CHANGELOG.md has been improved since the
      release went out — a caveat dropped, a path reference generalised. Then
      the two are genuinely different documents and the Workshop entry will
      carry the current wording, not the shipped one.

    Both are surfaced rather than resolved. The second is a judgement about what
    a history entry should say, and it is not this tool's to make silently.
    """
    if release.modio_changelog == release.changelog:
        return None
    if html.unescape(release.modio_changelog) == release.changelog:
        return "mod.io's HTML escaping only"
    return "edited in the repository since"


# --- the progress record -----------------------------------------------------


def render_metadata(submitted: list[Release]) -> str:
    """The record to write with the submit that completes `submitted`.

    Compact separators, and only what identifies an entry: Steam documents 5,000
    bytes for this field, and `ck-workshop` refuses a longer string rather than
    truncating one — a truncated record is not a shorter record, it is a JSON
    document that no longer parses, which reads back as "unknown".

    The version rides along beside the modfile id purely so a human opening the
    field on Steam can read it. `resume_state` matches on the id.
    """
    return json.dumps(
        {
            "schema": SCHEMA,
            "tool": TOOL,
            "submitted": [
                {"version": release.version, "modfile": release.modfile}
                for release in submitted
            ],
        },
        separators=(",", ":"),
    )


def parse_metadata(raw: str | None) -> list[dict] | None:
    """The record in an item's Metadata string, or None when there is not one.

    None means **unknown**, and every caller has to treat it that way. It covers
    a genuinely empty field, a field written by something else, and a null —
    which Facepunch produces both for a query that did not ask for metadata and
    for a metadata read that failed. Those are not distinguishable from here,
    and none of them is evidence that nothing has been submitted.

    A record from a *newer* schema raises instead. "Unknown" would send this
    tool on to re-submit and overwrite it with an older idea of what is done;
    stopping is the only reading of a future record that cannot lose anything.
    """
    if not raw:
        return None
    try:
        record = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(record, dict):
        return None
    schema = record.get("schema")
    if not isinstance(schema, int):
        return None
    if schema > SCHEMA:
        raise ValueError(
            f"the item's progress record is schema {schema}, newer than this tool's "
            f"{SCHEMA} — a newer record must not be overwritten by an older reader"
        )
    submitted = record.get("submitted")
    if not isinstance(submitted, list):
        return None
    for entry in submitted:
        if not isinstance(entry, dict) or not isinstance(entry.get("modfile"), int):
            return None
    return submitted


def resume_state(
    file_id: int | None,
    item: dict | None,
    assume: list[str] | None,
    releases: list[Release],
) -> set[int]:
    """Which modfiles the item's history already carries.

    The one decision in this file that cannot be checked afterwards, so every
    answer it cannot establish is a refusal:

    - **No item.** Nothing has been submitted, because there is nowhere it could
      have gone. An assumption here contradicts that and is refused.
    - **An item whose own record answers.** That record was written in the same
      submit as the content it names, so it cannot claim an entry that is not
      there or miss one that is.
    - **An item with no record.** It exists, so *something* submitted to it —
      the SDK window, an ordinary publish, or a first backfill submit that
      failed after creating the item. Those leave histories of different
      lengths and nothing readable says which. Reading it as "nothing yet"
      would duplicate every entry already there, so the operator states it.
    - **An answer that may not be about the item at all.** A read that did not
      ask for metadata, or a placeholder page (empty title, owner 0), is refused
      before its null can be mistaken for an empty record.
    """
    if not file_id:
        if assume is not None:
            raise ValueError(
                "--assume-submitted was given, but there is no Workshop item yet — "
                "nothing can have been submitted to an item that does not exist"
            )
        return set()

    if item is None:
        raise ValueError(
            f"Workshop item {file_id} could not be read — its history cannot be "
            "treated as empty, so nothing is submitted"
        )
    if item.get("metadataQueried") is not True:
        raise ValueError(
            "the item was read without asking for its metadata — an unasked query "
            "returns null, which would read as 'nothing submitted yet'"
        )
    if item.get("result") != "OK" or not item.get("title") or not item.get("owner"):
        raise ValueError(
            f"Workshop item {file_id} came back as a placeholder (result "
            f"{item.get('result')!r}, title {item.get('title')!r}, owner "
            f"{item.get('owner')!r}) — that measures the response, not the item"
        )

    record = parse_metadata(item.get("metadata"))
    if record is not None:
        return {entry["modfile"] for entry in record}

    if assume is None:
        raise ValueError(
            f"Workshop item {file_id} exists but carries no progress record, so how "
            "many entries its history already holds is unknown. Open its change "
            "history, then say so: --assume-submitted 1.0.0,1.1.0 — or "
            "--assume-submitted '' if the history is empty."
        )

    by_version: dict[str, list[int]] = {}
    for release in releases:
        by_version.setdefault(release.version, []).append(release.modfile)
    state = set()
    for version in assume:
        modfiles = by_version.get(version)
        if not modfiles:
            raise ValueError(
                f"--assume-submitted names {version!r}, which mod.io never published — "
                f"published versions are {', '.join(r.version for r in releases)}"
            )
        if len(modfiles) > 1:
            raise ValueError(
                f"--assume-submitted names {version!r}, which mod.io published more "
                f"than once (modfiles {modfiles}) — which of them the history carries "
                "cannot be told from a version string"
            )
        state.add(modfiles[0])
    return state


def pending(releases: list[Release], done: set[int]) -> list[Release]:
    """What is left to submit, in submit order."""
    return [release for release in releases if release.modfile not in done]


def unexpected(releases: list[Release], done: set[int]) -> list[int]:
    """Modfiles the record claims but mod.io no longer lists.

    Changes nothing about what is left to do, and is still worth saying: it
    means the item's record and the platform's listing disagree — a modfile
    deleted on mod.io after it was mirrored — and working around a disagreement
    without naming it is how the next reader inherits a puzzle.
    """
    known = {release.modfile for release in releases}
    return sorted(modfile for modfile in done if modfile not in known)


# --- talking to mod.io -------------------------------------------------------


def download_url(binary_url: str, api_key: str) -> str:
    """A modfile's download URL with the read-only game key attached.

    The key is the *game* key out of the SDK's own mod.io config — no OAuth, no
    publisher rights, and it is what makes every modfile a mod ever published
    downloadable (`docs/ck/publishing.md`).
    """
    separator = "&" if "?" in binary_url else "?"
    return f"{binary_url}{separator}api_key={api_key}"


def modio_config(sdk_path: Path) -> tuple[str, int, str]:
    """(serverURL, gameId, gameKey) out of the SDK's mod.io config asset."""
    text = (sdk_path / MODIO_CONFIG).read_text()
    server, game, key = (
        SERVER_URL.search(text),
        GAME_ID.search(text),
        GAME_KEY.search(text),
    )
    if not (server and game and key):
        raise ValueError(f"{sdk_path / MODIO_CONFIG} has no serverURL/gameId/gameKey")
    return server.group(1), int(game.group(1)), key.group(1)


def _curl(url: str, dest: Path | None = None) -> bytes:
    """Fetch a URL with curl.

    curl rather than urllib, and not out of preference: mod.io answers urllib
    with a 403 and curl with the data (`docs/ck/publishing.md`).
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


def fetch_modfiles(sdk_path: Path, mod_id: int) -> list[dict]:
    """Every modfile mod.io lists for this mod.

    `_limit=100` because the default page is 30 and the longest history here is
    16 — a mod that ever passes 100 would silently lose its oldest releases, so
    the count is checked against what the API says the total is.
    """
    server, game, key = modio_config(sdk_path)
    url = f"{server}/games/{game}/mods/{mod_id}/files?api_key={key}&_limit=100"
    listing = json.loads(_curl(url))
    data = listing.get("data", [])
    total = listing.get("result_total", len(data))
    if len(data) != total:
        raise ValueError(
            f"mod {mod_id} lists {total} modfiles but the page returned {len(data)} — "
            "the listing is paginated and this would mirror an incomplete history"
        )
    return data


def read_modio_id(repo_root: Path, mod_name: str) -> int:
    """The mod's mod.io id, from the asset CLIPublishHelper publishes with."""
    asset = repo_root / "unity" / mod_name / "Editor" / f"{mod_name}_modio.asset"
    match = MODIO_ID.search(asset.read_text())
    if not match:
        raise ValueError(f"{asset} has no 'modId:' line")
    return int(match.group(1))


def download_release(release: Release, api_key: str, into: Path) -> Path:
    """Fetch and unpack one published build, and return its content folder.

    The archive's root *is* the content folder — `ModManifest.json`, `Bundles/`,
    `Scripts/`, exactly the layout ModBuilder writes and the layout a normal
    publish uploads — so unpacking it needs no rearranging.

    The hash is checked because the whole point of the exercise is that each
    history entry carries that version's real content; a truncated download
    would publish a broken build under a version number that is already out
    there working.
    """
    content = into / "content"
    if content.is_dir():
        # Fetched already by this run's rehearsal. Downloading a second time to
        # submit the same bytes would be a second chance for the two to differ.
        return content

    into.mkdir(parents=True, exist_ok=True)
    archive = into / f"{release.modfile}.zip"
    _curl(download_url(release.url, api_key), archive)

    if release.md5:
        digest = hashlib.md5(archive.read_bytes()).hexdigest()
        if digest != release.md5:
            raise ValueError(
                f"modfile {release.modfile} ({release.version}) downloaded with md5 "
                f"{digest}, mod.io says {release.md5}"
            )

    content.mkdir()
    with zipfile.ZipFile(archive) as unpacked:
        for member in unpacked.namelist():
            # An archive member that escapes the directory would write over
            # whatever it names. mod.io serves what this repository uploaded, so
            # this is not expected — but "not expected" is not a reason to
            # extract a path this code never looked at.
            target = (content / member).resolve()
            if not str(target).startswith(str(content.resolve()) + os.sep):
                raise ValueError(
                    f"modfile {release.modfile} contains a path outside the archive "
                    f"root: {member!r}"
                )
        unpacked.extractall(content)
    archive.unlink()
    return content


# --- talking to ck-workshop --------------------------------------------------


def _steam_app_id(utils_dir: Path) -> str:
    """Core Keeper's Steam app id, read rather than spelled out a fourth time.

    Steamworks refuses to initialise outside a Steam-launched process unless it
    can learn the app id, and it reads `SteamAppId` from the environment in
    preference to the `steam_appid.txt` it otherwise looks for relative to the
    current working directory. That file is the copy that exists for this
    purpose; taking the value from it keeps this from becoming a fourth place
    the constant has to be kept in step (Program.cs and upload.sh are the other
    two, and both say so).
    """
    return (utils_dir / "ck-workshop" / "steam_appid.txt").read_text().strip()


def run_ck_workshop(
    utils_dir: Path,
    env: dict,
    args: list[str],
    stdin: str | None,
    tee_to: Path | None,
) -> tuple[int, str]:
    """Run the .NET tool, streaming its output, and return (exit code, output).

    Streamed line by line rather than captured whole, for the same reason
    `utils/upload.sh` pipes it through `tee`: the tool prints a newly created
    item's id the moment `CreateItem` succeeds, and holding that back until the
    process returns would hide it for as long as the upload takes.

    `tee_to` is where that line has to survive a kill. It is a caller-owned path
    outside anything this run cleans up — see `_submit` on why.
    """
    child = dict(os.environ)
    child.update({k: v for k, v in env.items() if v is not None})
    child["SteamAppId"] = _steam_app_id(utils_dir)

    process = subprocess.Popen(
        ["dotnet", "run", "--project", str(utils_dir / "ck-workshop"), "--", *args],
        stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=child,
        text=True,
    )
    killer = threading.Timer(CK_WORKSHOP_TIMEOUT, process.kill)
    killer.start()
    try:
        if stdin is not None:
            # From a thread, so that reading the child's output and feeding it
            # cannot wait on each other. A bundle is well under a pipe buffer
            # today and the tool reads stdin to EOF before printing anything —
            # but both of those are properties of the other side, and a
            # deadlock here would look like a hung upload.
            feeder = threading.Thread(
                target=lambda: (process.stdin.write(stdin), process.stdin.close()),
                daemon=True,
            )
            feeder.start()
        lines = []
        sink = tee_to.open("w") if tee_to else None
        try:
            for line in process.stdout:
                lines.append(line)
                sys.stderr.write(line)
                if sink:
                    sink.write(line)
                    sink.flush()
        finally:
            if sink:
                sink.close()
        return process.wait(), "".join(lines)
    finally:
        killer.cancel()


def read_item(utils_dir: Path, env: dict, file_id: int) -> dict | None:
    """What the Workshop says about an item, or None when it could not be read.

    None rather than an exception because the caller — `resume_state` — has to
    treat "could not be read" as unknown either way, and it is the place where
    that reading is written down.
    """
    code, output = run_ck_workshop(
        utils_dir, env, ["--read-item", str(file_id)], stdin=None, tee_to=None
    )
    if code != 0:
        return None
    for line in reversed(output.splitlines()):
        if line.strip().startswith("{"):
            try:
                parsed = json.loads(line)
            except ValueError:
                continue
            if isinstance(parsed, dict) and "metadataQueried" in parsed:
                return parsed
    return None


# --- one mod's plan ----------------------------------------------------------


@dataclasses.dataclass
class ModPlan:
    repo: Path
    mod_name: str
    mod_id: int
    env: dict
    releases: list[Release]
    unpublished: list[str]
    file_id: int | None
    done: set[int]
    todo: list[Release]
    blocked: str | None = None
    # Created lazily, once, and kept for the whole run: the rehearsal downloads
    # each pending build and the submit phase uploads the very same bytes.
    workdir: Path | None = None

    def scratch(self) -> Path:
        if self.workdir is None:
            self.workdir = Path(
                tempfile.mkdtemp(prefix=f"ck-backfill-{self.mod_name}-")
            )
        return self.workdir

    def already(self) -> list[Release]:
        """The releases the item's history already carries, in submit order."""
        return [release for release in self.releases if release.modfile in self.done]


def direnv_env(repo: Path) -> dict:
    """A mod's environment, from its own `.envrc` via direnv.

    Not re-implemented here. The `.envrc` chain is where every mod's identity,
    tag set and shared paths already live, and it walks up into the parent
    `core_keeper/.envrc` for the machine-level values — a second reader of that
    arrangement would be a second thing to keep in step with it.
    """
    completed = subprocess.run(
        ["direnv", "exec", str(repo), "env"],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise ValueError(
            f"direnv could not load {repo}/.envrc: {completed.stderr.strip()} "
            "(a new checkout needs `direnv allow` in the mod directory)"
        )
    out = {}
    for line in completed.stdout.splitlines():
        key, _, value = line.partition("=")
        if _:
            out[key] = value
    return out


def plan_mod(repo: Path, utils_dir: Path, assume: list[str] | None) -> ModPlan:
    """Everything about one mod that can be established before anything is sent."""
    env = direnv_env(repo)
    mod_name = env.get("MOD_NAME")
    if not mod_name:
        raise ValueError(f"{repo}/.envrc sets no MOD_NAME")

    sdk_path = Path(env["SDK_PATH"])
    mod_id = read_modio_id(repo, mod_name)
    modfiles = fetch_modfiles(sdk_path, mod_id)
    entries = steam_bundle.changelog_entries((repo / "CHANGELOG.md").read_text())
    releases = pair_releases(modfiles, entries)

    file_id = steam_identity.read_file_id(steam_identity.asset_path(repo, mod_name))
    # Only when there is an item to read. A mod with no Workshop id has no
    # history and no metadata, so contacting Steam would answer a question
    # already settled — and it keeps a plan over every mod runnable without a
    # Steam session for as long as none of them has been published.
    item = read_item(utils_dir, env, file_id) if file_id else None
    done = resume_state(file_id, item, assume, releases)

    plan = ModPlan(
        repo=repo,
        mod_name=mod_name,
        mod_id=mod_id,
        env=env,
        releases=releases,
        unpublished=unpublished_versions(modfiles, entries),
        file_id=file_id,
        done=done,
        todo=pending(releases, done),
    )

    # The same preflight a publish runs, and for the same reason it runs it
    # first: a required dependency with no Workshop id, a missing
    # steam-description.txt or an unrecognizable identity asset must surface
    # while stopping still costs nothing. Caught rather than raised, so that a
    # mod waiting on a sibling's Workshop id appears in the overview as waiting
    # instead of ending the whole run.
    try:
        steam_bundle.check_prerequisites(repo, env)
    except ValueError as err:
        plan.blocked = str(err)
    return plan


# --- output ------------------------------------------------------------------


def _size(count: int) -> str:
    return (
        f"{count / 1024:.0f} KB" if count < 1024 * 1024 else f"{count / 1048576:.1f} MB"
    )


def report(plan: ModPlan, limit: int | None, brief: bool) -> None:
    print()
    print(f"{plan.mod_name}  ({plan.repo.name})  mod.io {plan.mod_id}")
    if plan.file_id:
        print(f"  Workshop item {plan.file_id}, {len(plan.done)} version(s) recorded")
    else:
        print("  Workshop item: none yet — the first submit creates it, hidden")
    if plan.blocked:
        print(f"  ! not publishable yet: {plan.blocked}")
    for version in plan.unpublished:
        print(f"  - CHANGELOG.md has {version}, which mod.io never published — skipped")
    for modfile in unexpected(plan.releases, plan.done):
        print(f"  ! recorded modfile {modfile} is no longer listed on mod.io")
    listed = todo(plan, limit)
    if not listed:
        print("  nothing to submit")
        return
    # Worded from what this run would do, not from what is outstanding: a
    # blocked mod submits nothing, and --max-versions caps the rest. A count
    # that ignored either would describe a run that is not the one being asked
    # for.
    verb = "would be submitted once that is resolved" if plan.blocked else "to submit"
    print(f"  {len(listed)} of {len(plan.releases)} version(s) {verb}, in order:")
    for index, release in enumerate(listed, 1):
        note = divergence(release)
        print(
            f"   {index:>2}. {release.version:<8} modfile {release.modfile}  "
            f"{_size(release.size):>9}" + (f"   (change note {note})" if note else "")
        )
        if not brief:
            # The converted note, not the Markdown it came from. This listing is
            # the last look anyone gets before a permanent history entry, so it
            # has to show the text that is actually submitted — printing the
            # source would hide the one class of mistake a rehearsal exists to
            # catch, which is precisely how Markdown got sent in the first place.
            note = steam_changenote.render(release.version, release.changelog)
            for line in note.splitlines() or [""]:
                print(f"       | {line}")


# --- doing it ----------------------------------------------------------------


def _submit(
    plan: ModPlan,
    release: Release,
    done: list[Release],
    utils_dir: Path,
    workdir: Path,
    dry_run: bool,
) -> int:
    """Build one submit's bundle and hand it to ck-workshop.

    The result file is a `mktemp` of its own, outside `workdir`, and is removed
    only once its contents are safely in the identity asset — the same
    discipline `utils/upload.sh` documents at length. It exists for the window
    between Steam creating an item and that id reaching disk: a signal aimed at
    this process ends it there, and without the file the next run would find no
    id, conclude the mod has never been published, and create a second item.
    """
    api_key = modio_config(Path(plan.env["SDK_PATH"]))[2]
    content = download_release(release, api_key, workdir / str(release.modfile))

    env = dict(plan.env)
    env["CK_STEAM_CONTENT"] = str(content)
    bundle = steam_bundle.build_bundle(
        plan.repo,
        env,
        workdir / "preview.png",
        release=(release.version, release.changelog),
        item_metadata=render_metadata([*done, release]),
    )

    if dry_run:
        # No result file: the dry run returns before SteamClient.Init, so no
        # item can come into existence and there is no id for one to hold.
        return run_ck_workshop(
            utils_dir, env, ["--dry-run"], stdin=json.dumps(bundle), tee_to=None
        )[0]

    handle, result_path = tempfile.mkstemp(
        prefix=f"ck-backfill-{plan.mod_name}-{release.version}-result."
    )
    os.close(handle)
    result_file = Path(result_path)

    code, _ = run_ck_workshop(
        utils_dir, env, [], stdin=json.dumps(bundle), tee_to=result_file
    )

    # Attempted whatever the exit code says, exactly as upload.sh does: the tool
    # reports a created item's id even when the publish then failed, because
    # CreateItem already ran and the item exists on Steam either way.
    persisted = _persist(plan, bundle, result_file)
    if persisted:
        result_file.unlink(missing_ok=True)
    else:
        print(
            f"  ! the id in {result_file} could not be stored — put it into "
            f"{steam_identity.asset_path(plan.repo, plan.mod_name)} by hand",
            file=sys.stderr,
        )
        return code or 1
    return code


def _persist(plan: ModPlan, bundle: dict, result_file: Path) -> bool:
    """Store a reported Workshop id in the identity asset. True if nothing is lost.

    `selectedPath` is deliberately not written, where `utils/steam_result.py`
    writes it: the content folder here is an unpacked download that this run
    deletes on its way out, and the SDK window reads that field as a place to
    build from. `write_file_id` documents None as "leave what is there", which
    is the honest answer for a value this caller cannot determine.
    """
    with result_file.open() as stream:
        result = steam_result.find_result(stream)
    if result is None or not result.get("fileId"):
        # Nothing was created, so there is nothing to lose. A tool that crashed
        # before reporting anything reports nothing, and that is not an id.
        return True
    asset = steam_identity.asset_path(plan.repo, plan.mod_name)
    created_asset = not asset.is_file()
    try:
        steam_identity.write_file_id(
            asset,
            result["fileId"],
            mod_owner=result.get("modOwner") or None,
            tags=bundle["tags"],
        )
    except Exception as err:  # noqa: BLE001 — the id must not be lost silently
        print(
            f"  ! Workshop item {result['fileId']} is live, but its id could not be "
            f"saved to {asset}: {err}",
            file=sys.stderr,
        )
        return False
    plan.file_id = result["fileId"]
    if created_asset:
        steam_identity.warn_if_untracked(asset)
    return True


def todo(plan: ModPlan, limit: int | None) -> list[Release]:
    """What this run would submit for one mod: pending, capped by --max-versions."""
    return plan.todo[:limit] if limit is not None else plan.todo


def rehearse(plans: list[ModPlan], utils_dir: Path, limit: int | None) -> int:
    """Build and validate every pending submit, across every mod, sending nothing.

    Not an optional mode and not what `--dry-run` selects: this is the first
    half of `--execute` too. `ck-workshop` checks a bundle before it does
    anything with it, and checking all of them *before the first one is sent* is
    what keeps an unusable bundle from surfacing at version 7 of 16 with six
    permanent history entries already published. The handbook says the same in
    platform terms: anything writing many entries should be rehearsed first,
    because correcting N of them is N visits to a web form.

    It also downloads each build, into a scratch directory the submit phase then
    reuses — so what was validated is what goes out, byte for byte.
    """
    for plan in plans:
        # Accumulated exactly as the submit phase will, not reset per version:
        # the record grows with every entry, and ck-workshop refuses one over
        # Steam's documented 5,000 bytes. Rehearsing each version against a
        # one-entry record would validate a string no submit ever sends and
        # leave the longest one — the last — unchecked.
        done = plan.already()
        for release in todo(plan, limit):
            print(f"\n  rehearsing {plan.mod_name} {release.version}...", flush=True)
            code = _submit(plan, release, done, utils_dir, plan.scratch(), dry_run=True)
            done.append(release)
            if code != 0:
                print(
                    f"  ✗ {plan.mod_name} {release.version} would not publish "
                    f"(exit {code}) — nothing has been sent",
                    file=sys.stderr,
                )
                return code
    return 0


def submit_all(plans: list[ModPlan], utils_dir: Path, limit: int | None) -> int:
    """Send the rehearsed submits, oldest version first.

    A failure stops that mod and leaves the rest of it for a re-run: skipping
    ahead would put a later version into the history before an earlier one, and
    no API can reorder them. Other mods carry on, because their histories are
    independent of this one's.
    """
    status = 0
    for plan in plans:
        done = plan.already()
        for release in todo(plan, limit):
            print(f"\n  submitting {plan.mod_name} {release.version}...", flush=True)
            code = _submit(
                plan, release, done, utils_dir, plan.scratch(), dry_run=False
            )
            if code != 0:
                print(
                    f"  ✗ {plan.mod_name} stopped at {release.version} (exit {code}). "
                    "The versions after it were NOT submitted — re-run to continue "
                    "from here; a history entry out of order cannot be reordered.",
                    file=sys.stderr,
                )
                status = code
                break
            done.append(release)
            plan.done.add(release.modfile)
    return status


def mod_repositories(root: Path) -> list[Path]:
    """Every mod repository beside this one, enumerated rather than listed.

    A written-down list of the mods goes stale silently, and has. A directory is
    a mod when it is its own git repository and carries the identity asset a
    publish reads.
    """
    return sorted(
        path
        for path in root.iterdir()
        if (path / ".git").exists() and list(path.glob("unity/*/Editor/*_modio.asset"))
    )


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Mirror a mod's mod.io release history into its Steam Workshop item.",
        epilog="Without --execute nothing is sent: every pending submit is built and "
        "validated, and the plan is printed.",
    )
    parser.add_argument("mods", nargs="*", help="mod repository directories")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="actually submit. Requires the mods to be named.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="the default; accept it explicitly so a rehearsal can be asked for by name",
    )
    parser.add_argument(
        "--assume-submitted",
        metavar="V,V",
        help="versions an existing item's history already holds, for an item that "
        "carries no progress record. Pass an empty value for 'none'.",
    )
    parser.add_argument(
        "--max-versions",
        type=int,
        metavar="N",
        help="submit at most N pending versions per mod, to rehearse against a live item",
    )
    parser.add_argument("--brief", action="store_true", help="omit the change notes")
    args = parser.parse_args(argv[1:])

    if args.execute and args.dry_run:
        parser.error("--execute and --dry-run contradict each other")
    if args.execute and not args.mods:
        # A run that appends dozens of permanent history entries should not be
        # startable by pressing up-arrow on a plan command.
        parser.error("--execute needs the mods named explicitly")

    # Block-buffered when piped, which puts the whole plan after the child
    # process output it is supposed to precede.
    sys.stdout.reconfigure(line_buffering=True)

    utils_dir = Path(__file__).resolve().parent
    root = utils_dir.parent
    repos = (
        [Path(mod) if Path(mod).is_dir() else root / mod for mod in args.mods]
        if args.mods
        else mod_repositories(root)
    )
    assume = (
        [v.strip() for v in args.assume_submitted.split(",") if v.strip()]
        if args.assume_submitted is not None
        else None
    )
    if assume is not None and len(repos) != 1:
        parser.error("--assume-submitted describes one item, so name exactly one mod")

    status = 0
    plans = []
    for repo in repos:
        try:
            plan = plan_mod(repo, utils_dir, assume)
        except (ValueError, OSError) as err:
            print(f"\n{repo.name}: {err}", file=sys.stderr)
            status = 1
            continue
        plans.append(plan)
        report(plan, args.max_versions, args.brief)

    # Blocked mods are dropped here rather than skipped later, so the counts
    # below and everything after them describe the same set of work. A mod
    # waiting on a sibling's Workshop id has already said so in its own report.
    runnable = [
        plan for plan in plans if not plan.blocked and todo(plan, args.max_versions)
    ]
    total = sum(len(todo(plan, args.max_versions)) for plan in runnable)
    print(
        f"\n{total} version(s) to submit across {len(runnable)} of {len(plans)} mod(s)."
    )
    if not total:
        return status

    try:
        code = rehearse(runnable, utils_dir, args.max_versions)
        if code != 0:
            return code
        if not args.execute:
            print(
                f"\n✓ all {total} submit(s) validated — nothing was sent. "
                "Add --execute to publish them.",
            )
            return status
        code = submit_all(runnable, utils_dir, args.max_versions)
        if code != 0:
            status = code
        else:
            print(
                f"\n✓ {total} history entr(ies) submitted. An item this run created "
                "is HIDDEN — review it on the Workshop and make it visible by hand, "
                "and commit the <Mod>_Steam.asset holding its id."
            )
    finally:
        for plan in plans:
            # mod.io's build artefacts, not this repository's.
            if plan.workdir:
                shutil.rmtree(plan.workdir, ignore_errors=True)
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv))
