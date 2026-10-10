#!/usr/bin/env bash
# utils/server.sh — Run the Core Keeper dedicated server inside the CrossOver bottle.
#
# The dedicated server (Steam app 1963720) ships as a Windows build only, so on
# macOS it runs under CrossOver in the same bottle as the game itself.
#
# Usage:
#   utils/server.sh start [options]   Relink the mods, launch, wait for GameInfo.txt
#   utils/server.sh stop              Terminate it (see the save caveat below)
#   utils/server.sh status            Show whether it runs, plus the join details
#   utils/server.sh log               Follow CoreKeeperServerLog.txt
#   utils/server.sh relink            Reconcile the mod symlinks with the client's set
#
# `utils/server.sh --help` lists the commands, `utils/server.sh start --help`
# every launch option (world name, seed, mode, season, content bundles, …).
#
# Env vars (set in .envrc; all optional, defaults shown). The launch settings
# are defaults: the matching `start` option overrides one for a single run.
#   CK_BOTTLE_NAME       CrossOver bottle name.                 "Core Keeper"
#   CK_BOTTLE_PATH       Full bottle path; overrides the above.
#   CK_SERVER_DIR        Server install dir inside the bottle.
#   CK_SERVER_WORLD      World index, 0-29.                     0
#   CK_SERVER_PORT       Direct-connect port. Empty = SDR only. 27015
#   CK_SERVER_PASSWORD   Join password. Empty = server-generated.
#   CK_SERVER_MAXPLAYERS Player cap.                            8
#   CK_SERVER_PLATFORM   -allowonlyplatform value. Empty = all. Steam
#   CK_CXSTART           The cxstart binary, for another CrossOver install.
#
# Exit codes:
#   0  Success
#   1  Missing path, bad argument, or start options while already running
#   2  Server did not come up within the timeout

set -euo pipefail

CK_BOTTLE_NAME="${CK_BOTTLE_NAME:-Core Keeper}"
CK_BOTTLE_PATH="${CK_BOTTLE_PATH:-$HOME/Library/Application Support/CrossOver/Bottles/$CK_BOTTLE_NAME}"
CK_SERVER_DIR="${CK_SERVER_DIR:-$CK_BOTTLE_PATH/drive_c/Program Files (x86)/Steam/steamapps/common/Core Keeper Dedicated Server}"
CK_SERVER_WORLD="${CK_SERVER_WORLD:-0}"
# No colon for these three: an empty value is a setting ("relay only", "let the
# server generate one", "every platform"), so only an unset one takes the default.
CK_SERVER_PORT="${CK_SERVER_PORT-27015}"
CK_SERVER_PASSWORD="${CK_SERVER_PASSWORD-}"
CK_SERVER_MAXPLAYERS="${CK_SERVER_MAXPLAYERS:-8}"
CK_SERVER_PLATFORM="${CK_SERVER_PLATFORM-Steam}"

CXSTART="${CK_CXSTART:-/Applications/CrossOver.app/Contents/SharedSupport/CrossOver/bin/cxstart}"
EXE="$CK_SERVER_DIR/CoreKeeperServer.exe"
GAMEINFO="$CK_SERVER_DIR/GameInfo.txt"
LOGFILE="$CK_SERVER_DIR/CoreKeeperServerLog.txt"
MODS_DIR="$CK_SERVER_DIR/CoreKeeperServer_Data/StreamingAssets/Mods"
MODIO_CACHE="$CK_BOTTLE_PATH/drive_c/users/Public/mod.io/5289/mods"
# The server's own parameter reference, shipped next to the exe.
ARGUMENTS_TXT="$CK_SERVER_DIR/ARGUMENTS.txt"
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
# `|| true`: without that directory find fails, pipefail passes it on, and set -e
# would end the script here without a word — before any command could report
# what is actually missing.
LOADER_CFG="$(find "$CK_BOTTLE_PATH/drive_c/users/${CK_WINE_USER:-crossover}/AppData/LocalLow/Pugstorm/Core Keeper/Steam" \
    -maxdepth 3 -name config.json -path "*/modloader/*" 2>/dev/null | head -1 || true)"

is_running() { pgrep -f "$PROC_PATTERN" >/dev/null 2>&1; }

# The command being run, for the pointer to its help in die_usage.
CMD=""

die_usage() {
    echo "ERROR: $*" >&2
    echo "Run 'utils/server.sh ${CMD:+$CMD }--help' for usage." >&2
    exit 1
}

is_uint() { case "$1" in '' | *[!0-9]*) return 1 ;; esac }
# Ten digits at most, so the comparison cannot overflow bash arithmetic.
in_range() { is_uint "$1" && [ "${#1}" -le 10 ] && [ "$1" -ge "$2" ] && [ "$1" -le "$3" ]; }

# Prints the values ARGUMENTS.txt lists for one parameter section, one per line.
# The file ships with the server and grows with game updates — the content
# bundles above all — so reading it keeps validation and --help current with no
# list to maintain here. Prints nothing when the file is absent.
allowed_values() {
    [ -f "$ARGUMENTS_TXT" ] || return 0
    tr -d '\r' < "$ARGUMENTS_TXT" | awk -v hdr="## $1" '
        /^## / { insec = ($0 == hdr); next }
        insec && /^- / { sub(/^- /, ""); sub(/:.*/, ""); print }'
}

# allowed_values on one line, for help and error messages.
allowed_list() {
    local v
    v="$(allowed_values "$1" | tr '\n' ' ')"
    printf '%s' "${v% }"
}

# Prints the spelling ARGUMENTS.txt uses for a value, matched case-insensitively
# against the given section; dies naming the valid values when nothing matches.
# With no list to check against — the file is missing, or an update renamed the
# section — the value passes through unchecked, and says so: a typo in --mode
# would otherwise create a world in the default mode for good.
canonical() {
    local section="$1" opt="$2" value="$3" allowed match
    allowed="$(allowed_values "$section")"
    if [ -z "$allowed" ]; then
        echo "WARNING: cannot check $opt: no '## $section' list in $ARGUMENTS_TXT — passing '$value' unchecked" >&2
        printf '%s' "$value"
        return 0
    fi
    match="$(printf '%s\n' "$allowed" | awk -v v="$value" 'tolower($0) == tolower(v) { print; exit }')"
    [ -n "$match" ] || die_usage "$opt: unknown value '$value' (valid: $(allowed_list "$section"))"
    printf '%s' "$match"
}

usage() {
    cat <<'EOF'
Usage: utils/server.sh <command> [options]

Run the Core Keeper dedicated server inside the CrossOver bottle.

Commands:
  start     Relink the mods, launch the server, wait for GameInfo.txt
  stop      Shut down gracefully (taskkill), SIGTERM only as a fallback
  status    Show whether it runs, plus the join details
  log       Follow CoreKeeperServerLog.txt
  relink    Reconcile the mod symlinks with the client's mod set

Run 'utils/server.sh start --help' for the launch options. Their defaults come
from the CK_SERVER_* variables in .envrc (see .envrc.example).
EOF
}

# A section's values wrapped into the option-description column of usage_start.
help_values() {
    local list
    list="$(allowed_list "$1")"
    printf '%s\n' "${list:-(see ARGUMENTS.txt)}" | fold -s -w 48 | sed 's/ *$//; s/^/                               /'
}

usage_start() {
    local pw="generated"
    [ -n "$CK_SERVER_PASSWORD" ] && pw="set"
    local modes seasons bundles platforms
    modes="$(help_values "World Mode")"
    seasons="$(help_values "Season")"
    bundles="$(help_values "Activate Content Bundles")"
    platforms="$(help_values "Platform")"
    cat <<EOF
Usage: utils/server.sh start [options] [-- server-args...]

Relink the mods, launch the server and wait until it is up. An option with a
CK_SERVER_* variable behind it overrides that for this run only; the value in
brackets is the current default. Options take their value as '--opt VALUE' or
'--opt=VALUE'.

World:
  -w, --world N              World index, 0-29.                  [${CK_SERVER_WORLD}]
      --world-name NAME      Name clients see in their network settings.
      --seed SEED            World seed, any string. Only used when the world
                             is first created; omit for a random seed.
      --hashed-seed N        An already hashed seed, 0-4294967295, for when
                             only that is known. Ignored together with --seed.
      --mode MODE            World mode at creation; creative and non-creative
                             cannot be switched later. One of:
${modes}
      --season SEASON        Default: from the system date. One of:
${seasons}
      --activate-content B1,B2
                             Activate content bundles, PERMANENT for this
                             world with no undo. Any of:
${bundles}
      --activate-all-content Activate every available bundle. PERMANENT.
      --data-path PATH       Save location: an existing macOS directory, or a
                             Windows path such as C:/Saves.
                             Default: the DedicatedServer folder, whose
                             symlinks share the client's worlds; any other
                             path leaves that shared world behind
                             (docs/dedicated-server.md).

Connection:
  -p, --port PORT            Direct-connect port.                [${CK_SERVER_PORT:-none}]
      --no-port              Steam relay (Game ID) only, no direct connect.
      --ip IP                Address to bind to; needs a port. Default 0.0.0.0.
      --password PW          Direct-connect password, at most 28 characters.
                                                                 [${pw}]
      --game-id ID           Fixed Game ID: 15-28 letters and digits, none of
                             Y y x 0 O. Default: random.
      --max-players N        Player cap.                         [${CK_SERVER_MAXPLAYERS}]
      --platform P           Admit one platform only; needs a port.
                                                                 [${CK_SERVER_PLATFORM:-all}]
${platforms}
      --all-platforms        Admit every platform. A joining client without
                             the crossplay privilege may then be refused.

Script:
      --no-relink            Start with the mod links as they are.
      --timeout SECONDS      How long to wait for GameInfo.txt.  [${START_TIMEOUT}]
  -n, --dry-run              Validate, print the launch command, start nothing.
  -h, --help                 Show this help.

Everything after '--' goes to CoreKeeperServer.exe unchanged. The server's own
reference for every parameter is ARGUMENTS.txt in its install directory; the
value lists above are read from it.
EOF
}

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
    # Without the loader config the plan cannot drop version-incompatible mods,
    # so the server may load one the client skips — a "Game version mismatch"
    # with nothing pointing here. Usually a wrong CK_WINE_USER.
    if [ -z "$LOADER_CFG" ]; then
        echo "WARNING: client loader config not found — version-incompatible mods are not filtered out" >&2
    fi

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
    local world_name="" seed="" hashed_seed="" mode="" season="" content="" all_content=0
    local data_path="" game_id="" ip="" relink=1 dry_run=0 have_opts=0 platform_opt=0
    local passthrough=()

    while [ $# -gt 0 ]; do
        local opt="$1" val="" inline=0
        case "$opt" in
            --*=*) val="${opt#*=}"; opt="${opt%%=*}"; inline=1 ;;
        esac
        case "$opt" in
            -w | --world | --world-name | --seed | --hashed-seed | --mode | --season | --activate-content | \
                --data-path | --game-id | -p | --port | --password | --ip | --max-players | --platform | --timeout)
                if [ "$inline" = 0 ]; then
                    [ $# -ge 2 ] || die_usage "$opt needs a value"
                    val="$2"
                    shift
                fi
                [ -n "$val" ] || die_usage "$opt needs a non-empty value"
                ;;
            *) [ "$inline" = 0 ] || die_usage "$opt takes no value" ;;
        esac
        case "$opt" in
            -h | --help) usage_start; exit 0 ;;
            -w | --world) CK_SERVER_WORLD="$val" ;;
            --world-name) world_name="$val" ;;
            --seed) seed="$val" ;;
            --hashed-seed) hashed_seed="$val" ;;
            --mode) mode="$val" ;;
            --season) season="$val" ;;
            --activate-content) content="$val" ;;
            --activate-all-content) all_content=1 ;;
            --data-path) data_path="$val" ;;
            -p | --port) CK_SERVER_PORT="$val" ;;
            --no-port) CK_SERVER_PORT="" ;;
            --ip) ip="$val" ;;
            --password) CK_SERVER_PASSWORD="$val" ;;
            --game-id) game_id="$val" ;;
            --max-players) CK_SERVER_MAXPLAYERS="$val" ;;
            --platform) CK_SERVER_PLATFORM="$val"; platform_opt=1 ;;
            --all-platforms) CK_SERVER_PLATFORM="" ;;
            --no-relink) relink=0 ;;
            --timeout) START_TIMEOUT="$val" ;;
            -n | --dry-run) dry_run=1 ;;
            --) shift; passthrough=("$@"); have_opts=1; break ;;
            *) die_usage "unknown option: $opt" ;;
        esac
        have_opts=1
        shift
    done

    # Validated after parsing, so a bad CK_SERVER_* value from .envrc is caught
    # the same way as a bad option. The server reports invalid or ignored
    # arguments in GameInfo.txt, which is easy to miss once it is running.
    in_range "$CK_SERVER_WORLD" 0 29 || die_usage "world index must be 0-29, got '$CK_SERVER_WORLD'"
    [ -z "$CK_SERVER_PORT" ] || in_range "$CK_SERVER_PORT" 1 65535 \
        || die_usage "port must be 1-65535, got '$CK_SERVER_PORT'"
    in_range "$CK_SERVER_MAXPLAYERS" 1 999999999 \
        || die_usage "max players must be a positive number, got '$CK_SERVER_MAXPLAYERS'"
    [ "${#CK_SERVER_PASSWORD}" -le 28 ] || die_usage "password is longer than 28 characters"
    in_range "$START_TIMEOUT" 1 999999999 || die_usage "timeout must be a positive number of seconds, got '$START_TIMEOUT'"
    [ -z "$hashed_seed" ] || in_range "$hashed_seed" 0 4294967295 \
        || die_usage "hashed seed must be 0-4294967295, got '$hashed_seed'"
    if [ -n "$game_id" ]; then
        [[ "$game_id" =~ ^[A-Za-z0-9]{15,28}$ ]] && [[ ! "$game_id" =~ [Yyx0O] ]] \
            || die_usage "game ID must be 15-28 letters and digits without Y, y, x, 0 or O"
    fi
    # Plain assignments, not `local x="$(…)"`: local would swallow the exit
    # status of a die_usage inside the substitution.
    [ -z "$mode" ] || mode="$(canonical "World Mode" --mode "$mode")"
    [ -z "$season" ] || season="$(canonical "Season" --season "$season")"
    [ -z "$CK_SERVER_PLATFORM" ] || CK_SERVER_PLATFORM="$(canonical "Platform" --platform "$CK_SERVER_PLATFORM")"
    if [ -n "$content" ]; then
        local bundle bundles=() canon
        IFS=',' read -r -a bundles <<< "$content"
        content=""
        for bundle in "${bundles[@]}"; do
            [ -n "$bundle" ] || continue
            canon="$(canonical "Activate Content Bundles" --activate-content "$bundle")"
            content="${content:+$content,}$canon"
        done
        [ -n "$content" ] || die_usage "--activate-content names no bundle"
    fi
    # cxstart turns an argument into a Windows path only when it names an
    # existing native file, so a macOS path that does not exist yet would reach
    # the server verbatim. A relative path or an unexpanded ~ would be resolved
    # by the server, against its own working directory, not this shell's.
    if [ -n "$data_path" ]; then
        case "$data_path" in
            /*) [ -d "$data_path" ] || die_usage "--data-path $data_path is not an existing directory; create it first" ;;
            [A-Za-z]:[/\\]*) ;;
            *) die_usage "--data-path must be an absolute macOS path or a Windows path like C:/Saves, got '$data_path'" ;;
        esac
    fi
    if [ -z "$CK_SERVER_PORT" ]; then
        if [ -n "$ip" ]; then
            echo "WARNING: --ip has no effect without a port; the server will ignore it" >&2
        fi
        if [ "$platform_opt" = 1 ]; then
            echo "WARNING: --platform has no effect without a port; the server will ignore it" >&2
        fi
    fi
    if [ -n "$seed" ] && [ -n "$hashed_seed" ]; then
        echo "WARNING: --hashed-seed is ignored when --seed is set" >&2
    fi

    local argv=(-batchmode -logfile CoreKeeperServerLog.txt
                -world "$CK_SERVER_WORLD" -maxplayers "$CK_SERVER_MAXPLAYERS")
    # NEVER add -nographics: part of the procedural world generation runs on the
    # GPU, so the server needs a graphics device even headless.
    [ -n "$CK_SERVER_PORT" ] && argv+=(-port "$CK_SERVER_PORT")
    [ -n "$CK_SERVER_PASSWORD" ] && argv+=(-password "$CK_SERVER_PASSWORD")
    [ -n "$CK_SERVER_PLATFORM" ] && argv+=(-allowonlyplatform "$CK_SERVER_PLATFORM")
    [ -n "$ip" ] && argv+=(-ip "$ip")
    [ -n "$game_id" ] && argv+=(-gameid "$game_id")
    [ -n "$world_name" ] && argv+=(-worldname "$world_name")
    [ -n "$seed" ] && argv+=(-worldseed "$seed")
    [ -n "$hashed_seed" ] && argv+=(-hashedworldseed "$hashed_seed")
    [ -n "$mode" ] && argv+=(-worldmode "$mode")
    [ -n "$season" ] && argv+=(-season "$season")
    [ -n "$content" ] && argv+=(-activatecontent "$content")
    [ "$all_content" = 1 ] && argv+=(-activateallcontent)
    [ -n "$data_path" ] && argv+=(-datapath "$data_path")
    argv+=("${passthrough[@]}")

    if [ "$dry_run" = 1 ]; then
        printf '%q ' "$CXSTART" --bottle "$CK_BOTTLE_NAME" --workdir "$CK_SERVER_DIR" --no-wait "$EXE" "${argv[@]}"
        echo
        return 0
    fi

    [ -x "$CXSTART" ] || { echo "ERROR: cxstart not found: $CXSTART" >&2; exit 1; }
    [ -f "$EXE" ] || { echo "ERROR: server not installed: $EXE" >&2; exit 1; }
    if is_running; then
        echo "Server already running (PID $(pgrep -f "$PROC_PATTERN" | head -1))."
        do_status
        # Asked for a particular setup and not getting it is a failure, not a
        # note: a script chaining on start would otherwise test the wrong world.
        if [ "$have_opts" = 1 ]; then
            echo "ERROR: options not applied — stop the server first to start it with them." >&2
            exit 1
        fi
        return 0
    fi

    # Always before launching: the mod set is read once at startup, so a link
    # left pointing at a superseded cache folder silently changes what runs.
    # A failure here is not fatal: without a readable state.json there is no
    # target set, and the server should still start with the links as they are.
    if [ "$relink" = 1 ]; then
        do_relink || echo "WARNING: mod links not reconciled — starting with the links as they are" >&2
    fi

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
    # Everything but the paste block — its header and the line after it — which
    # the join line below replaces: the server also writes notes on invalid or
    # ignored arguments here, and an allowlist of known lines would hide exactly
    # those. Positional rather than matching ";;", which a password may contain.
    tr -d '\r' < "$GAMEINFO" | awk '/^Paste to / { skip = 2 } skip > 0 { skip--; next } NF'
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

CMD="${1:-}"
[ $# -gt 0 ] && shift

# The commands other than start take no arguments. Reject anything trailing
# rather than ignoring it, so a stale "relink --prune" from muscle memory, or a
# start option given to the wrong command, is not silently dropped.
no_args() {
    case "${1:-}" in
        '') return 0 ;;
        -h | --help) usage; exit 0 ;;
        *) die_usage "'$CMD' takes no arguments, got '$1'" ;;
    esac
}

case "$CMD" in
    start)  do_start "$@" ;;
    stop)   no_args "$@"; do_stop ;;
    status) no_args "$@"; do_status ;;
    log)    no_args "$@"; exec tail -f "$LOGFILE" ;;
    relink) no_args "$@"; do_relink ;;
    -h | --help | help) usage ;;
    '')     usage >&2; exit 1 ;;
    *)      bad="$CMD"; CMD=""; die_usage "unknown command: $bad" ;;
esac
