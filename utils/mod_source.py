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

import dataclasses
import json
import os
import re
import subprocess
import unicodedata
import urllib.parse
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


# install-macos.sh gives every dev build an id above the real catalogue; the
# same threshold server.sh uses, so the two agree on what a dev build is.
FAKE_ID_MIN = 9999000


@dataclasses.dataclass(frozen=True)
class InstalledMod:
    """One mod installed in the cache, with all names and metadata from state.json."""

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
        match = _MODIO_ID.search(asset.read_text())
        mod_id = int(match.group(1)) if match else 0

        fake_id = None
        envrc = repo / ".envrc"
        if envrc.is_file():
            fake_match = _FAKE_ID.search(envrc.read_text())
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
_GAME_KEY = re.compile(r"gameKey:[ \t]*([A-Za-z0-9]{8,})[ \t]*$", re.MULTILINE)

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
    """One mod as mod.io's catalogue lists it, reduced to what a lookup needs."""

    mod_id: int
    title: str
    slug: str
    modfile_id: int | None


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
    text = (sdk_path / _MODIO_CONFIG).read_text()
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

    Stops after _MAX_PAGES rather than looping forever, and raises instead of
    writing a short mirror when that happens: a truncated catalogue would
    otherwise present later as "that mod does not exist" for whatever
    happened to sort last, which is worse than a loud failure now.
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
        if len(entries) >= total or not data:
            break
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


@dataclasses.dataclass
class Resolution:
    """Where a query landed, described as far as the evidence supports.

    modfile_id is the specific build a download would fetch -- only the
    catalogue mirror carries it, so it stays None whenever no catalogue entry
    matched any of the resolved mod's ids.
    """

    kind: str
    mod_id: int | None
    internal_name: str | None
    title: str
    slug: str
    source_path: Path | None
    modfile_id: int | None = None
    provisional: bool = False
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
        self.owner_of: dict[int, OwnMod] = {}
        for mod in own:
            for claimed in self._claimed_ids(mod):
                self.owner_of[claimed] = mod

        self.index = NameIndex()
        for mod in installed:
            self.index.add(mod.internal_name, mod.mod_id, ORIGIN_INTERNAL)
            self.index.add(mod.title, mod.mod_id, ORIGIN_TITLE)
            self.index.add(mod.slug, mod.mod_id, ORIGIN_SLUG)
        for entry in catalogue:
            self.index.add(entry.title, entry.mod_id, ORIGIN_TITLE)
            self.index.add(entry.slug, entry.mod_id, ORIGIN_SLUG)
        for mod in own:
            for claimed in self._claimed_ids(mod):
                self.index.add(mod.mod_name, claimed, ORIGIN_INTERNAL)

    @staticmethod
    def _claimed_ids(mod: OwnMod) -> list[int]:
        """The ids that name this mod: real, dev-build, or a synthetic one.

        A mod with neither a real id (never published) nor a dev-build id (no
        local dev build installed) would otherwise contribute nothing to the
        index -- yet that is the state of every mod new_mod.py scaffolds,
        which is precisely while someone is actively working on it, and
        read_own_mods's own docstring already promises it stays "findable by
        name, which is all the identity they have yet". The synthetic id is
        negative so it can never collide with a real mod.io id (always
        positive) or a dev-build id (always >= FAKE_ID_MIN), and it is
        derived from the mod's own directory (source_path), NOT the
        repository -- read_own_mods yields one entry per identity asset, so a
        repository holding more than one mod directory under unity/ would
        otherwise give two unpublished mods the same synthetic id from a
        shared repo path, and the second would silently overwrite the first
        in owner_of and the index. source_path is unique per mod regardless
        of how many mods share a repo. It is never shown to a caller:
        _describe reports owner.mod_id, which stays None for a mod that has
        no real id.
        """
        claimed = [i for i in (mod.mod_id, mod.fake_id) if i is not None]
        if claimed:
            return claimed
        return [-(abs(hash(str(mod.source_path))) or 1)]

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
            return [self._describe(min(ids), all_ids=ids) for ids in groups.values()]
        (ids,) = groups.values()
        return self._describe(min(ids), all_ids=ids)

    def _describe(self, mod_id: int, all_ids: list[int] | None = None) -> Resolution:
        """Build the Resolution for one already-resolved group of ids.

        Checked in this order -- own, then installed, then catalogue-only --
        because a repo in this workspace is the strongest evidence available,
        an installed copy is the next best (it is what actually runs), and a
        catalogue-only hit is what is left once neither exists locally.
        """
        owner = self.owner_of.get(mod_id)
        ids = sorted(all_ids or [mod_id])
        installed = next((self.installed[i] for i in ids if i in self.installed), None)
        entry = next((self.catalogue[i] for i in ids if i in self.catalogue), None)
        modfile_id = entry.modfile_id if entry else None
        notes: list[str] = []

        if owner is not None:
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
            provisional=True,
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
        # Own mod: walk the directory, match against filename only.
        matches = sorted(
            [
                str(p.relative_to(resolution.source_path))
                for p in resolution.source_path.rglob("*.cs")
                if needle.lower() in p.name.lower()
            ]
        )
        root = resolution.source_path

    if not matches:
        raise LookupError(f"no .cs file matching {needle!r}")
    if len(matches) > 1:
        return [root / m for m in matches]
    return (root / matches[0]).resolve()
