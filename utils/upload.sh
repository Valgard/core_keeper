#!/usr/bin/env bash
# utils/upload.sh — Publish a Core Keeper mod to mod.io and the Steam Workshop.
#
# Shared by every Core Keeper mod under this directory. Refreshes the SDK
# symlinks, then runs CoreKeeperModUtils.CLIPublishHelper.Publish (the shared
# helper, identified by MOD_NAME), which builds the mod and uploads it through
# the mod.io plugin. Steam Workshop publishing (utils/steam_bundle.py +
# utils/ck-workshop) runs afterward, against that same build output.
#
# Usage:
#   utils/upload.sh [mod-repo-path] [--dry-run] [--profile-only|--changelog-only] [--no-steam|--steam-only]
#
# The mod repo path defaults to $PWD. A relative path is fine, here and in the env
# vars below: MOD_CALLER_CWD carries this shell's directory into Unity as the anchor
# they resolve against.
#
# --profile-only updates just the mod.io profile (description, name, summary,
# logo) via EditModProfile — no build, no version tags, no dependency sync, no
# modfile upload. Use it to push an edited modio-description.md without cutting
# a new release.
#
# --changelog-only rewrites the published release's changelog text and nothing
# else. A changelog belongs to the modfile rather than the profile, so
# --profile-only cannot reach it; this mode edits the existing modfile in place
# (no upload, no version change). It refuses unless the live modfile's version
# equals CHANGELOG.md's topmost entry, so it can only correct the notes OF the
# published release. Use it when a shipped changelog entry is wrong; use a real
# release for anything that changes what the mod does. Steam has no equivalent
# edit for a shipped change note, so this mode is mod.io-only — Steam is skipped.
#
# --no-steam publishes to mod.io only. --steam-only skips mod.io and publishes
# to Steam only (the two contradict each other). Before mod.io even starts, a
# preflight checks everything the Steam stage needs that does not depend on a
# finished build: MOD_NAME, the ModBuilderSettings .asset, steam-description.txt,
# a CHANGELOG.md whose topmost "## [x.y.z]" entry parses, Editor/logo.png, a
# recognizable <Mod>_Steam.asset, and a Workshop id for every declared
# dependency. On failure it SKIPS Steam and lets the mod.io release proceed
# rather than aborting the run, since that release is what the invocation is
# actually for -- but the run then ends in exit 8, so a caller reading only the
# status still learns that Steam did not go out. (--steam-only has no mod.io
# release to protect, so there a failed preflight is a hard error instead.)
# Once Steam does run, it always runs after mod.io and never aborts it either:
# by then the mod.io release has already happened and cannot be taken back, so
# a Steam failure is reported and reflected in the exit code instead of being
# treated as fatal.
#
# Exit codes past the usual 0 and 1:
#   7  published everywhere, but the Steam dependency sync had failures
#   8  the mod.io release is done; Steam was skipped because its preflight failed
#
# Required env vars (set in the mod's .envrc):
#   UNITY_BIN, SDK_PATH, MOD_NAME, CK_GAME_VERSION, MOD_SUMMARY
#
# A mod with a discord-post.md also needs CK_DISCORD_TAGS; it is checked
# before Unity starts and printed, rendered, after a successful publish.
#
# Prerequisite: log in once via the SDK window's "Log in" tab.
# The Unity Editor must be closed (it locks the project).

set -euo pipefail

# The only variable both destinations need. UNITY_BIN/SDK_PATH/CK_GAME_VERSION/
# MOD_SUMMARY are mod.io- and Unity-specific — checked further down, and only
# when --steam-only is not in effect, so a Steam-only publish needs none of them.
: "${MOD_NAME:?must be set — see .envrc.example}"

REPO_ROOT="$PWD"
DRY_RUN=0
PROFILE_ONLY=0
CHANGELOG_ONLY=0
NO_STEAM=0
STEAM_ONLY=0
for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=1 ;;
        --profile-only) PROFILE_ONLY=1 ;;
        --changelog-only) CHANGELOG_ONLY=1 ;;
        --no-steam) NO_STEAM=1 ;;
        --steam-only) STEAM_ONLY=1 ;;
        *) REPO_ROOT="$arg" ;;
    esac
done

# Checked before Unity is launched at all, so a mistyped path costs a second instead of the
# two minutes an Editor start takes. Deliberately NOT absolutised here: link.sh resolves its
# own argument (it must — symlink targets), discord_post.py runs in this very directory, and
# the value handed to Unity is resolved there against MOD_CALLER_CWD, exported below.
if [ ! -d "$REPO_ROOT" ]; then
    echo "ERROR: '$REPO_ROOT' is not a directory." >&2
    exit 1
fi

if [ "$PROFILE_ONLY" = "1" ] && [ "$CHANGELOG_ONLY" = "1" ]; then
    echo "ERROR: --profile-only and --changelog-only are separate modes; pick one." >&2
    exit 1
fi

if [ "$NO_STEAM" = "1" ] && [ "$STEAM_ONLY" = "1" ]; then
    echo "ERROR: --no-steam and --steam-only contradict each other." >&2
    exit 1
fi

if [ "$STEAM_ONLY" = "1" ] && [ "$CHANGELOG_ONLY" = "1" ]; then
    echo "ERROR: --changelog-only has no Steam equivalent (see the mode comment" >&2
    echo "       above) — --steam-only with it would just skip everything." >&2
    exit 1
fi

if [ "$STEAM_ONLY" = "1" ] && [ "$PROFILE_ONLY" = "1" ]; then
    echo "ERROR: --profile-only has no Steam equivalent yet (see the mode comment" >&2
    echo "       above) — --steam-only with it would just skip everything." >&2
    exit 1
fi

UTILS_DIR="$(cd "$(dirname "$0")" && pwd)"

# Whether this run will touch the Steam stage at all — --changelog-only and
# --profile-only each already skip it further down for their own reasons (see
# the comment on that stage), and --no-steam skips it outright. Computed once,
# here, so the preflight below and that later stage can't drift apart on what
# "Steam will run" means.
if [ "$NO_STEAM" = "1" ] || [ "$CHANGELOG_ONLY" = "1" ] || [ "$PROFILE_ONLY" = "1" ]; then
    STEAM_WILL_RUN=0
else
    STEAM_WILL_RUN=1
fi

# mod.io needs a Unity batchmode build; Steam does not (steam_bundle.py reads
# straight from the repo and the already-built MOD_INSTALL_PATH). --steam-only
# skips the whole mod.io block below, so none of its requirements apply here.
if [ "$STEAM_ONLY" != "1" ]; then
    : "${UNITY_BIN:?must be set — see .envrc.example}"
    : "${SDK_PATH:?must be set — see .envrc.example}"
    : "${CK_GAME_VERSION:?must be set — see .envrc.example}"
    : "${MOD_SUMMARY:?must be set — see .envrc.example}"

    if [ ! -x "$UNITY_BIN" ]; then
        echo "ERROR: \$UNITY_BIN is not executable: $UNITY_BIN" >&2
        exit 1
    fi

    if [ ! -d "$SDK_PATH/Assets" ]; then
        echo "ERROR: \$SDK_PATH does not look like a Unity project: $SDK_PATH" >&2
        exit 1
    fi
fi

# The CLIPublishHelper reads these from the environment. MOD_CALLER_CWD is the anchor every
# relative one of them resolves against: a variable survives the jump into Unity, the working
# directory does not, and Unity's own is not this one — so without it `upload.sh .` dies two
# minutes in with "No CHANGELOG.md at ./CHANGELOG.md", naming a file that is plainly there.
# See EnvPaths at the bottom of utils/CLIBuildHelper.cs.
export MOD_CALLER_CWD="$PWD"
export MOD_REPO_ROOT="$REPO_ROOT"
# So the inline Python in the Steam stage below can import the sibling
# steam_*.py modules without relying on $PWD, which Unity's own step already
# does not preserve (see MOD_CALLER_CWD above).
export CK_UTILS_DIR="$UTILS_DIR"
[ "$DRY_RUN" = "1" ] && export PUBLISH_DRY_RUN=1
[ "$PROFILE_ONLY" = "1" ] && export PUBLISH_PROFILE_ONLY=1
[ "$CHANGELOG_ONLY" = "1" ] && export PUBLISH_CHANGELOG_ONLY=1

# Steam preflight — before mod.io, not after: mod.io's own release cannot be
# undone once it has happened, so a missing steam-description.txt or an
# unresolvable Steam dependency must surface before that release, not as a
# batchmode-log surprise once it has already gone out. Everything this checks
# is derivable without a finished build (see check_prerequisites); the one
# thing a Steam publish also needs — the built content folder — does not
# exist yet at this point, which is exactly why it is not checked here.
#
# A failure here SKIPS the Steam stage, it does not abort the run: the
# invariant below ("Steam can never fail the mod.io publish") has to hold
# for a preflight failure too, not just for a failure once Steam is actually
# uploading — otherwise a missing steam-description.txt would block a
# release that has nothing to do with Steam. --steam-only is the one
# exception: there is no mod.io release for the skip to protect, so a failed
# preflight there means the whole invocation would do nothing, and that must
# be a loud failure instead of a silent, misleading success.
if [ "$STEAM_WILL_RUN" = "1" ]; then
    if ! python3 - <<'PY'
import os, sys
from pathlib import Path

sys.path.insert(0, os.environ["CK_UTILS_DIR"])
import steam_bundle

try:
    steam_bundle.check_prerequisites(Path(os.environ["MOD_REPO_ROOT"]), os.environ)
except ValueError as err:
    print(f"ERROR: Steam preflight failed: {err}", file=sys.stderr)
    sys.exit(1)
PY
    then
        if [ "$STEAM_ONLY" = "1" ]; then
            echo "ERROR: Steam preflight failed (see above) — and --steam-only means" >&2
            echo "       there is nothing else for this run to do." >&2
            exit 1
        fi
        echo "! Steam preflight failed (see above) — skipping the Steam Workshop stage." >&2
        echo "  The mod.io release below is unaffected. Fix the issue above, then re-run" >&2
        echo "  with --steam-only to publish to Steam without cutting another mod.io release." >&2
        STEAM_WILL_RUN=0
    fi
fi

if [ "$STEAM_ONLY" != "1" ]; then
    # Discord preflight — before Unity, so a broken post surfaces in seconds
    # rather than after a ten-minute build, and at the top of the output
    # rather than buried in the batchmode log. A repo without a
    # discord-post.md prints nothing.
    #
    # CK_DISCORD_THREAD set means the mod already has a thread: both this
    # preflight and the post-publish banner below render with --update, the
    # version comment for that thread, instead of the full original
    # announcement -- posting the whole introduction again would land as a
    # duplicate in a thread that already exists.
    DISCORD_MODE_FLAGS=()
    if [ -n "${CK_DISCORD_THREAD:-}" ]; then
        DISCORD_MODE_FLAGS=(--update)
    fi

    # Exit 3 means the post itself is wrong, and that is waved through:
    # nothing about a forum thread should hold back a mod.io release. Any
    # other non-zero code is the tooling being broken (no python3, a corrupt
    # data file, a syntax error) and aborts, because continuing would publish
    # while silently skipping a check. Note the posts live in the *mod*
    # repos, whose pre-commit hooks run csharpier only —
    # utils/tests/test_discord_post_content.py sees them just when somebody
    # commits under utils/ here, so it is a backstop, not a gate.
    discord_rc=0
    python3 "$UTILS_DIR/discord_post.py" --check "${DISCORD_MODE_FLAGS[@]}" "$REPO_ROOT" || discord_rc=$?
    case "$discord_rc" in
        0) ;;
        3) echo "  (continuing — the Discord post is not part of the mod.io release)" >&2 ;;
        *) echo "ERROR: discord_post.py failed with exit $discord_rc — that is a tooling" >&2
           echo "       failure, not a problem with the post. Fix it or publish without it." >&2
           exit "$discord_rc" ;;
    esac

    # Refresh SDK symlinks (idempotent; self-heals after worktree moves).
    "$UTILS_DIR/link.sh" "$REPO_ROOT" >/dev/null

    # The shipped-build list, so CLIPublishHelper can tell a typo from a build
    # mod.io has no tag for without asking mod.io. That distinction is
    # otherwise only available on the tag-taxonomy path, which degrades to
    # additive tagging whenever the API hiccups -- and there a typo is
    # dropped in silence.
    CK_KNOWN_GAME_VERSIONS="$(python3 -c "
import json, sys
print(' '.join(json.load(open(sys.argv[1]))['versions']))
" "$UTILS_DIR/ck-game-versions.json")"
    export CK_KNOWN_GAME_VERSIONS

    echo "Publishing $MOD_NAME to mod.io${PUBLISH_PROFILE_ONLY:+ (profile only)}${PUBLISH_CHANGELOG_ONLY:+ (changelog only)}${PUBLISH_DRY_RUN:+ (dry run)}..."

    # No -quit: CLIPublishHelper drives async mod.io calls and exits itself.
    # timeout guards against a hung network call.
    if timeout 600 "$UNITY_BIN" \
            -batchmode \
            -nographics \
            -projectPath "$SDK_PATH" \
            -executeMethod CoreKeeperModUtils.CLIPublishHelper.Publish \
            -logFile -; then
        echo "✓ Publish complete."
        # A release is the moment the Discord thread goes stale, so hand the post
        # over right here instead of making it a separate thing to remember. Only
        # for a real release: --profile-only stops before the upload and
        # --changelog-only edits an existing modfile, so neither leaves the thread
        # out of date, and printing the post there is a false prompt to go post.
        if [ "$DRY_RUN" != "1" ] && [ "$PROFILE_ONLY" != "1" ] && [ "$CHANGELOG_ONLY" != "1" ]; then
            # A thread already exists -> render the version comment for it
            # instead of the full original announcement (see DISCORD_MODE_FLAGS
            # above) — the same duplicate-post reasoning, at the moment it
            # actually gets printed.
            if [ -n "${CK_DISCORD_THREAD:-}" ]; then
                discord_banner="version comment for the existing thread"
            else
                discord_banner="#available-mods post"
            fi
            # Captured rather than streamed: on failure the banner would otherwise
            # frame an empty post, which reads as "this mod has none".
            if post="$(python3 "$UTILS_DIR/discord_post.py" "${DISCORD_MODE_FLAGS[@]}" "$REPO_ROOT")" && [ -n "$post" ]; then
                printf '\n--- %s ---\n' "$discord_banner"
                printf '%s\n' "$post"
                printf -- '--------------------------------------------------------------\n'
            elif [ -f "$REPO_ROOT/discord-post.md" ]; then
                echo "! The Discord post did not render (see above). The mod.io release" >&2
                echo "  is published; the forum thread is not updated." >&2
            fi
        fi
    else
        code=$?
        [ "$code" = "124" ] && echo "✗ Publish timed out." >&2 \
                            || echo "✗ Publish failed (exit $code). Check the log above." >&2
        exit "$code"
    fi
else
    echo "Skipping mod.io (--steam-only)."
fi

# --- Steam Workshop -----------------------------------------------------------
# Runs after mod.io and never fails it: by this point the mod.io release has
# happened and cannot be taken back, so aborting here would reverse nothing and
# only obscure what succeeded. A Steam failure is reported and sets the exit code.
#
# --changelog-only is mod.io-only: Steam has no edit for an existing change
# note, and faking one costs a second history entry to correct a first.
#
# --profile-only is also excluded, for a different reason: this stage has only
# one mode, a full content+version+changelog publish — there is no Steam
# equivalent of mod.io's metadata-only EditModProfile (yet). Running it here
# would ship a full Workshop update for what the operator asked to be a
# text-only mod.io profile edit.
if [ "$NO_STEAM" = "1" ]; then
    echo "Skipping Steam (--no-steam)."
elif [ "$CHANGELOG_ONLY" = "1" ]; then
    echo "Skipping Steam (--changelog-only: no changelog-only edit on Steam)."
elif [ "$PROFILE_ONLY" = "1" ]; then
    echo "Skipping Steam (--profile-only: no metadata-only path on Steam yet)."
elif [ "$STEAM_WILL_RUN" != "1" ]; then
    # Only reachable when the preflight above turned this off: none of the
    # three flag-driven skips above fired, so STEAM_WILL_RUN started at 1 and
    # was flipped afterward. The detailed reason already went to stderr there.
    echo "Skipping Steam (preflight failed — see above)."
    # Non-zero, unlike the three skips above, because those are what the
    # operator asked for and this is not: the invocation wanted Steam and did
    # not get it. Exiting 0 here would report the same outcome the Steam stage
    # reports as a failure -- Steam did not go out -- as a clean run, and a
    # caller that only reads the status (a wrapper, a loop over several mods)
    # would never learn the difference. The mod.io release above is already
    # published and is not retracted by this; that is what a distinct code
    # rather than 1 is for.
    exit 8
else
    echo
    echo "Publishing $MOD_NAME to the Steam Workshop${PUBLISH_DRY_RUN:+ (dry run)}..."

    # A scratch directory rather than a bare mktemp file: build_bundle wants a
    # .png path for the preview, and mktemp has no portable way to hand it one
    # directly. A trap rather than an rm at the bottom of this branch: a Ctrl-C
    # or a killed `dotnet run` below would otherwise skip that rm and leak the
    # directory, the same reasoning fetch_steam_lib.sh's own trap documents.
    STEAM_TMP="$(mktemp -d -t ck-workshop.XXXXXX)"
    trap 'rm -rf "$STEAM_TMP"' EXIT
    STEAM_PREVIEW="$STEAM_TMP/preview.png"

    # Deliberately NOT inside $STEAM_TMP, and deliberately not on that trap.
    # This file can hold the id of a Workshop item that already exists on
    # Steam, and it is the only place that id lives until the persist step far
    # below reads it. The two interrupts worth planning for are safe either
    # way: `timeout` signals only its own child, and a terminal Ctrl-C reaches
    # the foreground group but leaves this script running -- both reach that
    # persist step. A signal aimed at THIS script (kill, a closed terminal, an
    # outer timeout wrapper) does not: the EXIT trap would fire first and
    # delete the id along with the directory, and the next run -- finding no
    # local id -- would create a second, public, duplicate item over the
    # orphaned one. Surviving that is the whole point, so: its own mktemp name
    # per run, removed on the way out of a run that got far enough to persist.
    # A killed run therefore leaves exactly one file behind, named for its mod,
    # holding the id to put into <Mod>_Steam.asset by hand -- and no later run
    # can overwrite it, which a fixed path would.
    STEAM_RESULT="$(mktemp "${TMPDIR:-/tmp}/ck-workshop-$MOD_NAME-result.XXXXXX")"
    steam_rc=0

    # Everything a publish needs is derivable from files already in the repo
    # (see steam_bundle.py) — this only serialises that derivation as JSON.
    # Nothing but the JSON may reach stdout here: the assignment below captures
    # it whole, and a stray line ahead of it would make the .NET tool's JSON
    # parse fail along with the whole publish (steam_bundle.py's own warnings
    # already go to stderr for exactly this reason).
    bundle="$(
        python3 - "$STEAM_PREVIEW" <<'PY'
import json, os, sys
from pathlib import Path

sys.path.insert(0, os.environ["CK_UTILS_DIR"])
import steam_bundle

repo_root = Path(os.environ["MOD_REPO_ROOT"])
print(json.dumps(steam_bundle.build_bundle(repo_root, os.environ, Path(sys.argv[1]))))
PY
    )" || steam_rc=$?

    if [ "$steam_rc" != "0" ]; then
        echo "✗ Steam bundle could not be assembled (exit $steam_rc)." >&2
    else
        # Core Keeper's Steam app id — kept in sync by hand with Program.cs's
        # CoreKeeperAppId constant, the same way steam_appid.txt duplicates it
        # a third time; it is a published, stable constant, not a secret.
        # Steamworks reads it from this environment variable in preference to
        # steam_appid.txt, and unlike that file (found via a relative fopen()
        # against the process's CURRENT WORKING DIRECTORY — see the comment
        # in ck-workshop.csproj) an environment variable is inherited by a
        # child process regardless of its working directory. That matters
        # here specifically: this script never `cd`s, so $PWD at this point
        # is still whatever directory the operator invoked it from (a mod's
        # own repo root, per its usage comment above) — not
        # utils/ck-workshop/ or its build output, so the copied
        # steam_appid.txt alone would not be found through this call.
        readonly STEAM_APP_ID="1621690"

        # stdout+stderr share one file here on purpose: unlike the bundle build
        # above, nothing downstream captures this stream directly — it is
        # dumped to the operator's terminal and scanned for its last JSON line.
        # timeout guards against a hung upload the same way mod.io's does —
        # Facepunch's submit loop can spin indefinitely on a stalled connection.
        printf '%s' "$bundle" | SteamAppId="$STEAM_APP_ID" timeout 600 dotnet run --project "$UTILS_DIR/ck-workshop" -- ${PUBLISH_DRY_RUN:+--dry-run} \
            >"$STEAM_RESULT" 2>&1 || steam_rc=$?
        cat "$STEAM_RESULT" >&2

        if [ "${PUBLISH_DRY_RUN:-}" = "1" ]; then
            if [ "$steam_rc" = "0" ]; then
                echo "✓ Steam Workshop dry run complete — nothing was sent."
            else
                echo "✗ Steam Workshop dry run failed (exit $steam_rc)." >&2
            fi
        else
            # Attempted regardless of steam_rc, not only on success: Program.cs
            # now reports a Workshop item's id even when the publish failed
            # afterward (a missed legal agreement, a network abort, a Ctrl-C),
            # because CreateItem already ran by that point and the item exists
            # on Steam whether or not the rest of the publish did. Losing that
            # id here is exactly how the NEXT run would see no local id
            # (steam_identity.read_file_id) and create a second, duplicate
            # item over the orphaned one. write_file_id raises on an asset it
            # does not recognise (see steam_identity.py) — that must surface,
            # not be swallowed, for the same reason.
            write_rc=0
            python3 - "$STEAM_RESULT" "$REPO_ROOT" <<'PY' || write_rc=$?
import json, os, sys
from pathlib import Path

sys.path.insert(0, os.environ["CK_UTILS_DIR"])
import steam_identity

lines = [line for line in open(sys.argv[1]) if line.strip().startswith("{")]
if not lines:
    sys.exit(0)  # ck-workshop crashed before it could report anything at all

result = json.loads(lines[-1])
file_id = result["fileId"]
if not file_id:
    sys.exit(0)  # nothing was created on Steam — nothing to persist

asset = Path(sys.argv[2]) / "unity" / os.environ["MOD_NAME"] / (os.environ["MOD_NAME"] + "_Steam.asset")

try:
    steam_identity.write_file_id(asset, file_id)
except Exception as err:
    print(f"  ! Workshop item {file_id} is live, but its id could not be saved to {asset}: {err}", file=sys.stderr)
    print(f"    Fix {asset} by hand — it needs a 'fileId:' line set to {file_id} — then re-run.", file=sys.stderr)
    sys.exit(1)

if result["success"]:
    status = "created, hidden" if result["created"] else "updated"
    print(f"  Workshop item {file_id} ({status})")
elif result["created"]:
    print(
        f"  Workshop item {file_id} was created despite the failed publish above — "
        "its id was saved so the next run reuses it instead of creating a duplicate.",
        file=sys.stderr,
    )
else:
    print(
        f"  Workshop item {file_id} already existed — its id was (re-)saved, but "
        "the update itself failed (see above).",
        file=sys.stderr,
    )
PY
            if [ "$write_rc" != "0" ]; then
                echo "! A Workshop item's id could not be saved locally (see above)." >&2
                # Only escalates a clean steam_rc: if the publish itself
                # already failed, that failure — not this one — is why the
                # run is non-zero.
                [ "$steam_rc" = "0" ] && steam_rc=$write_rc
            fi

            case "$steam_rc" in
                0) echo "✓ Steam Workshop publish complete." ;;
                7) echo "! Steam Workshop publish complete, but dependency sync had failures (see above)." >&2 ;;
                *) echo "✗ Steam Workshop publish failed (exit $steam_rc)." >&2 ;;
            esac
        fi
    fi

    # Only once its contents are safely elsewhere. A failed persist (write_rc
    # non-zero) means the id reached neither the asset nor anywhere else, and
    # the message above naming it has already scrolled past by the time anyone
    # acts on it -- this file is then the copy still there to read. Unset in
    # the dry-run and bundle-failure paths, where nothing was ever persisted
    # because nothing was ever created; the default covers both. An `if`
    # rather than `[ … ] && rm …`: under `set -e` a false test makes that
    # whole list the failing command and kills the script before the exit
    # below, which is how a Steam success once turned into a silent exit 1.
    if [ "${write_rc:-0}" = "0" ]; then
        rm -f "$STEAM_RESULT"
    fi

    exit "$steam_rc"
fi
