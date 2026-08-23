"""Holds every `Choice` setting's enum to the localisation table that renders it.

A `Choice<T>` over an enum makes the C# member NAMES an external contract, twice
over. `SectionBuilder.Choice` persists the selected value as `value.ToString()`,
and the widget resolves each option's label as `<ModId>-Config/<key>/<name>`. So
renaming a member silently resets every player who chose it back to the default
AND drops its label to the raw token -- no error, no log, nothing in the build.

Both framework fallbacks are deliberately quiet, and a mod cannot change that.
The only place the drift can be caught is here: comparing the member names in the
C# against the leaves in `localization.yaml` turns a silent runtime degradation
into a red test in the same commit that introduces it.

Scope is discovered, not listed: every mod repo, every `Choice` call whose values
are enum members. Numeric choices (`new[] { 1, 2, 3 }`) are skipped on purpose --
the widget renders those numerically and they have no terms to check.
"""

import re

import new_mod as nm
import pytest

# .Choice(out var handle, "key", <values>, <default>) -- `values` is captured up
# to the last comma so the default stays out of it. Non-greedy across newlines,
# because CSharpier wraps these calls once they pass printWidth.
CHOICE_CALL = re.compile(
    r"\.Choice\s*\(\s*out\s+var\s+\w+\s*,\s*\"(?P<key>[^\"]+)\"\s*,(?P<values>.*?),(?P<default>[^,]*?)\)\s*(?:\.|;)",
    re.DOTALL,
)

# `Something.Member` inside a values expression -- the enum members offered.
QUALIFIED_MEMBER = re.compile(r"\b(?:\w+\.)*(?P<enum>\w+)\.(?P<member>\w+)\b")

# The whole-enum form: (T[])System.Enum.GetValues(typeof(T)).
GET_VALUES = re.compile(
    r"GetValues\s*\(\s*typeof\s*\(\s*(?:\w+\.)*(?P<enum>\w+)\s*\)\s*\)"
)


def _mod_repos():
    """Every sibling mod repo as (path, PascalCase MOD_NAME), enumerated live.

    Same discovery as the new_mod parity suite: a hardcoded roster is the thing
    this repo has repeatedly found stale, and resolve_mods_dir() works from a
    worktree too.
    """
    mods = []
    for git_entry in sorted(nm.resolve_mods_dir().glob("*/.git")):
        repo = git_entry.parent
        if repo.name == "CoreKeeperModSDK":
            continue
        envrc = repo / ".envrc.example"
        if not envrc.is_file():
            continue
        match = re.search(r'MOD_NAME="([^"]+)"', envrc.read_text())
        if match:
            mods.append((repo, match.group(1)))
    return mods


def _enum_members(sources, enum_name):
    """The member names of `enum_name`, or None if no such enum is declared.

    Reads the body between the declaration's braces and takes each leading
    identifier, so XML docs, attributes and trailing commas do not matter.
    Explicit values (`Foo = 3`) keep only the name, which is what ToString()
    yields and therefore what the term key uses.
    """
    for text in sources:
        match = re.search(rf"\benum\s+{re.escape(enum_name)}\b\s*\{{", text)
        if not match:
            continue
        depth, start = 1, match.end()
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    body = text[start:i]
                    break
        else:
            return None
        members = []
        for line in body.splitlines():
            line = line.strip()
            if (
                not line
                or line.startswith("//")
                or line.startswith("/")
                or line.startswith("[")
            ):
                continue
            name = re.match(r"(\w+)", line)
            if name:
                members.append(name.group(1))
        return members
    return None


def _enum_choices(repo):
    """Every enum-valued Choice in `repo`, as (setting key, enum name, members).

    Numeric and other non-enum choices yield nothing: they have no labels to
    localise, so including them would produce failures for terms that are
    correctly absent.
    """
    sources = [
        p.read_text(encoding="utf-8") for p in sorted(repo.glob("unity/**/*.cs"))
    ]
    found = []
    for text in sources:
        for call in CHOICE_CALL.finditer(text):
            key, values = call.group("key"), call.group("values")

            whole_enum = GET_VALUES.search(values)
            if whole_enum:
                enum_name = whole_enum.group("enum")
                members = _enum_members(sources, enum_name)
                if members:
                    found.append((key, enum_name, members))
                continue

            listed = QUALIFIED_MEMBER.findall(values)
            if not listed:
                continue
            enum_name = listed[0][0]
            # All values must name the same enum; a mixed list means the regex
            # caught something else, and guessing at it would invent failures.
            if any(owner != enum_name for owner, _ in listed):
                continue
            if _enum_members(sources, enum_name) is None:
                continue
            found.append((key, enum_name, [member for _, member in listed]))
    return found


def _yaml_leaves(path, namespace):
    """Leaf keys directly under `namespace:` in a localisation table.

    Deliberately a small indent-aware scan rather than a YAML parser: the tables
    are two levels deep by construction (the generator rejects anything else),
    and this keeps the suite dependency-free.
    """
    if not path.is_file():
        return None
    leaves, inside = [], False
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if not raw[:1].isspace():
            inside = raw.rstrip().rstrip(":") == namespace
            continue
        if inside and re.match(r"^ {2}\S", raw):
            leaves.append(raw.strip().rstrip(":").split(":")[0].strip())
    return leaves if inside or leaves else None


MODS = _mod_repos()
CASES = [(repo, mod, *choice) for repo, mod in MODS for choice in _enum_choices(repo)]

pytestmark = pytest.mark.skipif(
    not MODS,
    reason=(
        f"found no mod repos beside {nm.resolve_mods_dir()} -- there are no Choice "
        "settings to hold to their localisation, so these guards did NOT run"
    ),
)


def test_family_has_enum_choices():
    """Guards the guard: if the discovery breaks, every case below vanishes silently."""
    assert CASES, (
        "no enum-valued Choice setting found in any mod repo. Either the family "
        "genuinely has none (then delete this suite), or CHOICE_CALL no longer "
        "matches how the calls are written -- in which case the parity checks "
        "below are passing vacuously."
    )


@pytest.mark.parametrize(
    "repo, mod, key, enum_name, members", CASES, ids=lambda v: getattr(v, "name", v)
)
def test_choice_members_are_localised(repo, mod, key, enum_name, members):
    """Every offered enum member has a label term, and no term is left orphaned.

    Both directions matter and fail differently. A missing leaf shows in game as
    a raw token like `BelowMinimap`; an orphaned leaf is dead weight that outlives
    a renamed member and makes the table look complete when it is not.
    """
    namespace = f"{mod}-Config/{key}"
    leaves = _yaml_leaves(repo / "localization" / "localization.yaml", namespace)

    assert leaves is not None, (
        f"{repo.name}: Choice '{key}' offers {enum_name} members {sorted(members)}, but "
        f"localization.yaml has no '{namespace}:' namespace. In game every option would "
        f"render as its raw token."
    )

    missing = sorted(set(members) - set(leaves))
    orphaned = sorted(set(leaves) - set(members))

    assert not missing, (
        f"{repo.name}: {enum_name} member(s) {missing} have no term under '{namespace}'. "
        f"They render as raw tokens. Note the name is also the persisted value, so if this "
        f"appeared after a rename, existing players were reset to the default as well."
    )
    assert not orphaned, (
        f"{repo.name}: term(s) {orphaned} under '{namespace}' match no {enum_name} member. "
        f"Either a member was renamed (players who chose it are now on the default) or the "
        f"leaf is left over from one that was removed."
    )
