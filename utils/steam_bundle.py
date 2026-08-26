"""Assemble everything a Steam Workshop publish needs, from existing sources.

Nothing here talks to Steam. That separation is the point: the values a publish
sends are all derivable from files in the repository, and deriving them is
testable, whereas the Steamworks calls are not. What crosses into the .NET tool
is this dict, as JSON.

Where each value comes from is the spec's table, and the reason it is a table
rather than a form is that mod.io already publishes from these same sources — a
value typed twice is a value that will eventually differ.
"""

import json
import re
import sys
from collections.abc import Mapping
from pathlib import Path

import steam_identity
import steam_preview

CHANGELOG_ENTRY = re.compile(r"^##\s*\[([^\]]+)\]", re.MULTILINE)
DEPENDENCY = re.compile(
    r"^\s*-\s*modName:\s*(\S+)\s*\n\s*required:\s*(\d+)", re.MULTILINE
)

# requiredOn is a [Flags] enum: None=0, Client=1, Server=2, ClientAndServer=3.
# 0 is valid and means "gates nothing", so it produces no Application Type tag.
APPLICATION_TYPE = {1: ["Client"], 2: ["Server"], 3: ["Client", "Server"]}


def parse_changelog(text: str) -> tuple[str, str]:
    """The topmost '## [x.y.z]' entry: its version and its body."""
    matches = list(CHANGELOG_ENTRY.finditer(text))
    if not matches:
        raise ValueError("CHANGELOG.md has no '## [x.y.z]' entry")
    first = matches[0]
    end = matches[1].start() if len(matches) > 1 else len(text)
    body = text[first.end() :][: end - first.end()]
    # Drop the trailing date on the heading line, then the blank line under it.
    body = body.split("\n", 1)[1] if "\n" in body else ""
    return first.group(1), body.strip()


def _read_metadata(asset_text: str) -> dict:
    """The `metadata:` block of a ModBuilderSettings .asset, flat and shallow."""
    out: dict[str, object] = {}
    for key in ("name", "displayName", "skipSafetyChecks", "requiredOn"):
        match = re.search(rf"^\s*{key}:\s*(.*?)\s*$", asset_text, re.MULTILINE)
        if match and match.group(1):
            value = match.group(1)
            out[key] = int(value) if value.lstrip("-").isdigit() else value
    return out


def parse_dependencies(asset_text: str) -> list[tuple[str, bool]]:
    """Every `modName`/`required` pair under `metadata.dependencies`, in .asset order.

    All declared names are reported, required or not — CLIPublishHelper's own
    mod.io sync (EnsureDependenciesThenTag) resolves every entry the same way
    and only lets `required` decide what happens when resolution fails, so that
    decision belongs downstream, to whatever resolves a name to a Workshop id,
    not to reading the .asset. `modName:` occurs nowhere else in this schema,
    so a plain search needs no help finding the surrounding `dependencies:`
    key first.
    """
    return [(name, flag != "0") for name, flag in DEPENDENCY.findall(asset_text)]


def resolve_dependencies(
    declared: list[tuple[str, bool]], cache_path: Path | None
) -> list[dict]:
    """Map declared dependencies onto Workshop file ids via the cache.

    Resolution is never guessed. A Steam title is a display name rather than an
    identity — several items may share one, and a mod may be published under a
    title that differs from its loader name — so a miss is reported for a human
    to settle once, not decided by picking the most popular candidate. A wrong
    id would make subscribers install an unrelated mod, and nothing about that
    failure points back at the publish.

    Severity follows the `.asset`'s own `required` flag, as the mod.io path does.
    """
    if not declared:
        return []

    cache: dict[str, object] = {}
    if cache_path and cache_path.is_file():
        try:
            cache = json.loads(cache_path.read_text())
        except json.JSONDecodeError as err:
            raise ValueError(f"{cache_path} is not valid JSON: {err}") from err

    resolved = []
    for name, required in declared:
        file_id = cache.get(name)
        if file_id:
            try:
                file_id = int(file_id)
            except (TypeError, ValueError) as err:
                raise ValueError(
                    f"{cache_path} has a non-numeric Workshop id for {name!r}: {file_id!r}"
                ) from err
            resolved.append({"name": name, "fileId": file_id, "required": required})
            continue
        if required:
            raise ValueError(
                f"required dependency {name!r} has no Workshop id. Add it to "
                f"{cache_path} once — see the spec on why this is not searched automatically."
            )
        # stderr, not stdout: Task 7 captures this function's caller's stdout
        # whole as the JSON bundle for the .NET tool, and a warning line ahead
        # of the JSON would make that capture fail to parse.
        print(
            f"  ! optional dependency {name!r} has no Workshop id — skipped",
            file=sys.stderr,
        )
    return resolved


def derive_tags(metadata: Mapping[str, object], modio_type: str) -> list[str]:
    """Category tags from CK_MODIO_TYPE, plus the two derived groups.

    Sent flat: Core Keeper's Workshop configuration owns the grouping, so a
    value like "Quality of Life" needs no prefix. Steam drops an unknown value
    without a word, exactly as mod.io does.
    """
    tags = [part.strip() for part in modio_type.split("|") if part.strip()]
    tags += APPLICATION_TYPE.get(int(metadata.get("requiredOn", 0) or 0), [])
    tags.append(
        "Script (Elevated Access)"
        if int(metadata.get("skipSafetyChecks", 0) or 0)
        else "Script"
    )
    return tags


def build_bundle(repo_root: Path, env: Mapping[str, str], preview_dest: Path) -> dict:
    mod_name = env.get("MOD_NAME")
    if not mod_name:
        raise ValueError("MOD_NAME is not set")

    asset = repo_root / "unity" / f"{mod_name}.asset"
    if not asset.is_file():
        raise ValueError(f"no ModBuilderSettings asset at {asset}")
    asset_text = asset.read_text()
    metadata = _read_metadata(asset_text)

    description_path = repo_root / "steam-description.txt"
    if not description_path.is_file():
        raise ValueError(
            f"no steam-description.txt at {description_path} — "
            "the Workshop description is BBCode and is not converted from modio-description.md"
        )

    changelog_path = repo_root / "CHANGELOG.md"
    if not changelog_path.is_file():
        raise ValueError(f"no CHANGELOG.md at {changelog_path}")
    version, changelog = parse_changelog(changelog_path.read_text())

    install_path = env.get("MOD_INSTALL_PATH")
    if not install_path:
        raise ValueError("MOD_INSTALL_PATH is not set")
    content = Path(install_path) / mod_name
    if not content.is_dir():
        raise ValueError(f"no built content at {content} — build the mod first")

    logo = repo_root / "unity" / mod_name / "Editor" / "logo.png"
    if not logo.is_file():
        raise ValueError(f"no logo at {logo}")
    steam_preview.derive_preview(logo, preview_dest)

    identity_asset = repo_root / "unity" / mod_name / f"{mod_name}_Steam.asset"
    file_id = steam_identity.read_file_id(identity_asset)

    return {
        "fileId": file_id or 0,
        "title": metadata.get("displayName") or metadata.get("name") or mod_name,
        "description": description_path.read_text(),
        "tags": derive_tags(metadata, env.get("CK_MODIO_TYPE", "")),
        "changelog": changelog,
        "version": version,
        "contentPath": str(content),
        "previewPath": str(preview_dest),
        # A new item must never appear half-configured in the catalogue; an
        # existing one's visibility was set by a human and is not ours to change.
        "visibility": "unchanged" if file_id else "hidden",
        "dependencies": resolve_dependencies(
            parse_dependencies(asset_text),
            Path(env["STEAM_DEPS_MAP"]) if env.get("STEAM_DEPS_MAP") else None,
        ),
    }
