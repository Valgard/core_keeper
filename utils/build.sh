#!/usr/bin/env bash
# utils/build.sh — Build a Core Keeper mod via Unity batchmode.
#
# Shared by every Core Keeper mod under this directory.
#
# Usage:
#   utils/build.sh [mod-repo-path]
# The mod repo path defaults to $PWD — run this from the mod repo root, or
# pass the path explicitly. A relative path is fine, here and in the env vars
# below: MOD_CALLER_CWD carries this shell's directory into Unity as the anchor
# they resolve against.
#
# Required env vars (set in the mod's .envrc):
#   UNITY_BIN          Path to the Unity Editor binary (Unity 6000.0.59f2)
#   SDK_PATH           Path to the cloned Pugstorm CoreKeeperModSDK
#   MOD_INSTALL_PATH   Destination folder Pugstorm's ModBuilder writes to
#   MOD_NAME           The mod's PascalCase name (e.g. DisableDurability)
#
# On macOS, this also runs install-macos.sh after the build to apply the
# CrossOver/Wine workaround. Set SKIP_MACOS_INSTALL=1 to opt out.
#
# Exit codes:
#   0  Build succeeded (and on macOS, install step also succeeded)
#   1  Env var missing or invalid path
#   2  Unity returned non-zero (build failure or Unity crash)
#   3  macOS install step failed
#   4  The mod's DOTS codegen is missing from the build (see check_dots_codegen.py)

set -euo pipefail

# 1. Validate env vars.
: "${UNITY_BIN:?must be set in the mod's .envrc — see .envrc.example}"
: "${SDK_PATH:?must be set in the mod's .envrc}"
: "${MOD_INSTALL_PATH:?must be set in the mod's .envrc}"
: "${MOD_NAME:?must be set in the mod's .envrc}"

REPO_ROOT="${1:-$PWD}"
UTILS_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ ! -x "$UNITY_BIN" ]; then
    echo "ERROR: \$UNITY_BIN is not executable: $UNITY_BIN" >&2
    exit 1
fi

if [ ! -d "$SDK_PATH/Assets" ]; then
    echo "ERROR: \$SDK_PATH does not look like a Unity project: $SDK_PATH" >&2
    exit 1
fi

# 2. Ensure install path exists.
mkdir -p "$MOD_INSTALL_PATH"

# 3. Refresh symlinks into the SDK clone. Idempotent; cheap; self-heals
# after worktree switches or repo moves where existing symlinks would dangle.
"$UTILS_DIR/link.sh" "$REPO_ROOT" >/dev/null

# 3b. Make Unity recompile the mod. Its DOTS source generators only run on a
# recompile, and ModBuilder copies their output from a Temp folder that starts
# empty in every batchmode session -- so a build with unchanged sources would
# ship the systems without their generated bodies. Bumping the timestamps is
# enough to trigger the recompile; check_dots_codegen.py below verifies it did.
if [ -d "$REPO_ROOT/unity/$MOD_NAME" ]; then
    find "$REPO_ROOT/unity/$MOD_NAME" -name '*.cs' -exec touch {} +
fi

# 4. Invoke Unity.
# The anchor for every relative path that reaches the Editor helpers — a variable
# survives the jump into Unity, the working directory does not, and Unity's own is
# not this one. Without it a relative MOD_INSTALL_PATH or LOC_YAML would resolve
# somewhere nobody named. See EnvPaths at the bottom of utils/CLIBuildHelper.cs.
export MOD_CALLER_CWD="$PWD"

echo "Building $MOD_NAME mod..."
echo "  SDK:     $SDK_PATH"
echo "  Install: $MOD_INSTALL_PATH"

if "$UNITY_BIN" \
        -batchmode \
        -nographics \
        -projectPath "$SDK_PATH" \
        -executeMethod CoreKeeperModUtils.CLIBuildHelper.Build \
        -logFile - \
        -quit; then
    # A build that did not recompile the mod ships its DOTS systems without the
    # generated method bodies, and nothing in Unity's output says so -- the game
    # throws at the first system update. See check_dots_codegen.py.
    if ! python3 "$UTILS_DIR/check_dots_codegen.py" \
            "$SDK_PATH/Library/ScriptAssemblies/$MOD_NAME.dll" \
            "$MOD_INSTALL_PATH/$MOD_NAME"; then
        exit 4
    fi
    echo "✓ Build complete."
    # Tell the SDK window about this build. Its Steam Workshop tab finds the folder
    # it uploads only through ModPaths.asset, which otherwise just CreateMod.cs
    # fills -- so without this a batchmode build is invisible there and the tab
    # says "No built mod found". Registered is the content folder ModBuilder
    # created, not the staging dir: only that one ends in the PascalCase mod name
    # the tab matches on. Never fatal -- the mod is already built.
    python3 "$UTILS_DIR/register_build_path.py" \
        "$SDK_PATH/Packages/dev.pugstorm.mod/SDK/Editor/ModPaths.asset" \
        "$MOD_INSTALL_PATH/$MOD_NAME" || true
else
    echo "✗ Build failed. Check Unity log output above for errors." >&2
    exit 2
fi

# 5. On macOS, apply the CrossOver/Wine workaround.
if [ "$(uname -s)" = "Darwin" ] && [ -z "${SKIP_MACOS_INSTALL:-}" ]; then
    echo
    if "$UTILS_DIR/install-macos.sh"; then
        echo "✓ macOS install complete. Launch Core Keeper to load."
        echo "  Reminder: do NOT open the in-game Mod menu."
    else
        echo "✗ macOS install step failed." >&2
        exit 3
    fi
else
    echo "  Restart Core Keeper to load."
fi
