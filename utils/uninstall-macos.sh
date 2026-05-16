#!/usr/bin/env bash
# utils/uninstall-macos.sh — Remove a fake-ID local dev install (macOS/CrossOver).
#
# Shared by every Core Keeper mod under this directory.
#
# The mirror image of install-macos.sh. Use it before subscribing to the
# real published mod, so the dev build and the published build never load
# at the same time. Idempotent — a no-op if the mod is not installed.
#
# Required env vars (set in the mod's .envrc):
#   MOD_NAME           The mod's PascalCase name (e.g. DisableDurability).
#   FAKE_MOD_ID        The numeric mod.io ID to uninstall (same as used in
#                      install-macos.sh).
#
# Optional env vars:
#   CK_BOTTLE_PATH     CrossOver bottle path. Defaults to the standard
#                      "Core Keeper" bottle.

set -euo pipefail

: "${MOD_NAME:?must be set in the mod's .envrc}"
: "${FAKE_MOD_ID:?must be set in the mod's .envrc}"

# --- Constants ---------------------------------------------------------------

GAME_ID="5289"             # Core Keeper's mod.io game ID.
FAKE_MODFILE_ID="1"        # Pugstorm uses this as the cached modfile version.

# --- Resolve bottle path and derive loader paths -----------------------------

CK_BOTTLE_PATH="${CK_BOTTLE_PATH:-$HOME/Library/Application Support/CrossOver/Bottles/Core Keeper}"

WINE_USER="crossover"   # CrossOver's default Wine username; adjust if your bottle differs.

MODIO_BASE="$CK_BOTTLE_PATH/drive_c/users/Public/mod.io/$GAME_ID"
MODIO_DST="$MODIO_BASE/mods/${FAKE_MOD_ID}_${FAKE_MODFILE_ID}"
ZIP_DIR="$CK_BOTTLE_PATH/drive_c/users/$WINE_USER/AppData/Local/Temp/Pugstorm/Core Keeper/$GAME_ID"
ZIP_DST="$ZIP_DIR/${FAKE_MOD_ID}_${FAKE_MODFILE_ID}.zip"
STATE_JSON="$MODIO_BASE/state.json"
MODLOADER_CACHE="$CK_BOTTLE_PATH/drive_c/users/$WINE_USER/AppData/Local/Temp/Pugstorm/Core Keeper/ModLoader/$MOD_NAME"

echo "Uninstalling $MOD_NAME (fake id $FAKE_MOD_ID) for macOS / CrossOver…"

# --- 1. Remove extracted mod files and the cache zip -------------------------

rm -rf "$MODIO_DST"
rm -f "$ZIP_DST"
rm -rf "$MODLOADER_CACHE"

# --- 2. Drop the fake mod from state.json ------------------------------------

if [ -f "$STATE_JSON" ]; then
    jq --arg modid "$FAKE_MOD_ID" '
        (.existingUsers) |= map_values(
            .subscribedMods |= ((. // []) | map(select(. != $modid)))
        )
        | del(.mods[$modid])
    ' "$STATE_JSON" > "$STATE_JSON.tmp"
    mv "$STATE_JSON.tmp" "$STATE_JSON"
    echo "  Removed $FAKE_MOD_ID from $STATE_JSON"
else
    echo "  No state.json — nothing to unsubscribe."
fi

echo "✓ Uninstall complete."
