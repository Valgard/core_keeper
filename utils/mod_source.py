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
