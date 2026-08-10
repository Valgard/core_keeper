#!/usr/bin/env bash
# utils/server.sh — Run the Core Keeper dedicated server inside the CrossOver bottle.
#
# The dedicated server (Steam app 1963720) ships as a Windows build only, so on
# macOS it runs under CrossOver in the same bottle as the game itself.
#
# Usage:
#   utils/server.sh start     Relink the mods, launch, wait for GameInfo.txt
#   utils/server.sh stop      Terminate it (see the save caveat below)
#   utils/server.sh status    Show whether it runs, plus the join details
#   utils/server.sh log       Follow CoreKeeperServerLog.txt
#   utils/server.sh relink    Re-point the mod symlinks at the current cache
#                   relink --prune   …and drop links whose mod is gone for good
#
# Env vars (set in .envrc; all optional, defaults shown):
#   CK_BOTTLE_NAME       CrossOver bottle name.                 "Core Keeper"
#   CK_BOTTLE_PATH       Full bottle path; overrides the above.
#   CK_SERVER_DIR        Server install dir inside the bottle.
#   CK_SERVER_WORLD      World index, 0-29.                     0
#   CK_SERVER_PORT       Direct-connect port. Empty = SDR only. 27015
#   CK_SERVER_PASSWORD   Join password. Empty = server-generated.
#   CK_SERVER_MAXPLAYERS Player cap.                            8
#   CK_SERVER_PLATFORM   -allowonlyplatform value. Empty = all. Steam
#
# Exit codes:
#   0  Success
#   1  Missing path or bad argument
#   2  Server did not come up within the timeout

set -euo pipefail

CK_BOTTLE_NAME="${CK_BOTTLE_NAME:-Core Keeper}"
CK_BOTTLE_PATH="${CK_BOTTLE_PATH:-$HOME/Library/Application Support/CrossOver/Bottles/$CK_BOTTLE_NAME}"
CK_SERVER_DIR="${CK_SERVER_DIR:-$CK_BOTTLE_PATH/drive_c/Program Files (x86)/Steam/steamapps/common/Core Keeper Dedicated Server}"
CK_SERVER_WORLD="${CK_SERVER_WORLD:-0}"
CK_SERVER_PORT="${CK_SERVER_PORT:-27015}"
CK_SERVER_PASSWORD="${CK_SERVER_PASSWORD:-}"
CK_SERVER_MAXPLAYERS="${CK_SERVER_MAXPLAYERS:-8}"
CK_SERVER_PLATFORM="${CK_SERVER_PLATFORM:-Steam}"

CXSTART="/Applications/CrossOver.app/Contents/SharedSupport/CrossOver/bin/cxstart"
EXE="$CK_SERVER_DIR/CoreKeeperServer.exe"
GAMEINFO="$CK_SERVER_DIR/GameInfo.txt"
LOGFILE="$CK_SERVER_DIR/CoreKeeperServerLog.txt"
MODS_DIR="$CK_SERVER_DIR/CoreKeeperServer_Data/StreamingAssets/Mods"
MODIO_CACHE="$CK_BOTTLE_PATH/drive_c/users/Public/mod.io/5289/mods"
# Matches the Windows process inside the bottle; -f is the only pgrep/pkill flag
# that behaves correctly under macOS proctools.
PROC_PATTERN="CoreKeeperServer.exe"
# Cold start with a full mod set takes minutes: every mod's scripts go through
# Roslyn and the world is brotli-decompressed (~1.5 MB -> ~22 MB). A restart
# right after a hard stop is slower still, because the compile cache is gone.
START_TIMEOUT=420

# install-macos.sh gives every dev build a fake mod.io id well above the real
# catalogue, so the id alone says whether a cache folder is a local build.
FAKE_ID_MIN=9999000

is_running() { pgrep -f "$PROC_PATTERN" >/dev/null 2>&1; }

# metadata.name from a mod folder's ModManifest.json — the identity the server
# actually goes by. Empty when the file is missing or unparsable.
manifest_name() {
    python3 -c 'import json,sys
try:
    print(json.load(open(sys.argv[1]))["name"])
except Exception:
    pass' "$1/ModManifest.json" 2>/dev/null
}

# The server has no mod directory of its own: every entry under
# StreamingAssets/Mods is a symlink into the *client's* mod.io cache, whose
# folders are named <modId>_<modfileId>. mod.io mints a fresh modfileId on every
# release, so each update — ours or a foreign mod's — leaves the link pointing at
# a folder that is on its way out. Two ways that hurts, both quiet: the folder
# disappears and the server drops the mod (with the Server flag in requiredOn the
# client then refuses to join), or the folder lingers and the server keeps
# running the *old* version while the client has the new one. Re-point every link
# at the highest modfileId currently in the cache.
#
# A link whose mod has no cache folder at all is only reported, not removed:
# "folder is missing" covers both "unsubscribed for good" and "mod.io is
# rewriting it right now" (opening the in-game Mods menu triggers exactly such a
# sweep), and the script cannot tell them apart. Since the symlinks *are* the
# server's mod selection — there is no second list to restore from — deleting on
# a guess is the expensive mistake, while a stale link is inert: the loader gates
# on File.Exists(ModManifest.json) and skips it silently. --prune is the explicit
# opt-in for cleaning up, and do_start never passes it.
do_relink() {
    [ -d "$MODS_DIR" ] || { echo "ERROR: server mod dir not found: $MODS_DIR" >&2; exit 1; }
    [ -d "$MODIO_CACHE" ] || { echo "ERROR: mod.io cache not found: $MODIO_CACHE" >&2; exit 1; }

    local prune=0
    if [ "${1:-}" = "--prune" ]; then
        prune=1
    fi

    local updated=0 unchanged=0 missing=0 pruned=0 deduped=0
    local link target id newest want
    for link in "$MODS_DIR"/*; do
        [ -L "$link" ] || continue          # leave real directories alone
        target="$(readlink "$link")"
        # Take the modId from the current target rather than the link name:
        # folder names here are free-form (the loader reads each
        # ModManifest.json), and readlink still answers once the link dangles.
        id="$(basename "$target")"
        id="${id%%_*}"
        case "$id" in ''|*[!0-9]*) continue ;; esac   # not a mod.io cache link
        # Sort numerically on the modfileId suffix — the highest is the newest
        # release. Normally there is exactly one candidate.
        newest="$(find "$MODIO_CACHE" -maxdepth 1 -type d -name "${id}_*" \
                  -exec basename {} \; | sort -t_ -k2,2n | tail -1)"
        if [ -z "$newest" ]; then
            if [ "$prune" -eq 1 ]; then
                rm -f "$link"
                echo "  pruned $(basename "$link") (was $(basename "$target"))"
                pruned=$((pruned + 1))
            else
                echo "WARNING: no cache folder for mod $id — server starts without it" >&2
                missing=$((missing + 1))
            fi
            continue
        fi
        want="$MODIO_CACHE/$newest"
        if [ "$target" = "$want" ]; then
            unchanged=$((unchanged + 1))
        else
            # -n so an existing link to a directory is replaced instead of the
            # new link being created *inside* it.
            ln -sfn "$want" "$link"
            echo "  $(basename "$link"): $(basename "$target") -> $newest"
            updated=$((updated + 1))
        fi
    done

    # Resolve duplicates. A mod installed both from mod.io and as a fake-ID dev
    # build has two cache folders, and nothing downstream separates them: the
    # server derives ModId from -Abs(metadata.name.GetHashCode()) and the loader
    # extracts scripts to ModLoader/<metadata.name>, so two links to the same mod
    # get the same id and the same working directory. The client is no better off
    # — it feeds both into the loader and only survives because of that same
    # collision. The dev build wins, which is what effectively happens there too.
    local dup_names losers name winner loser
    dup_names="$(mktemp)"; losers="$(mktemp)"
    : > "$dup_names"
    for link in "$MODS_DIR"/*; do
        [ -L "$link" ] || continue
        target="$(readlink "$link")"
        [ -f "$target/ModManifest.json" ] || continue
        name="$(manifest_name "$target")"
        [ -n "$name" ] || continue
        id="$(basename "$target")"; id="${id%%_*}"
        printf '%s\t%s\t%s\n' "$name" "$id" "$link" >> "$dup_names"
    done
    while IFS= read -r name; do
        [ -n "$name" ] || continue
        winner="$(awk -F'\t' -v n="$name" -v m="$FAKE_ID_MIN" '$1==n && $2+0>=m {print $3}' "$dup_names")"
        if [ "$(printf '%s' "$winner" | grep -c .)" -ne 1 ]; then
            echo "WARNING: '$name' is linked more than once and no single dev build settles it — resolve by hand" >&2
            continue
        fi
        awk -F'\t' -v n="$name" -v w="$winner" '$1==n && $3!=w {print $3}' "$dup_names" > "$losers"
        while IFS= read -r loser; do
            [ -n "$loser" ] || continue
            rm -f "$loser"
            echo "  deduped $name: dropped $(basename "$loser"), kept $(basename "$winner")"
            deduped=$((deduped + 1))
        done < "$losers"
    done < <(cut -f1 "$dup_names" | sort | uniq -d)
    rm -f "$dup_names" "$losers"

    local summary="Mod symlinks: $updated updated, $unchanged unchanged"
    if [ "$deduped" -gt 0 ]; then
        summary="$summary, $deduped deduped"
    fi
    if [ "$pruned" -gt 0 ]; then
        summary="$summary, $pruned pruned"
    fi
    if [ "$missing" -gt 0 ]; then
        summary="$summary, $missing WITHOUT a cache folder (drop them with: relink --prune)"
    fi
    echo "$summary"
}

do_start() {
    [ -x "$CXSTART" ] || { echo "ERROR: cxstart not found: $CXSTART" >&2; exit 1; }
    [ -f "$EXE" ] || { echo "ERROR: server not installed: $EXE" >&2; exit 1; }
    is_running && { echo "Server already running (PID $(pgrep -f "$PROC_PATTERN" | head -1))."; do_status; return 0; }

    # Always before launching: the mod set is read once at startup, so a link
    # left pointing at a superseded cache folder silently changes what runs.
    do_relink

    local argv=(-batchmode -logfile CoreKeeperServerLog.txt
                -world "$CK_SERVER_WORLD" -maxplayers "$CK_SERVER_MAXPLAYERS")
    # NEVER add -nographics: part of the procedural world generation runs on the
    # GPU, so the server needs a graphics device even headless.
    [ -n "$CK_SERVER_PORT" ] && argv+=(-port "$CK_SERVER_PORT")
    [ -n "$CK_SERVER_PASSWORD" ] && argv+=(-password "$CK_SERVER_PASSWORD")
    [ -n "$CK_SERVER_PLATFORM" ] && argv+=(-allowonlyplatform "$CK_SERVER_PLATFORM")

    rm -f "$GAMEINFO" "$LOGFILE"
    # nohup + disown: cxstart --no-wait alone still keeps the process attached to
    # this shell, so it would die with the caller.
    nohup "$CXSTART" --bottle "$CK_BOTTLE_NAME" --workdir "$CK_SERVER_DIR" --no-wait \
        "$EXE" "${argv[@]}" >/dev/null 2>&1 &
    disown

    echo "Starting (world $CK_SERVER_WORLD)…"
    local waited=0
    while [ ! -f "$GAMEINFO" ] && [ "$waited" -lt "$START_TIMEOUT" ]; do
        sleep 4
        waited=$((waited + 4))
    done
    if [ ! -f "$GAMEINFO" ]; then
        # A live process past the timeout is slow, not broken — say so instead
        # of reporting a failure the user would go hunting for.
        if is_running; then
            echo "Still starting after ${START_TIMEOUT}s (process alive)." >&2
            echo "Follow it with: utils/server.sh log" >&2
        else
            echo "ERROR: server died during startup — see $LOGFILE" >&2
        fi
        exit 2
    fi
    echo "Up after ${waited}s."
    echo
    do_status
}

do_stop() {
    is_running || { echo "Server is not running."; return 0; }

    # Graceful shutdown goes through Windows' WM_CLOSE, which Unity turns into a
    # quit request: Application.wantsToQuit lets the managers block until they
    # have finished writing, then QuitHandler() runs Deinit() on all of them and
    # removes PID.txt. A POSIX signal (pkill/SIGTERM) bypasses all of that — the
    # process just disappears and the last autosave is what survives.
    # This is also why Pugstorm's own Launch.ps1 uses `taskkill` without /F.
    echo "Requesting shutdown (taskkill)…"
    "$CXSTART" --bottle "$CK_BOTTLE_NAME" --no-wait --no-convert \
        'C:\windows\system32\taskkill.exe' /IM CoreKeeperServer.exe >/dev/null 2>&1 || true

    local waited=0
    while is_running && [ "$waited" -lt 60 ]; do
        sleep 2
        waited=$((waited + 2))
    done

    if is_running; then
        echo "Still running after ${waited}s — falling back to SIGTERM (no final save)." >&2
        pkill -f "$PROC_PATTERN" || true
        while is_running && [ "$waited" -lt 90 ]; do
            sleep 2
            waited=$((waited + 2))
        done
        is_running && { echo "WARNING: still running after ${waited}s." >&2; return 1; }
    fi

    echo "Stopped after ${waited}s."
    # "Running quit handlers" only appears when the graceful path was taken; a
    # leftover PID.txt is the same signal inverted.
    if grep -q "Running quit handlers" "$LOGFILE" 2>/dev/null; then
        echo "Quit handlers ran — world was flushed."
    else
        echo "NOTE: no quit handlers in the log — the last autosave is what survives." >&2
    fi
}

do_status() {
    if is_running; then
        echo "Running (PID $(pgrep -f "$PROC_PATTERN" | head -1))"
    else
        echo "Not running"
    fi
    [ -f "$GAMEINFO" ] || return 0
    echo
    grep -E "^(Steam GameID|Local IP|Public IP|Port|Password|Allowed platforms):" "$GAMEINFO" || true
    # `|| true` on every capture: with `set -o pipefail` a non-matching grep
    # would fail the whole assignment and abort the script under `set -e`.
    local ip port pass
    ip=$(grep -E "^Local IP:" "$GAMEINFO" | awk '{print $3}' || true)
    port=$(grep -E "^Port:" "$GAMEINFO" | awk '{print $2}' || true)
    pass=$(grep -E "^Password:" "$GAMEINFO" | awk '{print $2}' || true)
    if [ -n "$ip" ] && [ -n "$port" ]; then
        echo
        echo "Join via IP:  $ip;$port;;$pass"
    fi
}

case "${1:-}" in
    start)  do_start ;;
    stop)   do_stop ;;
    status) do_status ;;
    log)    exec tail -f "$LOGFILE" ;;
    relink)
        # Validate the flag instead of passing it straight through: a typo like
        # --prun would otherwise quietly read as "no pruning".
        case "${2:-}" in
            ''|--prune) do_relink "${2:-}" ;;
            *) echo "Usage: utils/server.sh relink [--prune]" >&2; exit 1 ;;
        esac
        ;;
    *)      echo "Usage: utils/server.sh start|stop|status|log|relink [--prune]" >&2; exit 1 ;;
esac
