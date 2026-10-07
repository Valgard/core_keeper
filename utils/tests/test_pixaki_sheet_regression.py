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

# (mod repo, master under sources/, sheet under unity/, sprite definition under the
# repo or None for the sibling <master>.json)
SHEETS = [
    (
        "item-checklist",
        "sources/Item checklist sprites.pixaki",
        "unity/ItemChecklist/Art/UI/ui_checklist.png",
        None,
    ),
    (
        "player-coordinates-hud",
        "sources/player_position.pixaki",
        "unity/PlayerCoordinatesHud/Art/UI/player_position.png",
        None,
    ),
    (
        "map-markers-enhanced",
        "sources/mme_markers.pixaki",
        "unity/MapMarkersEnhanced/Art/markers_large.png",
        "sources/mme_markers.large.json",
    ),
    (
        "map-markers-enhanced",
        "sources/mme_markers.pixaki",
        "unity/MapMarkersEnhanced/Art/markers_small.png",
        "sources/mme_markers.small.json",
    ),
]


@pytest.mark.parametrize(
    ("repo", "master", "sheet", "config"), SHEETS, ids=[Path(s[2]).stem for s in SHEETS]
)
def test_committed_sheet_is_reproduced_byte_for_byte(repo, master, sheet, config, tmp_path):
    """Cutting the committed master with the committed meta and GUID returns the committed sheet."""
    pixaki = ROOT / repo / master
    committed = ROOT / repo / sheet
    committed_meta = Path(str(committed) + ".meta")
    if not (pixaki.exists() and committed.exists() and committed_meta.exists()):
        pytest.skip(
            f"{repo}'s main checkout does not hold {sheet} yet (for map-markers-enhanced: "
            "the icon-rework branch is not merged) or the repo is not checked out beside this one"
        )
    guid = re.search(r"^guid: ([0-9a-f]{32})", committed_meta.read_text(), re.M).group(1)
    out = tmp_path / committed.name
    config_path = str(ROOT / repo / config) if config else None
    p.build_sheet(str(pixaki), str(out), str(committed_meta), guid=guid, config_path=config_path)
    assert out.read_bytes() == committed.read_bytes()
    assert Path(str(out) + ".meta").read_text() == committed_meta.read_text()
