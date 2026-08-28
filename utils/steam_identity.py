"""Read and write a mod's Steam Workshop file id.

The id lives in the SDK's own <Mod>_Steam.asset so that the SDK window keeps
working, but it is addressed BY PATH. The asset's modName field is written from
the display title and looked up by metadata.name, so it stops matching as soon
as a readable title is used (CoreKeeperModSDK#11); keying on it here would
inherit that defect.

Besides the id, the asset carries modOwner, selectedPath and tags — fields only
the SDK window reads. They are written when the caller can supply them, so that
an asset this pipeline created is complete in the window too, rather than one
the window shows half-filled. Each is optional and left untouched when omitted:
a caller without a live Steam session cannot know modOwner, and having none is
no reason to erase one that is already there.

modName stays ours to write only on creation. It is the window's lookup key and
goes stale by design (#11); rewriting it on every publish would fight the window
over a value we have no better answer for.

A created asset gets its .meta too, because a GUID carrier that only exists
after someone next opens the Editor is one the repo cannot hold — see
../docs/publishing.md on committing this asset.
"""

import os
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

# Long enough that a cold index or a network-backed checkout answers, short
# enough that a publish never stalls on a question it is allowed not to answer.
GIT_TIMEOUT_SECONDS = 10

# Reading and recognising: the value must be a number, so a file that merely
# has the word in it is not mistaken for an identity asset.
FILE_ID = re.compile(r"^(\s*fileId:\s*)(\d+)\s*$", re.MULTILINE)

# Writing has no constants of its own: the three patterns differed only in the
# key name, so _set_scalar builds one from the key it is given. FILE_ID above
# stays separate — it is not a fourth spelling of the same thing, it is the
# stricter "and the value is a number" test that recognition rests on.

TEMPLATE = """%YAML 1.1
%TAG !u! tag:unity3d.com,2011:
--- !u!114 &11400000
MonoBehaviour:
  m_ObjectHideFlags: 0
  m_CorrespondingSourceObject: {{fileID: 0}}
  m_PrefabInstance: {{fileID: 0}}
  m_PrefabAsset: {{fileID: 0}}
  m_GameObject: {{fileID: 0}}
  m_Enabled: 1
  m_EditorHideFlags: 0
  m_Script: {{fileID: 11500000, guid: ef61ecb41356dbc4db1133ad6be0ebf9, type: 3}}
  m_Name: {name}
  m_EditorClassIdentifier:\x20
  fileId: {file_id}
  modOwner:\x20
  modName: {mod_name}
  selectedPath:\x20
  tags: []
"""

# Unity's own shape for a ScriptableObject asset, copied from one the SDK
# generated. mainObjectFileID matches the &11400000 anchor in TEMPLATE above.
META_TEMPLATE = """fileFormatVersion: 2
guid: {guid}
NativeFormatImporter:
  externalObjects: {{}}
  mainObjectFileID: 11400000
  userData:\x20
  assetBundleName:\x20
  assetBundleVariant:\x20
"""


def item_url(file_id: int) -> str:
    """The public Workshop page for an item id.

    Here rather than at the caller because this module is what knows a Workshop
    item at all, and a URL spelled out at each consumer is a URL that gets
    spelled differently at one of them. Steam accepts several forms for this
    page; the query-string one is what the Workshop's own links and the SDK
    window use, so it is the one a reader will recognise.
    """
    return f"https://steamcommunity.com/sharedfiles/filedetails/?id={file_id}"


def asset_path(repo_root: Path, mod_name: str) -> Path:
    """Where a mod repo keeps its Workshop identity asset.

    One function rather than the same three path segments spelled out at each
    call site. Every caller here addresses the asset BY PATH — the modName
    field inside it is not a usable key (see the module docstring) — so the
    path is the identity, and a reader that computes it differently from the
    writer does not read a different file, it reads nothing: no id, a mod that
    looks like it has never been published, and a second Workshop item created
    over the first.
    """
    return repo_root / "unity" / mod_name / f"{mod_name}_Steam.asset"


def read_file_id(asset: Path) -> int | None:
    """The stored id, or None when there is none — a missing asset, or a zero.

    Only a missing file reads as "no id" here. Anything else that stops the
    read (permissions, a directory where a file was expected) is a real
    problem with an asset that DOES exist, and must not be silently folded
    into "this is a brand-new mod" — that is exactly the misreading that lets
    a publish create a second Workshop item over one whose id merely could
    not be read.
    """
    try:
        text = asset.read_text()
    except FileNotFoundError:
        return None
    match = FILE_ID.search(text)
    if not match:
        return None
    return int(match.group(2)) or None


def is_tracked(asset: Path) -> bool | None:
    """Whether git has this file in its index — None when git cannot say.

    Three answers, not two. "git says no" and "git could not be asked" look
    the same to a caller that collapses them into False, and they call for
    opposite responses: the first is a real hazard worth a warning, the second
    is a checkout with no repository, no git binary, or a layout this does not
    understand — none of which is the author's problem to be told about.

    `ls-files --error-unmatch` rather than `status`: it answers exactly the
    question (is this path in the index) with an exit code, so nothing has to
    parse porcelain output, and staged-but-uncommitted counts as tracked —
    which is right, that file is on its way into the commit.
    """
    if shutil.which("git") is None:
        return None
    # GIT_DIR and GIT_INDEX_FILE outrank -C, so inherited they would have git
    # answer about whatever repository invoked the publish rather than the
    # mod's. Measured: a tracked asset then reports untracked, and a warning
    # that fires on a correctly committed asset is one the author stops
    # reading. Same defence check_docs_wrapping.markdown_files documents.
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    try:
        completed = subprocess.run(
            [
                "git",
                "-C",
                str(asset.parent),
                "ls-files",
                "--error-unmatch",
                "--",
                asset.name,
            ],
            capture_output=True,
            timeout=GIT_TIMEOUT_SECONDS,
            env=env,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    # Measured against git 2.x: 0 = in the index, 1 = "did not match any
    # file(s) known to git", 128 = not a repository at all. Anything else is
    # a reading this does not have, and guessing at one here would turn a
    # note into a false alarm.
    return {0: True, 1: False}.get(completed.returncode)


def ensure_recognizable(asset: Path) -> None:
    """Check the identity asset at the point where losing its id would hurt.

    Two things, both about the same failure — a Workshop item alive on Steam
    with its id recorded nowhere:

    First, raise if an existing asset has no `fileId:` line. A missing asset
    is fine — that is a mod's first publish, and one will be created from
    TEMPLATE. An existing file that write_file_id would refuse (see below) is
    not fine, and the whole point is to find that out HERE: checked after the
    read above, this still runs before the Steam upload that follows it, so a
    bad asset aborts before a Workshop item is created rather than after — an
    item created and then unrecognized on write would be a live,
    duplicate-risking item whose id has nowhere to go.

    Second, warn — never raise — if git does not have the asset. See
    ../docs/publishing.md: an untracked asset is one `git clean` or fresh
    checkout away from taking the id with it, after which the next publish
    creates a second Workshop item indistinguishable from the first. That is a
    hazard to the NEXT run, not this one, and this run's caller
    (steam_bundle.check_prerequisites) aborts the mod.io release too — so
    raising would cancel a release that is in no danger, over something a
    single `git add` fixes.
    """
    if not asset.is_file():
        return
    if not FILE_ID.search(asset.read_text()):
        raise ValueError(
            f"{asset} exists but has no 'fileId:' line — expected a Steam Workshop asset. "
            "Fix or remove it before publishing: found only after the upload, this would "
            "leave a newly created Workshop item with its id unrecorded."
        )
    warn_if_untracked(asset)


def warn_if_untracked(asset: Path) -> None:
    """Say so, once, when the Workshop id is only as durable as a temp file.

    Only on a definite "no" from git: silence covers both "tracked" and
    "unanswerable", because a note that fires on every checkout without a
    repository is one an author learns to scroll past — including on the
    publish where it is true.
    """
    if is_tracked(asset) is not False:
        return
    print(
        f"  ! {asset} is not tracked by git — the Workshop id it holds would be lost "
        "to a `git clean` or a fresh checkout, and the next publish would then create "
        "a SECOND Workshop item beside the existing one.",
        file=sys.stderr,
    )
    print(f"    Commit it: git add {asset}", file=sys.stderr)


def _set_scalar(text: str, key: str, value: object) -> str:
    """Replace a `key: value` line's value, treating it as literal text.

    A plain replacement string would read a backslash in `value` as a group
    reference — and one of these values is a filesystem path. `key` is escaped
    for the same class of reason, one step earlier: every caller passes a
    literal, but a regex built by interpolation should not depend on that
    staying true.

    Note what this does NOT do: a key that is absent leaves the text unchanged
    and says nothing, because that is what re.sub does on a non-match. Callers
    that need the line to exist have to establish it themselves — see
    write_file_id.
    """
    return re.sub(
        rf"^(\s*{re.escape(key)}:).*$",
        lambda m: f"{m.group(1)} {value}",
        text,
        count=1,
        flags=re.MULTILINE,
    )


def _set_tags(text: str, tags: list[str]) -> str:
    """Replace the whole `tags:` block, matching how the SDK writes it.

    Line-oriented rather than a regex: the block is a YAML sequence whose
    length varies, and an empty one is `tags: []` on a single line — a pattern
    covering both is harder to read than the loop, and gets the append-instead-
    of-replace case wrong in ways nothing would notice until a listing showed
    tags nobody set.
    """
    lines = text.splitlines()
    out: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.lstrip()
        if not stripped.startswith("tags:"):
            out.append(line)
            index += 1
            continue

        indent = line[: len(line) - len(stripped)]
        index += 1
        while index < len(lines) and lines[index].lstrip().startswith("- "):
            index += 1
        if tags:
            out.append(f"{indent}tags:")
            # At the key's own indent, not one level deeper: YAML allows both,
            # and Unity writes them flush. Indenting would diff against every
            # asset the SDK wrote for no gain.
            out.extend(f"{indent}- {tag}" for tag in tags)
        else:
            out.append(f"{indent}tags: []")
    return "\n".join(out) + "\n"


def write_file_id(
    asset: Path,
    file_id: int,
    *,
    mod_owner: int | None = None,
    selected_path: str | None = None,
    tags: list[str] | None = None,
) -> None:
    """Set the id, creating the asset if it does not exist yet.

    An *existing* file that does not carry a `fileId:` line is refused rather
    than templated over — silently replacing it would also discard modName,
    which is the SDK window's and not ours to invent.

    The optional fields are the ones only the SDK window reads. Each is left
    exactly as found when not given, because a caller that cannot determine a
    value (modOwner needs a live Steam session) must not blank out one that is
    already there. Passed, they are written on both paths: the window's own
    copies go stale — `selectedPath` still named the pre-MOD_INSTALL_PATH build
    directory — and a publish is the moment the current values are known.
    """
    creating = not asset.is_file()
    if creating:
        mod_name = asset.stem.removesuffix("_Steam")
        text = TEMPLATE.format(name=asset.stem, file_id=file_id, mod_name=mod_name)
        asset.parent.mkdir(parents=True, exist_ok=True)
    else:
        text = asset.read_text()
        if not FILE_ID.search(text):
            raise ValueError(
                f"{asset} exists but has no 'fileId:' line — expected a Steam Workshop asset"
            )

    # Redundant on the create path as things stand — TEMPLATE was just formatted
    # with this very id — and kept deliberately. Without it the id would arrive
    # by two different mechanisms depending on the branch above: TEMPLATE's
    # {file_id} when creating, this substitution when updating. One line for
    # both is worth a wasted regex, because re.sub says nothing on a non-match,
    # so a create path that quietly stopped interpolating the id would produce
    # an asset with the wrong one and report success.
    #
    # Its limit, so nobody expects more of it: it can only rewrite a `fileId:`
    # line that is there. A TEMPLATE that dropped the line entirely would defeat
    # this too — read_file_id is what would notice that.
    text = _set_scalar(text, "fileId", file_id)
    if mod_owner is not None:
        text = _set_scalar(text, "modOwner", mod_owner)
    if selected_path is not None:
        text = _set_scalar(text, "selectedPath", selected_path)
    if tags is not None:
        text = _set_tags(text, tags)
    asset.write_text(text)

    if not creating:
        return

    # Never overwritten, only supplied when missing: once a .meta exists its
    # GUID is the one Unity — and anything referencing the asset — already
    # knows, and this asset outliving its own .meta (deleted by hand, dropped
    # by a checkout) is exactly when replacing it would do damage.
    meta = asset.parent / f"{asset.name}.meta"
    if not meta.exists():
        meta.write_text(META_TEMPLATE.format(guid=uuid.uuid4().hex))
