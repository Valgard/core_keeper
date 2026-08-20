#!/usr/bin/env bash
# utils/upload.sh — Publish a Core Keeper mod to mod.io via Unity batchmode.
#
# Shared by every Core Keeper mod under this directory. Refreshes the SDK
# symlinks, then runs CoreKeeperModUtils.CLIPublishHelper.Publish (the shared
# helper, identified by MOD_NAME), which builds the mod and uploads it through
# the mod.io plugin.
#
# Usage:
#   utils/upload.sh [mod-repo-path] [--dry-run] [--profile-only|--changelog-only]
#
# --profile-only updates just the mod.io profile (description, name, summary,
# logo) via EditModProfile — no build, no version tags, no dependency sync, no
# modfile upload. Use it to push an edited modio-description.md without cutting
# a new release.
#
# --changelog-only rewrites the published release's changelog text and nothing
# else. A changelog belongs to the modfile rather than the profile, so
# --profile-only cannot reach it; this mode edits the existing modfile in place
# (no upload, no version change). It refuses unless the live modfile's version
# equals CHANGELOG.md's topmost entry, so it can only correct the notes OF the
# published release. Use it when a shipped changelog entry is wrong; use a real
# release for anything that changes what the mod does.
#
# Required env vars (set in the mod's .envrc):
#   UNITY_BIN, SDK_PATH, MOD_NAME, CK_GAME_VERSION, MOD_SUMMARY
#
# A mod with a discord-post.md also needs CK_DISCORD_TAGS; it is checked
# before Unity starts and printed, rendered, after a successful publish.
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
CHANGELOG_ONLY=0
for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=1 ;;
        --profile-only) PROFILE_ONLY=1 ;;
        --changelog-only) CHANGELOG_ONLY=1 ;;
        *) REPO_ROOT="$arg" ;;
    esac
done

if [ "$PROFILE_ONLY" = "1" ] && [ "$CHANGELOG_ONLY" = "1" ]; then
    echo "ERROR: --profile-only and --changelog-only are separate modes; pick one." >&2
    exit 1
fi

UTILS_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ ! -x "$UNITY_BIN" ]; then
    echo "ERROR: \$UNITY_BIN is not executable: $UNITY_BIN" >&2
    exit 1
fi

if [ ! -d "$SDK_PATH/Assets" ]; then
    echo "ERROR: \$SDK_PATH does not look like a Unity project: $SDK_PATH" >&2
    exit 1
fi

# Discord preflight — before Unity, so a broken post surfaces in seconds rather
# than after a ten-minute build, and at the top of the output rather than buried
# in the batchmode log. Deliberately non-fatal: a post 30 characters over the
# limit is no reason to hold back a mod release. The hard gate is the pytest
# suite (utils/tests/test_discord_post_content.py), where prose problems belong.
# A repo without a discord-post.md prints nothing and exits 0.
if ! python3 "$UTILS_DIR/discord_post.py" --check "$REPO_ROOT"; then
    echo "  (continuing — the Discord post is not part of the mod.io release)" >&2
fi

# Refresh SDK symlinks (idempotent; self-heals after worktree moves).
"$UTILS_DIR/link.sh" "$REPO_ROOT" >/dev/null

# The CLIPublishHelper reads these from the environment.
export MOD_REPO_ROOT="$REPO_ROOT"
[ "$DRY_RUN" = "1" ] && export PUBLISH_DRY_RUN=1
[ "$PROFILE_ONLY" = "1" ] && export PUBLISH_PROFILE_ONLY=1
[ "$CHANGELOG_ONLY" = "1" ] && export PUBLISH_CHANGELOG_ONLY=1

echo "Publishing $MOD_NAME to mod.io${PUBLISH_PROFILE_ONLY:+ (profile only)}${PUBLISH_CHANGELOG_ONLY:+ (changelog only)}${PUBLISH_DRY_RUN:+ (dry run)}..."

# No -quit: CLIPublishHelper drives async mod.io calls and exits itself.
# timeout guards against a hung network call.
if timeout 600 "$UNITY_BIN" \
        -batchmode \
        -nographics \
        -projectPath "$SDK_PATH" \
        -executeMethod CoreKeeperModUtils.CLIPublishHelper.Publish \
        -logFile -; then
    echo "✓ Publish complete."
    # The release is the moment the Discord thread goes stale, so hand over the
    # post right here instead of making it a separate thing to remember.
    if [ "$DRY_RUN" != "1" ] && [ -f "$REPO_ROOT/discord-post.md" ]; then
        echo
        echo "--- #available-mods post ---------------------------------------"
        python3 "$UTILS_DIR/discord_post.py" "$REPO_ROOT" || true
        echo "----------------------------------------------------------------"
    fi
else
    code=$?
    [ "$code" = "124" ] && echo "✗ Publish timed out." >&2 \
                        || echo "✗ Publish failed (exit $code). Check the log above." >&2
    exit "$code"
fi
