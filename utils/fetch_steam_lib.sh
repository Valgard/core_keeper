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

if [ -f "$DEST" ] && [ "$(shasum -a 256 "$DEST" | awk '{print $1}')" = "$EXPECTED_SHA256" ]; then
    echo "✓ libsteam_api.dylib already present and verified."
    exit 0
fi

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
echo "Fetching libsteam_api.dylib (Steamworks 1.55)…"
curl -sSL -o "$tmp" "$SOURCE_URL"

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

# Native plugin import settings: Editor + macOS only. Without "Any: enabled: 0"
# this would be offered to every build target and could ship inside a mod.
cat > "$DEST.meta" <<'META'
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

echo "✓ Installed $DEST"
echo "  Restart the Unity Editor — native plugins are loaded at startup."
