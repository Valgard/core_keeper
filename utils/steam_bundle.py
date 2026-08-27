"""Assemble everything a Steam Workshop publish needs, from existing sources.

Nothing here talks to Steam. That separation is the point: the values a publish
sends are all derivable from files in the repository, and deriving them is
testable, whereas the Steamworks calls are not. What crosses into the .NET tool
is this dict, as JSON.

No value here is entered for Steam's benefit: each is read from the file that
already owns it for the mod.io publish — the ModBuilderSettings `.asset`,
`CHANGELOG.md`, `steam-description.txt`, the mod's logo. A value typed a second
time is a value that will eventually differ, and the two platforms would then
ship the same version under different descriptions. `docs/adrs/003-steam-workshop-publishing.md`
records why publishing to both is worth that constraint.
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
# The [Flags] bits of ModExistsOn, in the order the tags should appear. 0 is
# valid and means "gates nothing", so it produces no Application Type tag.
APPLICATION_TYPE = ((1, "Client"), (2, "Server"))


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
    """The `metadata:` block of a ModBuilderSettings .asset, flat and shallow.

    Horizontal whitespace only around the value — `\\s` would match the newline
    too, so a key with an empty value would swallow the line break and capture
    the line below it. `displayName:` is empty on any mod the SDK's settings GUI
    created, and it becomes the Workshop item's title.
    """
    out: dict[str, object] = {}
    for key in ("name", "displayName", "skipSafetyChecks", "requiredOn"):
        match = re.search(
            rf"^[^\S\n]*{key}:[^\S\n]*(.*?)[^\S\n]*$", asset_text, re.MULTILINE
        )
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
) -> list[dict] | None:
    """Map declared dependencies onto Workshop file ids via the cache.

    Resolution is never guessed. A Steam title is a display name rather than an
    identity — several items may share one, and a mod may be published under a
    title that differs from its loader name — so a miss is reported for a human
    to settle once, not decided by picking the most popular candidate. A wrong
    id would make subscribers install an unrelated mod, and nothing about that
    failure points back at the publish.

    Severity follows the `.asset`'s own `required` flag, as the mod.io path does.

    **Returns None when any declared entry could not be resolved**, and that
    distinction is the point rather than a detail. ck-workshop syncs the list in
    full — it removes every dependency the item carries that the list does not
    name — so a list is only safe to send when it is a complete picture of what
    the mod declares. An incomplete one is a floor, and sending it removes
    entries nobody asked to remove while the publish reports success. The two
    values therefore mean different things: `[]` is "this mod has none, remove
    what is stale", `None` is "unknown, change nothing", which is the case
    Program.cs early-returns on. An empty list from a mod that declares two
    dependencies would be read as the first and mean the second.
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
    unresolved = []
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
            if cache_path:
                raise ValueError(
                    f"required dependency {name!r} has no Workshop id. Add it to "
                    f"{cache_path} once — a Workshop title is a display name, not an "
                    "identity, so this is looked up by hand rather than searched."
                )
            raise ValueError(
                f"required dependency {name!r} has no Workshop id, and STEAM_DEPS_MAP "
                "is not set — point it at a cache JSON file and add the id there once."
            )
        unresolved.append(name)
        # stderr, not stdout: upload.sh captures this function's caller's stdout
        # whole as the JSON bundle for the .NET tool, and a warning line ahead
        # of the JSON would make that capture fail to parse.
        print(
            f"  ! optional dependency {name!r} has no Workshop id — skipped",
            file=sys.stderr,
        )
    if unresolved:
        # See the docstring: a partial list is not a smaller truth, it is a
        # different claim. Nothing is sent rather than a claim we cannot back.
        print(
            f"  ! dependency sync skipped — {len(unresolved)} of {len(declared)} "
            "declared dependencies have no Workshop id, so the list would be "
            "incomplete and syncing it would remove what it cannot name",
            file=sys.stderr,
        )
        return None
    return resolved


def category_tags(modio_type: str) -> list[str]:
    """The `Type` group's values out of CK_MODIO_TYPE, pipe-separated.

    Pipes rather than spaces because the values contain spaces themselves
    ("Quality of Life"). Shared with the preflight rather than inlined in
    `derive_tags`, so that what the preflight accepts and what a publish sends
    cannot drift apart — a check reimplementing the split would eventually
    approve a value the split then drops.
    """
    return [part.strip() for part in modio_type.split("|") if part.strip()]


def derive_tags(metadata: Mapping[str, object], modio_type: str) -> list[str]:
    """Category tags from CK_MODIO_TYPE, plus the two derived groups.

    Sent flat: Core Keeper's Workshop configuration owns the grouping, so a
    value like "Quality of Life" needs no prefix. Steam drops an unknown value
    without a word, exactly as mod.io does.

    `requiredOn` is read bit by bit, the way the mod.io path reads it — it is a
    [Flags] enum, and the SDK's own settings GUI writes -1 ("Everything") when
    "Client and Server" is picked. Mapping whole values instead would tag that
    input with nothing at all, on the one platform that never says a tag went
    missing, while mod.io tagged both from the same field.
    """
    tags = category_tags(modio_type)

    required_on = int(metadata.get("requiredOn", 0) or 0)
    app_types = [name for bit, name in APPLICATION_TYPE if required_on & bit]
    if not app_types:
        # Legitimate for a mod that gates neither side — and equally what an
        # unset field reads as. Only the author can tell those apart, so it
        # earns a line rather than silence, as it does on the mod.io side.
        print(
            f"  ! requiredOn is {required_on} — publishing with no 'Application Type' tag. "
            "Set 1 (Client), 2 (Server) or 3 (both) if that was not intended.",
            file=sys.stderr,
        )
    tags += app_types
    tags.append(
        "Script (Elevated Access)"
        if int(metadata.get("skipSafetyChecks", 0) or 0)
        else "Script"
    )
    return tags


def check_prerequisites(repo_root: Path, env: Mapping[str, str]) -> list[dict] | None:
    """Validate everything a Steam publish needs that does NOT depend on a
    finished build, by raising ValueError on the first thing that is missing.

    Returns what it resolved the declared dependencies to, so `build_bundle` can
    reuse it instead of resolving a second time. That is not a convenience: the
    resolution prints a warning per skipped optional dependency, and running it
    twice in one process printed each warning twice, which reads as two separate
    skips of two different entries.

    Deliberately excludes the built content folder: on the normal path that is
    the directory CLIPublishHelper creates for this very run, so it genuinely
    cannot exist yet — it is the one thing here that the mod.io build produces
    rather than the repository. (The claim used to be made of MOD_INSTALL_PATH,
    which no build in the publish path ever writes; that folder was checkable
    all along, and reading it was the bug this exclusion now correctly
    describes.)

    Call this before that build starts — mod.io's own release cannot be undone
    once it has happened, so a missing steam-description.txt or an unresolvable
    dependency should surface before it, not after, on a mod.io release that
    already went out.
    """
    mod_name = env.get("MOD_NAME")
    if not mod_name:
        raise ValueError("MOD_NAME is not set")

    # Checked here because --steam-only is the one path that reaches a publish
    # without CLIPublishHelper, which is where this is otherwise enforced. Steam
    # discards a tag value it does not know without a word, and an unset variable
    # sends no value at all — so an unchecked publish puts up an item with no
    # category tags and reports success. Tested for what comes OUT of the split,
    # not for the variable being set: "|" is neither empty nor a category.
    if not category_tags(env.get("CK_MODIO_TYPE", "")):
        raise ValueError(
            "CK_MODIO_TYPE names no category — pipe-separated mod.io 'Type' tags, "
            'e.g. CK_MODIO_TYPE="Visual|Quality of Life"'
        )

    asset = repo_root / "unity" / f"{mod_name}.asset"
    if not asset.is_file():
        raise ValueError(f"no ModBuilderSettings asset at {asset}")
    asset_text = asset.read_text()

    description_path = repo_root / "steam-description.txt"
    if not description_path.is_file():
        raise ValueError(
            f"no steam-description.txt at {description_path} — "
            "the Workshop description is BBCode and is not converted from modio-description.md"
        )

    changelog_path = repo_root / "CHANGELOG.md"
    if not changelog_path.is_file():
        raise ValueError(f"no CHANGELOG.md at {changelog_path}")
    parse_changelog(changelog_path.read_text())

    logo = repo_root / "unity" / mod_name / "Editor" / "logo.png"
    if not logo.is_file():
        raise ValueError(f"no logo at {logo}")

    identity_asset = repo_root / "unity" / mod_name / f"{mod_name}_Steam.asset"
    steam_identity.ensure_recognizable(identity_asset)

    return resolve_dependencies(
        parse_dependencies(asset_text),
        Path(env["STEAM_DEPS_MAP"]) if env.get("STEAM_DEPS_MAP") else None,
    )


def build_bundle(repo_root: Path, env: Mapping[str, str], preview_dest: Path) -> dict:
    dependencies = check_prerequisites(repo_root, env)

    mod_name = env["MOD_NAME"]
    asset = repo_root / "unity" / f"{mod_name}.asset"
    asset_text = asset.read_text()
    metadata = _read_metadata(asset_text)

    description_path = repo_root / "steam-description.txt"
    changelog_path = repo_root / "CHANGELOG.md"
    version, changelog = parse_changelog(changelog_path.read_text())

    # The directory mod.io was just published from, when this run published to
    # mod.io at all. CLIPublishHelper builds into a fresh temporary one per run
    # and uploads exactly that, so anything else here would put a different
    # build on Steam than the one the version number refers to.
    #
    # MOD_INSTALL_PATH is the fallback, not the source: only build.sh writes
    # there, so it holds the last *local* build. That is the right answer for
    # --steam-only, where no mod.io build ran, and the wrong one everywhere
    # else — which is what it used to be used for.
    reported = env.get("CK_STEAM_CONTENT")
    if reported:
        content = Path(reported)
    else:
        install_path = env.get("MOD_INSTALL_PATH")
        if not install_path:
            raise ValueError("MOD_INSTALL_PATH is not set")
        content = Path(install_path) / mod_name
    if not content.is_dir():
        raise ValueError(f"no built content at {content} — build the mod first")

    # Existence and recognizability were already checked by
    # check_prerequisites above; both are cheap, so re-deriving the paths
    # here costs nothing and keeps this function correct even if a future
    # caller ever invokes it without going through that check first.
    logo = repo_root / "unity" / mod_name / "Editor" / "logo.png"
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
        # Resolved by check_prerequisites above, deliberately not again here:
        # see its docstring on why resolving twice warns twice.
        "dependencies": dependencies,
    }
