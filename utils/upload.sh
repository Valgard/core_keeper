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
# The mod repo path defaults to $PWD. A relative path is fine, here and in the env
# vars below: MOD_CALLER_CWD carries this shell's directory into Unity as the anchor
# they resolve against.
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

# Checked before Unity is launched at all, so a mistyped path costs a second instead of the
# two minutes an Editor start takes. Deliberately NOT absolutised here: link.sh resolves its
# own argument (it must — symlink targets), discord_post.py runs in this very directory, and
# the value handed to Unity is resolved there against MOD_CALLER_CWD, exported below.
if [ ! -d "$REPO_ROOT" ]; then
    echo "ERROR: '$REPO_ROOT' is not a directory." >&2
    exit 1
fi

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
# in the batchmode log. A repo without a discord-post.md prints nothing.
#
# CK_DISCORD_THREAD set means the mod already has a thread: both this
# preflight and the post-publish banner below render with --update, the
# version comment for that thread, instead of the full original
# announcement -- posting the whole introduction again would land as a
# duplicate in a thread that already exists.
DISCORD_MODE_FLAGS=()
if [ -n "${CK_DISCORD_THREAD:-}" ]; then
    DISCORD_MODE_FLAGS=(--update)
fi

# Exit 3 means the post itself is wrong, and that is waved through: nothing
# about a forum thread should hold back a mod.io release. Any other non-zero
# code is the tooling being broken (no python3, a corrupt data file, a syntax
# error) and aborts, because continuing would publish while silently skipping a
# check. Note the posts live in the *mod* repos, whose pre-commit hooks run
# csharpier only — utils/tests/test_discord_post_content.py sees them just when
# somebody commits under utils/ here, so it is a backstop, not a gate.
discord_rc=0
python3 "$UTILS_DIR/discord_post.py" --check "${DISCORD_MODE_FLAGS[@]}" "$REPO_ROOT" || discord_rc=$?
case "$discord_rc" in
    0) ;;
    3) echo "  (continuing — the Discord post is not part of the mod.io release)" >&2 ;;
    *) echo "ERROR: discord_post.py failed with exit $discord_rc — that is a tooling" >&2
       echo "       failure, not a problem with the post. Fix it or publish without it." >&2
       exit "$discord_rc" ;;
esac

# Refresh SDK symlinks (idempotent; self-heals after worktree moves).
"$UTILS_DIR/link.sh" "$REPO_ROOT" >/dev/null

# The shipped-build list, so CLIPublishHelper can tell a typo from a build
# mod.io has no tag for without asking mod.io. That distinction is otherwise
# only available on the tag-taxonomy path, which degrades to additive tagging
# whenever the API hiccups -- and there a typo is dropped in silence.
CK_KNOWN_GAME_VERSIONS="$(python3 -c "
import json, sys
print(' '.join(json.load(open(sys.argv[1]))['versions']))
" "$UTILS_DIR/ck-game-versions.json")"
export CK_KNOWN_GAME_VERSIONS

# The CLIPublishHelper reads these from the environment. MOD_CALLER_CWD is the anchor every
# relative one of them resolves against: a variable survives the jump into Unity, the working
# directory does not, and Unity's own is not this one — so without it `upload.sh .` dies two
# minutes in with "No CHANGELOG.md at ./CHANGELOG.md", naming a file that is plainly there.
# See EnvPaths at the bottom of utils/CLIBuildHelper.cs.
export MOD_CALLER_CWD="$PWD"
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
    # A release is the moment the Discord thread goes stale, so hand the post
    # over right here instead of making it a separate thing to remember. Only
    # for a real release: --profile-only stops before the upload and
    # --changelog-only edits an existing modfile, so neither leaves the thread
    # out of date, and printing the post there is a false prompt to go post.
    if [ "$DRY_RUN" != "1" ] && [ "$PROFILE_ONLY" != "1" ] && [ "$CHANGELOG_ONLY" != "1" ]; then
        # A thread already exists -> render the version comment for it
        # instead of the full original announcement (see DISCORD_MODE_FLAGS
        # above) — the same duplicate-post reasoning, at the moment it
        # actually gets printed.
        if [ -n "${CK_DISCORD_THREAD:-}" ]; then
            discord_banner="version comment for the existing thread"
        else
            discord_banner="#available-mods post"
        fi
        # Captured rather than streamed: on failure the banner would otherwise
        # frame an empty post, which reads as "this mod has none".
        if post="$(python3 "$UTILS_DIR/discord_post.py" "${DISCORD_MODE_FLAGS[@]}" "$REPO_ROOT")" && [ -n "$post" ]; then
            printf '\n--- %s ---\n' "$discord_banner"
            printf '%s\n' "$post"
            printf -- '--------------------------------------------------------------\n'
        elif [ -f "$REPO_ROOT/discord-post.md" ]; then
            echo "! The Discord post did not render (see above). The mod.io release" >&2
            echo "  is published; the forum thread is not updated." >&2
        fi
    fi
else
    code=$?
    [ "$code" = "124" ] && echo "✗ Publish timed out." >&2 \
                        || echo "✗ Publish failed (exit $code). Check the log above." >&2
    exit "$code"
fi
