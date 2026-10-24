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
# --profile-only updates the mod.io profile (description, name, summary, logo)
# via EditModProfile and syncs its tags and dependencies — no build, no modfile
# upload, no version change. Use it to push an edited modio-description.md, or
# to add a game-version tag for a build the published modfile already runs on,
# without cutting a new release.
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
# Before anything else reaches out — in every mode, --dry-run included — a
# checkout that lacks the mod.io id its mod repo's main records is refused
# (steam_guard.py modio-id). Release tags often predate the commit that
# recorded the id, and on modId 0 CLIPublishHelper takes the mod for a new one
# and creates a SECOND mod.io profile; skipping Steam would not prevent that.
#
# --no-steam publishes to mod.io only. --steam-only skips mod.io and publishes
# to Steam only (the two contradict each other). Before mod.io even starts, a
# preflight checks the repository-side inputs a Steam publish needs: MOD_NAME,
# a CK_MODIO_TYPE that names at least one category, a CK_GAME_VERSION whose
# every value has three numeric parts, the ModBuilderSettings .asset,
# steam-description.txt, a CHANGELOG.md whose topmost "## [x.y.z]" entry
# parses, Editor/logo.png, a recognizable <Mod>_Steam.asset, no Workshop or
# mod.io id that main records and this checkout lacks, and a Workshop id for
# every dependency the .asset marks `required` (an unresolvable OPTIONAL one
# only warns and is skipped).
#
# It is not a check of everything the stage needs, and should not be read as
# one: libsteam_api.dylib under SDK_PATH, a working dotnet toolchain and a
# signed-in Steam client are all independent of the build and all unchecked
# here -- they surface from ck-workshop or its MSBuild step instead. What IS
# excluded on purpose is the built content folder: this run's own build
# creates it, later, so at preflight time it genuinely cannot exist yet.
#
# On failure it SKIPS Steam and lets the mod.io release proceed
# rather than aborting the run, since that release is what the invocation is
# actually for -- but the run then ends in exit 8, so a caller reading only the
# status still learns that Steam did not go out. (--steam-only has no mod.io
# release to protect, so there a failed preflight is a hard error instead.)
# Once Steam does run, it always runs after mod.io and never aborts it either:
# by then the mod.io release has already happened and cannot be taken back, so
# a Steam failure is reported and reflected in the exit code instead of being
# treated as fatal.
#
# --steam-only builds what it publishes: the checkout named on the command line
# (default: $PWD), in this run, through CLIPublishHelper.PublishSteamOnly — the
# same publish build, then a read of what mod.io holds, and no mod.io write of
# any kind. It never publishes from MOD_INSTALL_PATH, and reads that variable
# only to refuse an override inside it. That folder holds whatever build.sh made
# last, from any checkout, and it used to be what --steam-only shipped: on
# 2026-10-11 it put an unreleased build on the Workshop under the checkout's
# version, for eleven days. Before Unity starts, the checkout is refused when
# unity/, localization/ or CHANGELOG.md has uncommitted changes, or
# CHANGELOG.md has notes under [Unreleased] — either way the build would not be
# the release its version names (steam_guard.py checkout, which also prints the
# commit it builds from). After the build and before anything is sent, the
# folder is held against mod.io (steam_guard.py pre-upload): the mod.io id Unity
# read must be the one the checkout's <Mod>_modio.asset records, the folder may
# carry no Finder .DS_Store, and for a mod on mod.io this version has to be the
# live one there and the folder its size, or nothing is sent — so --steam-only
# catches up a release mod.io already has and never runs ahead of it. A mod not
# on mod.io is published uncompared, and the run says so.
#
# CK_STEAM_CONTENT=<dir> with --steam-only replaces the build with that folder —
# the repair route, for a release today's toolchain no longer rebuilds byte for
# byte. It is announced, Unity still runs (to read mod.io, not to build), and it
# is accepted only when mod.io serves this version at exactly that folder's size
# and the folder lies outside MOD_INSTALL_PATH. Any other run ignores an
# inherited CK_STEAM_CONTENT, and says so.
#
# Exit codes past the usual 0 and 1 — this script's own:
#   7  published, but an OPTIONAL Steam dependency did not sync
#   8  the mod.io release is done; Steam never started, its preflight failed
#   9  published, but a REQUIRED Steam dependency may be missing from the item
#  11  published, but the Workshop item does not match mod.io's modfile of this
#      version: Steam serves other content than mod.io under the same number
#  12  published, but that comparison could not be made (see the run's output)
#
# 7 and 9 both mean the item is live and something about its dependency list is
# wrong; they are separate because the cost to a subscriber is not the same —
# a missing optional dependency loses them a convenience, a missing required one
# loses them a mod that does not run.
#
# 11 and 12 come from the check after every real Steam upload (steam_guard.py
# post-upload): the item's size on Steam against mod.io's for this version.
# Equal size is strong evidence of the same build, not proof. On the normal path
# both destinations get one folder, so it shows delivery, not that the build was
# right. 11 outranks 0, 7, 9 and 130; 12 outranks only 0; neither masks a Steam
# failure (steam_guard.combine_exit). Both leave the item live — nothing can be
# undone at that point, so the code says precisely what happened.
#
# Every other non-zero code is passed through from whatever produced it, so this
# list is not exhaustive by design: 2-6 come from utils/ck-workshop (its own
# header says what each means), 124 from any `timeout` in here, and 130 when
# a Ctrl-C killed the `tee` in the Steam pipeline (see STEAM_RESULT below — the
# publish itself survives that, and so does this script).
#
# Required env vars (set in the mod's .envrc):
#   UNITY_BIN, SDK_PATH, MOD_NAME, CK_GAME_VERSION — and MOD_SUMMARY, except
#   under --steam-only, which writes nothing to mod.io
#
# A mod with a discord-post.md also needs CK_DISCORD_TAGS; it is checked
# before Unity starts and printed, rendered, after a successful publish.
#
# Prerequisite: log in once via the SDK window's "Log in" tab.
# The Unity Editor must be closed (it locks the project).

set -euo pipefail

# The two variables both destinations need. MOD_NAME identifies the mod
# everywhere. SDK_PATH is less obvious: ck-workshop.csproj binds the Facepunch
# assembly AND the native libsteam_api.dylib out of it and hard-errors without
# it, so a Steam-only publish needs it exactly as much as a mod.io one. It used
# to sit in the --steam-only-exempt block below, on the theory that it was
# Unity-specific — so under --steam-only the check was skipped and the miss
# surfaced as an MSBuild error inside `dotnet run`, minutes later, instead of
# here in a second.
#
# UNITY_BIN and CK_GAME_VERSION are checked further down, beside the one that
# depends on a flag: MOD_SUMMARY really is mod.io-specific and stays exempt
# under --steam-only.
: "${MOD_NAME:?must be set — see .envrc.example}"
: "${SDK_PATH:?must be set — see .envrc.example}"

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

# Both narrow modes edit mod.io metadata that the Workshop's single-item model
# has no counterpart for, so --steam-only with either would skip both
# destinations and publish nothing at all. One guard rather than two, because
# the reason is one reason; the distinction the two used to carry is that
# --changelog-only can never gain a Steam equivalent (the Workshop has no
# separate change note to edit) while --profile-only merely has none yet, and
# that belongs in this comment rather than in a word of the error text.
if [ "$STEAM_ONLY" = "1" ] && { [ "$CHANGELOG_ONLY" = "1" ] || [ "$PROFILE_ONLY" = "1" ]; }; then
    if [ "$CHANGELOG_ONLY" = "1" ]; then
        contradicting_mode="--changelog-only"
    else
        contradicting_mode="--profile-only"
    fi
    echo "ERROR: $contradicting_mode has no Steam equivalent (see the mode comment" >&2
    echo "       above) — --steam-only with it would just skip everything." >&2
    exit 1
fi

# Neither may come in from the shell. CK_STEAM_OVERRIDE makes CLIPublishHelper
# skip the Steam-only build, and only the override announced below sets it —
# inherited, it would change what a run does without a word. PUBLISH_STEAM_ONLY
# is no longer set by anything: Steam-only is an entry point of its own now
# (PublishSteamOnly, below), and CLIPublishHelper.Publish refuses the variable
# so that an old caller cannot turn into a mod.io release. A leftover in the
# shell would only make a normal publish fail on that refusal.
unset CK_STEAM_OVERRIDE PUBLISH_STEAM_ONLY

# CK_STEAM_CONTENT names the folder the Steam stage uploads; this run sets it
# from its own build further down. A value already in the environment came from
# outside: the override under --steam-only (the repair route — a mod.io modfile
# downloaded by hand), or a leftover from such a repair session. The two cannot
# be told apart, so under --steam-only every such value is taken as the
# override — announced here, and accepted only if the check against mod.io
# before the upload holds. On any other run it would replace the folder mod.io
# was just published from, so it is dropped, loudly.
STEAM_OVERRIDE=0
if [ -n "${CK_STEAM_CONTENT:-}" ]; then
    if [ "$STEAM_ONLY" = "1" ]; then
        STEAM_OVERRIDE=1
        export CK_STEAM_OVERRIDE=1
        echo "Content: $CK_STEAM_CONTENT (override from CK_STEAM_CONTENT — checked against mod.io before the upload)"
    else
        echo "! CK_STEAM_CONTENT is set from outside — ignored; Steam gets the folder this run builds." >&2
        unset CK_STEAM_CONTENT
    fi
fi

UTILS_DIR="$(cd "$(dirname "$0")" && pwd)"

# Whether the Steam preflight below has anything to check — that is this
# variable's whole job, and the only place that reads it. The Steam stage far
# below does NOT consult it: it re-tests the same three flags itself, one per
# branch, so that each skip can print its own reason. That duplication is
# deliberate and this comment used to deny it, claiming the value was computed
# once "so the two can't drift apart"; they were never sharing it.
#
# What the stage must not do is INFER a reason from this variable, because a
# fourth reason added here would then be reported down there as "preflight
# failed". STEAM_PREFLIGHT_FAILED below exists so it does not have to.
if [ "$NO_STEAM" = "1" ] || [ "$CHANGELOG_ONLY" = "1" ] || [ "$PROFILE_ONLY" = "1" ]; then
    STEAM_WILL_RUN=0
else
    STEAM_WILL_RUN=1
fi
STEAM_PREFLIGHT_FAILED=0

# Unconditional, like SDK_PATH itself: ck-workshop resolves its two Steam
# libraries under $SDK_PATH/Assets/Plugins/, so a value that is not a Unity
# project fails a Steam-only publish just as surely as a mod.io one.
if [ ! -d "$SDK_PATH/Assets" ]; then
    echo "ERROR: \$SDK_PATH does not look like a Unity project: $SDK_PATH" >&2
    exit 1
fi

# Every run starts Unity: mod.io's publish builds there, and so does
# --steam-only, which publishes only what it built itself — or, with the
# override, still reads mod.io there, with the plugin's login. It used to be
# exempt, back when it shipped the last local build out of MOD_INSTALL_PATH
# instead. CK_GAME_VERSION is needed by both destinations' tags.
: "${UNITY_BIN:?must be set — see .envrc.example}"
: "${CK_GAME_VERSION:?must be set — see .envrc.example}"

if [ ! -x "$UNITY_BIN" ]; then
    echo "ERROR: \$UNITY_BIN is not executable: $UNITY_BIN" >&2
    exit 1
fi

# The profile summary is the one requirement that is mod.io's alone, and
# --steam-only writes nothing there.
if [ "$STEAM_ONLY" != "1" ]; then
    : "${MOD_SUMMARY:?must be set — see .envrc.example}"
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

# A checkout without the mod.io id its main records stops here, whatever the
# mode — the one id check that cannot wait for the Steam preflight below. With
# modId 0, CLIPublishHelper takes the mod for a new one and calls
# CreateModProfile: a SECOND mod.io profile, with this release uploaded to it
# and its id written into the asset. A failed Steam preflight only skips Steam,
# which would not stop that. --dry-run is refused too, so that it predicts the
# real run, and so are --profile-only and --changelog-only: those cannot create
# a profile (both Fail on modId 0), but they would get there only after a Unity
# start, advising "run a normal publish first" — the run that would duplicate
# it. A git that cannot answer claims no gap (steam_identity.id_gaps); a
# crashed check stops the run, since passing it is what costs the profile.
if ! python3 "$UTILS_DIR/steam_guard.py" modio-id "$REPO_ROOT"; then
    echo "ERROR: stopped before anything reached mod.io (see above)." >&2
    exit 1
fi

# Where CLIPublishHelper reports the directory it just built, so the Steam
# stage can upload that exact directory — the one mod.io was published from, or
# under --steam-only the one this run built for Steam alone. It builds into a
# fresh temporary one per run — deliberately, so a publish can never ship stale
# Generated/ assets — and the Steam stage used to read MOD_INSTALL_PATH instead,
# which only build.sh ever writes. The two were never the same folder: Steam
# would have shipped whatever was last built locally, labelled with the version
# mod.io was publishing from somewhere else.
BUILD_DIR_FILE="$(mktemp -t ck-build-dir.XXXXXX)"
export CK_BUILD_DIR_OUT="$BUILD_DIR_FILE"
# Where CLIPublishHelper records what mod.io holds for the mod — after the
# upload on the normal path, after the build (or, with the override, instead of
# one) under --steam-only — for steam_guard.py to hold the Steam content
# against. Created here because CLIPublishHelper only writes to it: a run that
# never got that far leaves it empty, which the guard reads as "could not be
# compared", never as a pass.
MODIO_REF_FILE="$(mktemp -t ck-modio-ref.XXXXXX)"
export CK_MODIO_REF_OUT="$MODIO_REF_FILE"
# Set here rather than in the Steam stage: that stage arms its own EXIT trap
# for its scratch directory, and a second `trap … EXIT` would replace this one
# instead of adding to it.
trap 'rm -f "$BUILD_DIR_FILE" "$MODIO_REF_FILE"' EXIT

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
        STEAM_PREFLIGHT_FAILED=1
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

    # Make Unity recompile the mod, or a publish with unchanged sources ships its
    # DOTS systems without their generated bodies -- the same reason and the same
    # remedy as in build.sh, which this publish does not go through.
    # CLIPublishHelper checks the result before anything is uploaded.
    # --profile-only and --changelog-only build nothing, so they skip it.
    if [ "$PROFILE_ONLY" != "1" ] && [ "$CHANGELOG_ONLY" != "1" ] && [ -d "$REPO_ROOT/unity/$MOD_NAME" ]; then
        find "$REPO_ROOT/unity/$MOD_NAME" -name '*.cs' -exec touch {} +
    fi

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

    # The checkout first, before a Unity start costs minutes: uncommitted
    # changes under unity/ or localization/ or to CHANGELOG.md, or notes under
    # [Unreleased], mean the build would not be the release its version names.
    # The override path is checked too — its version label still comes from
    # this checkout's CHANGELOG.md. On a pass this prints the commit, so the
    # log can say which checkout a published build came from, which nothing
    # could after the incident.
    if ! steam_commit="$(python3 "$UTILS_DIR/steam_guard.py" checkout "$REPO_ROOT")"; then
        echo "ERROR: this checkout is not the release it would be published as (see above)." >&2
        exit 1
    fi
    echo "  Checkout: $steam_commit"

    # The same steps as the publish build above, for the same reasons. link.sh
    # points the SDK's symlink at THIS checkout — the incident's build came from
    # another worktree's link — and runs for the override too: CLIPublishHelper
    # reads the mod.io id from the linked <Mod>_modio.asset, so a stale link
    # would report another checkout's id (pre-upload holds that id against the
    # checkout's own asset, and refuses a difference). The touch makes Unity
    # recompile, so DOTS codegen runs and DotsCodegen.Check inside the build
    # passes the folder that is uploaded; the override builds nothing and skips
    # it.
    "$UTILS_DIR/link.sh" "$REPO_ROOT" >/dev/null
    if [ "$STEAM_OVERRIDE" != "1" ] && [ -d "$REPO_ROOT/unity/$MOD_NAME" ]; then
        find "$REPO_ROOT/unity/$MOD_NAME" -name '*.cs' -exec touch {} +
    fi

    if [ "$STEAM_OVERRIDE" = "1" ]; then
        echo "Reading what mod.io holds for $MOD_NAME — no build, CK_STEAM_CONTENT supplies the content..."
    else
        echo "Building $MOD_NAME for the Steam Workshop, then reading what mod.io holds for it..."
    fi

    # PublishSteamOnly: the publish build (BuildInto, shared with the normal
    # path), then the mod.io reference into CK_MODIO_REF_OUT. A mod.io read
    # that fails does not fail this run — it lands in the reference, where
    # steam_guard.py refuses on it and can say why. As in the publish above: no
    # -quit, timeout for a hang.
    #
    # Its own entry point, not Publish with a mode variable, because of the
    # stale editor assembly (docs/publishing.md, "Known build gotcha"):
    # -executeMethod runs whichever mod's compiled copy of the helper sorts
    # first, and a copy from before the Steam-only mode would read no variable
    # and do a full mod.io release. A copy without PublishSteamOnly cannot run
    # this at all, so a stale one fails closed — nothing sent — instead.
    if timeout 600 "$UNITY_BIN" \
            -batchmode \
            -nographics \
            -projectPath "$SDK_PATH" \
            -executeMethod CoreKeeperModUtils.CLIPublishHelper.PublishSteamOnly \
            -logFile -; then
        echo "✓ Steam-only Unity run complete."
    else
        code=$?
        [ "$code" = "124" ] && echo "✗ Steam-only Unity run timed out." >&2 \
                            || echo "✗ Steam-only Unity run failed (exit $code). Check the log above." >&2
        exit "$code"
    fi
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
elif [ "$STEAM_PREFLIGHT_FAILED" = "1" ]; then
    # Set only where the preflight actually failed, rather than inferred from
    # STEAM_WILL_RUN being 0 — which is also what all three flags above make it,
    # so a fourth flag-driven reason added up there would have been reported
    # here as a preflight failure. The detailed reason already went to stderr.
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

    # The folder Steam gets, from exactly two sources: the directory
    # CLIPublishHelper reported for THIS run's build (see CK_BUILD_DIR_OUT
    # above) — the one mod.io was published from, or under --steam-only the
    # build of this checkout — or, under --steam-only, the override announced
    # at the top. Nothing else. There used to be a third, MOD_INSTALL_PATH, and
    # that is the folder the incident shipped; steam_bundle no longer falls back
    # to it either, so an unset CK_STEAM_CONTENT fails there too. Decided before
    # the scratch files below exist, so a refusal leaves none of them behind.
    if [ -s "$BUILD_DIR_FILE" ]; then
        CK_STEAM_CONTENT="$(cat "$BUILD_DIR_FILE")"
        export CK_STEAM_CONTENT
        if [ "$STEAM_ONLY" = "1" ]; then
            echo "  Content: the build this run made from the checkout above"
        else
            echo "  Content: the build mod.io was published from"
        fi
    elif [ "$STEAM_OVERRIDE" = "1" ]; then
        # The DOTS check runs inside the build (DotsCodegen.Check), against the
        # folder it builds. The override has no build, and checking it against
        # Library/ScriptAssemblies/<Mod>.dll — what the bash call here used to
        # do, on MOD_INSTALL_PATH — would compare a downloaded modfile with the
        # assembly compiled from the checkout. What it does carry is what
        # mod.io serves for this version, which the size check below holds it
        # to.
        echo "  DOTS codegen check skipped: the override is a mod.io modfile; the compiled assembly belongs to the checkout, not to it."
    else
        # A Unity run that exits 0 has always reported its folder, so this is a
        # helper that broke, not a state to publish around. Exit 1, not 2-6:
        # those belong to ck-workshop in this script.
        echo "ERROR: no build directory was reported — nothing to publish." >&2
        exit 1
    fi

    # --steam-only only, and before anything is assembled or sent: the folder
    # against what mod.io holds for this checkout's version (steam_guard.py,
    # decide_pre_upload). A mod on mod.io must have this version live there,
    # at exactly this folder's size; an override must also lie outside
    # MOD_INSTALL_PATH; a mod not on mod.io goes through uncompared, and the
    # verdict says so. The normal path has no such check before its upload —
    # mod.io was just published from this very folder — and is compared
    # after it instead, below.
    if [ "$STEAM_ONLY" = "1" ]; then
        echo "  Holding the content against mod.io..."
        if ! CK_MODIO_REF="$MODIO_REF_FILE" python3 "$UTILS_DIR/steam_guard.py" pre-upload "$REPO_ROOT"; then
            echo "ERROR: refused before the upload (see above) — nothing was sent to Steam." >&2
            exit 1
        fi
    fi

    # A scratch directory rather than a bare mktemp file: build_bundle wants a
    # .png path for the preview, and mktemp has no portable way to hand it one
    # directly. A trap rather than an rm at the bottom of this branch: a signal
    # aimed at THIS script — `kill`, a closed terminal, an outer `timeout`
    # wrapper — ends it right here, and an rm down there would never run.
    # Specifically NOT a Ctrl-C and NOT a killed `dotnet run`, which is what
    # this comment used to claim: neither one ends this script (measured — see
    # STEAM_RESULT just below), so neither could have skipped the rm.
    STEAM_TMP="$(mktemp -d -t ck-workshop.XXXXXX)"
    # Replaces the earlier trap rather than adding to it, so it has to clean up
    # everything that one did — bash keeps one handler per signal.
    trap 'rm -rf "$STEAM_TMP"; rm -f "$BUILD_DIR_FILE" "$MODIO_REF_FILE"' EXIT
    STEAM_PREVIEW="$STEAM_TMP/preview.png"

    # Deliberately NOT inside $STEAM_TMP, and deliberately not on that trap.
    # This file can hold the id of a Workshop item that already exists on
    # Steam, and it is the only place that id lives until the persist step far
    # below reads it.
    #
    # Most ways a run ends still reach that step. Measured against the real
    # pipeline shape below -- printf | timeout N <cmd> 2>&1 | tee "$STEAM_RESULT"
    # -- with the script in its own process group and SIGINT delivered to the
    # WHOLE group, which is what a tty does:
    #   `timeout` firing                     -> script continues, persist runs
    #   a terminal Ctrl-C                    -> script continues, persist runs
    #   a signal aimed at THIS script
    #     (`kill`, closed terminal, an
    #      outer `timeout` wrapper)          -> EXIT trap fires, persist does NOT
    #
    # Ctrl-C is survivable because GNU `timeout` puts itself and its child into
    # a process group of their own (setpgid) -- verified: the script's group
    # holds only bash and the `tee`. So the group-wide SIGINT reaches neither
    # `timeout` nor `dotnet`; only the `tee` dies, and bash goes on waiting for
    # a pipeline whose other members are still running. An earlier version of
    # this comment claimed a Ctrl-C kills the script, from a measurement whose
    # harness had no `timeout` in it -- the one thing that makes the difference.
    #
    # So only the last case loses the id, and that is the case this file exists
    # for: there the EXIT trap would have taken the id with the scratch
    # directory, and the next run -- finding no local id -- would create a
    # second, public, duplicate item over the orphaned one. Hence its own mktemp
    # name per run, removed on the way out of a run that got far enough to
    # persist. A killed run leaves exactly one file behind, named for its mod,
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
        # here specifically: the only `cd` this script runs is inside a command
        # substitution (UTILS_DIR, above), which happens in a subshell and so
        # cannot move the script's own $PWD — it is still whatever directory
        # the operator invoked this from (a mod's own repo root, per the usage
        # comment above), not utils/ck-workshop/ or its build output, so the
        # copied steam_appid.txt alone would not be found through this call.
        readonly STEAM_APP_ID="1621690"

        # The item's size before the upload, for the comparison after it: Steam
        # is expected to report the new size only some time after a submit
        # (not measured for the size; the Web API's tag reads can lag, see
        # steam_retag.VERIFY_ATTEMPTS), and a read that still returns this one
        # means "not updated yet", not a verdict. steam-size prints one of
        # three tokens, which reach steam_guard.py post-upload through
        # CK_STEAM_SIZE_BEFORE: a positive number, the size; `none`, no
        # Workshop id, an item this upload creates; and `unreadable`, an item
        # that exists but whose size is not known. A crash of steam-size is
        # `unreadable` too, through the `||` below — never the empty answer,
        # which post-upload, like anything else it does not recognise, also
        # reads as unknown. The distinction matters: only a new item may end in
        # a mismatch (11) with no size from before, judged from the last read;
        # an unknown old size ends at worst in 12
        # (steam_guard.compare_after_upload). A read of 0 is never taken for a
        # size, in any case: no uploaded build is 0 bytes. Not in a dry run,
        # which sends nothing and so compares nothing. The read is the public
        # Web API's `file_size` (steam_guard.steam_size); a hidden item is
        # presumed invisible to it (unverified) and would read as unreadable.
        if [ "${PUBLISH_DRY_RUN:-}" != "1" ]; then
            echo "  Reading the Workshop item's current size, for the check after the upload..."
            CK_STEAM_SIZE_BEFORE="$(python3 "$UTILS_DIR/steam_guard.py" steam-size "$REPO_ROOT" || echo unreadable)"
            export CK_STEAM_SIZE_BEFORE
        fi

        # stdout+stderr share one file here on purpose: unlike the bundle build
        # above, nothing downstream captures this stream directly — it is
        # dumped to the operator's terminal and scanned for its last JSON line.
        # timeout guards against a hung upload the same way mod.io's does —
        # Facepunch's submit loop can spin indefinitely on a stalled connection.
        #
        # `tee` rather than a plain redirect, so the operator sees the output
        # as it happens rather than only once the tool returns. That matters
        # for exactly one line: the id ck-workshop prints the moment CreateItem
        # succeeds, which a plain redirect would hold back for as long as the
        # rest of the upload takes — up to the full 600 s.
        #
        # A Ctrl-C does not end this script (see STEAM_RESULT above), but it
        # does kill this `tee`. Two consequences, both measured: the terminal
        # falls silent while the upload keeps running to completion, and
        # $STEAM_RESULT stops growing at that instant — so an id already
        # reported survives into the persist step, while one reported after the
        # Ctrl-C is lost.
        #
        # `pipefail` is already on from the top of the script, so a failing
        # `dotnet run` still reaches steam_rc through the added `tee` — and so
        # does that killed `tee` itself, as 130.
        printf '%s' "$bundle" | SteamAppId="$STEAM_APP_ID" timeout 600 dotnet run --project "$UTILS_DIR/ck-workshop" -- ${PUBLISH_DRY_RUN:+--dry-run} \
            2>&1 | tee "$STEAM_RESULT" >&2 || steam_rc=$?

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
            # The bundle rides along so the asset can be filled in completely,
            # not just with the id: the SDK window reads the tags from it, and
            # they are already derived here. (Its selectedPath is cleared, not
            # filled — no folder of this run outlives it; see steam_result.py.)
            # Through the environment rather than as an argument because it
            # carries the whole Workshop description.
            #
            # A script rather than the heredoc this used to be: it is the step
            # that decides whether write_file_id runs at all, and inline it was
            # the one part of the Steam stage no test could reach.
            CK_STEAM_BUNDLE="$bundle" \
                python3 "$UTILS_DIR/steam_result.py" "$STEAM_RESULT" "$REPO_ROOT" || write_rc=$?
            if [ "$write_rc" != "0" ]; then
                echo "! A Workshop item's id could not be saved locally (see above)." >&2
                # Only escalates a clean steam_rc: if the publish itself
                # already failed, that failure — not this one — is why the
                # run is non-zero.
                [ "$steam_rc" = "0" ] && steam_rc=$write_rc
            fi

            # The item against mod.io, once the upload is in: Steam's size of
            # the item against mod.io's filesize_uncompressed for this version
            # (steam_guard.py post-upload, which re-reads for a bounded time
            # until the size matches or the attempts run out — see
            # compare_after_upload for what counts as "not updated yet"). Only
            # where the upload may have gone through — 0, 7 and 9 are a live
            # item, and 130 is a killed `tee` after which the upload ran on to
            # its end (see STEAM_RESULT above); steam_guard.COMPARABLE_STEAM_CODES
            # is the same list. 2-6 and 124 sent nothing or failed midway, and a
            # failed persist on an otherwise clean run (steam_rc = write_rc) is
            # not compared.
            #
            # On the normal path both destinations got this one folder, so a
            # match shows delivery — Steam holds what mod.io holds — and says
            # nothing about whether the build was right. Under --steam-only the
            # check that matters ran before the upload; this one confirms it.
            #
            # combine_exit owns the precedence: a mismatch (11) outranks 0, 7, 9
            # and 130, an unmade comparison (12) outranks only 0, and a guard
            # that crashed counts as an unmade comparison. Should combine itself
            # fail — the interpreter that just ran the guard — or print anything
            # but a number, the same rule holds without it: 12 replaces only a
            # 0, so a run never reports a success nobody checked, and a 7, 9 or
            # 130 stays what it was. Inside the `if`, a failure cannot trip
            # `set -e`, which would end the script with Python's code and skip
            # the STEAM_RESULT clean-up below.
            case "$steam_rc" in
                0|7|9|130)
                    echo "  Comparing the Workshop item with mod.io..."
                    guard_rc=0
                    CK_MODIO_REF="$MODIO_REF_FILE" \
                        python3 "$UTILS_DIR/steam_guard.py" post-upload "$REPO_ROOT" || guard_rc=$?
                    if combined="$(python3 "$UTILS_DIR/steam_guard.py" combine "$steam_rc" "$guard_rc")" \
                            && [[ "$combined" =~ ^[0-9]+$ ]]; then
                        steam_rc="$combined"
                    elif [ "$steam_rc" = "0" ]; then
                        steam_rc=12
                    fi
                    ;;
            esac

            # 7 and 9 are both "the item is live, its dependency list is not
            # right" — ck-workshop splits them by what it costs a subscriber,
            # and the catch-all would report either as a failed publish, which
            # is the one thing they are not. 11 and 12 are live items too, so
            # the same holds for them. Anything genuinely unrecognised still
            # lands there: 2-6 from ck-workshop, 124 from `timeout`, 130 from a
            # Ctrl-C'd `tee`.
            case "$steam_rc" in
                0) echo "✓ Steam Workshop publish complete." ;;
                7) echo "! Steam Workshop publish complete, but an optional dependency did not sync (see above)." >&2 ;;
                9) echo "! Steam Workshop publish complete, but a REQUIRED dependency may be missing from the item (see above)." >&2 ;;
                11) echo "✗ Steam Workshop publish complete, but the item does NOT match mod.io's modfile of this version (see above)." >&2 ;;
                12) echo "! Steam Workshop publish complete, but it could not be compared with mod.io (see above)." >&2 ;;
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
    # rather than `[ … ] && rm …` because such a list returns 1 when its test
    # is false, and that becomes the script's own exit status whenever it is
    # the last thing the script runs -- which is how a Steam success once
    # turned into a silent exit 1. `set -e` is NOT the mechanism: bash exempts
    # every command in an && list but the final one, so the `&&` form would be
    # safe here too (an `exit` follows it), exactly as it is at the
    # steam_rc/write_rc line above. The `if` is simply the form that stays
    # correct no matter what is written after it.
    if [ "${write_rc:-0}" = "0" ]; then
        rm -f "$STEAM_RESULT"
    fi

    exit "$steam_rc"
fi
