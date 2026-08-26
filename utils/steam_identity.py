"""Read and write a mod's Steam Workshop file id.

The id lives in the SDK's own <Mod>_Steam.asset so that the SDK window keeps
working, but it is addressed BY PATH. The asset's modName field is written from
the display title and looked up by metadata.name, so it stops matching as soon
as a readable title is used (CoreKeeperModSDK#11); keying on it here would
inherit that defect.

Only the fileId line is touched on write. The asset also carries modOwner, tags
and a selectedPath, and every one of those belongs to the SDK window.
"""

import re
from pathlib import Path

FILE_ID = re.compile(r"^(\s*fileId:\s*)(\d+)\s*$", re.MULTILINE)

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


def write_file_id(asset: Path, file_id: int) -> None:
    """Set the id, creating the asset if it does not exist yet.

    An *existing* file that does not carry a `fileId:` line is refused rather
    than templated over — silently replacing it would also discard modOwner,
    modName, selectedPath and tags, which belong to the SDK window, not to us.
    """
    if asset.is_file():
        text = asset.read_text()
        if not FILE_ID.search(text):
            raise ValueError(
                f"{asset} exists but has no 'fileId:' line — expected a Steam Workshop asset"
            )
        asset.write_text(FILE_ID.sub(rf"\g<1>{file_id}", text, count=1))
        return

    mod_name = asset.stem.removesuffix("_Steam")
    asset.parent.mkdir(parents=True, exist_ok=True)
    asset.write_text(
        TEMPLATE.format(name=asset.stem, file_id=file_id, mod_name=mod_name)
    )
