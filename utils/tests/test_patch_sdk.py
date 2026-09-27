"""Unit tests for re-applying the local SDK source patches.

The script edits a file that belongs to Pugstorm, not to us, and an SDK update
replaces it wholesale. So the behaviour worth testing is not "does it patch" but
what it does when the ground moves: a file that already carries the patch must be
left alone, and a file upstream has rewritten must stop the run rather than be
forced into a shape nobody verified.

That last case is the reason the match is verbatim, indentation included. A
fuzzy match would keep succeeding after upstream reworked the method and would
silently produce a file that compiles and does the wrong thing -- which is the
one failure mode a patch script must not have.
"""

from __future__ import annotations

# ruff: noqa: E501 -- the fixture below quotes Pugstorm's C# verbatim, and its
# line length is theirs. See the same note in patch_sdk.py.
import subprocess as sp
from pathlib import Path

import patch_sdk
import pytest

ORIGINAL_FILE = f"""\
#if PUG_MOD_SDK && USE_PUG_OTHER
public class ModBuilderCustomScenesProcessor : IPugModBuilderProcessor
{{
    public void Execute(ModBuilderSettings settings, string installDirectory, List<string> assetPaths)
    {{
        var sceneDataBlocks = new List<CustomSceneDataBlock>();

{patch_sdk.CUSTOM_SCENES_BEFORE}
        var activeScene = EditorSceneManager.GetActiveScene();
    }}
}}
#endif
"""


def stock_sdk(tmp_path: Path) -> Path:
    """A throwaway SDK in which *every* patch target exists, unpatched.

    Every one, not just the file under test: `main()` walks the whole of PATCHES
    and exits 2 for a target that is not there, so an SDK holding a single file
    would have each test measuring the absence of the others instead of the case
    it describes. Each target gets its own stock text surrounded by a little
    context, which is all `state()` needs to find the match.
    """
    sdk = tmp_path / "CoreKeeperModSDK"
    for entry in patch_sdk.PATCHES:
        target = sdk / entry.relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"head\n{entry.before}tail\n", encoding="utf-8")
    return sdk


def make_sdk(tmp_path: Path, contents: str | None) -> Path:
    """A stock SDK whose custom-scenes file is replaced by `contents`.

    `None` removes that file, which is how the missing-target case is built --
    the others stay in place so the run fails on the one absence the test means.
    """
    sdk = stock_sdk(tmp_path)
    target = sdk / patch_sdk.CUSTOM_SCENES
    if contents is None:
        target.unlink()
    else:
        target.write_text(contents, encoding="utf-8")
    return sdk


@pytest.fixture
def patch() -> patch_sdk.Patch:
    """The custom-scenes patch, which most of this suite is written against."""
    return patch_sdk.PATCHES[0]


def test_unpatched_source_is_applicable(tmp_path, patch):
    """A stock SDK file is recognised as something the patch can still go into."""
    sdk = make_sdk(tmp_path, ORIGINAL_FILE)
    assert patch.state(sdk) == "applicable"


def test_apply_makes_it_applied(tmp_path, patch, monkeypatch):
    """Applying puts the catch in and leaves the file in the 'applied' state."""
    sdk = make_sdk(tmp_path, ORIGINAL_FILE)
    monkeypatch.setenv("SDK_PATH", str(sdk))

    assert patch_sdk.main(["patch_sdk.py", "apply"]) == 0
    assert patch.state(sdk) == "applied"

    patched = (sdk / patch.relative_path).read_text(encoding="utf-8")
    assert "catch (Exception e)" in patched
    assert "the build continues" in patched


def test_apply_is_idempotent(tmp_path, patch, monkeypatch):
    """A second run must not nest the try block or duplicate the comment."""
    sdk = make_sdk(tmp_path, ORIGINAL_FILE)
    monkeypatch.setenv("SDK_PATH", str(sdk))

    patch_sdk.main(["patch_sdk.py", "apply"])
    once = (sdk / patch.relative_path).read_text(encoding="utf-8")
    patch_sdk.main(["patch_sdk.py", "apply"])
    twice = (sdk / patch.relative_path).read_text(encoding="utf-8")

    assert once == twice
    assert once.count("LOCAL PATCH") == 1
    assert once.count("catch (Exception e)") == 1


def test_analyse_reports_missing_without_writing(tmp_path, patch, monkeypatch):
    """Analysing says what is missing and changes nothing -- it is the safe mode."""
    sdk = make_sdk(tmp_path, ORIGINAL_FILE)
    monkeypatch.setenv("SDK_PATH", str(sdk))
    before = (sdk / patch.relative_path).read_text(encoding="utf-8")

    assert patch_sdk.main(["patch_sdk.py"]) == 1
    assert (sdk / patch.relative_path).read_text(encoding="utf-8") == before


def test_analyse_is_clean_once_applied(tmp_path, monkeypatch):
    """After applying, analysing reports nothing to do -- so it is safe to re-run."""
    sdk = make_sdk(tmp_path, ORIGINAL_FILE)
    monkeypatch.setenv("SDK_PATH", str(sdk))

    patch_sdk.main(["patch_sdk.py", "apply"])
    assert patch_sdk.main(["patch_sdk.py"]) == 0


def test_rewritten_target_stops_the_run(tmp_path, patch, monkeypatch):
    """Upstream reworked the method: refuse rather than force a guessed shape."""
    reworked = ORIGINAL_FILE.replace(
        "foreach (var sceneDataBlock in ScriptableDataEditorUtility.GetCachedDataBlocks<CustomSceneDataBlock>())",
        "foreach (var sceneDataBlock in ScriptableDataEditorUtility.GetSceneDataBlocks())",
    )
    sdk = make_sdk(tmp_path, reworked)
    monkeypatch.setenv("SDK_PATH", str(sdk))

    assert patch.state(sdk) == "target-changed"
    assert patch_sdk.main(["patch_sdk.py", "apply"]) == 2
    assert (sdk / patch.relative_path).read_text(encoding="utf-8") == reworked


def test_reindented_target_is_not_matched(tmp_path, patch):
    """Indentation is part of the match -- a reformat must not pass as the original."""
    reindented = ORIGINAL_FILE.replace("\n        foreach (", "\n\tforeach (")
    sdk = make_sdk(tmp_path, reindented)
    assert patch.state(sdk) == "target-changed"


def test_missing_file_stops_the_run(tmp_path, patch, monkeypatch):
    """A target that is not there at all is refused, not silently skipped."""
    sdk = make_sdk(tmp_path, None)
    monkeypatch.setenv("SDK_PATH", str(sdk))

    assert patch.state(sdk) == "missing-file"
    assert patch_sdk.main(["patch_sdk.py", "apply"]) == 2


def test_unknown_action_is_refused(tmp_path, monkeypatch):
    """A mistyped action exits 2 rather than falling through to analysing."""
    sdk = make_sdk(tmp_path, ORIGINAL_FILE)
    monkeypatch.setenv("SDK_PATH", str(sdk))

    assert patch_sdk.main(["patch_sdk.py", "install"]) == 2


def test_sdk_is_found_from_inside_a_worktree(tmp_path, monkeypatch):
    """A worktree finds the SDK beside the main checkout, not beside itself.

    This repository's convention is that every change happens in a worktree under
    `.worktrees/`, so that is the normal place to run this script from -- and
    there `git rev-parse --show-toplevel` answers with the worktree, beside which
    no SDK clone exists. The script then reported the SDK as missing in exactly
    the situation it is meant for. `--git-common-dir` names the main checkout's
    `.git` from either place, which is what makes the two agree.
    """
    monkeypatch.delenv("SDK_PATH", raising=False)

    # conftest's autouse fixture already clears GIT_*, so cwd decides. Passing
    # env= as well is belt and braces for the one test here that *writes*: this
    # is the call sequence that once left the real repository with core.bare
    # and a stray identity, and it should not depend on a fixture staying put.
    env = patch_sdk.git_env()

    main = tmp_path / "workspace"
    main.mkdir()
    for args in (
        ["init", "-q"],
        ["config", "user.email", "t@e.st"],
        ["config", "user.name", "T"],
        ["commit", "-q", "--allow-empty", "-m", "root"],
    ):
        sp.run(["git", *args], cwd=main, env=env, check=True, capture_output=True)
    (main / "CoreKeeperModSDK").mkdir()

    tree = main / ".worktrees" / "probe"
    sp.run(
        ["git", "worktree", "add", "-q", str(tree), "HEAD", "--detach"],
        cwd=main,
        env=env,
        check=True,
        capture_output=True,
    )

    assert patch_sdk.find_sdk(start=main) == main / "CoreKeeperModSDK"
    assert patch_sdk.find_sdk(start=tree) == main / "CoreKeeperModSDK"


def test_sdk_path_env_wins_over_the_repo_layout(tmp_path, monkeypatch):
    """SDK_PATH overrides the layout search, for an SDK kept somewhere else."""
    elsewhere = tmp_path / "somewhere" / "CoreKeeperModSDK"
    elsewhere.mkdir(parents=True)
    monkeypatch.setenv("SDK_PATH", str(elsewhere))
    assert patch_sdk.find_sdk() == elsewhere.resolve()


@pytest.mark.parametrize("entry", patch_sdk.PATCHES, ids=lambda p: p.name)
def test_every_patch_is_well_formed(entry):
    """Each patch must actually change something, and say why it exists.

    Parametrised over PATCHES rather than checking the one this suite grew up
    with, so a patch added later is held to the same shape without anybody
    remembering to extend this file.
    """
    assert entry.before, f"{entry.name} has no original to match"
    assert entry.after, f"{entry.name} has no replacement"
    assert entry.before != entry.after, f"{entry.name} replaces text with itself"
    assert entry.why, f"{entry.name} does not say why it exists"
    assert entry.relative_path.endswith((".cs", ".meta")), entry.relative_path


@pytest.mark.parametrize("entry", patch_sdk.PATCHES, ids=lambda p: p.name)
def test_applying_twice_is_recognised_as_done(tmp_path, entry, monkeypatch):
    """The patched form must not still contain the original.

    That is what makes `state()` able to tell 'applied' from 'applicable' at
    all: were the original text still present afterwards, a second run would
    match it again and patch the file twice.
    """
    assert entry.before not in entry.after, (
        f"{entry.name}: the original survives inside the replacement, so a "
        "second run would apply it again"
    )

    sdk = stock_sdk(tmp_path)
    target = sdk / entry.relative_path
    monkeypatch.setenv("SDK_PATH", str(sdk))

    assert patch_sdk.main(["patch_sdk.py", "apply"]) == 0
    once = target.read_text(encoding="utf-8")
    assert patch_sdk.main(["patch_sdk.py", "apply"]) == 0
    assert target.read_text(encoding="utf-8") == once


def test_steamworks_patches_hand_macos_to_the_posix_build():
    """The two importer patches have to move in opposite directions.

    Both libraries competing for the Editor slot is the failure this repairs, so
    a patch that enabled or disabled both would reintroduce it in a new shape.
    """
    posix = next(p for p in patch_sdk.PATCHES if p.name == "steamworks-posix-platforms")
    win64 = next(p for p in patch_sdk.PATCHES if p.name == "steamworks-win64-platforms")

    # Posix gains macOS ...
    assert "Exclude OSXUniversal: 1" in posix.before
    assert "Exclude OSXUniversal: 0" in posix.after
    assert "CPU: None" in posix.before and "CPU: AnyCPU" in posix.after

    # ... and Win64 gives up the Editor.
    assert "Exclude Editor: 0" in win64.before
    assert "Exclude Editor: 1" in win64.after


def test_patched_form_carries_the_real_loop_body(patch):
    """The replacement must keep what the original did, not just wrap a stub.

    Every statement of the original body has to survive into the patched form;
    otherwise the patch would silently drop scene collection for the one case
    where it does work (a Windows host, or a project with few data blocks).
    """
    for statement in (
        "sceneDataBlock.sceneReference.IsAssigned()",
        "AssetDatabase.GetAssetPath(sceneDataBlock)",
        "StringComparison.OrdinalIgnoreCase",
        "sceneDataBlocks.Add(sceneDataBlock);",
    ):
        assert statement in patch.before, f"test fixture lost {statement!r}"
        assert statement in patch.after, f"patched form drops {statement!r}"
