"""Register a freshly built mod's content folder in the SDK's ModPaths asset.

Why this exists: the SDK's Steam Workshop tab resolves the folder it uploads via
`latestBuildOrInstallPaths.LastOrDefault(x => x.EndsWith(modName))`, and nothing
fills that list except `CreateMod.cs` -- that is, building through the Mod SDK
window. A batchmode build through `build.sh` leaves it untouched, so the tab
answers "No built mod found" for a mod that was built a minute ago, and the only
way out is to rebuild through the GUI.

What makes the entry usable is that ModBuilder creates a `<ModName>/` directory
inside `MOD_INSTALL_PATH`, so the registered path ends in the PascalCase mod name
and satisfies the tab's `EndsWith` test. The kebab-case staging directory above it
never would -- which is why this registers the content folder, not
`MOD_INSTALL_PATH` itself.

`AddPath` in the SDK keeps the list at five entries and drops the oldest; this
mirrors that, so the asset stays exactly what the Editor expects to read back.

Nothing here is allowed to fail a build. By the time this runs the mod is already
built; registering the path is a convenience for the Editor's dropdown, not part
of producing the artefact. Every problem is reported on stderr and exits 0.

Usage:
    register_build_path.py <ModPaths.asset> <content-folder>
"""

import sys
from pathlib import Path

# Mirrors AddPath in Packages/dev.pugstorm.mod/SDK/Editor/ModSDKWindow/CreateMod.cs.
MAX_ENTRIES = 5

FIELD = "latestBuildOrInstallPaths:"

# Unity writes plain scalars and only quotes when it must. A path containing these
# would be re-read as something else (or as a syntax error), so quote defensively --
# single quotes with doubled inner quotes is the YAML rule.
NEEDS_QUOTING = (
    ":",
    "#",
    "[",
    "]",
    "{",
    "}",
    ",",
    "&",
    "*",
    "!",
    "|",
    ">",
    "%",
    "@",
    "`",
    '"',
    "'",
)


def _quote(path: str) -> str:
    if (
        path != path.strip()
        or path.startswith("-")
        or any(c in path for c in NEEDS_QUOTING)
    ):
        return "'" + path.replace("'", "''") + "'"
    return path


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        inner = value[1:-1]
        return inner.replace("''", "'") if value[0] == "'" else inner
    return value


def split_list(lines: list[str]) -> tuple[int, int, list[str], str]:
    """Locate the path list. Returns (start, end, paths, indent).

    `start`/`end` bound the lines the list occupies, so the caller can splice a
    rewritten block back in without disturbing anything else in the asset.
    """
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith(FIELD):
            continue
        indent = line[: len(line) - len(line.lstrip())]
        # `field: []` -- Unity's rendering of an empty list, no item lines follow.
        if stripped != FIELD:
            return i, i + 1, [], indent
        j = i + 1
        paths = []
        while j < len(lines) and lines[j].startswith(indent + "- "):
            paths.append(_unquote(lines[j][len(indent) + 2 :]))
            j += 1
        return i, j, paths, indent
    raise LookupError(f"no '{FIELD}' field found")


def register(
    asset_text: str, content_path: str, limit: int = MAX_ENTRIES
) -> tuple[str, str]:
    """Return (new_text, message). Re-registering an existing path moves it last.

    Last position matters: the tab reads with `LastOrDefault`, so on two candidates
    ending in the same name the most recent build must win.
    """
    lines = asset_text.splitlines()
    start, end, paths, indent = split_list(lines)

    already_last = bool(paths) and paths[-1] == content_path
    paths = [p for p in paths if p != content_path]
    paths.append(content_path)
    dropped = paths[:-limit]
    paths = paths[-limit:]

    block = [f"{indent}{FIELD}"] + [f"{indent}- {_quote(p)}" for p in paths]
    new_text = "\n".join(lines[:start] + block + lines[end:]) + "\n"

    if already_last:
        message = "already registered"
    elif dropped:
        message = f"registered (dropped oldest: {dropped[0]})"
    else:
        message = "registered"
    return new_text, message


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(
            f"usage: {Path(argv[0]).name} <ModPaths.asset> <content-folder>",
            file=sys.stderr,
        )
        return 0

    asset, content = Path(argv[1]), argv[2]
    try:
        text = asset.read_text()
    except OSError as exc:
        print(f"  ! ModPaths not updated: {exc}", file=sys.stderr)
        return 0

    try:
        new_text, message = register(text, content)
    except LookupError as exc:
        print(f"  ! ModPaths not updated: {exc}", file=sys.stderr)
        return 0

    if new_text != text:
        try:
            asset.write_text(new_text)
        except OSError as exc:
            print(f"  ! ModPaths not updated: {exc}", file=sys.stderr)
            return 0
    print(f"  SDK path: {message}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
