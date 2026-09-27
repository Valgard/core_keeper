#!/usr/bin/env python3
# ruff: noqa: E501 -- the patch constants below are Pugstorm's C#, quoted verbatim.
# Their line length is theirs, and rewrapping one would stop it matching: the
# match is exact, indentation included, which is the whole point of the design
# (see `test_reindented_target_is_not_matched`).
"""Re-apply the local source patches this machine needs in the Pugstorm Mod SDK.

The SDK ships one Windows-only P/Invoke in a code path every mod build runs
through, so on macOS and Linux alike a build dies before it produces anything.
This script puts the fix back after an SDK update has overwritten it.

It is the counterpart of `corekeeper-patch` one layer up: that one patches the
*installed game's* DLLs after a game update, this one patches the *SDK clone's*
sources after an SDK update. Same shape, same reason -- upstream ships something
that only works on Windows, the repair is small and known, and the update path
reverts it every time.

## The patch, and why it is shaped this way

`ScriptableDataEditorUtility.FilePathComparer` is

    [DllImport("shlwapi.dll", CharSet = CharSet.Unicode)]
    private static extern int StrCmpLogicalW(string psz1, string psz2);

    public static int FilePathComparer(string a, string b) => StrCmpLogicalW(a, b);

with no platform branch and no managed fallback, so it throws
`DllNotFoundException` anywhere that is not Windows. `GetCachedDataBlocks` sorts
every ScriptableDataBlock in the project through that comparer -- and `List.Sort`
only invokes a comparer from two elements up, which is why the defect slept for
so long: with no game assets imported there is nothing to sort. Import them and
the project holds ~13k data blocks, after which the sort, and the exception, are
unavoidable.

Three call sites reach it and Unity catches the exception at all of them --
`ScriptableDataEditorLoader.Init` and twice inside `ModBuilder.BuildAssets`,
where it lands in the log and the build carries on. CK 1.3 added a fourth,
`ModBuilderCustomScenesProcessor`, reached through `ModBuilder.PreProcess`, and
that one has no catch: the exception propagates and the build fails. So the
patch does not try to fix the comparer (it lives in a compiled assembly); it
makes the one unprotected call site behave like the three protected ones.

The cost is the custom-scene processing step, which only does anything for a mod
that ships its own scene -- and for such a mod on a non-Windows host the step was
never reachable to begin with.

## Usage

    uv run utils/patch_sdk.py            # analyse: report what is applied
    uv run utils/patch_sdk.py apply      # apply what is missing

Exit codes: 0 everything applied (or applied just now), 1 a patch is missing
(analyse only), 2 a target no longer matches -- the SDK changed and the patch
has to be re-derived rather than forced.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

SDK_DIR_NAME = "CoreKeeperModSDK"

CUSTOM_SCENES = "Packages/dev.pugstorm.mod/SDK/Editor/ModBuilderCustomScenesProcessor.cs"

# The original block, verbatim from the SDK. Indentation is part of the match:
# if upstream reformats the file, the patch must be re-derived, not guessed at.
CUSTOM_SCENES_BEFORE = """\
        foreach (var sceneDataBlock in ScriptableDataEditorUtility.GetCachedDataBlocks<CustomSceneDataBlock>())
        {
            if (!sceneDataBlock.sceneReference.IsAssigned())
            {
                continue;
            }
            string assetPath = AssetDatabase.GetAssetPath(sceneDataBlock)?.Replace('\\\\', '/');
            if (string.IsNullOrEmpty(assetPath))
            {
                continue;
            }

            bool isInsideMod = assetPath.Equals(normalizedModPath, StringComparison.OrdinalIgnoreCase)
                || assetPath.StartsWith(normalizedModPath + "/", StringComparison.OrdinalIgnoreCase);

            if (isInsideMod)
            {
                sceneDataBlocks.Add(sceneDataBlock);
            }
        }
"""

CUSTOM_SCENES_AFTER = """\
        // LOCAL PATCH, not upstream -- re-apply after an SDK update.
        //
        // GetCachedDataBlocks sorts every ScriptableDataBlock in the project by file
        // path, and that comparison goes through StrCmpLogicalW from Windows'
        // shlwapi.dll, which does not exist on macOS or Linux. List.Sort only invokes
        // a comparer from two elements up, so the call slept until game assets were
        // imported; with the ~13k data blocks that import brings, the sort -- and the
        // DllNotFoundException -- is unavoidable on every single build.
        //
        // The same exception is raised from ScriptableDataEditorLoader.Init and twice
        // from ModBuilder.BuildAssets, where Unity catches and logs it. Only this call
        // site, reached via ModBuilder.PreProcess, let it abort the build. Matching the
        // others costs the custom-scene step, which a mod without its own scene does
        // not use anyway.
        try
        {
            foreach (var sceneDataBlock in ScriptableDataEditorUtility.GetCachedDataBlocks<CustomSceneDataBlock>())
            {
                if (!sceneDataBlock.sceneReference.IsAssigned())
                {
                    continue;
                }
                string assetPath = AssetDatabase.GetAssetPath(sceneDataBlock)?.Replace('\\\\', '/');
                if (string.IsNullOrEmpty(assetPath))
                {
                    continue;
                }

                bool isInsideMod = assetPath.Equals(normalizedModPath, StringComparison.OrdinalIgnoreCase)
                    || assetPath.StartsWith(normalizedModPath + "/", StringComparison.OrdinalIgnoreCase);

                if (isInsideMod)
                {
                    sceneDataBlocks.Add(sceneDataBlock);
                }
            }
        }
        catch (Exception e)
        {
            UnityEngine.Debug.LogException(e);
            UnityEngine.Debug.LogWarning(
                "[ModBuilderCustomScenesProcessor] Could not enumerate custom scene data blocks "
                + "(see the exception above). Skipping custom-scene processing; the build continues.");
            return;
        }
"""


@dataclass(frozen=True)
class Patch:
    """One source edit: where it goes, what it replaces, what it becomes."""

    name: str
    relative_path: str
    before: str
    after: str
    why: str

    def state(self, sdk: Path) -> str:
        """One of: applied, applicable, missing-file, target-changed."""
        path = sdk / self.relative_path
        if not path.is_file():
            return "missing-file"
        text = path.read_text(encoding="utf-8")
        if self.after in text:
            return "applied"
        if self.before in text:
            return "applicable"
        return "target-changed"


PATCHES = (
    Patch(
        name="custom-scenes-processor",
        relative_path=CUSTOM_SCENES,
        before=CUSTOM_SCENES_BEFORE,
        after=CUSTOM_SCENES_AFTER,
        why="shlwapi.dll P/Invoke aborts every build on a non-Windows host",
    ),
)


def git_env() -> dict[str, str]:
    """The environment minus GIT_*, so `cwd` decides which repository is read.

    Inside a hook git exports GIT_DIR and GIT_INDEX_FILE, and those take
    precedence over `cwd` -- a read aimed at one repository then answers from
    another, with no error and a plausible result. This script runs from the
    pre-commit hook like everything else here, so it cannot skip the scrub.
    """
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def find_sdk(start: Path | None = None) -> Path:
    """Locate the SDK clone: $SDK_PATH, else beside the main checkout.

    `--git-common-dir` rather than `--show-toplevel`, because this repository's
    own convention puts every change in a worktree under `.worktrees/`, and there
    `--show-toplevel` answers with the worktree. No SDK sits beside that one, so
    the script would report the SDK as missing in exactly the situation it is
    normally run from. The common dir is the main checkout's `.git` from either
    place, so its parent is the directory the SDK clone is a sibling of.
    """
    from_env = os.environ.get("SDK_PATH")
    if from_env:
        return Path(from_env).expanduser().resolve()
    here = start or Path(__file__).resolve().parent
    try:
        common = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            cwd=here,
            env=git_env(),
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        root = str(Path(common).parent)
    except (subprocess.CalledProcessError, FileNotFoundError):
        root = str(Path(here).parent)
    return Path(root) / SDK_DIR_NAME


def main(argv: list[str]) -> int:
    """Report or apply every patch, and return the exit code documented above."""
    action = argv[1] if len(argv) > 1 else "analyze"
    if action not in {"analyze", "apply"}:
        print(f"unknown action {action!r}; expected 'analyze' or 'apply'", file=sys.stderr)
        return 2

    sdk = find_sdk()
    if not sdk.is_dir():
        print(f"SDK not found at {sdk}", file=sys.stderr)
        return 2

    print(f"SDK: {sdk}")
    exit_code = 0

    for patch in PATCHES:
        state = patch.state(sdk)
        if state == "applied":
            print(f"  [ok]      {patch.name}: already applied")
        elif state == "applicable":
            if action == "apply":
                path = sdk / patch.relative_path
                text = path.read_text(encoding="utf-8")
                path.write_text(text.replace(patch.before, patch.after, 1), encoding="utf-8")
                print(f"  [patched] {patch.name}: {patch.why}")
            else:
                print(f"  [missing] {patch.name}: {patch.why}")
                exit_code = max(exit_code, 1)
        elif state == "missing-file":
            print(
                f"  [gone]    {patch.name}: {patch.relative_path} does not exist",
                file=sys.stderr,
            )
            exit_code = 2
        else:
            print(
                f"  [changed] {patch.name}: {patch.relative_path} matches neither the\n"
                f"            original nor the patched form. The SDK changed it; re-derive\n"
                f"            the patch from the current source instead of forcing it.",
                file=sys.stderr,
            )
            exit_code = 2

    if exit_code == 1:
        print("\nRun `uv run utils/patch_sdk.py apply` to apply.")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
