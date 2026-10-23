"""Decide whether a Steam publish may go out as the release it names.

The incident this exists for: `upload.sh --steam-only` uploaded whatever build
had last been left in a shared folder, labelled with the checkout's version.
Nothing failed and nothing said so — the Workshop simply served other content
than mod.io under the same version. So every way a run can publish something
other than the release it names gets a rule here, and each refusal says what to
do about it:

- the checkout: uncommitted changes under `unity/`, `localization/` or to
  `CHANGELOG.md`, or notes under `## [Unreleased]`, mean the build is not the
  release its version label claims (`checkout_problems`);
- the content against mod.io: the version must be on mod.io and live there,
  and the folder must have the size mod.io serves for it; an override folder is
  accepted only on those terms and never from `MOD_INSTALL_PATH`
  (`decide_pre_upload`).

The ids a checkout may be missing are `steam_identity.id_gaps`, because the
Steam preflight in `steam_bundle` needs them too and must not import this; the
`modio-id` command only hands upload.sh the mod.io half, which stops a whole
run rather than just its Steam stage.

Pure apart from asking git and the file system, and kept apart from
`upload.sh` for the reason `steam_result.py` was moved out of it: a shell
script cannot be handed a fixture, and these are exactly the decisions a test
has to be able to put every case to. What mod.io holds arrives as the reference
file Unity writes (`CLIPublishHelper`, `ModioReference`), read here and never
fetched, so nothing in this module talks to mod.io. The one thing it asks
Steam is an item's size (`steam_size`), from the public Web API — the Steam
session's own UGC query reports 0 for an item whose content is a folder.
"""

import json
import os
import stat
import subprocess
import sys
import time
from collections.abc import Callable
from collections.abc import Mapping
from pathlib import Path
from typing import NamedTuple

import steam_bundle
import steam_identity
import steam_retag

# upload.sh and ck-workshop share one exit-code space; ck-workshop's header
# names 10 as its own next code, so the guard's two start past it.
EXIT_CONTENT_MISMATCH = 11  # Steam's content does not match mod.io
EXIT_UNVERIFIED = 12  # the comparison could not be made
SIZE_UNREADABLE = "unreadable"  # steam-size: the item exists but its size could not be read

# D3, verbatim but for one flag: `git status --porcelain -- unity localization
# CHANGELOG.md` must print nothing. Untracked files count — ModBuilder collects
# by folder, not by git status, so a stray file under unity/ ships — and
# ignored ones do not: those are the link helpers, .DS_Store and generated
# output that every checkout carries. `--untracked-files=normal` pins the first
# half: `status.showUntrackedFiles = no` in anyone's config would otherwise
# hide them, and git says nothing when it does.
D3_PATHS = ("unity", "localization", "CHANGELOG.md")

HIDDEN_HINT = "if the profile is still hidden, make it visible on mod.io and re-run"


class Verdict(NamedTuple):
    """Whether the run may publish, and the sentence the operator reads either way."""

    proceed: bool
    message: str


def dirty_paths(repo_root: Path) -> list[str]:
    """The porcelain lines of D3's `git status` — empty for a clean checkout.

    Raises RuntimeError when git cannot answer: an unanswered D3 is not a
    clean one, and turning it into an empty list would pass exactly the
    checkout this check exists to stop.
    """
    try:
        completed = steam_identity.run_git(
            repo_root, "status", "--porcelain", "--untracked-files=normal", "--", *D3_PATHS
        )
    except (OSError, subprocess.SubprocessError) as err:
        raise RuntimeError(f"git could not be run: {err}") from err
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or f"git exited {completed.returncode}")
    return [line for line in completed.stdout.splitlines() if line.strip()]


def checkout_problems(repo_root: Path) -> list[str]:
    """Everything that makes this checkout something other than the release it is labelled as.

    One message per dirty path, so a run lists all of them at once rather
    than one per attempt; one more for notes under `## [Unreleased]`, which
    say the repository is past its newest release even when every change is
    committed. An empty `## [Unreleased]` heading kept by habit is no problem.
    """
    problems = []
    try:
        lines = dirty_paths(repo_root)
    except RuntimeError as err:
        problems.append(
            f"could not ask git whether {', '.join(D3_PATHS)} are committed in {repo_root} "
            f"({err}) — refusing rather than publishing a build nobody checked."
        )
    else:
        problems.extend(
            f"uncommitted: {line} — commit it or remove it first. This run builds what is "
            "on disk and labels it with the checkout's version, so the two have to agree."
            for line in lines
        )

    try:
        changelog = (repo_root / "CHANGELOG.md").read_text(encoding="utf-8")
    except (OSError, ValueError) as err:
        problems.append(
            f"CHANGELOG.md could not be read ({err}) — it supplies the version this build "
            "would be labelled with."
        )
    else:
        if steam_bundle.unreleased_notes(changelog):
            problems.append(
                "CHANGELOG.md has notes under [Unreleased] — this checkout is past its newest "
                "release, so its build is not the release it would be labelled as. Release it "
                "first (upload.sh without --steam-only), or run --steam-only from the commit "
                "of the release."
            )
    return problems


def describe_commit(repo_root: Path) -> str:
    """The commit a run builds from, for the log: hash, branch or "detached HEAD", and the path.

    The path is the checkout's own, resolved — a linked worktree's, not the
    main checkout's — because which checkout the build came from is what the
    incident left nobody able to say. It refuses nothing, so a git failure
    becomes a description that says so rather than an exception.
    """
    where = Path(repo_root).resolve()
    try:
        head = steam_identity.run_git(repo_root, "rev-parse", "--short", "HEAD")
        branch = steam_identity.run_git(repo_root, "symbolic-ref", "--short", "-q", "HEAD")
    except (OSError, subprocess.SubprocessError) as err:
        return f"unknown commit — git could not be run: {err} ({where})"
    if head.returncode != 0:
        return f"unknown commit — {head.stderr.strip() or 'git rev-parse failed'} ({where})"
    short = head.stdout.strip()
    if branch.returncode == 0 and branch.stdout.strip():
        return f"{short} on {branch.stdout.strip()} ({where})"
    return f"{short}, detached HEAD ({where})"


def folder_size(path: Path) -> int:
    """The byte total of the regular files under `path`: what Steam and mod.io both report.

    Measured: Steam's `file_size`, mod.io's `filesize_uncompressed` and this
    total agree for the folder a mod was published from. Symlinks inside are
    neither counted nor followed — a link is not content the upload carries as
    such. `path` itself is followed when it is one, since that is the folder
    the caller named. A missing folder raises rather than measuring 0, and so
    does an unreadable subfolder: a size short by a subtree is a wrong size.
    """
    if not Path(path).is_dir():
        raise FileNotFoundError(f"no content folder at {path}")

    def _raise(err: OSError) -> None:
        raise err

    total = 0
    for directory, _, files in os.walk(path, onerror=_raise):
        for name in files:
            info = os.lstat(os.path.join(directory, name))
            if stat.S_ISREG(info.st_mode):
                total += info.st_size
    return total


def load_reference(path: Path) -> dict:
    """The mod.io reference Unity wrote, or the error shape when there is nothing usable in it.

    Unity writes one of three shapes (see `ModioReference` in
    CLIPublishHelper.cs). What arrives here can also be an empty file — upload.sh
    creates it up front, and a Unity run that crashed or timed out never fills
    it — or something unparsable. Those become `{"modId": None, "error": …}`,
    which `decide_pre_upload` refuses with the reason, instead of an exception
    that ends the run without one. Read as UTF-8: mod.io's bodies are, whatever
    the locale says.
    """
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, ValueError) as err:
        return {"modId": None, "error": f"{path} could not be read: {err}"}
    if not text.strip():
        return {
            "modId": None,
            "error": f"{path} is empty — the Unity run ended before it recorded what mod.io holds",
        }
    try:
        data = json.loads(text)
    except ValueError as err:
        return {"modId": None, "error": f"{path} is not JSON: {err}"}
    if not isinstance(data, dict):
        return {"modId": None, "error": f"{path} does not hold a JSON object"}
    return data


def live_modfile(ref: dict) -> dict | None:
    """The modfile mod.io serves today — the profile's `modfile` — or None when it has none."""
    mod = ref.get("mod") if isinstance(ref, dict) else None
    modfile = mod.get("modfile") if isinstance(mod, dict) else None
    return modfile if isinstance(modfile, dict) and modfile.get("id") else None


def _modfiles(ref: dict) -> list | None:
    """The reference's modfile list, or None when the reference has none to give."""
    files = ref.get("files") if isinstance(ref, dict) else None
    data = files.get("data") if isinstance(files, dict) else None
    return data if isinstance(data, list) else None


def _whole_number(value: object) -> bool:
    """An int that came from JSON as a number — not a bool, which Python counts as one."""
    return isinstance(value, int) and not isinstance(value, bool)


def _is_size(value: object) -> bool:
    """A byte count mod.io can have meant: a whole number above 0, since no build is 0 bytes."""
    return _whole_number(value) and value > 0  # type: ignore[operator]


def modfile_for_version(ref: dict, version: str) -> dict | None:
    """The newest upload of `version`, by `date_added`, or None when mod.io has none.

    One version can be uploaded twice; the later upload is the one that
    replaced the earlier, so it is the one that counts.
    """
    candidates = [
        entry
        for entry in _modfiles(ref) or []
        if isinstance(entry, dict) and entry.get("version") == version
    ]
    return max(
        candidates,
        key=lambda entry: tuple(
            entry.get(key) if _whole_number(entry.get(key)) else 0 for key in ("date_added", "id")
        ),
        default=None,
    )


def _inside(path: Path, root: Path) -> bool:
    """Whether `path` is `root` or lies under it, however either was spelled.

    Both are resolved first — relative, a trailing slash, `..`, a symlink —
    and then compared by component, so `install-2` is not inside `install`.
    resolve() keeps the case that was typed, though, and macOS's default
    volume is case-insensitive, so each existing ancestor is also asked
    whether it IS `root` on disk.
    """
    path, root = Path(path).resolve(), Path(root).resolve()
    if path.is_relative_to(root):
        return True
    if not root.exists():
        return False
    for candidate in (path, *path.parents):
        try:
            if candidate.exists() and os.path.samefile(candidate, root):
                return True
        except OSError:
            continue
    return False


def _unreadable(why: str) -> Verdict:
    """The fail-closed refusal for a reference that does not say what mod.io holds."""
    return Verdict(
        False,
        f"the mod.io reference could not be read ({why}) — without it this content cannot be "
        f"compared with mod.io, so nothing is sent. Re-run once mod.io answers; {HIDDEN_HINT}.",
    )


def decide_pre_upload(
    *,
    version: str,
    ref: dict,
    content: Path,
    content_size: int,
    override: bool,
    install_path: Path | None,
) -> Verdict:
    """Whether `content` may go to Steam as `version`, judged against what mod.io serves.

    The rules, in order — the first that applies decides:

    1. An override inside MOD_INSTALL_PATH is refused, whatever its size: that
       folder holds whichever build was left there last.
    2. A mod not on mod.io (`modId` 0) proceeds uncompared, and says so; an
       override for it is refused, since nothing can vouch for one.
    3. A reference that records a failed read — or, Ruling R4, is not the
       shape a successful one has — is refused: fail closed.
    4. A version mod.io does not have is refused (D7): mod.io comes first.
    5. A version mod.io has but no longer serves is refused: the checkout is
       behind it.
    6. A size other than the live modfile's is refused; for a build, the
       refusal names both causes — a checkout that is not the released state,
       or a toolchain that changed since — and the override as the repair,
       since builds of one commit reproduce byte for byte.
    7. Otherwise the content matches mod.io and proceeds.

    `content_size` is passed in rather than measured here so that the rules
    stay a function of their inputs; `folder_size` is the measure.
    """
    if override and install_path is not None and _inside(content, install_path):
        return Verdict(
            False,
            f"{content} lies inside MOD_INSTALL_PATH ({install_path}) — MOD_INSTALL_PATH is "
            "never a source: it holds whichever build was left there last, whatever its size. "
            "Point CK_STEAM_CONTENT at the modfile downloaded from mod.io instead.",
        )

    if not isinstance(ref, dict) or "modId" not in ref:
        return _unreadable("it records no modId")
    mod_id = ref["modId"]
    if _whole_number(mod_id) and mod_id == 0:
        if override:
            return Verdict(
                False,
                "a mod not on mod.io has no override: CK_STEAM_CONTENT is accepted only when "
                "mod.io's modfile of this version can vouch for it. Unset it, and --steam-only "
                "builds this checkout instead.",
            )
        return Verdict(
            True,
            "not on mod.io — no comparison: the repository records no mod.io id, so there is "
            "no modfile to check this build against.",
        )

    if "error" in ref:
        return _unreadable(f"reading mod.io failed: {ref['error']}")

    modfiles = _modfiles(ref)
    if modfiles is None:
        return _unreadable("it holds no modfile list")
    # Kept as strings only, and counted against the list: a modfile without a
    # version — or with a number where mod.io writes a string — is a reference
    # this guard cannot read, and the join below must never meet one.
    versions = [
        entry["version"]
        for entry in modfiles
        if isinstance(entry, dict) and isinstance(entry.get("version"), str)
    ]
    if len(versions) != len(modfiles):
        return _unreadable("a modfile in it has no version")
    if version not in versions:
        known = ", ".join(dict.fromkeys(versions)) or "none"
        return Verdict(
            False,
            f"version {version} is not on mod.io (it has: {known}) — publish to mod.io first "
            "(upload.sh without --steam-only). A mod on mod.io does not run ahead of it on Steam.",
        )

    live = live_modfile(ref)
    if live is None:
        return _unreadable("mod.io reports no live modfile")
    live_version = live.get("version")
    expected = live.get("filesize_uncompressed")
    if not isinstance(live_version, str) or not _is_size(expected):
        return _unreadable("the live modfile carries no version or no size")
    if live_version != version:
        return Verdict(
            False,
            f"mod.io's live version is {live_version}; this checkout is behind it (its "
            f"CHANGELOG.md names {version}). Run from a checkout of {live_version}.",
        )

    if content_size != expected:
        if override:
            return Verdict(
                False,
                f"the folder does not match what mod.io serves: {content} holds "
                f"{content_size} B, mod.io's {live_version} is {expected} B. Download that "
                "modfile again and point CK_STEAM_CONTENT at it.",
            )
        # Two causes, the likelier first. Builds of one commit reproduce byte
        # for byte (docs/build-environment.md), so a difference means either a
        # checkout that is not the released state — closing an id gap by
        # bringing <Mod>_Steam.asset over from main is enough, because the
        # asset's path ships in the bundle's .assetbundle.manifest — or a
        # toolchain that moved since the release.
        return Verdict(
            False,
            f"this build ({content_size} B) differs from mod.io's {live_version} "
            f"({expected} B). Either this checkout is not the released state — an asset "
            "brought over from main, such as <Mod>_Steam.asset to close an id gap, is enough, "
            "since its path ships in the bundle's .assetbundle.manifest — or the toolchain "
            "changed since the release (an SDK or game-asset update). Repair with the "
            "override: download the modfile, `CK_STEAM_CONTENT=<dir> upload.sh --steam-only`.",
        )

    return Verdict(True, f"matches mod.io ({content_size} bytes)")


def compare_after_upload(
    expected: int | None,
    before: int | None,
    read_size: Callable[[], int | None],
    *,
    attempts: int = 6,
    interval: float = 5.0,
    sleep: Callable[[float], None] = time.sleep,
    before_unreadable: bool = False,
) -> tuple[int, str]:
    """Whether the Workshop item now holds what mod.io serves, as (exit code, sentence).

    `before` is the item's size from before the upload, None for an item that
    did not exist yet (or could not be read). Steam's size lags the upload, so
    reads are retried up to `attempts` times, `interval` seconds apart, and
    what counts as "not updated yet" rather than a verdict is:

    - a read equal to `before`, the item's old size;
    - a read of 0, which is never taken as a size: no uploaded build is 0
      bytes, so a 0 is a size Steam is not reporting yet — a new item's first
      reads are the expected case, though that is not measured;
    - for a new item (`before` None), any read but the last — with no old size
      to tell a lagging read from a final one, a wrong nonzero size is
      concluded only once every attempt is used, from the last read.

    `before_unreadable` is the third case: the item exists but its old size could
    not be read, so `before` is None for want of an answer, not for want of an
    item. A lagging read of the old size cannot then be told from other content,
    so a nonzero read that is not `expected` is never concluded as 11 — it ends
    the attempts like any unchanged size, in 12.

    A read equal to `expected` matches at once, even when it equals `before`: a
    re-upload of the same build changes nothing to wait for. With `before`
    known, a nonzero read that is neither `before` nor `expected` is final —
    the item changed and holds other content (11). Running out of attempts on
    an unreadable, zero or unchanged size leaves the comparison unmade (12).
    """
    if expected is None:
        return 0, "not compared: mod.io has no size to compare the Workshop item with."

    def mismatch(size: int) -> tuple[int, str]:
        return (
            EXIT_CONTENT_MISMATCH,
            f"the Workshop item holds {size} B, mod.io's modfile is {expected} B — Steam "
            "serves other content than mod.io under this version. Re-publish from the "
            "released checkout, or with CK_STEAM_CONTENT set to mod.io's modfile.",
        )

    last: int | None = None
    for attempt in range(attempts):
        if attempt:
            sleep(interval)
        last = read_size()
        if last == expected:
            return 0, f"the Workshop item matches mod.io ({expected} bytes)"
        if before is not None and last not in (None, 0, before):
            return mismatch(last)
    if before is None and not before_unreadable and last not in (None, 0):
        return mismatch(last)
    if last is None:
        why = "the item's size could not be read"
    elif last == 0:
        why = "Steam still reports no size for the item (0 B)"
    elif before_unreadable:
        why = f"the item reports {last} B, and its size from before the upload is unknown"
    else:
        why = f"the item still reports its size from before the upload ({before} B)"
    return (
        EXIT_UNVERIFIED,
        f"could not verify the Workshop item against mod.io ({expected} B): {why} after "
        f"{attempts} reads. Check the item's size on Steam by hand.",
    )


def combine_exit(steam_rc: int, guard_rc: int) -> int:
    """The one exit code for a run whose Steam stage and guard each ended with their own.

    A failure of the Steam stage itself (2-6, 124) is what happened first and
    wins. Otherwise a content mismatch (11) outranks everything — it says the
    item is live with the wrong content, whatever else is also true; 12 outranks
    only success. Any other guard code is a guard that crashed, which is the
    comparison not having been made: 12.
    """
    if steam_rc in (2, 3, 4, 5, 6, 124):
        return steam_rc
    if guard_rc == EXIT_CONTENT_MISMATCH:
        return EXIT_CONTENT_MISMATCH
    if guard_rc != 0 and steam_rc == 0:
        return EXIT_UNVERIFIED
    return steam_rc


def steam_size(utils_dir: Path, env: Mapping[str, str], file_id: int) -> int | None:
    """The item's size in bytes as the public Web API reports it now, or None on any failure.

    The Web API's `file_size`, a string, which for a folder-content item is the
    content's byte total and equals mod.io's `filesize_uncompressed`. Not the
    Steam session's UGC query: its `SizeBytes` measured 0 for such an item.
    None covers a network error, an unexpected shape, a `result` other than 1
    — deleted, or hidden: the item a first publish has just created is hidden,
    and the API cannot see it — and a `file_size` that is not a whole number.
    `utils_dir` and `env` are kept for the callers' sake; nothing here needs them.
    """
    try:
        details = steam_retag.item_details(file_id)
        if details.get("result") != 1:
            return None
        raw = details.get("file_size")
        return int(raw) if isinstance(raw, str) and raw.isdigit() else None
    except Exception:
        return None


def _version(repo: Path) -> str:
    """The topmost CHANGELOG.md version — what the run labels its release with."""
    version, _ = steam_bundle.parse_changelog((repo / "CHANGELOG.md").read_text(encoding="utf-8"))
    return version


def _cmd_modio_id(repo: Path, mod_name: str, env: Mapping[str, str]) -> int:
    """`modio-id`: refuse a checkout that lacks the mod.io id `main` records; 0 when it does not.

    Run by upload.sh before anything reaches mod.io, in every mode: on modId 0
    a normal publish creates a second mod.io profile, and that is not a Steam
    problem a skipped Steam stage could contain. The Workshop-id gap is left to
    the Steam preflight (`steam_identity.id_gaps` has both).
    """
    gaps = steam_identity.id_gaps(repo, mod_name, modio_only=True)
    if gaps:
        print("\n".join(gaps), file=sys.stderr)
        return 1
    return 0


def _cmd_pre_upload(repo: Path, mod_name: str, env: Mapping[str, str]) -> int:
    """`pre-upload`: print the verdict on the content bound for Steam; 0 proceeds, 1 refuses."""
    ref = load_reference(Path(env.get("CK_MODIO_REF", "")))
    try:
        version = _version(repo)
    except (OSError, ValueError) as err:
        print(f"CHANGELOG.md names no version for this run: {err}", file=sys.stderr)
        return 1
    content = Path(env.get("CK_STEAM_CONTENT", ""))
    override = bool(env.get("CK_STEAM_OVERRIDE"))
    install = env.get("MOD_INSTALL_PATH")
    try:
        size = folder_size(content)
    except OSError as err:
        if ref.get("modId") != 0:
            print(f"the content could not be measured: {err}", file=sys.stderr)
            return 1
        size = 0  # not on mod.io: nothing to compare it with
    verdict = decide_pre_upload(
        version=version,
        ref=ref,
        content=content,
        content_size=size,
        override=override,
        install_path=Path(install) if install else None,
    )
    print(verdict.message, file=None if verdict.proceed else sys.stderr)
    return 0 if verdict.proceed else 1


def _cmd_steam_size(repo: Path, mod_name: str, env: Mapping[str, str]) -> int:
    """`steam-size`: print the item's current size; nothing for no id, `unreadable` for no answer.

    The two silences mean different things to post-upload: no id is a new item,
    whose first reads are judged by the new-item rule; an id with no answer is
    an existing item whose old size is unknown, which must never end in 11.
    """
    file_id = steam_identity.read_file_id(steam_identity.asset_path(repo, mod_name))
    if file_id is not None:
        size = steam_size(Path(__file__).resolve().parent, env, file_id)
        print(SIZE_UNREADABLE if size is None else size)
    return 0


def _cmd_post_upload(repo: Path, mod_name: str, env: Mapping[str, str]) -> int:
    """`post-upload`: compare the item with mod.io after the upload; the exit code says how."""
    ref = load_reference(Path(env.get("CK_MODIO_REF", "")))
    if ref.get("modId") == 0:
        print("not compared: not on mod.io — there is no modfile to check the item against.")
        return 0
    if "error" in ref:
        print(f"could not verify: the mod.io reference is unusable ({ref['error']})")
        return EXIT_UNVERIFIED
    try:
        version = _version(repo)
    except (OSError, ValueError) as err:
        print(f"could not verify: CHANGELOG.md names no version ({err})")
        return EXIT_UNVERIFIED
    modfile = modfile_for_version(ref, version)
    expected = modfile.get("filesize_uncompressed") if modfile else None
    if not _is_size(expected):
        print(f"could not verify: mod.io has no size on record for version {version}")
        return EXIT_UNVERIFIED
    file_id = steam_identity.read_file_id(steam_identity.asset_path(repo, mod_name))
    if file_id is None:
        print("could not verify: no Workshop item id is recorded, so there is no item to read")
        return EXIT_UNVERIFIED
    raw = env.get("CK_STEAM_SIZE_BEFORE", "").strip()
    before = int(raw) if raw.isdigit() else None
    before_unreadable = raw == SIZE_UNREADABLE
    utils_dir = Path(__file__).resolve().parent
    code, message = compare_after_upload(
        expected,
        before,
        lambda: steam_size(utils_dir, env, file_id),
        before_unreadable=before_unreadable,
    )
    print(message)
    return code


def main(argv: list[str], env: Mapping[str, str] | None = None) -> int:
    """Dispatch `steam_guard.py <command> <repo>` (or `combine <steam_rc> <guard_rc>`)."""
    env = os.environ if env is None else env
    usage = (
        "usage: steam_guard.py checkout|modio-id|pre-upload|steam-size|post-upload <repo>"
        " | combine <steam_rc> <guard_rc>"
    )
    if len(argv) == 4 and argv[1] == "combine":
        try:
            print(combine_exit(int(argv[2]), int(argv[3])))
        except ValueError:
            print(usage, file=sys.stderr)
            return 2
        return 0
    if len(argv) != 3:
        print(usage, file=sys.stderr)
        return 2
    command, repo = argv[1], Path(argv[2])
    if command == "checkout":
        problems = checkout_problems(repo)
        if problems:
            print("\n".join(problems), file=sys.stderr)
            return 1
        print(describe_commit(repo))
        return 0
    commands = {
        "modio-id": _cmd_modio_id,
        "pre-upload": _cmd_pre_upload,
        "steam-size": _cmd_steam_size,
        "post-upload": _cmd_post_upload,
    }
    if command not in commands:
        print(usage, file=sys.stderr)
        return 2
    mod_name = env.get("MOD_NAME", "")
    if not mod_name:
        print("MOD_NAME is not set", file=sys.stderr)
        return 2
    return commands[command](repo, mod_name, env)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
