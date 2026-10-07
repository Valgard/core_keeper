"""The sheets sibling mods committed must be what pixaki_to_sheet cuts today.

Every option the tool gains is opt-in; this is the check that an existing
caller's output stays byte-identical. It reads the sibling mod repos beside this
one and skips, with the reason, in a checkout that does not have them.
"""

import re
import subprocess
from pathlib import Path

import pixaki_to_sheet as p
import pytest

THIS = Path(__file__).resolve().parents[2]


def _workspace():
    """The main checkout: the mod repos sit in it, not in a linked worktree of it."""
    out = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        cwd=THIS,
        capture_output=True,
        text=True,
        check=False,
    )
    return Path(out.stdout.strip()).parent if out.returncode == 0 else THIS


ROOT = _workspace()

# (mod repo, master under sources/, sheet under unity/)
SHEETS = [
    (
        "item-checklist",
        "sources/Item checklist sprites.pixaki",
        "unity/ItemChecklist/Art/UI/ui_checklist.png",
    ),
    (
        "player-coordinates-hud",
        "sources/player_position.pixaki",
        "unity/PlayerCoordinatesHud/Art/UI/player_position.png",
    ),
]


@pytest.mark.parametrize(("repo", "master", "sheet"), SHEETS, ids=[s[0] for s in SHEETS])
def test_committed_sheet_is_reproduced_byte_for_byte(repo, master, sheet, tmp_path):
    """Cutting the committed master with the committed meta and GUID returns the committed sheet."""
    pixaki = ROOT / repo / master
    committed = ROOT / repo / sheet
    committed_meta = Path(str(committed) + ".meta")
    if not (pixaki.exists() and committed.exists() and committed_meta.exists()):
        pytest.skip(f"sibling repo {repo} is not checked out beside this one")
    guid = re.search(r"^guid: ([0-9a-f]{32})", committed_meta.read_text(), re.M).group(1)
    out = tmp_path / committed.name
    p.build_sheet(str(pixaki), str(out), str(committed_meta), guid=guid)
    assert out.read_bytes() == committed.read_bytes()
    assert Path(str(out) + ".meta").read_text() == committed_meta.read_text()
