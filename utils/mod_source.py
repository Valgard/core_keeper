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
import unicodedata
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
