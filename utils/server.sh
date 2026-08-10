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
#   utils/server.sh relink    Reconcile the mod symlinks with the client's set
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

# The client's loader config: carries the normalised game version and the mods
# the player waved through the incompatible-mod dialog. Both are needed to model
# the version filter; empty when absent, which simply disables that filter.
LOADER_CFG="$(find "$CK_BOTTLE_PATH/drive_c/users/${CK_WINE_USER:-crossover}/AppData/LocalLow/Pugstorm/Core Keeper/Steam" \
    -maxdepth 3 -name config.json -path "*/modloader/*" 2>/dev/null | head -1)"

is_running() { pgrep -f "$PROC_PATTERN" >/dev/null 2>&1; }

# Prints the reconciliation plan, one tab-separated action per line:
#   ADD <link> <cacheFolder> <modName>    create a missing link
#   SET <link> <cacheFolder> <modName>    re-point an existing link
#   MOV <link> <newName> <modName>        rename a link to the mod.io slug
#   DEL <link> <reason>                   remove a link
#   KEEP                                  counted only
#   WARN <message>                        reported, nothing done
# Exits non-zero when the target set cannot be determined (unreadable state.json,
# or nothing subscribed and installed); the caller then leaves everything alone.
relink_plan() {
    MODS_DIR="$MODS_DIR" MODIO_CACHE="$MODIO_CACHE" LOADER_CFG="$LOADER_CFG" \
    FAKE_ID_MIN="$FAKE_ID_MIN" python3 -c '
import json, os, glob, sys

mods_dir = os.environ["MODS_DIR"]
cache    = os.environ["MODIO_CACHE"]
cfg      = os.environ["LOADER_CFG"]
fake_min = int(os.environ["FAKE_ID_MIN"])
state    = os.path.join(os.path.dirname(cache), "state.json")

# --- what the client will load: subscribed, enabled, installed --------------
# This mirrors PugMod.Platform: it walks GetSubscribedMods() and skips anything
# disabled, not installed, or without a manifest. Taking the folder from
# currentModfile.id rather than guessing at the cache matters - the cache keeps
# superseded folders around (CoreLib had 3177992_7845185 next to _7710097), and
# "highest number wins" is a guess where state.json has the answer.
try:
    st = json.load(open(state, encoding="utf-8"))
except Exception:
    sys.exit(1)

mods = st.get("mods", {})
subs, disabled = set(), set()
for u in st.get("existingUsers", {}).values():
    subs     |= {str(x.get("id") if isinstance(x, dict) else x) for x in u.get("subscribedMods", [])}
    disabled |= {str(x) for x in u.get("disabledMods", [])}

# The client also drops mods whose mod.io tags do not carry the running game
# version, unless the player confirmed them through the incompatible-mod dialog.
# ModVersion compares only the first three components, so 1.2.1.5 accepts a
# 1.2.1.0 tag. The loader writes that normalised version into its own config.
game_ver, forced = None, set()
try:
    c = json.load(open(cfg, encoding="utf-8"))
    game_ver = c.get("version")
    forced = {str(x) for x in c.get("unsupportedModsToLoad", [])}
except Exception:
    pass

def compatible(tags):
    if not game_ver:
        return True
    want3 = game_ver.split(".")[:3]
    for tag in tags:
        parts = str(tag.get("name") if isinstance(tag, dict) else tag).split(".")
        if len(parts) >= 3 and parts[:3] == want3:
            return True
    return False

# metadata.name and guid live only in the manifest - modObject.name is the mod.io
# profile name, which differs ("Mod Settings Menu" vs "ModSettingsMenu").
cands = {}
for mid in sorted(subs - disabled):
    entry = mods.get(mid) or {}
    cf = entry.get("currentModfile") or {}
    fid = cf.get("id")
    if fid is None:
        continue
    folder = "%s_%s" % (mid, fid)
    mf = os.path.join(cache, folder, "ModManifest.json")
    if not os.path.isfile(mf):
        continue
    try:
        meta = json.load(open(mf, encoding="utf-8"))
    except Exception:
        continue
    tags = (entry.get("modObject") or {}).get("tags") or []
    if not compatible(tags) and meta.get("guid", "") not in forced:
        continue
    mo = entry.get("modObject") or {}
    slug = mo.get("name_id") or ("mod_%s" % mid)
    label = mo.get("name") or meta.get("name", "")
    cands.setdefault(meta.get("name", ""), []).append((int(mid), meta.get("guid", ""), folder, slug, label))

if not cands:
    sys.exit(1)

want = set(cands)

out = []

resolved = {}
for name, lst in cands.items():
    # metadata.name is the server-side identity: ModId is hashed from it and
    # SortMods keys on it, so two enabled folders under one name displace each
    # other no matter what they are. Report it and name the pick.
    #
    # A shared guid does NOT mean it is the same mod: a fork inherits the guid
    # along with the manifest, so two different authors can ship the same name
    # AND the same guid (Auto Plant 3 / AutoPlant for 1.2.1.5). It is worth
    # calling out anyway, because the data-block loader keys on the guid and
    # would clash on top of the name collision.
    if len(lst) > 1:
        ids = ", ".join(str(e[0]) for e in sorted(lst))
        note = ""
        if len({e[1] for e in lst}) == 1:
            note = " (they also share a guid - forked or re-uploaded)"
        out.append(("WARN", "several enabled folders provide metadata.name %r: ids %s%s - "
                            "only one can run" % (name, ids, note), "", ""))
    dev = [e for e in lst if e[0] >= fake_min]
    if len(dev) == 1:
        resolved[name] = dev[0]
    else:
        # Same name from different mod ids: prefer the newer profile.
        resolved[name] = sorted(lst)[-1]

# --- current state ---------------------------------------------------------
have = {}
for link in sorted(glob.glob(mods_dir + "/*")):
    if not os.path.islink(link):
        continue
    target = os.readlink(link)
    mf = os.path.join(os.path.realpath(link), "ModManifest.json")
    name = None
    if os.path.isfile(mf):
        try:
            name = json.load(open(mf, encoding="utf-8")).get("name")
        except Exception:
            pass
    have.setdefault(name, []).append((os.path.basename(link), os.path.basename(target)))

# --- plan ------------------------------------------------------------------
for name, entries in sorted(have.items(), key=lambda kv: kv[0] or ""):
    if name is None:
        for ln, tg in entries:
            out.append(("DEL", ln, "target %s has no readable manifest" % tg, ""))
        continue
    if name not in want:
        for ln, tg in entries:
            out.append(("DEL", ln, "not in the client mod set (disabled, uninstalled or version-incompatible)", ""))
        continue
    _, _, folder, slug, label = resolved[name]
    # On a duplicate, keep the one already carrying the slug rather than whichever
    # sorts first, so the surviving link is the correctly named one.
    entries.sort(key=lambda e: e[0] != slug)
    keep, keep_target = entries[0]
    for ln, tg in entries[1:]:
        out.append(("DEL", ln, "duplicate of %s" % keep, ""))
    # The link name is cosmetic to the loader, so use the mod.io slug: it is
    # unique, filesystem-safe and readable, unlike mod_<id>.
    if keep != slug:
        out.append(("MOV", keep, slug, label))
        keep = slug
    if keep_target != folder:
        out.append(("SET", keep, folder, label))
    else:
        out.append(("KEEP", "", "", ""))

for name in sorted(want - {k for k in have if k}):
    if name not in resolved:
        out.append(("WARN", "client loads %r but no enabled cache folder provides it" % name, "", ""))
        continue
    _, _, folder, slug, label = resolved[name]
    out.append(("ADD", slug, folder, label))

for row in out:
    print("\t".join(row))
'
}

# The server has no mod directory of its own: every entry under
# StreamingAssets/Mods is a symlink into the client's mod.io cache. Four things
# make those links drift, and patching each one separately is how this function
# grew a special case per symptom:
#
#   * a mod update mints a fresh <modId>_<modfileId> folder
#   * a mod is switched off in the game, or unsubscribed for good
#   * a mod is newly subscribed, or moves between mod.io and a dev build - which
#     changes the modId itself, so the old link cannot even be repaired
#   * the same mod ends up linked twice
#
# All four are the same problem: the links say what the server runs, and nothing
# keeps them in step with the client. So reconcile instead of patch - derive the
# target set the way the loader does - subscribed, minus disabled, minus what is
# not installed - resolve each mod name to the cache folder state.json names, and
# make the link directory match.
#
# Safety: when the target set cannot be read, nothing is touched. These symlinks
# are the only record of the server is mod selection.
do_relink() {
    [ -d "$MODS_DIR" ] || { echo "ERROR: server mod dir not found: $MODS_DIR" >&2; exit 1; }
    [ -d "$MODIO_CACHE" ] || { echo "ERROR: mod.io cache not found: $MODIO_CACHE" >&2; exit 1; }

    local plan
    plan="$(mktemp)"
    if ! relink_plan > "$plan"; then
        rm -f "$plan"
        echo "ERROR: cannot determine the installed mod set (state.json unreadable" >&2
        echo "       or empty cache) — leaving every link untouched." >&2
        return 1
    fi

    local added=0 repointed=0 removed=0 renamed=0 unchanged=0 warned=0
    local action arg1 arg2 arg3
    while IFS="$(printf '\t')" read -r action arg1 arg2 arg3; do
        case "$action" in
            ADD)  ln -sfn "$MODIO_CACHE/$arg2" "$MODS_DIR/$arg1"
                  echo "  + $arg3: $arg1 -> $arg2"; added=$((added + 1)) ;;
            SET)  ln -sfn "$MODIO_CACHE/$arg2" "$MODS_DIR/$arg1"
                  echo "  ~ $arg3: $arg1 -> $arg2"; repointed=$((repointed + 1)) ;;
            MOV)  mv "$MODS_DIR/$arg1" "$MODS_DIR/$arg2"
                  echo "  » $arg3: $arg1 -> $arg2"; renamed=$((renamed + 1)) ;;
            DEL)  rm -f "$MODS_DIR/$arg1"
                  echo "  - $arg1 ($arg2)"; removed=$((removed + 1)) ;;
            KEEP) unchanged=$((unchanged + 1)) ;;
            WARN) echo "WARNING: $arg1" >&2; warned=$((warned + 1)) ;;
        esac
    done < "$plan"
    rm -f "$plan"

    local summary="Mod links: $added added, $repointed repointed, $removed removed, $unchanged unchanged"
    if [ "$renamed" -gt 0 ]; then
        summary="$summary, $renamed renamed"
    fi
    if [ "$warned" -gt 0 ]; then
        summary="$summary, $warned warning(s)"
    fi
    echo "$summary"
}

do_start() {
    [ -x "$CXSTART" ] || { echo "ERROR: cxstart not found: $CXSTART" >&2; exit 1; }
    [ -f "$EXE" ] || { echo "ERROR: server not installed: $EXE" >&2; exit 1; }
    is_running && { echo "Server already running (PID $(pgrep -f "$PROC_PATTERN" | head -1))."; do_status; return 0; }

    # Always before launching: the mod set is read once at startup, so a link
    # left pointing at a superseded cache folder silently changes what runs.
    # A failure here is not fatal: without a readable state.json there is no
    # target set, and the server should still start with the links as they are.
    do_relink || echo "WARNING: mod links not reconciled — starting with the links as they are" >&2

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
        # relink takes no arguments; reject anything trailing rather than
        # ignoring it, so a stale "--prune" from muscle memory is not silent.
        case "${2:-}" in
            '') do_relink ;;
            *) echo "Usage: utils/server.sh relink" >&2; exit 1 ;;
        esac
        ;;
    *)      echo "Usage: utils/server.sh start|stop|status|log|relink" >&2; exit 1 ;;
esac
