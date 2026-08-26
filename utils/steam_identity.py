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

import re
import uuid
from pathlib import Path

# Reading and recognising: the value must be a number, so a file that merely
# has the word in it is not mistaken for an identity asset.
FILE_ID = re.compile(r"^(\s*fileId:\s*)(\d+)\s*$", re.MULTILINE)

# Writing: match the key and replace whatever follows it, whatever that is.
FILE_ID_LINE = re.compile(r"^(\s*fileId:).*$", re.MULTILINE)
MOD_OWNER = re.compile(r"^(\s*modOwner:).*$", re.MULTILINE)
SELECTED_PATH = re.compile(r"^(\s*selectedPath:).*$", re.MULTILINE)

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


def ensure_recognizable(asset: Path) -> None:
    """Raise before any Steam call if an existing asset has no `fileId:` line.

    A missing asset is fine — that is a mod's first publish, and one will be
    created from TEMPLATE. An existing file that write_file_id would refuse
    (see below) is not fine, and the whole point is to find that out HERE:
    checked after the read above, this still runs before the Steam upload
    that follows it, so a bad asset aborts before a Workshop item is created
    rather than after — an item created and then unrecognized on write would
    be a live, duplicate-risking item whose id has nowhere to go.
    """
    if not asset.is_file():
        return
    if not FILE_ID.search(asset.read_text()):
        raise ValueError(
            f"{asset} exists but has no 'fileId:' line — expected a Steam Workshop asset. "
            "Fix or remove it before publishing: found only after the upload, this would "
            "leave a newly created Workshop item with its id unrecorded."
        )


def _set_scalar(text: str, pattern: re.Pattern, value: object) -> str:
    """Replace a `key: value` line's value, treating it as literal text.

    A plain replacement string would read a backslash in `value` as a group
    reference — and one of these values is a filesystem path.
    """
    return pattern.sub(lambda m: f"{m.group(1)} {value}", text, count=1)


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

    text = _set_scalar(text, FILE_ID_LINE, file_id)
    if mod_owner is not None:
        text = _set_scalar(text, MOD_OWNER, mod_owner)
    if selected_path is not None:
        text = _set_scalar(text, SELECTED_PATH, selected_path)
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
