"""Resolve a Core Keeper mod name to where its source actually lives.

The question this answers has no answer in the repository today beyond the
path pattern. docs/ck/reverse-engineering.md states that every installed mod
ships readable C# and gives the shape `<modId>_<modfileId>`; what is missing
is the step from a NAME to those numbers, and without it a dispatched agent
falls back to searching the filesystem.

A mod carries three names that routinely disagree -- NameChests is "More
Labels" on mod.io -- so the index covers all three at once rather than
privileging the internal one, which resolves only 88 % of installed mods.
"""

import re
import unicodedata

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
