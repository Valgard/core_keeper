#!/usr/bin/env bash
# utils/link.sh — Idempotently symlink a mod into the shared SDK clone.
#
# Shared by every Core Keeper mod under this directory. The mod's canonical
# files live in the mod repo under `unity/`, laid out as a 1:1 mirror of the
# SDK's `Assets/` tree. This script links that mirror into the SDK clone so
# Unity builds against it:
#
#   $SDK_PATH/Assets/$MOD_NAME            -> <repo>/unity/$MOD_NAME/   (dir symlink)
#   $SDK_PATH/Assets/$MOD_NAME.asset      -> <repo>/unity/$MOD_NAME.asset
#   $SDK_PATH/Assets/$MOD_NAME.asset.meta -> <repo>/unity/$MOD_NAME.asset.meta
#   $SDK_PATH/Assets/$MOD_NAME.meta       -> <repo>/unity/$MOD_NAME.meta
#
# The single directory symlink captures every file inside the mod folder —
# including ones the Unity Editor adds later. The three Assets-level files
# sit beside the mod folder and need their own links.
#
# Usage:
#   utils/link.sh [mod-repo-path]
# The mod repo path defaults to $PWD — run this from the mod repo root, or
# pass the path explicitly.
#
# Required env vars (set in the mod's .envrc):
#   SDK_PATH   Path to the cloned Pugstorm CoreKeeperModSDK
#   MOD_NAME   The mod's PascalCase name (e.g. DisableDurability)
#
# The symlinks encode an absolute path, so they dangle after a worktree
# switch or repo move. `build.sh` re-runs this on every build.

set -euo pipefail

: "${SDK_PATH:?must be set in the mod's .envrc}"
: "${MOD_NAME:?must be set in the mod's .envrc}"

REPO_ROOT="${1:-$PWD}"
ASSETS="$SDK_PATH/Assets"
MIRROR="$REPO_ROOT/unity"

if [ ! -d "$ASSETS" ]; then
    echo "ERROR: SDK Assets dir not found: $ASSETS" >&2
    echo "Is SDK_PATH correct, and has the SDK been set up?" >&2
    exit 1
fi

if [ ! -d "$MIRROR/$MOD_NAME" ]; then
    echo "ERROR: mod mirror not found: $MIRROR/$MOD_NAME" >&2
    echo "Is the mod repo path correct? Got: $REPO_ROOT" >&2
    exit 1
fi

# -s symbolic, -f overwrite existing link, -n don't dereference an existing
# symlink-to-dir (so re-runs replace the link instead of nesting inside it).
ln -sfn "$MIRROR/$MOD_NAME"            "$ASSETS/$MOD_NAME"
ln -sfn "$MIRROR/$MOD_NAME.asset"      "$ASSETS/$MOD_NAME.asset"
ln -sfn "$MIRROR/$MOD_NAME.asset.meta" "$ASSETS/$MOD_NAME.asset.meta"
ln -sfn "$MIRROR/$MOD_NAME.meta"       "$ASSETS/$MOD_NAME.meta"

echo "✓ Symlinks created in $ASSETS:"
ls -la "$ASSETS/$MOD_NAME" "$ASSETS/$MOD_NAME.asset" \
       "$ASSETS/$MOD_NAME.asset.meta" "$ASSETS/$MOD_NAME.meta"
