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
#   CK_BOTTLE_NAME     CrossOver bottle name (the folder under .../Bottles/).
#                      Defaults to "Core Keeper".
#   CK_BOTTLE_PATH     Full CrossOver bottle path. Overrides CK_BOTTLE_NAME;
#                      defaults to the standard bottles dir + CK_BOTTLE_NAME.
#   CK_WINE_USER       Wine username inside the bottle. Defaults to "crossover".
#   LOC_OUT            Presence marks the mod as loc-shipping and enables step 3
#                      (the Localization.csv clear). Same gate as install-macos.sh.

set -euo pipefail

: "${MOD_NAME:?must be set in the mod's .envrc}"
: "${FAKE_MOD_ID:?must be set in the mod's .envrc}"

# --- Constants ---------------------------------------------------------------

GAME_ID="5289"             # Core Keeper's mod.io game ID.
FAKE_MODFILE_ID="1"        # Pugstorm uses this as the cached modfile version.

# --- Resolve bottle path and derive loader paths -----------------------------

CK_BOTTLE_NAME="${CK_BOTTLE_NAME:-Core Keeper}"
CK_BOTTLE_PATH="${CK_BOTTLE_PATH:-$HOME/Library/Application Support/CrossOver/Bottles/$CK_BOTTLE_NAME}"

WINE_USER="${CK_WINE_USER:-crossover}"   # CrossOver's default Wine username; override via CK_WINE_USER.

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

# --- 3. Force a fresh localization export ------------------------------------
# The mirror of install-macos.sh step 5, and needed for the same reason: Core
# Keeper accumulates every mod's loc terms into the game-wide
# localization/Localization.csv (its I2 Localization source) first-write-wins,
# and renders from that CSV rather than from the mod's AssetBundle. Removing a
# mod leaves its rows behind, which bites in exactly the transition this script
# exists for — swapping a dev build for the published mod. Any term whose value
# CHANGED in between would keep rendering the dev-era text, because the row
# already exists (NEW terms are additive and unaffected). Deleting the CSV makes
# CK rebuild it in full — game + every remaining mod — from the current
# TextDataBlocks on next launch. It is a regenerable cache. Only for
# loc-shipping mods; no-op if the CSV is absent.
LOC_CSV="$CK_BOTTLE_PATH/drive_c/Program Files (x86)/Steam/steamapps/common/Core Keeper/localization/Localization.csv"
if [ -n "${LOC_OUT:-}" ] && [ -f "$LOC_CSV" ]; then
    rm -f "$LOC_CSV"
    echo "  Cleared Localization.csv — CK rebuilds it (game + all mods) on next launch."
fi

echo "✓ Uninstall complete."
