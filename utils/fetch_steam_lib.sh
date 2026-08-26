#!/usr/bin/env bash
# utils/fetch_steam_lib.sh — put libsteam_api.dylib where the SDK can load it.
#
# The SDK ships the managed Facepunch assemblies and a Windows steam_api64.dll,
# but no macOS native library, so the Steam Workshop tab's "Initialize Steam"
# throws and the upload path is unusable. This fetches the one version that
# works and installs it with import settings limited to the macOS Editor.
#
# WHY THIS EXACT VERSION: the managed assembly requests SteamAPI_SteamUGC_v016
# and SteamAPI_SteamUser_v021, and calls SteamAPI_Init — which Valve removed
# from the flat API around Steamworks 1.59. Newer libraries fail with
# "SteamAPI_Init"; 1.57 offers v017/v023 and initialises but returns nulls.
# Steamworks 1.55 is the match. After an SDK update, re-derive rather than
# trust this pin: the bundled steam_api64.dll names the target generation.
#
# The library is Valve's redistributable and is NOT committed — this repository
# is public.

set -euo pipefail

: "${SDK_PATH:?must be set — see .envrc.example}"

# Facepunch.Steamworks at the commit that vendored Steamworks SDK 1.55.
readonly SOURCE_COMMIT="0fda7e39fe"
readonly SOURCE_URL="https://raw.githubusercontent.com/Facepunch/Facepunch.Steamworks/${SOURCE_COMMIT}/UnityPlugin/redistributable_bin/osx/libsteam_api.dylib"
readonly EXPECTED_SHA256="88dc79403f68e81b6674c927ed362ef3cf69046f587ed009fdc6ad85d85e97f2"

readonly DEST_DIR="$SDK_PATH/Assets/Plugins/CoreKeeperModSDK"
readonly DEST="$DEST_DIR/libsteam_api.dylib"

if [ ! -d "$DEST_DIR" ]; then
    echo "ERROR: $DEST_DIR does not exist — is SDK_PATH right?" >&2
    exit 1
fi

# Native plugin import settings: Editor + macOS only. Without "Any: enabled: 0"
# this would be offered to every build target and could ship inside a mod.
# A function, not a one-shot heredoc, because two call sites below need it:
# a Unity reimport can mangle or drop a .meta independently of the .dylib
# sitting right next to it, so the idempotent early-return path has to repair
# it too rather than report success while quietly leaving it broken.
render_meta() {
    cat <<'META'
fileFormatVersion: 2
guid: 84299398483f4bac894bf4f619c4d3b8
PluginImporter:
  externalObjects: {}
  serializedVersion: 3
  iconMap: {}
  executionOrder: {}
  defineConstraints: []
  isPreloaded: 0
  isOverridable: 0
  isExplicitlyReferenced: 0
  validateReferences: 1
  platformData:
    Any:
      enabled: 0
      settings: {}
    Editor:
      enabled: 1
      settings:
        CPU: AnyCPU
        DefaultValueInitialized: true
        OS: OSX
    OSXUniversal:
      enabled: 1
      settings:
        CPU: AnyCPU
  userData:
  assetBundleName:
  assetBundleVariant:
META
}

# Only touches disk if the file is missing or differs — a correct .meta
# already in place shouldn't get its mtime bumped (and Unity nudged into an
# unnecessary reimport) on every idempotent run.
ensure_meta() {
    if [ ! -f "$DEST.meta" ] || ! diff -q <(render_meta) "$DEST.meta" >/dev/null 2>&1; then
        render_meta >"$DEST.meta"
    fi
}

# Keep the library (and its .meta) out of this SDK clone's history. This is
# Pugstorm's own repository — its .gitignore is theirs, not ours to edit — so
# the guard goes into .git/info/exclude, which is local-only. Best-effort: a
# worktree checkout (where .git is a file, not a directory), a missing git
# binary, or SDK_PATH not being a git repo at all must not fail the fetch —
# protecting the file from an accidental `git add` is a courtesy, not the job
# this script exists to do.
protect_from_git() {
    command -v git >/dev/null 2>&1 || return 0
    local common_dir
    common_dir="$(git -C "$SDK_PATH" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)"
    if [ -z "$common_dir" ]; then
        echo "NOTE: $SDK_PATH is not a git repository — skipping the .git/info/exclude guard." >&2
        return 0
    fi
    local exclude_file="$common_dir/info/exclude"
    local rel="${DEST#"$SDK_PATH"/}"
    mkdir -p "$(dirname "$exclude_file")" 2>/dev/null || return 0
    touch "$exclude_file" 2>/dev/null || return 0
    local pattern
    for pattern in "/$rel" "/$rel.meta"; do
        grep -qxF "$pattern" "$exclude_file" 2>/dev/null || echo "$pattern" >>"$exclude_file" 2>/dev/null || true
    done
    return 0
}

if [ -f "$DEST" ] && [ "$(shasum -a 256 "$DEST" | awk '{print $1}')" = "$EXPECTED_SHA256" ]; then
    echo "✓ libsteam_api.dylib already present and verified."
    ensure_meta
    protect_from_git || true
    exit 0
fi

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
echo "Fetching libsteam_api.dylib (Steamworks 1.55)…"
# --fail, because plain `curl -sSL` exits 0 on every HTTP status and would
# hand the error page to the checksum guard below — which still catches it,
# but as a "mismatch", reading like a tampered or stale pin rather than what
# actually happened. Same failure mode utils/refresh_game_versions.py's
# _get() documents ("plain curl -sS exits 0 on every HTTP status"), fixed
# there with --fail-with-body because it also needed the JSON error body;
# here the body is worthless, so plain --fail is enough.
curl -sSL --fail -o "$tmp" "$SOURCE_URL"

actual="$(shasum -a 256 "$tmp" | awk '{print $1}')"
if [ "$actual" != "$EXPECTED_SHA256" ]; then
    echo "ERROR: checksum mismatch — refusing to install." >&2
    echo "  expected: $EXPECTED_SHA256" >&2
    echo "  actual:   $actual" >&2
    exit 2
fi

# Verify it is what we think it is before it goes anywhere near the Editor.
if ! nm -gU "$tmp" 2>/dev/null | grep -qE " _SteamAPI_Init$"; then
    echo "ERROR: the fetched library does not export SteamAPI_Init." >&2
    exit 3
fi

mv "$tmp" "$DEST"
trap - EXIT
xattr -c "$DEST" 2>/dev/null || true
ensure_meta
protect_from_git || true

echo "✓ Installed $DEST"
echo "  Restart the Unity Editor — native plugins are loaded at startup."
