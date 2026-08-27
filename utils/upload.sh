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
# preflight checks the repository-side inputs a Steam publish needs: MOD_NAME,
# a CK_MODIO_TYPE that names at least one category, the ModBuilderSettings
# .asset, steam-description.txt, a CHANGELOG.md whose topmost "## [x.y.z]"
# entry parses, Editor/logo.png, a recognizable <Mod>_Steam.asset, and a
# Workshop id for every dependency the .asset marks `required` (an
# unresolvable OPTIONAL one only warns and is skipped).
#
# It is not a check of everything the stage needs, and should not be read as
# one: libsteam_api.dylib under SDK_PATH, a working dotnet toolchain and a
# signed-in Steam client are all independent of the build and all unchecked
# here -- they surface from ck-workshop or its MSBuild step instead. What IS
# excluded on purpose is the built content folder: on the normal path mod.io's
# own build creates it, so at preflight time it genuinely cannot exist yet.
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
# Exit codes past the usual 0 and 1 — this script's own:
#   7  published, but an OPTIONAL Steam dependency did not sync
#   8  the mod.io release is done; Steam never started, its preflight failed
#   9  published, but a REQUIRED Steam dependency may be missing from the item
#
# 7 and 9 both mean the item is live and something about its dependency list is
# wrong; they are separate because the cost to a subscriber is not the same —
# a missing optional dependency loses them a convenience, a missing required one
# loses them a mod that does not run.
#
# Every other non-zero code is passed through from whatever produced it, so this
# list is not exhaustive by design: 2-6 come from utils/ck-workshop (its own
# header says what each means), 124 from either `timeout` in here, and 130 when
# a Ctrl-C killed the `tee` in the Steam pipeline (see STEAM_RESULT below — the
# publish itself survives that, and so does this script).
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

# The two variables both destinations need. MOD_NAME identifies the mod
# everywhere. SDK_PATH is less obvious: ck-workshop.csproj binds the Facepunch
# assembly AND the native libsteam_api.dylib out of it and hard-errors without
# it, so a Steam-only publish needs it exactly as much as a mod.io one. It used
# to sit in the --steam-only-exempt block below, on the theory that it was
# Unity-specific — so under --steam-only the check was skipped and the miss
# surfaced as an MSBuild error inside `dotnet run`, minutes later, instead of
# here in a second.
#
# UNITY_BIN/CK_GAME_VERSION/MOD_SUMMARY really are mod.io- and Unity-specific
# and stay down there.
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

# mod.io needs a Unity batchmode build; Steam publishes whatever that build
# produced, and under --steam-only the last local one in MOD_INSTALL_PATH,
# so it needs no Unity of its own. --steam-only skips the whole mod.io block
# below, so none of ITS requirements apply here — but SDK_PATH is not one of
# them, which is why it is checked above rather than inside this guard.
if [ "$STEAM_ONLY" != "1" ]; then
    : "${UNITY_BIN:?must be set — see .envrc.example}"
    : "${CK_GAME_VERSION:?must be set — see .envrc.example}"
    : "${MOD_SUMMARY:?must be set — see .envrc.example}"

    if [ ! -x "$UNITY_BIN" ]; then
        echo "ERROR: \$UNITY_BIN is not executable: $UNITY_BIN" >&2
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

# Where CLIPublishHelper reports the directory it just built for mod.io, so the
# Steam stage can upload that exact directory. It builds into a fresh temporary
# one per run — deliberately, so a publish can never ship stale Generated/
# assets — and the Steam stage used to read MOD_INSTALL_PATH instead, which
# only build.sh ever writes. The two were never the same folder: Steam would
# have shipped whatever was last built locally, labelled with the version
# mod.io was publishing from somewhere else.
BUILD_DIR_FILE="$(mktemp -t ck-build-dir.XXXXXX)"
export CK_BUILD_DIR_OUT="$BUILD_DIR_FILE"
# Set here rather than in the Steam stage: that stage arms its own EXIT trap
# for its scratch directory, and a second `trap … EXIT` would replace this one
# instead of adding to it.
trap 'rm -f "$BUILD_DIR_FILE"' EXIT

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
    # both — bash keeps one handler per signal.
    trap 'rm -rf "$STEAM_TMP"; rm -f "$BUILD_DIR_FILE"' EXIT
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

    # The directory mod.io was just published from, reported by CLIPublishHelper
    # (see CK_BUILD_DIR_OUT above). Empty under --steam-only, where no mod.io
    # build ran at all — there the last local build is the only thing to
    # publish, and steam_bundle falls back to MOD_INSTALL_PATH for it.
    if [ -s "$BUILD_DIR_FILE" ]; then
        CK_STEAM_CONTENT="$(cat "$BUILD_DIR_FILE")"
        export CK_STEAM_CONTENT
        echo "  Content: the build mod.io was published from"
    fi

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
            # not just with the id: the SDK window reads selectedPath and tags
            # from it, and both are already derived here. Through the
            # environment rather than as an argument because it carries the
            # whole Workshop description.
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

            # 7 and 9 are both "the item is live, its dependency list is not
            # right" — ck-workshop splits them by what it costs a subscriber,
            # and the catch-all would report either as a failed publish, which
            # is the one thing they are not. Anything genuinely unrecognised
            # still lands there: 2-6 from ck-workshop, 124 from `timeout`, 130
            # from a Ctrl-C'd `tee`.
            case "$steam_rc" in
                0) echo "✓ Steam Workshop publish complete." ;;
                7) echo "! Steam Workshop publish complete, but an optional dependency did not sync (see above)." >&2 ;;
                9) echo "! Steam Workshop publish complete, but a REQUIRED dependency may be missing from the item (see above)." >&2 ;;
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
