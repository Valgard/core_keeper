#!/usr/bin/env bash
# utils/install-macos.sh — Workaround installer for macOS / CrossOver.
#
# Shared by every Core Keeper mod under this directory.
#
# Pugstorm's mod loader fails to extract Scripts/ from locally built mods
# under Wine (a `\\?\C:\…` long-path bug in RemoveDirectoryRecursive). Mods
# from mod.io load via a different codepath that avoids the bug. This script
# makes a locally built mod look mod.io-installed by populating three places:
#
#   1. mod.io/<game_id>/mods/<mod_id>_<modfile_id>/   (extracted)
#   2. <Temp>/Pugstorm/Core Keeper/<game_id>/<mod_id>_<modfile_id>.zip (cache)
#   3. mod.io/<game_id>/state.json — subscribedMods + mods.<mod_id> entry
#
# Required env vars (set in the mod's .envrc):
#   MOD_INSTALL_PATH   Directory containing the built `$MOD_NAME/` folder.
#   CK_GAME_VERSION    Space-separated list of one or more Core Keeper game
#                      versions, each written as a mod.io compatibility tag
#                      (step 3). Without a tag matching the running game the
#                      loader rejects the mod as "not compatible with current
#                      version". A single version (e.g. "1.2.1.4") works as a
#                      one-element list; add more to support multiple builds
#                      (e.g. "1.2.1.2 1.2.1.4").
#   MOD_NAME           The mod's PascalCase name (e.g. DisableDurability).
#   MOD_NAME_ID        The mod's kebab-case id (e.g. disable-durability).
#   MOD_SUMMARY        One-line mod summary, written into state.json.
#   FAKE_MOD_ID        A numeric mod.io ID not in the catalog; must be
#                      distinct per mod or their mods/<id>_1/ folders collide.
#
# Optional env vars:
#   CK_BOTTLE_NAME     CrossOver bottle name (the folder under .../Bottles/).
#                      Defaults to "Core Keeper".
#   CK_BOTTLE_PATH     Full CrossOver bottle path. Overrides CK_BOTTLE_NAME;
#                      defaults to the standard bottles dir + CK_BOTTLE_NAME.
#   CK_WINE_USER       Wine username inside the bottle. Defaults to "crossover".
#
# Idempotent — safe to re-run after each build.
#
# IMPORTANT: after running this, launch Core Keeper but DO NOT open the
# in-game Mod menu — it triggers a mod.io API sync that deletes the cache.

set -euo pipefail

: "${MOD_INSTALL_PATH:?must be set in the mod's .envrc — see .envrc.example}"
: "${CK_GAME_VERSION:?must be set in the mod's .envrc — see .envrc.example}"
: "${MOD_NAME:?must be set in the mod's .envrc}"
: "${MOD_NAME_ID:?must be set in the mod's .envrc}"
: "${MOD_SUMMARY:?must be set in the mod's .envrc}"
: "${FAKE_MOD_ID:?must be set in the mod's .envrc}"

# --- Constants ---------------------------------------------------------------

GAME_ID="5289"             # Core Keeper's mod.io game ID.
FAKE_MODFILE_ID="1"        # Pugstorm uses this as the cached modfile version.

# --- Resolve bottle path and derive loader paths -----------------------------

CK_BOTTLE_NAME="${CK_BOTTLE_NAME:-Core Keeper}"
CK_BOTTLE_PATH="${CK_BOTTLE_PATH:-$HOME/Library/Application Support/CrossOver/Bottles/$CK_BOTTLE_NAME}"

if [ ! -d "$CK_BOTTLE_PATH" ]; then
    echo "ERROR: CrossOver bottle not found at:" >&2
    echo "       $CK_BOTTLE_PATH" >&2
    echo "       Set CK_BOTTLE_NAME (or CK_BOTTLE_PATH for a non-standard location) in .envrc." >&2
    exit 1
fi

WINE_USER="${CK_WINE_USER:-crossover}"   # CrossOver's default Wine username; override via CK_WINE_USER.

SRC="$MOD_INSTALL_PATH/$MOD_NAME"
MODIO_BASE="$CK_BOTTLE_PATH/drive_c/users/Public/mod.io/$GAME_ID"
MODIO_DST="$MODIO_BASE/mods/${FAKE_MOD_ID}_${FAKE_MODFILE_ID}"
ZIP_DIR="$CK_BOTTLE_PATH/drive_c/users/$WINE_USER/AppData/Local/Temp/Pugstorm/Core Keeper/$GAME_ID"
ZIP_DST="$ZIP_DIR/${FAKE_MOD_ID}_${FAKE_MODFILE_ID}.zip"
STATE_JSON="$MODIO_BASE/state.json"
MODLOADER_CACHE="$CK_BOTTLE_PATH/drive_c/users/$WINE_USER/AppData/Local/Temp/Pugstorm/Core Keeper/ModLoader/$MOD_NAME"

# --- Sanity check on the built mod -------------------------------------------

if [ ! -f "$SRC/ModManifest.json" ]; then
    echo "ERROR: no built mod at $SRC/ModManifest.json" >&2
    echo "       Run the build first." >&2
    exit 1
fi

echo "Installing $MOD_NAME for macOS / CrossOver…"
echo "  Source:    $SRC"
echo "  mod.io:    $MODIO_DST"
echo "  Cache zip: $ZIP_DST"

# --- 1. Copy extracted mod into mod.io path ----------------------------------

rm -rf "$MODIO_DST"
mkdir -p "$MODIO_DST"
cp -R "$SRC/ModManifest.json" "$MODIO_DST/"
[ -d "$SRC/Scripts" ] && cp -R "$SRC/Scripts" "$MODIO_DST/"
[ -d "$SRC/Bundles" ] && cp -R "$SRC/Bundles" "$MODIO_DST/"

# macOS extended attributes can trip Wine in some operations; strip defensively.
xattr -rc "$MODIO_DST/" 2>/dev/null || true

# --- 2. Build the ZIP at the loader's expected cache path --------------------

mkdir -p "$ZIP_DIR"
rm -f "$ZIP_DST"

# zip must produce a flat archive: Bundles/, Scripts/, ModManifest.json at root,
# matching how mods downloaded by Pugstorm's client are packaged.
( cd "$SRC" && zip -qr "$ZIP_DST" Bundles Scripts ModManifest.json )

# --- 3. Patch state.json to register our fake mod ----------------------------

if [ ! -f "$STATE_JSON" ]; then
    echo "ERROR: $STATE_JSON not found. Has the game ever launched with mod.io enabled?" >&2
    exit 1
fi

# Backup once; do not overwrite an existing backup.
[ -f "$STATE_JSON.macos-backup" ] || cp "$STATE_JSON" "$STATE_JSON.macos-backup"

# Find the first user ID under existingUsers (typically the only one).
USER_ID="$(jq -r '.existingUsers | keys[0]' "$STATE_JSON")"
if [ -z "$USER_ID" ] || [ "$USER_ID" = "null" ]; then
    echo "ERROR: could not find a user under existingUsers in $STATE_JSON." >&2
    exit 1
fi

# Add the fake mod to subscribedMods if not already, and write/refresh the
# stub mod entry. jq handles both cases idempotently.
jq --arg user "$USER_ID" \
   --arg modid "$FAKE_MOD_ID" \
   --argjson modidNum "$FAKE_MOD_ID" \
   --argjson modfileNum "$FAKE_MODFILE_ID" \
   --arg name "$MOD_NAME" \
   --arg nameId "$MOD_NAME_ID" \
   --arg summary "$MOD_SUMMARY" \
   --arg gameVersions "$CK_GAME_VERSION" \
   '
   (.existingUsers[$user].subscribedMods) |=
       (if index($modid) then . else . + [$modid] end)
   |
   .mods[$modid] = {
       currentModfile: {
           id: $modfileNum,
           mod_id: $modidNum,
           version: "1.0.0",
           filename: ($name + ".zip")
       },
       modObject: {
           id: $modidNum,
           game_id: 5289,
           status: 1,
           visible: 1,
           name: $name,
           name_id: $nameId,
           summary: $summary,
           tags: ($gameVersions | split(" ") | map(select(length > 0))
                  | map({ name: ., date_added: "0" })),
           modfile: { id: $modfileNum, mod_id: $modidNum }
       }
   }
   ' "$STATE_JSON" > "$STATE_JSON.tmp"
mv "$STATE_JSON.tmp" "$STATE_JSON"

# --- 4. Clean the ModLoader cache for this mod -------------------------------
# The loader will not touch this path for mod.io-routed mods, but a stale entry
# from an earlier StreamingAssets-style install can still trip future runs.

rm -rf "$MODLOADER_CACHE"

# --- 5. Force a fresh localization export ------------------------------------
# Core Keeper accumulates every mod's loc terms into the game-wide
# localization/Localization.csv (its I2 Localization source) first-write-wins:
# a rebuilt bundle with a CHANGED loc value does NOT refresh the stale row (the
# fake dev build keeps modfile id "1", so nothing ever triggers a re-export and
# the old text keeps rendering, even after a cold start). Deleting the CSV makes
# CK rebuild it in full — game + every installed mod — from the current
# TextDataBlocks on next launch, so edited loc values take immediately. It is a
# regenerable cache (verified: every row is I2 " [new]"; a real mod.io update,
# with a new modfile id, is unaffected). Only for loc-shipping mods; no-op if
# the CSV is absent.
LOC_CSV="$CK_BOTTLE_PATH/drive_c/Program Files (x86)/Steam/steamapps/common/Core Keeper/localization/Localization.csv"
if [ -n "${LOC_OUT:-}" ] && [ -f "$LOC_CSV" ]; then
    rm -f "$LOC_CSV"
    echo "  Cleared Localization.csv — CK rebuilds it (game + all mods) on next launch."
fi

echo "✓ Install complete."
echo
echo "  Next: launch Core Keeper. Do NOT open the in-game Mod menu — that"
echo "  triggers a mod.io API sync that will delete this fake entry."
