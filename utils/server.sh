#!/usr/bin/env bash
# utils/server.sh — Run the Core Keeper dedicated server inside the CrossOver bottle.
#
# The dedicated server (Steam app 1963720) ships as a Windows build only, so on
# macOS it runs under CrossOver in the same bottle as the game itself.
#
# Usage:
#   utils/server.sh start     Launch the server, wait until GameInfo.txt appears
#   utils/server.sh stop      Terminate it (see the save caveat below)
#   utils/server.sh status    Show whether it runs, plus the join details
#   utils/server.sh log       Follow CoreKeeperServerLog.txt
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
# Matches the Windows process inside the bottle; -f is the only pgrep/pkill flag
# that behaves correctly under macOS proctools.
PROC_PATTERN="CoreKeeperServer.exe"
# Cold start with a full mod set takes minutes: every mod's scripts go through
# Roslyn and the world is brotli-decompressed (~1.5 MB -> ~22 MB). A restart
# right after a hard stop is slower still, because the compile cache is gone.
START_TIMEOUT=420

is_running() { pgrep -f "$PROC_PATTERN" >/dev/null 2>&1; }

do_start() {
    [ -x "$CXSTART" ] || { echo "ERROR: cxstart not found: $CXSTART" >&2; exit 1; }
    [ -f "$EXE" ] || { echo "ERROR: server not installed: $EXE" >&2; exit 1; }
    is_running && { echo "Server already running (PID $(pgrep -f "$PROC_PATTERN" | head -1))."; do_status; return 0; }

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
    # Caveat: this does NOT trigger a final save — the last autosave is what
    # survives. Give the world a moment rather than stopping mid-session.
    pkill -f "$PROC_PATTERN" || true
    local waited=0
    while is_running && [ "$waited" -lt 40 ]; do
        sleep 2
        waited=$((waited + 2))
    done
    is_running && { echo "WARNING: still running after ${waited}s." >&2; return 1; }
    echo "Stopped after ${waited}s."
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
    *)      echo "Usage: utils/server.sh start|stop|status|log" >&2; exit 1 ;;
esac
