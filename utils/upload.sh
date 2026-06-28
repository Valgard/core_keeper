#!/usr/bin/env bash
# utils/upload.sh — Publish a Core Keeper mod to mod.io via Unity batchmode.
#
# Shared by every Core Keeper mod under this directory. Refreshes the SDK
# symlinks, then runs CoreKeeperModUtils.CLIPublishHelper.Publish (the shared
# helper, identified by MOD_NAME), which builds the mod and uploads it through
# the mod.io plugin.
#
# Usage:
#   utils/upload.sh [mod-repo-path] [--dry-run] [--profile-only]
#
# --profile-only updates just the mod.io profile (description, name, summary,
# logo) via EditModProfile — no build, no version tags, no dependency sync, no
# modfile upload. Use it to push an edited modio-description.md without cutting
# a new release.
#
# Required env vars (set in the mod's .envrc):
#   UNITY_BIN, SDK_PATH, MOD_NAME, CK_GAME_VERSION, MOD_SUMMARY
#
# Prerequisite: log in once via the SDK window's "Log in" tab.
# The Unity Editor must be closed (it locks the project).

set -euo pipefail

: "${UNITY_BIN:?must be set — see .envrc.example}"
: "${SDK_PATH:?must be set — see .envrc.example}"
: "${MOD_NAME:?must be set — see .envrc.example}"
: "${CK_GAME_VERSION:?must be set — see .envrc.example}"
: "${MOD_SUMMARY:?must be set — see .envrc.example}"

REPO_ROOT="$PWD"
DRY_RUN=0
PROFILE_ONLY=0
for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=1 ;;
        --profile-only) PROFILE_ONLY=1 ;;
        *) REPO_ROOT="$arg" ;;
    esac
done

UTILS_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ ! -x "$UNITY_BIN" ]; then
    echo "ERROR: \$UNITY_BIN is not executable: $UNITY_BIN" >&2
    exit 1
fi

if [ ! -d "$SDK_PATH/Assets" ]; then
    echo "ERROR: \$SDK_PATH does not look like a Unity project: $SDK_PATH" >&2
    exit 1
fi

# Refresh SDK symlinks (idempotent; self-heals after worktree moves).
"$UTILS_DIR/link.sh" "$REPO_ROOT" >/dev/null

# The CLIPublishHelper reads these from the environment.
export MOD_REPO_ROOT="$REPO_ROOT"
[ "$DRY_RUN" = "1" ] && export PUBLISH_DRY_RUN=1
[ "$PROFILE_ONLY" = "1" ] && export PUBLISH_PROFILE_ONLY=1

echo "Publishing $MOD_NAME to mod.io${PUBLISH_PROFILE_ONLY:+ (profile only)}${PUBLISH_DRY_RUN:+ (dry run)}..."

# No -quit: CLIPublishHelper drives async mod.io calls and exits itself.
# timeout guards against a hung network call.
if timeout 600 "$UNITY_BIN" \
        -batchmode \
        -nographics \
        -projectPath "$SDK_PATH" \
        -executeMethod CoreKeeperModUtils.CLIPublishHelper.Publish \
        -logFile -; then
    echo "✓ Publish complete."
else
    code=$?
    [ "$code" = "124" ] && echo "✗ Publish timed out." >&2 \
                        || echo "✗ Publish failed (exit $code). Check the log above." >&2
    exit "$code"
fi
