"""Resolve a Core Keeper mod name to where its source actually lives.

The question this answers has no answer in the repository today beyond the
path pattern. docs/ck/reverse-engineering.md states that every installed mod
ships readable C# and gives the shape `<modId>_<modfileId>`; what is missing
is the step from a NAME to those numbers, and without it a dispatched agent
falls back to searching the filesystem.

A mod carries three names that routinely disagree -- NameChests is "More
Labels" on mod.io -- so the index covers all three at once rather than
privileging the internal one, which leaves a substantial minority of installed
mods unresolvable. The measurement and the cases that defeat it are in
docs/specs/2026-09-20-mod-source-lookup-design.md.
"""

import argparse
import dataclasses
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import unicodedata
import urllib.parse
import zipfile
from pathlib import Path

# Reading the real id, not the fake one. FAKE_MOD_ID identifies only a mod
# with a dev build INSTALLED (2 of 13 when measured) and lives in a gitignored
# .envrc; the real modId is in a tracked asset and present for all of them.
_MODIO_ID = re.compile(r"^\s*modId:\s*(\d+)\s*$", re.MULTILINE)
_FAKE_ID = re.compile(r'^\s*export\s+FAKE_MOD_ID="?(\d+)', re.MULTILINE)

ORIGIN_INTERNAL = "internal name"
ORIGIN_TITLE = "mod.io title"
ORIGIN_SLUG = "slug"

# Anything that is not a letter or a digit IN ANY SCRIPT. An [^a-z0-9] filter
# looks equivalent and is not: it deletes Cyrillic, Greek and CJK wholesale,
# collapsing every such title onto the empty key. Measured on the live
# catalogue, that merged three unrelated mods into one ambiguous entry.
_NOT_ALPHANUMERIC = re.compile(r"[^\w]|_", re.UNICODE)


def normalise(text: str) -> str:
    """The lookup key for a name: casefolded, alphanumeric, script-preserving.

    NFKC first so that visually identical spellings agree before anything is
    stripped; casefold rather than lower() because it is the comparison Unicode
    defines for exactly this purpose.
    """
    folded = unicodedata.normalize("NFKC", text).casefold()
    return _NOT_ALPHANUMERIC.sub("", folded)


class NameIndex:
    """Normalised key -> {mod id: origins that produced it}.

    The origins are kept because they are what the output reports and what
    tells a reader WHY two mods share a key -- `autoplant3` is one mod's
    internal name and another's title, which looks like a coincidence until
    the origins are shown.
    """

    def __init__(self) -> None:
        self._keys: dict[str, dict[int, set[str]]] = {}

    def add(self, key_source: str, mod_id: int, origin: str) -> None:
        """Index one name of one mod. An empty key is dropped, not stored.

        Dropping rather than storing: a key nothing can ever legitimately
        match is not an entry, it is a collision waiting for the next name
        that also normalises to nothing.
        """
        key = normalise(key_source)
        if not key:
            return
        self._keys.setdefault(key, {}).setdefault(mod_id, set()).add(origin)

    def lookup(self, query: str) -> dict[int, set[str]]:
        """Every mod whose any name matches, with the origins that matched."""
        return self._keys.get(normalise(query), {})


# new_mod.py is what ALLOCATES a dev-build id: it counts down from 9999999,
# skipping the values sibling repos already use, and writes the result into the
# new mod's .envrc. install-macos.sh only reads that value back
# (`${FAKE_MOD_ID:?must be set in the mod's .envrc}`) -- it hands out nothing.
# The threshold below is the one utils/server.sh uses verbatim, so this tool
# and that one agree on what counts as a dev build.
FAKE_ID_MIN = 9999000

# Same bound steam_identity.py's own git call uses -- long enough for a git
# process to answer, short enough that a hung git does not hang this tool.
GIT_TIMEOUT_SECONDS = 10


@dataclasses.dataclass(frozen=True)
class InstalledMod:
    """One mod installed in the cache, read from TWO files rather than one.

    state.json -- the game's own record -- supplies mod_id, the live modfile
    (and with it the folder), the mod.io title and slug, and whether the mod
    is disabled. ModManifest.json INSIDE that folder supplies internal_name
    and source_files; state.json carries neither, which is exactly why an
    uninstalled mod's internal name is unknowable without a download.
    """

    mod_id: int
    modfile_id: int
    folder: Path
    internal_name: str
    title: str
    slug: str
    enabled: bool
    source_files: list[str]

    @property
    def is_fake_id(self) -> bool:
        """Whether this mod uses a dev build id rather than a published one."""
        return self.mod_id >= FAKE_ID_MIN

    @property
    def source_path(self) -> Path:
        """Where the mod's C# source lives inside its folder."""
        return self.folder / "Scripts"

    @property
    def ships_source(self) -> bool:
        """Whether the mod carries a Scripts directory at all."""
        return self.source_path.is_dir()


@dataclasses.dataclass(frozen=True)
class OwnMod:
    """A mod repository in this workspace, with the ids that name it."""

    repo: Path
    mod_name: str
    mod_id: int | None
    fake_id: int | None
    source_path: Path


def bottle_path() -> Path:
    """The CrossOver bottle, resolved exactly as server.sh resolves it.

    Checks CK_BOTTLE_PATH environment variable first, then falls back to
    CK_BOTTLE_NAME (defaulting to "Core Keeper") inside the standard CrossOver
    bottles directory.
    """
    explicit = os.environ.get("CK_BOTTLE_PATH")
    if explicit:
        return Path(explicit)
    name = os.environ.get("CK_BOTTLE_NAME", "Core Keeper")
    return Path.home() / "Library/Application Support/CrossOver/Bottles" / name


def read_installed(cache_dir: Path) -> tuple[list[InstalledMod], list[str]]:
    """Every mod the cache holds, taking the live folder from state.json.

    state.json rather than the folder name, because the cache keeps superseded
    folders -- CoreLib sat at 3177992_7710097 next to _7845185 -- and "highest
    modfile id wins" is a guess where state.json has the answer.

    Returns warnings rather than raising for a state.json read that lands mid-write:
    the running game rewrites that file, so a syntax error is transient and expected,
    and a traceback there would make a routine lookup look like a broken tool. A
    missing cache DIRECTORY is the opposite case and does raise -- that is a
    configuration error, and returning an empty list would read as "no such mod" for
    every query.

    The warnings carry one more thing besides a file that could not be read: a mod
    whose current folder is on disk but holds no ModManifest.json. It is left out of
    the returned list either way, and saying so is what separates "not installed"
    from "installed, but nothing here can be read".
    """
    if not cache_dir.is_dir():
        raise FileNotFoundError(
            f"no mod.io cache at {cache_dir} — set CK_BOTTLE_PATH (or CK_BOTTLE_NAME) "
            "if the bottle lives elsewhere"
        )

    warnings: list[str] = []
    state_file = cache_dir.parent / "state.json"
    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
    except FileNotFoundError:
        warnings.append(
            f"{state_file} is missing — cannot tell which folders are current"
        )
        return [], warnings
    except (json.JSONDecodeError, OSError) as error:
        warnings.append(
            f"{state_file} could not be read ({error}) — the game rewrites it while "
            "running, so this is usually transient"
        )
        return [], warnings

    disabled: set[str] = set()
    for user in (state.get("existingUsers") or {}).values():
        disabled |= {str(x) for x in user.get("disabledMods", [])}

    mods: list[InstalledMod] = []
    for mod_id, entry in (state.get("mods") or {}).items():
        modfile_id = (entry.get("currentModfile") or {}).get("id")
        if modfile_id is None:
            continue
        folder = cache_dir / f"{mod_id}_{modfile_id}"
        manifest = folder / "ModManifest.json"
        if not manifest.is_file():
            # A folder that does not exist at all is ordinary and silent:
            # state.json lists every subscribed mod, including ones whose
            # download has not happened yet. A folder that EXISTS without a
            # manifest is not -- that is the shape the superseded CoreLib
            # folder had -- and dropping it without a word makes the mod read
            # as "not installed" when the truth is "installed, but its
            # identity could not be checked". The first is a wrong answer, the
            # second a missing one, and this tool may only ever give the
            # second.
            if folder.is_dir():
                warnings.append(
                    f"{folder} is the current folder for mod {mod_id} but carries no "
                    "ModManifest.json — its internal name and file list cannot be "
                    "read, so this mod is left out of the index entirely"
                )
            continue
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as error:
            warnings.append(f"{manifest} could not be read ({error})")
            continue
        profile = entry.get("modObject") or {}
        mods.append(
            InstalledMod(
                mod_id=int(mod_id),
                modfile_id=int(modfile_id),
                folder=folder,
                internal_name=data.get("name", ""),
                title=profile.get("name", ""),
                slug=profile.get("name_id", ""),
                enabled=str(mod_id) not in disabled,
                source_files=[
                    f["path"]
                    for f in data.get("files", [])
                    if f.get("path", "").endswith(".cs")
                ],
            )
        )
    return mods, warnings


def read_own_mods(workspace: Path) -> list[OwnMod]:
    """One entry per identity asset (one mod directory in the workspace).

    A directory qualifies by carrying unity/<Mod>/Editor/<Mod>_modio.asset.
    A repository holding more than one mod directory therefore contributes
    more than one entry. We index by asset, not by repository, because the
    asset is what identifies the mod.

    A directory is identified as a mod repo by carrying the asset file,
    not by being a git repository: CoreKeeperModDocs is a checkout of someone
    else's documentation and would otherwise read as a mod whose dev build is
    parked somewhere.

    `modId: 0` reads as no id. new_mod.py scaffolds exactly that, so it is the
    state of every mod not yet published -- and two such repos indexed under
    the id 0 would collide with each other for no reason. They stay findable
    by name, which is all the identity they have yet.

    A fake id from .envrc is only accepted if it is at or above FAKE_ID_MIN,
    the threshold for dev-build ids. A below-threshold value is treated as
    absent, to avoid accepting a real mod.io id that is not actually installed
    as a dev build.
    """
    mods: list[OwnMod] = []
    for asset in sorted(workspace.glob("*/unity/*/Editor/*_modio.asset")):
        mod_dir = asset.parent.parent
        repo = mod_dir.parent.parent
        match = _MODIO_ID.search(asset.read_text(encoding="utf-8"))
        mod_id = int(match.group(1)) if match else 0

        fake_id = None
        envrc = repo / ".envrc"
        if envrc.is_file():
            fake_match = _FAKE_ID.search(envrc.read_text(encoding="utf-8"))
            if fake_match:
                candidate = int(fake_match.group(1))
                if candidate >= FAKE_ID_MIN:
                    fake_id = candidate

        mods.append(
            OwnMod(
                repo=repo,
                mod_name=mod_dir.name,
                mod_id=mod_id or None,
                fake_id=fake_id,
                source_path=mod_dir,
            )
        )
    return mods


# steam_backfill reads these out of the SDK's own mod.io config asset; the same
# three values drive the catalogue fetch, which is why SDK_PATH is an input of
# this tool and not only of a download.
_MODIO_CONFIG = "Assets/Resources/mod.io/config.asset"
_SERVER_URL = re.compile(r"^\s*serverURL:\s*(\S+)\s*$", re.MULTILINE)
_GAME_ID = re.compile(r"^\s*gameId:\s*(\d+)\s*$", re.MULTILINE)
# Identical to steam_backfill.py's own GAME_KEY, on purpose: an
# [A-Za-z0-9]{8,}-only pattern used to sit here, narrower than that twin's
# \S+ for no reason tied to this file's own needs -- a key the other file
# accepts must not be rejected here.
_GAME_KEY = re.compile(r"^\s*gameKey:\s*(\S+)\s*$", re.MULTILINE)

# The catalogue is small (312 mods when measured) but the API pages at 100.
_PAGE = 100

# Headroom, not a realistic ceiling: the real catalogue pages four times at
# _PAGE=100. This exists for the case where mod.io keeps sending non-empty
# pages while perpetually reporting a result_total the accumulated count
# never reaches -- without a cap that loops forever with no message and no
# way out, which is the failure shape a cap exists to rule out.
_MAX_PAGES = 50


@dataclasses.dataclass(frozen=True)
class CatalogueEntry:
    """One mod as mod.io's catalogue lists it, reduced to what a lookup needs.

    md5 is the live modfile's own `filehash.md5`, carried so that --download
    can check the bytes it receives against what mod.io says they are. It
    defaults to the empty string, which means "this mirror does not know" --
    either because mod.io omitted the field or because the mirror was written
    before this tool captured it. That is not an error and must not force a
    refetch: an old mirror resolves names exactly as well as a new one.
    """

    mod_id: int
    title: str
    slug: str
    modfile_id: int | None
    md5: str = ""


def cache_root() -> Path:
    """Where derived runtime state lives — never inside the repository.

    The mirror and anything --download fetches are a foreign service's data,
    not this repository's. Putting them in utils/ would TRACK them, because
    .gitignore excludes everything with /* and re-includes the whole directory
    with !/utils/ -- so every refresh would be a committable diff.
    """
    explicit = os.environ.get("CK_MOD_SOURCE_CACHE")
    if explicit:
        return Path(explicit)
    return Path.home() / "Library/Caches/ck-mod-source"


def read_catalogue(path: Path) -> list[CatalogueEntry]:
    """The mirrored catalogue, or an empty list when there is none to read.

    A damaged file reads as absent rather than raising: the only way to get
    one is an interrupted fetch, and the right response to half a download is
    to download it again, not to fail every lookup until a human intervenes.
    "Damaged" covers a missing file, truncated JSON, AND JSON that parses but
    is the wrong shape (entries that is not a list, an entry that is not a
    dict) -- there is no state of this file that means anything other than
    "discard it and fetch again", so the catch is wide on purpose. Contrast
    read_installed(), which narrows instead of widens: that file belongs to
    the running game, not to this module, so a broad catch there would hide a
    real defect in someone else's data rather than recover from our own.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [
            CatalogueEntry(
                mod_id=entry["id"],
                title=entry.get("name", ""),
                slug=entry.get("name_id", ""),
                modfile_id=entry.get("modfile"),
                # `or ""` rather than a .get() default: a mirror written
                # before this field existed omits the key, and a mod.io entry
                # with no hash sends it as null -- both mean "unknown", and
                # only the first would be caught by the default alone.
                md5=entry.get("md5") or "",
            )
            for entry in data.get("entries", [])
            if "id" in entry
        ]
    except (
        FileNotFoundError,
        OSError,
        json.JSONDecodeError,
        AttributeError,
        TypeError,
    ):
        return []


def _modio_config(sdk_path: Path) -> tuple[str, int, str]:
    """(serverURL, gameId, gameKey) out of the SDK's mod.io config asset."""
    text = (sdk_path / _MODIO_CONFIG).read_text(encoding="utf-8")
    server, game, key = (
        _SERVER_URL.search(text),
        _GAME_ID.search(text),
        _GAME_KEY.search(text),
    )
    if not (server and game and key):
        raise ValueError(f"{sdk_path / _MODIO_CONFIG} has no serverURL/gameId/gameKey")
    return server.group(1), int(game.group(1)), key.group(1)


def _curl(url: str) -> bytes:
    """Fetch a URL with curl.

    curl rather than urllib, and not out of preference: mod.io answers urllib
    with a 403 and curl with the data (docs/ck/publishing.md).
    """
    completed = subprocess.run(["curl", "-sSfL", url], capture_output=True, check=False)
    if completed.returncode != 0:
        raise ValueError(
            f"curl failed ({completed.returncode}) for {url.split('?')[0]}: "
            f"{completed.stderr.decode().strip()}"
        )
    return completed.stdout


def fetch_catalogue(sdk_path: Path, path: Path) -> list[CatalogueEntry]:
    """Mirror every mod mod.io lists for this game, reduced to four fields.

    Reduced because the raw listing is 2.0 MB of descriptions and statistics
    for the 30 KB that matters. Mirrored at all because the live search cannot
    do the job: _q matches the title alone, so a slug or an internal name
    returns nothing, and a title returns a ranked list rather than an answer.

    A short mirror is never written. There are two ways the paging can fail to
    complete -- the server keeps sending pages without the count ever reaching
    result_total (bounded by _MAX_PAGES), or it sends an EMPTY page while the
    count is still short of it -- and both raise. They have to be treated
    alike because their consequence is identical and silent: a catalogue
    missing whatever happened to sort after the gap presents later as "that
    mod does not exist", not as "the fetch went wrong".

    Also captures each entry's modfile md5, which --download verifies the
    bytes it receives against.
    """
    server, game, key = _modio_config(sdk_path)
    entries: list[dict] = []
    offset = 0
    for _ in range(_MAX_PAGES):
        query = urllib.parse.urlencode(
            {"api_key": key, "_limit": _PAGE, "_offset": offset}
        )
        page = json.loads(_curl(f"{server}/games/{game}/mods?{query}"))
        # .get(key, default) only substitutes for an ABSENT key -- a server
        # that sends the key with a null value (a real API violation, but one
        # we are not in a position to rule out) needs the same fallback.
        data = page.get("data")
        if data is None:
            data = []
        entries += data
        total = page.get("result_total")
        if total is None:
            total = len(entries)
        if len(entries) >= total:
            break
        if not data:
            raise ValueError(
                f"mod.io sent an empty page at offset {offset} after {len(entries)} "
                f"of a reported {total} mods — aborting instead of mirroring a short "
                "catalogue that would later look like a missing mod"
            )
        offset += _PAGE
    else:
        raise ValueError(
            f"mod.io catalogue still incomplete after {_MAX_PAGES} pages "
            f"({len(entries)} entries fetched) — aborting instead of mirroring a "
            "short catalogue that would later look like a missing mod"
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "id": e["id"],
                        "name": e.get("name", ""),
                        "name_id": e.get("name_id", ""),
                        "modfile": (e.get("modfile") or {}).get("id"),
                        # Read exactly the way steam_backfill.py reads the
                        # same field off the same object -- `or {}` twice,
                        # because mod.io sends both `modfile` and `filehash`
                        # as null for a mod with no published build.
                        "md5": ((e.get("modfile") or {}).get("filehash") or {}).get(
                            "md5"
                        )
                        or "",
                    }
                    for e in entries
                ]
            }
        )
    )
    return read_catalogue(path)


KIND_OWN = "own"
KIND_INSTALLED = "installed"
KIND_PARKED = "parked"
KIND_CATALOGUE = "catalogue"

# Whether the mod that was resolved is provably the mod that was asked for.
# Four values rather than a boolean, because the check has four outcomes and
# the two a boolean merges are the two furthest apart -- see Resolution.
IDENTITY_CONFIRMED = "confirmed"
IDENTITY_UNCHECKED = "unchecked"
IDENTITY_UNCONFIRMABLE = "unconfirmable"
IDENTITY_CONTRADICTED = "contradicted"


@dataclasses.dataclass
class Resolution:
    """Where a query landed, described as far as the evidence supports.

    modfile_id is the specific build a download would fetch -- only the
    catalogue mirror carries it, so it stays None whenever no catalogue entry
    matched any of the resolved mod's ids. modfile_md5 is that same build's
    hash from that same entry, and is what --download checks the bytes it
    receives against; "" means the mirror does not know it.

    downloaded and identity are independent facts about the SAME fetch, not
    two names for one thing. downloaded says whether THIS RUN populated
    source_path by fetching the mod (main() sets it once download() returns);
    identity says how the check against the archive's own ModManifest.json
    came out. A verified download and a refuted one differ in the check's
    RESULT, not in whether a download happened -- collapsing the two onto one
    flag is how _status_phrase used to report a verified download as
    "installed", as if it had already been there before this run.

    identity has four values because the check has four outcomes:

    - IDENTITY_CONFIRMED -- the name comes from local ground truth (an own
      mod's own directory, an installed mod's own manifest), or a downloaded
      manifest agreed with the query. The default, because every kind except
      a catalogue-only hit starts here.
    - IDENTITY_UNCHECKED -- a catalogue-only hit. Its internal name exists
      only inside a ModManifest.json, and nothing short of a download can see
      one, so the check has not run and cannot.
    - IDENTITY_UNCONFIRMABLE -- a download happened, but its manifest could
      not be read (bad JSON, wrong shape, a non-string name), so the check
      could not run on what did arrive.
    - IDENTITY_CONTRADICTED -- the check RAN and the downloaded mod calls
      itself something that is neither the queried title nor its slug.

    The last two are why this is not a boolean. "Could not be confirmed" and
    "was refuted" are one value in a boolean and opposite answers to the only
    question this tool exists to answer, and a renderer given the boolean can
    only report the weaker of the two.
    """

    kind: str
    mod_id: int | None
    internal_name: str | None
    title: str
    slug: str
    source_path: Path | None
    modfile_id: int | None = None
    modfile_md5: str = ""
    identity: str = IDENTITY_CONFIRMED
    downloaded: bool = False
    notes: list[str] = dataclasses.field(default_factory=list)
    source_files: list[str] = dataclasses.field(default_factory=list)


class Workspace:
    """The three sources, indexed together and resolvable by any name.

    Built rather than constructed so that the read of each source stays
    testable on its own, and so a caller can hand in synthetic paths.
    """

    def __init__(
        self,
        installed: list[InstalledMod],
        own: list[OwnMod],
        catalogue: list[CatalogueEntry],
        warnings: list[str],
    ) -> None:
        self.installed = {m.mod_id: m for m in installed}
        self.own = own
        self.catalogue = {c.mod_id: c for c in catalogue}
        self.warnings = list(warnings)

        # A repo claims both its ids: the real one names its subscription, the
        # fake one its dev build. Mapping both to the repo is what turns "dev
        # build beside subscription" from an ambiguity into two locations. A
        # mod with neither (never published, no dev build installed -- what
        # new_mod.py scaffolds, so the state of every mod not yet shipped)
        # falls back to a synthetic id from _claimed_ids so it still lands in
        # the index instead of silently having no identity at all.
        #
        # Two mod directories claiming the SAME id is a state that really
        # occurs: copying a repo is how a mod gets started here, and a
        # <Mod>_modio.asset or a FAKE_MOD_ID that was never reset leaves both
        # copies claiming one id. It used to be settled by whichever one this
        # loop reached last -- so a query for the one answered with the
        # other's path and name, which is precisely the wrong answer this
        # tool must never give. An id two directories claim identifies
        # neither, so it is withdrawn from both and reported; each keeps its
        # synthetic id and stays findable under its own name.
        #
        # Kept on the instance, not consumed here, because a warning printed
        # to stderr is not an answer: _describe has to be able to put the
        # contest into the resolution itself, which is what both renderers
        # carry and what a dispatched agent reads.
        claims: dict[int, list[OwnMod]] = {}
        for mod in own:
            for claimed in self._claimed_ids(mod):
                claims.setdefault(claimed, []).append(mod)
        self.contested: dict[int, list[OwnMod]] = {
            i: claimants for i, claimants in claims.items() if len(claimants) > 1
        }
        for identifier in sorted(self.contested):
            directories = ", ".join(
                sorted(str(m.source_path) for m in self.contested[identifier])
            )
            self.warnings.append(
                f"mod id {identifier} is claimed by more than one mod directory "
                f"({directories}) — a copied repo whose <Mod>_modio.asset or "
                "FAKE_MOD_ID was never reset looks exactly like this. That id now "
                "identifies neither of them: each stays findable under its own name, "
                "and no installed build or catalogue entry carrying it is attributed "
                "to either"
            )

        self.owner_of: dict[int, OwnMod] = {}
        own_ids: list[tuple[OwnMod, list[int]]] = []
        for mod in own:
            ids = [i for i in self._claimed_ids(mod) if i not in self.contested] or [
                self._synthetic_id(mod)
            ]
            own_ids.append((mod, ids))
            for claimed in ids:
                self.owner_of[claimed] = mod

        self.index = NameIndex()
        for mod in installed:
            self.index.add(mod.internal_name, mod.mod_id, ORIGIN_INTERNAL)
            self.index.add(mod.title, mod.mod_id, ORIGIN_TITLE)
            self.index.add(mod.slug, mod.mod_id, ORIGIN_SLUG)
        for entry in catalogue:
            self.index.add(entry.title, entry.mod_id, ORIGIN_TITLE)
            self.index.add(entry.slug, entry.mod_id, ORIGIN_SLUG)
        for mod, ids in own_ids:
            for claimed in ids:
                self.index.add(mod.mod_name, claimed, ORIGIN_INTERNAL)

    @staticmethod
    def _synthetic_id(mod: OwnMod) -> int:
        """An id for a mod that has none of its own, unique to its directory.

        Negative, so it can never collide with a real mod.io id (always
        positive) or a dev-build id (always >= FAKE_ID_MIN). Derived from the
        mod's own directory (source_path), NOT the repository --
        read_own_mods yields one entry per identity asset, so a repository
        holding more than one mod directory under unity/ would otherwise give
        two unpublished mods the same synthetic id from a shared repo path,
        and the second would silently overwrite the first in owner_of and the
        index. source_path is unique per mod regardless of how many mods
        share a repo. It is never shown to a caller: _describe reports
        owner.mod_id, which stays None for a mod that has no real id.
        """
        return -(abs(hash(str(mod.source_path))) or 1)

    @classmethod
    def _claimed_ids(cls, mod: OwnMod) -> list[int]:
        """The ids that name this mod: real, dev-build, or a synthetic one.

        A mod with neither a real id (never published) nor a dev-build id (no
        local dev build installed) would otherwise contribute nothing to the
        index -- yet that is the state of every mod new_mod.py scaffolds,
        which is precisely while someone is actively working on it, and
        read_own_mods's own docstring already promises it stays "findable by
        name, which is all the identity they have yet".

        These are the ids the mod CLAIMS, not necessarily the ones it gets:
        __init__ withdraws any that a second mod directory claims too.
        """
        claimed = [i for i in (mod.mod_id, mod.fake_id) if i is not None]
        return claimed or [cls._synthetic_id(mod)]

    @classmethod
    def build(
        cls, cache_dir: Path | None, workspace: Path, catalogue_path: Path
    ) -> "Workspace":
        """Read all three sources and index them.

        cache_dir=None skips the cache read rather than probing a directory
        that may not exist -- a caller with no bottle to offer (a fresh test,
        a machine with no CrossOver bottle yet) should not have to invent a
        path just to dodge read_installed's own FileNotFoundError.
        """
        installed, warnings = ([], [])
        if cache_dir is not None:
            installed, warnings = read_installed(cache_dir)
        return cls(
            installed,
            read_own_mods(workspace),
            read_catalogue(catalogue_path),
            warnings,
        )

    def _group(self, hits: dict[int, set[str]]) -> dict[object, list[int]]:
        """Collapse ids that belong to one mod onto one group key.

        An own mod's real id and fake id are two keys in `hits` but one
        candidate: they both come from the SAME OwnMod object, so they share
        its source_path. Everything else groups on its own id, since nothing
        else ties two ids to the same mod.

        Keys on source_path, not repo: a repo can hold more than one mod
        directory under unity/ (read_own_mods yields one entry per identity
        asset), and two of them whose names normalise to the same key --
        "ToolResizer" and "Tool-Resizer" -- would otherwise share `repo` and
        collapse into one group, silently hiding one of two genuinely
        different mods behind a single candidate instead of reporting the
        real ambiguity.
        """
        groups: dict[object, list[int]] = {}
        for mod_id in hits:
            owner = self.owner_of.get(mod_id)
            key = owner.source_path if owner is not None else mod_id
            groups.setdefault(key, []).append(mod_id)
        return groups

    def resolve(self, query: str) -> Resolution | list[Resolution]:
        """One Resolution, or a list of candidates when genuinely ambiguous.

        Never a best guess. A display title is not an identity -- two authors
        ship a "Tool Resizer" -- and the cost of choosing wrong is an agent
        reading a different mod's source and reporting confidently about it.
        """
        if not normalise(query):
            raise ValueError(f"{query!r} has no letters or digits to match on")

        hits = self.index.lookup(query)
        if not hits:
            raise LookupError(f"no mod matches {query!r}")

        groups = self._group(hits)
        if len(groups) > 1:
            # Every candidate is described from its OWN id list, not just its
            # first (dict-insertion-order, not sort-order) member -- an own
            # mod's real id and fake id can both be in `hits` while this
            # candidate is still only one of several genuinely different
            # mods, and describing it from a single arbitrary id would hide
            # whichever catalogue entry or dev-build note sits under the
            # other one.
            return [self._describe(ids) for ids in groups.values()]
        (ids,) = groups.values()
        return self._describe(ids)

    def _describe(self, ids: list[int]) -> Resolution:
        """Build the Resolution for one already-resolved group of ids.

        Takes the whole group, where it used to take a representative id AND
        the group beside it. Both call sites passed the group and its own
        minimum, so the pair could only ever disagree through a caller's
        mistake -- and the fallback that covered an omitted group was
        unreachable from either of them.

        Checked in this order -- own, then installed, then catalogue-only --
        because a repo in this workspace is the strongest evidence available,
        an installed copy is the next best (it is what actually runs), and a
        catalogue-only hit is what is left once neither exists locally.
        """
        ids = sorted(ids)
        owner = self.owner_of.get(ids[0])
        installed = next((self.installed[i] for i in ids if i in self.installed), None)
        entry = next((self.catalogue[i] for i in ids if i in self.catalogue), None)
        modfile_id = entry.modfile_id if entry else None
        modfile_md5 = entry.md5 if entry else ""
        notes: list[str] = []

        if owner is not None:
            # The mod_id below is reported straight off the OwnMod, and a
            # contested one is still printed there -- it is what the repo's
            # own asset says. So the resolution has to admit that the id
            # names more than one directory. __init__ already warns, but a
            # warning goes to stderr and is dropped, and this is the same
            # shape of defect as a download proved wrong that renders clean:
            # the tool knowing something the answer does not say.
            for claimed in (owner.mod_id, owner.fake_id):
                if claimed is None or claimed not in self.contested:
                    continue
                rivals = ", ".join(
                    sorted(
                        str(m.source_path)
                        for m in self.contested[claimed]
                        if m.source_path != owner.source_path
                    )
                )
                notes.append(
                    f"mod id {claimed} is claimed by another mod directory as well "
                    f"({rivals}) — it identifies neither of them, so nothing "
                    "installed or listed under that id is attributed to this mod"
                )
            dev = next(
                (
                    self.installed[i]
                    for i in ids
                    if i in self.installed and self.installed[i].is_fake_id
                ),
                None,
            )
            if dev is not None:
                notes.append(f"also built as a dev build at {dev.folder}")
            return Resolution(
                kind=KIND_OWN,
                mod_id=owner.mod_id,
                internal_name=owner.mod_name,
                title=entry.title if entry else (installed.title if installed else ""),
                slug=entry.slug if entry else (installed.slug if installed else ""),
                source_path=owner.source_path,
                modfile_id=modfile_id,
                modfile_md5=modfile_md5,
                notes=notes,
            )

        if installed is not None:
            if installed.is_fake_id:
                notes.append(
                    "temporary: this fake id belongs to no mod repo, so it is a foreign "
                    "mod parked locally — a mod.io sync deletes such entries"
                )
                kind = KIND_PARKED
            else:
                kind = KIND_INSTALLED
            if not installed.ships_source:
                notes.append("ships no Scripts/ — this mod is assets only")
            if not installed.enabled:
                notes.append("installed but disabled in the game's mod menu")
            return Resolution(
                kind=kind,
                mod_id=installed.mod_id,
                internal_name=installed.internal_name,
                title=installed.title,
                slug=installed.slug,
                source_path=installed.source_path,
                modfile_id=modfile_id,
                modfile_md5=modfile_md5,
                notes=notes,
                source_files=installed.source_files,
            )

        return Resolution(
            kind=KIND_CATALOGUE,
            mod_id=entry.mod_id,
            internal_name=None,
            title=entry.title,
            slug=entry.slug,
            source_path=None,
            modfile_id=modfile_id,
            modfile_md5=modfile_md5,
            identity=IDENTITY_UNCHECKED,
            notes=[
                (
                    "not installed — internal name unknown, it exists only in a "
                    "ModManifest.json, so this hit could be a different mod with a "
                    "similar title"
                )
            ],
        )


def find_file(resolution: Resolution, needle: str) -> Path | list[Path]:
    """The absolute path of the one .cs file whose filename contains needle.

    Returns the file's absolute path when exactly one matches. Returns a sorted
    list of absolute paths when several match. Raises LookupError when none do
    or when the mod is not installed.

    Matching is against the filename only (p.name), not the path -- so a needle
    like "Config" finds ConfigScope.cs, not every file in a Config/ directory.
    """
    if resolution.source_path is None:
        raise LookupError(
            f"{resolution.title or resolution.internal_name} is not installed — "
            "fetch it with --download before asking for a file"
        )

    if resolution.source_files:
        # Installed mod: match against filename only, but keep the full relative path.
        matches = sorted(
            [
                f
                for f in resolution.source_files
                if needle.lower() in Path(f).name.lower()
            ]
        )
        root = resolution.source_path.parent
    else:
        # Own mod, or one this run downloaded: no manifest to read a file list
        # out of, so it comes from the walk _walked_source_files does. Shared
        # rather than repeated, so the path this hands back and the .cs count
        # the report prints beside it can never come from two different
        # traversals of the same directory.
        matches = sorted(
            f
            for f in _walked_source_files(resolution)
            if needle.lower() in Path(f).name.lower()
        )
        root = resolution.source_path

    if not matches:
        raise LookupError(f"no .cs file matching {needle!r}")
    if len(matches) > 1:
        return [(root / m).resolve() for m in matches]
    return (root / matches[0]).resolve()


def download(
    resolution: Resolution, sdk_path: Path, into: Path
) -> tuple[Path, list[str]]:
    """Fetch one mod's published build and settle whether it is the mod asked for.

    Only ever for a catalogue-only resolution that has no source of its own.
    main()'s branch already establishes that, and the guard below establishes
    it again, because everything after it assumes it: called on any other
    resolution this would fetch a foreign archive and unpack it over an
    installed mod's cache folder or a repository in this workspace. A
    precondition that holds only because the single caller happens to satisfy
    it is not an enforced one.

    steam_backfill's download_release deletes its own scratch directory once
    the bytes are re-uploaded -- it only ever needed the bytes in transit. The
    unpacked copy here is the opposite case: it IS the answer this tool exists
    to give, so it stays under `into` for an agent to read after this function
    returns, rather than being cleaned up on the way out.

    Two checks run, in the order in which their failures matter.

    The BYTES are checked first, against the md5 the catalogue mirror carries
    for this modfile -- the same check steam_backfill.download_release makes,
    for the same reason. An archive whose bytes are not what mod.io says they
    are is not unpacked at all, so that one raises. A mirror that does not
    know the hash (written before this tool captured it, or an entry mod.io
    sends without one) cannot check: that is reported rather than passed over
    in silence, but it does not stop the download, since an old mirror
    resolves names exactly as well as a new one.

    The IDENTITY is checked second, once the files are on disk, and it is what
    makes a provisional hit final. A catalogue-only hit's internal name is
    unknowable ahead of time -- it exists only inside a ModManifest.json,
    which nothing short of a download can see -- and two mods can normalise
    onto one lookup key through different name spaces (AutoPlant3 is one
    mod's internal name and another mod's title). So the archive settles it,
    into one of the three outcomes Resolution.identity distinguishes: the
    manifest name agrees with the queried title or slug (CONFIRMED), it could
    not be read at all (UNCONFIRMABLE), or it names a different mod
    (CONTRADICTED).

    Every outcome other than CONFIRMED is written to resolution.notes as well
    as to the returned warnings, and that duplication is the point. The
    warnings are printed once to stderr and dropped; the resolution is what
    both renderers carry, and what a dispatched agent is handed. A download
    this tool has ALREADY PROVED is a different mod must not reach that agent
    as a clean answer.

    The extracted files come back in all three cases: the caller asked for
    them and they are on disk. A refuted identity is a reason to distrust the
    answer, not a reason to withhold what was fetched.
    """
    if resolution.kind != KIND_CATALOGUE or resolution.source_path is not None:
        raise ValueError(
            "download() only ever fetches a catalogue-only resolution that has no "
            f"source of its own; this one is {resolution.kind!r} with source_path "
            f"{resolution.source_path}"
        )

    server, game, key = _modio_config(sdk_path)
    url = (
        f"{server}/games/{game}/mods/{resolution.mod_id}/files/"
        f"{resolution.modfile_id}/download?api_key={key}"
    )
    payload = _curl(url)

    warnings: list[str] = []
    if resolution.modfile_md5:
        digest = hashlib.md5(payload).hexdigest()
        if digest != resolution.modfile_md5:
            # Raised before the archive is opened, let alone extracted: bytes
            # that are not the bytes mod.io published are not this mod's
            # source, whatever they unpack into.
            raise ValueError(
                f"mod {resolution.mod_id}'s modfile {resolution.modfile_id} arrived "
                f"with md5 {digest}, mod.io says {resolution.modfile_md5} — refusing "
                "to unpack it"
            )
    else:
        unverified = (
            "the mirrored catalogue carries no md5 for this build, so the bytes that "
            "arrived could not be checked against mod.io — re-run with --refresh to "
            "record it"
        )
        warnings.append(unverified)
        resolution.notes.append(unverified)

    target = into.resolve()
    try:
        # The whole archive lifecycle -- open, list, extract -- is inside this
        # try: a truncated or corrupted response can raise BadZipFile at any
        # of those three points, not only at construction, and all of them
        # mean the same thing to a caller: the download did not produce a
        # usable archive. Re-raised as ValueError so main()'s existing
        # `except (ValueError, OSError)` around this call already handles it
        # -- without this, BadZipFile (neither a ValueError nor an OSError)
        # would escape as a raw traceback instead of a clean error message,
        # the same class of gap the manifest read below is already guarded
        # against.
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            # Validated in full BEFORE the first write. A member found bad
            # halfway through extractall() would leave every member before it
            # on disk -- a partial write is still a write, and this archive
            # comes from a foreign server, so a member name cannot be trusted
            # before it is checked against the directory it is about to land
            # in.
            for member in archive.namelist():
                # `target / member` discards `target` outright when `member`
                # is itself absolute -- that is pathlib's own join rule for
                # `/`, not a bug here -- but the joined result then fails
                # is_relative_to exactly like a "../" traversal does, so this
                # one check catches both kinds of escape without telling them
                # apart.
                destination = (target / member).resolve()
                if not destination.is_relative_to(target):
                    raise ValueError(
                        f"refusing to extract {member!r} from mod {resolution.mod_id} "
                        f"— it would land outside {target}"
                    )
            # Created only once every member is known-safe: a rejected or
            # corrupted archive must not leave an empty directory behind for
            # the next run to find and mistake for a completed download.
            target.mkdir(parents=True, exist_ok=True)
            archive.extractall(target)
    except zipfile.BadZipFile as error:
        raise ValueError(
            f"mod {resolution.mod_id}'s modfile {resolution.modfile_id} download is "
            f"not a valid zip archive ({error}) — it may have been corrupted or "
            "truncated in transit"
        ) from error

    manifest = target / "ModManifest.json"
    if manifest.is_file():
        # The archive is foreign data, so a manifest that is not valid JSON,
        # not a JSON object, or whose "name" is not a string must not crash a
        # download that otherwise already succeeded -- the files are on disk
        # either way, and only the name comparison below becomes impossible.
        # Caught narrowly, naming the errors a malformed manifest actually
        # produces (read_catalogue's justification for a wide catch does not
        # apply: this file is not our own cache, and a read failure that is
        # NOT one of these shapes is a real defect worth seeing).
        try:
            internal = json.loads(manifest.read_text(encoding="utf-8")).get("name", "")
            if not isinstance(internal, str):
                raise TypeError(f"'name' is {type(internal).__name__}, not a string")
        except (json.JSONDecodeError, AttributeError, TypeError) as error:
            # internal_name is deliberately left untouched: a name that could
            # not be read is not evidence, and half-applying the update would
            # put an unverified string where a verified one belongs.
            resolution.identity = IDENTITY_UNCONFIRMABLE
            unreadable = (
                f"{manifest} carries no readable mod name ({error}) — the downloaded "
                "mod's identity could not be checked against the query"
            )
            warnings.append(unreadable)
            resolution.notes.append(unreadable)
        else:
            resolution.internal_name = internal
            if normalise(internal) in {
                normalise(resolution.title),
                normalise(resolution.slug),
            }:
                resolution.identity = IDENTITY_CONFIRMED
            else:
                # The check ran and came back negative. That is a stronger
                # statement than "could not confirm", and the resolution has
                # to carry it: this used to set identity to confirmed one
                # line above and then report the contradiction into a warning
                # list that main() prints and discards, so both renderers
                # showed a clean, settled answer for a download already
                # proved to be a different mod.
                resolution.identity = IDENTITY_CONTRADICTED
                mismatch = (
                    f"the downloaded mod calls itself {internal!r}, which matches "
                    f"neither {resolution.title!r} nor its slug {resolution.slug!r} "
                    "— this is not the mod that was asked for, or mod.io's listing "
                    "and the build disagree"
                )
                warnings.append(mismatch)
                resolution.notes.append(mismatch)
    else:
        # An archive with no manifest at all. The download succeeded, so the
        # resolution is no longer UNCHECKED ("no download has happened"); the
        # check simply had nothing to run against, which is what
        # UNCONFIRMABLE says.
        resolution.identity = IDENTITY_UNCONFIRMABLE
        absent = (
            "the downloaded archive contains no ModManifest.json — the mod's "
            "identity could not be checked against the query"
        )
        warnings.append(absent)
        resolution.notes.append(absent)
    return target, warnings


def _installed_mods_dir() -> Path:
    """Where mod.io unpacks installed mods, inside the CrossOver bottle.

    The same suffix utils/server.sh's own MODIO_CACHE appends: 5289 is Core
    Keeper's mod.io game id, fixed and identical everywhere it is used in
    this repository (docs/ck/platforms.md). Kept separate from cache_root()
    on purpose -- that directory is THIS tool's own derived state (the
    catalogue mirror, a --download target); this one belongs to the game's
    own mod.io client and is only ever read, never written.
    """
    return bottle_path() / "drive_c/users/Public/mod.io/5289/mods"


def _catalogue_path() -> Path:
    """Where the mirrored catalogue lives -- the one file under cache_root()."""
    return cache_root() / "catalogue.json"


def _sdk_path() -> Path | None:
    """SDK_PATH from the environment, or None when it is not set.

    None rather than an exception, because the two call sites need opposite
    things from the same absence and only they can decide which. The
    catalogue refresh warns and carries on: every lookup that does not need a
    fresh mirror still works without it. A --download cannot carry on at all
    -- the mod.io server URL, game id and read-only key live in that SDK
    asset and there is nowhere else to read them from -- so main() prints an
    error there and exits 1. Absent is therefore a hard failure on exactly
    one of the two paths.
    """
    value = os.environ.get("SDK_PATH")
    return Path(value) if value else None


def _git_common_dir(start: Path) -> str | None:
    """`git -C <start> rev-parse --git-common-dir`'s raw stdout, or None.

    None covers every way git can fail to answer: no git binary, `start` is
    not inside a repository, or the process errors out -- callers treat all
    three alike. Kept apart from the path arithmetic in _default_workspace()
    so a test can monkeypatch exactly this call and assert on the resolution
    logic without a real worktree on disk.
    """
    if shutil.which("git") is None:
        return None
    # GIT_DIR / GIT_INDEX_FILE outrank -C and are inherited when this runs
    # under a git hook, which would point git at whatever repository invoked
    # US rather than at `start`'s own checkout -- the same hazard
    # steam_identity.is_tracked and check_docs_links.markdown_files already
    # defend against.
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    try:
        completed = subprocess.run(
            ["git", "-C", str(start), "rev-parse", "--git-common-dir"],
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SECONDS,
            env=env,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def _default_workspace() -> Path:
    """Where this repo's own mod repositories live -- git-resolved, worktree-safe.

    Path(__file__).resolve().parent.parent is only correct OUTSIDE a git
    worktree. CLAUDE.md mandates that all work happen in a worktree under
    REPO_ROOT/.worktrees/, and a worktree is a small, isolated checkout that
    does not contain the sibling mod repositories at all -- they are
    separate git repos, excluded by the parent .gitignore and never checked
    out into a worktree. So from inside one, __file__'s own directory has no
    sibling mods to find, read_own_mods() returns empty, and every one of
    this workspace's own mods -- including an installed dev build -- is
    reported as a foreign mod merely parked locally. Both halves of that
    contradiction lived in this same repository's CLAUDE.md: the rule that
    tells a session to run this tool unqualified, and the rule that tells
    every session to work from a worktree.

    `git rev-parse --git-common-dir` answers the question a worktree
    actually needs asked: it names the ONE .git directory every worktree of
    a repository shares, so its parent is always the MAIN checkout -- where
    the sibling mod repos actually sit -- whether this process happens to
    run from the main checkout or from a worktree of it.

    Falls back to the old __file__-based default whenever git cannot answer
    (no git binary, not a repository, a timeout) or answers with something
    that does not look like a real .git directory -- this tool must keep
    working without git, exactly as it always could.
    """
    fallback = Path(__file__).resolve().parent.parent
    here = Path(__file__).resolve().parent
    raw = _git_common_dir(here)
    if raw is None:
        return fallback
    common_dir = (here / raw).resolve()
    if common_dir.name != ".git" or not common_dir.is_dir():
        return fallback
    return common_dir.parent


def _display_name(resolution: Resolution) -> str:
    """The header name -- what a human most likely searched for.

    Title first, not the internal name: it is the name that exists for every
    kind except a brand-new own mod with no catalogue entry, whereas the
    internal name is exactly the field a catalogue-only hit does NOT have
    (Workspace._describe leaves it None until a download settles it).

    The mod id is the last fallback and is genuinely reachable: an installed
    mod whose ModManifest.json carries an empty "name" and whose state.json
    profile carries an empty one too has neither name, and always has an id.
    What cannot occur is no name AND no id -- mod_id is None only for an own
    mod, and an own mod's internal name is its own directory name, which the
    glob that found it cannot have matched empty. A fixed "(unpublished mod)"
    used to sit below this, claiming to cover exactly the state new_mod.py
    scaffolds; that state returns at the internal-name check two lines above
    and never reached it. So the impossible case now raises instead of being
    given a plausible-looking name: a resolution that can name itself in no
    way at all is a defect in whatever built it, and a fixed string would
    print over it.
    """
    if resolution.title:
        return resolution.title
    if resolution.internal_name:
        return resolution.internal_name
    if resolution.mod_id is not None:
        return f"mod {resolution.mod_id}"
    raise ValueError(
        "this resolution carries no title, no internal name and no mod id, so it "
        "cannot be named at all — no source this tool reads can produce that"
    )


def _status_phrase(resolution: Resolution) -> str:
    """The clause after the header's em dash: kind plus source availability.

    source_path being None (catalogue-only, never downloaded) and source_path
    existing but not being a directory (installed, but the mod ships no
    Scripts/) are different facts and must not collapse into the same
    "no source" phrase -- one means "not installed", the other "installed,
    assets only". A resolution a --download just settled looks like neither
    of the ordinary kinds: its `kind` is still KIND_CATALOGUE (classification
    is a property of how it was FOUND, not of what has happened to it since),
    but it now has a real source_path, so it reads as "installed" rather than
    "not installed" once one exists -- the whole reason main() updates
    source_path in place after a successful fetch instead of building a new
    Resolution.

    Selected on resolution.downloaded, NOT on identity -- identity only says
    how the check on the archive came out, and a verified download is still
    something THIS RUN fetched, not a mod that was already sitting installed.
    The two facts are reported separately: "downloaded" states what happened,
    and the identity is called out in addition to it rather than in place of
    it. It takes three phrasings, because a check that could not run and a
    check that came back negative are not the same news -- the second is the
    one an agent must not read past.
    """
    if resolution.source_path is None:
        return "not installed" + (
            ", provisional match" if resolution.identity == IDENTITY_UNCHECKED else ""
        )

    availability = (
        "source available" if resolution.source_path.is_dir() else "no source shipped"
    )
    if resolution.downloaded:
        if resolution.identity == IDENTITY_CONTRADICTED:
            status = "downloaded, identity mismatch"
        elif resolution.identity == IDENTITY_CONFIRMED:
            status = "downloaded"
        else:
            status = "downloaded, identity unconfirmed"
    elif resolution.kind == KIND_OWN:
        status = "own mod in this workspace"
    elif resolution.kind == KIND_PARKED:
        status = "installed (temporary/foreign)"
    elif resolution.kind == KIND_INSTALLED:
        status = "installed"
    else:
        # Everything above is exhaustive over what this module builds, and a
        # silent "installed" used to sit here for whatever was left. That
        # phrase is plausible for any input, which is what makes it the wrong
        # default: it would report a kind this function has never heard of,
        # and a catalogue-only resolution that acquired a source_path without
        # going through a download, as an ordinary installed mod.
        raise ValueError(
            f"cannot describe a {resolution.kind!r} resolution that has a source path "
            "without having been downloaded this run"
        )
    return f"{status}, {availability}"


def _names_line(resolution: Resolution) -> str:
    """One line naming the mod in all three spaces, plus its mod.io id.

    Every field defaults to a literal "unknown"/"unpublished" rather than
    being omitted -- a caller that only ever sees the line when it is
    complete could read a missing field as "this tool didn't check", when
    what it actually means is "this name space has no answer yet".
    """
    internal = resolution.internal_name or "unknown"
    title = resolution.title or "unknown"
    slug = resolution.slug or "unknown"
    mod_id = resolution.mod_id if resolution.mod_id is not None else "unpublished"
    return f'internal {internal} · mod.io "{title}" · slug {slug} · modId {mod_id}'


def _walked_source_files(resolution: Resolution) -> list[str]:
    """.cs files under source_path, relative to it -- the fallback for when
    source_files is empty and there is no manifest to have populated it from.

    An own mod carries no manifest (ModManifest.json is build-generated, per
    read_own_mods's own docstring), and neither does a freshly downloaded
    catalogue-only mod the moment after main() points its source_path at the
    unpacked archive -- both need this walk instead. The one traversal every
    caller that needs it shares: find_file's own-mod branch, _source_count
    (render()'s Size line) and _resolution_payload (render_json()'s
    source_files), so none of those three can disagree with another about
    what "the same facts" means.
    """
    if resolution.source_path is None or not resolution.source_path.is_dir():
        return []
    return sorted(
        str(p.relative_to(resolution.source_path))
        for p in resolution.source_path.rglob("*.cs")
    )


def _source_count(resolution: Resolution) -> int | None:
    """How many .cs files ship, or None when that cannot be known.

    source_files comes straight from the manifest for an installed or parked
    mod -- no directory walk needed; otherwise this counts _walked_source_files.

    The label is one word ("Size") but the two paths answer different
    questions: for an installed or parked mod it is what the manifest says
    actually SHIPS, while for an own mod (no manifest exists to read) it is
    every .cs found under unity/<Mod>/, Editor-only scripts included, which
    never ship at all. Both are correct answers -- to different questions --
    so a comparison across kinds (own mod vs. its own published build) is not
    apples to apples even though the rendered line looks identical.
    """
    if resolution.source_files:
        return len(resolution.source_files)
    if resolution.source_path is not None and resolution.source_path.is_dir():
        return len(_walked_source_files(resolution))
    return None


def render(resolution: Resolution) -> str:
    """A resolution in the exact shape a dispatch prompt can carry unchanged.

    This is the requirement the whole tool is judged by. The originating
    failure was eight subagents sent to verify a claim about CoreLib: 19 of
    23 across the run were never told where its source was, and seven fell
    back to `find /` for up to 12h49m. A correct answer nobody can paste into
    a prompt as it stands changes nothing -- so the Source line is always an
    absolute path, the Names line spells the mod out in every name space it
    is known in, and the rest (the status clause, Size, Notes) is prose that
    stands on its own. Nothing here asks the reader to already know a mod id,
    a cache directory layout, or which of the three name spaces (internal,
    mod.io title, slug) actually matched.
    """
    lines = [f"{_display_name(resolution)}  —  {_status_phrase(resolution)}"]

    source = (
        str(resolution.source_path)
        if resolution.source_path is not None
        else "not installed — fetch it with --download"
    )
    lines.append(f"  Source    {source}")
    lines.append(f"  Names     {_names_line(resolution)}")

    count = _source_count(resolution)
    if count is not None:
        noun = ".cs file" if count == 1 else ".cs files"
        lines.append(f"  Size      {count} {noun}")

    if resolution.notes:
        lines.append("  Notes")
        for note in resolution.notes:
            lines.append(f"    - {note}")

    return "\n".join(lines)


def _resolution_payload(resolution: Resolution) -> dict:
    """Resolution as a JSON-safe dict, carrying the same facts render() does.

    dataclasses.asdict copies a Path field verbatim rather than converting
    it, and json.dumps cannot encode one -- so it is stringified explicitly
    here, on the one field known to hold a Path, rather than through a
    default= hook that would silently apply to any OTHER field that later
    became one. source_files is filled the same way render()'s Size line is
    (_walked_source_files) when it arrived empty -- an own mod, or a freshly
    downloaded catalogue-only mod, has no manifest to have populated it from,
    and asdict() alone would leave it at [] even though render() shows a
    nonzero .cs count for the very same resolution.
    """
    payload = dataclasses.asdict(resolution)
    payload["source_path"] = (
        str(resolution.source_path) if resolution.source_path is not None else None
    )
    if not payload["source_files"]:
        payload["source_files"] = _walked_source_files(resolution)
    return payload


def render_json(resolution: Resolution) -> str:
    """The same facts as render(), for a caller that parses rather than reads."""
    return json.dumps(_resolution_payload(resolution))


def main(argv: list[str] | None = None) -> int:
    """The CLI: resolve one query, optionally find one file in it or fetch it.

    Deliberately thin. Every piece of behaviour here already exists above
    with its own tests (Workspace.resolve, find_file, download, render) --
    this only wires argv to them and picks an exit code.
    """
    parser = argparse.ArgumentParser(
        prog="mod_source.py",
        description="Resolve a Core Keeper mod name to where its source lives.",
    )
    parser.add_argument("mod", help="internal name, mod.io title, or slug")
    parser.add_argument(
        "file",
        nargs="?",
        help="find one .cs file by (partial, case-insensitive) filename in the resolved mod",
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument(
        "--download",
        action="store_true",
        help="fetch the published build when the mod is not installed locally",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="refetch the mod.io catalogue mirror before resolving",
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        # Not `default=_default_workspace()`: argparse evaluates a default at
        # add_argument time, so that git subprocess ran on EVERY invocation
        # -- including the ones that pass --workspace explicitly and never
        # look at the answer. None here, resolved below only when it is
        # actually the value being used. The cost of spelling the default out
        # in words rather than through %(default)s is that --help no longer
        # prints the concrete path; the cost of the other arrangement was a
        # process spawn per run.
        default=None,
        help="directory holding this repo's own mods "
        "(default: the main checkout this file belongs to, resolved with git)",
    )
    args = parser.parse_args(argv)
    # Resolved here, once, rather than at each use site: an own mod's
    # source_path is derived from args.workspace (read_own_mods's glob), so a
    # relative --workspace would otherwise flow straight into the printed
    # Source line -- and AC2 requires every path in the output to be usable
    # in a dispatch prompt unchanged, which a path relative to some unknown
    # future cwd is not.
    args.workspace = (args.workspace or _default_workspace()).resolve()

    sdk_path = _sdk_path()
    catalogue_path = _catalogue_path()
    if args.refresh or not catalogue_path.is_file():
        # Checked once, before any fetch attempt: Workspace.build reads
        # catalogue_path regardless of whether the fetch below runs or
        # succeeds, so an EXISTING mirror is still used -- possibly stale,
        # but still usable, and an uninstalled mod still resolves through
        # it. The stronger claim ("proceeding with cache and repos only, a
        # mod that is not installed cannot be resolved") is true only when
        # there is no mirror at all to fall back on.
        fallback = (
            "proceeding with the mirror as it stands"
            if catalogue_path.is_file()
            else "proceeding with the cache and repos only, a mod that is "
            "not installed cannot be resolved"
        )
        if sdk_path is None:
            print(f"warning: SDK_PATH is not set — {fallback}", file=sys.stderr)
        else:
            try:
                fetch_catalogue(sdk_path, catalogue_path)
            except (ValueError, OSError) as error:
                print(
                    f"warning: could not refresh the mod.io catalogue ({error}) "
                    f"— {fallback}",
                    file=sys.stderr,
                )

    try:
        workspace = Workspace.build(
            _installed_mods_dir(), args.workspace, catalogue_path
        )
    except FileNotFoundError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    for warning in workspace.warnings:
        print(f"warning: {warning}", file=sys.stderr)

    try:
        result = workspace.resolve(args.mod)
    except (LookupError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    if isinstance(result, list):
        # Gated the same way the file-ambiguity branch below already is: the
        # count line is prose for a human, and printing it unconditionally
        # ahead of the JSON array is exactly what makes --json output on this
        # branch unparseable as JSON.
        if args.json:
            print(json.dumps([_resolution_payload(r) for r in result]))
        else:
            print(f"{len(result)} mods match {args.mod!r} — which one?")
            for candidate in result:
                print()
                print(render(candidate))
        return 2

    if args.download and result.source_path is None:
        if result.modfile_id is None:
            print(
                f"error: {result.title!r} has no published build to download",
                file=sys.stderr,
            )
            return 1
        if sdk_path is None:
            print(
                "error: --download needs SDK_PATH set in the environment",
                file=sys.stderr,
            )
            return 1
        into = cache_root() / "downloads" / f"{result.mod_id}_{result.modfile_id}"
        try:
            downloaded, warnings = download(result, sdk_path, into)
        except (ValueError, OSError) as error:
            print(f"error: download failed ({error})", file=sys.stderr)
            return 1
        for warning in warnings:
            print(f"warning: {warning}", file=sys.stderr)
        scripts = downloaded / "Scripts"
        result.source_path = scripts if scripts.is_dir() else downloaded
        # Set here, not inferred later from identity -- _status_phrase needs
        # to say "downloaded" regardless of how the identity check came out,
        # and identity alone cannot carry that: a verified download reads
        # CONFIRMED, exactly like a mod that was never fetched at all.
        result.downloaded = True
        # The "not installed" note _describe attached before the fetch is now
        # stale -- the mod just was installed, right here -- and notes are the
        # only place render() surfaces it, so leaving it in would print a
        # downloaded mod as still not installed. Matched on the note's OPENING
        # words rather than anywhere in it: download() puts its own notes into
        # this same list, and one of them has to survive this filter even
        # though it reports that the downloaded archive is *not* the mod that
        # was asked for.
        result.notes = [
            note for note in result.notes if not note.startswith("not installed")
        ]

    # A refuted identity is reported through the exit code as well as through
    # the output, and deliberately through the SAME code the ambiguity branch
    # above returns: both mean "resolved, but a human has to decide", and this
    # is the one that protects a caller which checks the code without parsing
    # the payload -- a shell step in a dispatch, a script. It must stop rather
    # than carry on with a mod this tool has proved is the wrong one. It adds
    # to the status line, the notes and the JSON; it replaces none of them.
    settled = 2 if result.identity == IDENTITY_CONTRADICTED else 0

    if args.file:
        try:
            found = find_file(result, args.file)
        except LookupError as error:
            print(f"error: {error}", file=sys.stderr)
            return 1
        if isinstance(found, list):
            if args.json:
                print(json.dumps([str(p) for p in found]))
            else:
                print(f"{len(found)} files match {args.file!r}:")
                for path in found:
                    print(path)
            return 2
        # Not 0 on a refuted identity either: the path is real, and it points
        # into a mod that is not the one that was asked for, which is exactly
        # the case where handing an agent a file path is most expensive.
        print(json.dumps(str(found)) if args.json else found)
        return settled

    print(render_json(result) if args.json else render(result))
    return settled


if __name__ == "__main__":
    sys.exit(main())
