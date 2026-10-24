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
- the content against mod.io: the mod.io id Unity read must be the one the
  checkout records, the version must be on mod.io and live there, and the
  folder must have the size mod.io serves for it and carry no Finder
  metadata; an override folder is accepted only on those terms and never
  from `MOD_INSTALL_PATH` (`classify_reference`, `decide_pre_upload`);
- after the upload: the item's size on Steam against mod.io's for this
  version (`compare_after_upload`), and how that verdict merges into the
  run's exit code (`combine_exit`).

The ids a checkout may be missing are `steam_identity.id_gaps`, because the
Steam preflight in `steam_bundle` needs them too and must not import this; the
`modio-id` command only hands upload.sh the mod.io half, which stops a whole
run rather than just its Steam stage.

Pure apart from git, the file system and one Web API read, and kept apart from
`upload.sh` for the reason `steam_result.py` was moved out of it: a shell
script cannot be handed a fixture, and these are exactly the decisions a test
has to be able to put every case to. What mod.io holds arrives as the reference
file Unity writes (`CLIPublishHelper`, `ModioReference`), read here and never
fetched, so nothing in this module talks to mod.io. The one thing it asks
Steam is an item's size (`steam_size`), from the public Web API: the Steam
session's own UGC query reported 0 for the one folder-content item it was
measured on (docs/ck/steam-workshop.md).
"""

import http.client
import json
import os
import stat
import subprocess
import sys
import time
from collections.abc import Callable
from collections.abc import Mapping
from collections.abc import Sequence
from enum import Enum
from pathlib import Path
from typing import NamedTuple

import steam_bundle
import steam_identity
import steam_retag

# upload.sh and ck-workshop share one exit-code space; ck-workshop's header
# names 10 as its own next code, so the guard's two start past it.
EXIT_CONTENT_MISMATCH = 11  # Steam's content does not match mod.io
EXIT_UNVERIFIED = 12  # the comparison could not be made

# The Steam stage's exit codes after which the upload may have gone through,
# and so the only ones a comparison may change: 0, 7 and 9 leave a live item,
# and 130 is a Ctrl-C that killed upload.sh's `tee` while the upload ran on to
# its end. upload.sh runs post-upload for exactly these; every other code — a
# failure, or one nobody has assigned yet — passes through combine_exit as it is.
COMPARABLE_STEAM_CODES = (0, 7, 9, 130)

# The checkout rule: `git status --porcelain -- unity localization
# CHANGELOG.md` must print nothing. Untracked files count — ModBuilder collects
# by folder, not by git status, so a stray file under unity/ ships — and
# ignored ones do not: those are the link helpers, .DS_Store and generated
# output that every checkout carries. `--untracked-files=normal` pins the first
# half: `status.showUntrackedFiles = no` in anyone's config would otherwise
# hide them, and git says nothing when it does.
CHECKOUT_PATHS = ("unity", "localization", "CHANGELOG.md")

# Files Finder writes into a folder it opens. A content folder unpacked and
# looked at by hand — the override's repair route — gains one, and the upload
# would carry it to Steam and change the size the comparison rests on.
FINDER_LITTER = (".DS_Store",)


class SizeBefore(Enum):
    """What `steam-size` knew of the Workshop item before the upload, when it was not a size.

    The values are the tokens `steam-size` prints, which upload.sh hands on
    as CK_STEAM_SIZE_BEFORE; a known size travels as its number. Three states
    in one value, so that no pair of parameters can contradict each other.
    """

    NEW_ITEM = "none"  # no Workshop id recorded: the upload creates the item
    UNKNOWN = "unreadable"  # an item exists, but its size before the upload is not known


class Verdict(NamedTuple):
    """Whether the run may publish, and the sentence the operator reads either way."""

    proceed: bool
    message: str

    def __bool__(self) -> bool:
        """Refuse: a two-field tuple is always truthy, so `if verdict:` would pass every refusal."""
        raise TypeError("a Verdict has no truth value — read its .proceed")


class Reference(Enum):
    """What a mod.io reference says once it is held against the checkout's own record."""

    READ = "read"  # mod.io's answer for the id the checkout records
    NOT_ON_MODIO = "not on mod.io"  # no id on either side
    UNUSABLE = "unusable"  # anything else: refused before, unverified after


def dirty_paths(repo_root: Path) -> list[str]:
    """The porcelain lines of the checkout rule's `git status` — empty for a clean checkout.

    Raises RuntimeError when git cannot answer: an unanswered check is not a
    clean one, and turning it into an empty list would pass exactly the
    checkout this check exists to stop.
    """
    try:
        completed = steam_identity.run_git(
            repo_root, "status", "--porcelain", "--untracked-files=normal", "--", *CHECKOUT_PATHS
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
            f"could not ask git whether {', '.join(CHECKOUT_PATHS)} are committed in {repo_root} "
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


def finder_litter(path: Path) -> list[str]:
    """The Finder metadata files under `path`, by their path inside it, sorted; [] for no folder.

    A missing or unreadable folder is `folder_size`'s to report, so this says
    nothing about it rather than reporting it a second time.
    """
    root = Path(path)
    found = []
    for directory, _, files in os.walk(root):
        found.extend(
            (Path(directory) / name).relative_to(root).as_posix()
            for name in files
            if name in FINDER_LITTER
        )
    return sorted(found)


def load_reference(path: Path) -> dict:
    """The mod.io reference Unity wrote, or the error shape when there is nothing usable in it.

    Unity writes one of three shapes (see `ModioReference` in
    CLIPublishHelper.cs). What arrives here can also be an empty file — upload.sh
    creates it up front, so anything that kept Unity from filling it leaves it
    so — or something unparsable. Those become `{"modId": None, "error": …}`,
    which `classify_reference` refuses with the reason, instead of an exception
    that ends the run without one. Read as UTF-8: mod.io's bodies are, whatever
    the locale says.
    """
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, ValueError) as err:
        return {"modId": None, "error": f"{path} could not be read: {err}"}
    if not text.strip():
        # Three producers leave the file empty and nothing here tells them
        # apart, so the text names each as a possibility rather than blaming one.
        return {
            "modId": None,
            "error": f"{path} is empty — nothing was recorded in it. Possible causes: the "
            "Unity run ended before it got that far; a stale compiled copy of the publish "
            "helper ran, one that predates the reference and never writes it (re-link every "
            "mod with link.sh — docs/publishing.md, the known build gotcha); or the write "
            "failed, which the Unity log reports as 'could not write the mod.io reference'",
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
    replaced the earlier, so it is the one that counts — unless an older one
    was made live again, which `reference_modfile` looks at first.
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


def reference_modfile(ref: dict, version: str, *, prefer_live: bool) -> dict | None:
    """The modfile of `version` the Steam content is held against.

    With `prefer_live` — `--steam-only`, before the upload and after it — the
    live modfile when it carries `version`: that is what mod.io serves, even
    when the same version was uploaded again and the older upload made live by
    hand, and it is the one pre-upload required, so a pass before the upload
    cannot turn into a mismatch after it by looking at another modfile.
    Otherwise, and without `prefer_live`, the newest upload of `version`.

    The normal path passes False after its own upload: Steam was handed the
    folder that upload came from, which is the newest one, while mod.io's live
    pointer may still name an older upload of the same version until the new
    one is processed (not measured; the code does not assume it cannot).
    Compared with that older one, a correct delivery would read as a mismatch.
    """
    if prefer_live:
        live = live_modfile(ref)
        if live is not None and live.get("version") == version:
            return live
    return modfile_for_version(ref, version)


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


# Appended to a failed mod.io read Unity recorded. Each cause is a possibility:
# the reference carries mod.io's or the plugin's message, not a diagnosis.
MODIO_READ_HINT = (
    "Possible causes: mod.io did not answer in time (re-run); the SDK login is missing or "
    "has lapsed (log in once via the SDK window's Log in tab); or the profile is still "
    "hidden — whether the owner's login can read a hidden profile is unverified, so if it "
    "is, make it visible on mod.io and re-run."
)


def classify_reference(ref: object, recorded_id: int) -> tuple[Reference, str]:
    """Whether `ref` is mod.io's answer for this checkout — one rule before and after the upload.

    `recorded_id` is the mod.io id the checkout's own `<Mod>_modio.asset`
    records, 0 for none, read from disk by the caller. It is not taken from
    the reference because Unity reports modId 0 for an asset it did not load
    — not imported yet, or no longer loadable after an SDK update — exactly
    as for one that does not exist, and a 0 read as "not on mod.io" publishes
    with no comparison at all: the incident's own failure class.

    In order, the first that applies decides:

    1. A reference that records a failed read is unusable, whatever its
       modId says: `{"modId": 0, "error": …}` is representable, and read the
       other way round it would pass as "not on mod.io".
    2. A modId that is not a whole number of at least 0 — a bool, a float, a
       string, null — is unusable: Unity writes none of those.
    3. A modId other than the one the checkout records is unusable: Unity
       read another asset than this checkout's, or none.
    4. 0 on both sides is "not on mod.io"; the same id on both is mod.io's
       answer to compare with.

    The sentence returned with UNUSABLE says what is wrong and what may have
    caused it, but not what follows: the callers add that ("nothing is sent",
    "could not verify").
    """
    if not isinstance(ref, dict) or "modId" not in ref:
        return Reference.UNUSABLE, "the mod.io reference could not be read (it records no modId)."
    mod_id = ref["modId"]
    if "error" in ref:
        if _whole_number(mod_id):
            return (
                Reference.UNUSABLE,
                f"the mod.io reference could not be read (reading mod.io failed: "
                f"{ref['error']}). {MODIO_READ_HINT}",
            )
        return (
            Reference.UNUSABLE,
            f"the mod.io reference could not be read ({ref['error']}). See the Unity log above.",
        )
    if not _whole_number(mod_id) or mod_id < 0:
        return (
            Reference.UNUSABLE,
            f"the mod.io reference could not be read (its modId is {mod_id!r}, not a whole "
            "number). Unity writes a whole number into every reference it completes, so this "
            "one is no record of the run — see the Unity log above, and re-run.",
        )
    if mod_id != recorded_id:
        if recorded_id == 0:
            return (
                Reference.UNUSABLE,
                f"the checkout records no mod.io id, but the Unity run read mod.io id {mod_id}: "
                "it saw another checkout's <Mod>_modio.asset, possibly through an SDK link that "
                "another worktree's build re-pointed. Re-run, and check what the SDK's "
                "Assets/<Mod> links to if it repeats.",
            )
        reported = f"read mod.io id {mod_id}" if mod_id else "reported modId 0"
        return (
            Reference.UNUSABLE,
            f"Unity did not see the mod.io id the checkout records: its <Mod>_modio.asset "
            f"records {recorded_id}, and the Unity run {reported}. Possible causes: Unity "
            "loaded no asset there (not imported yet, or no longer loadable after an SDK "
            "update) and took the mod for one not on mod.io, or the SDK's Assets/<Mod> link "
            "pointed at another checkout's asset. Re-run, and check the Unity log and that link "
            "if it repeats.",
        )
    if mod_id == 0:
        return Reference.NOT_ON_MODIO, ""
    return Reference.READ, ""


def _refused(sentence: str) -> Verdict:
    """The fail-closed refusal for a reference that does not say what mod.io holds."""
    return Verdict(
        False,
        f"{sentence} Without a usable reference this content cannot be compared with mod.io, "
        "so nothing is sent.",
    )


def _unreadable(why: str) -> Verdict:
    """The refusal for a reference mod.io answered, but without what the comparison needs."""
    return _refused(
        f"the mod.io reference could not be read ({why}). mod.io answered, but not with what "
        "the comparison needs, so a re-run is likely to refuse the same way — check this "
        "mod's modfiles on mod.io."
    )


def decide_pre_upload(
    *,
    version: str,
    ref: dict,
    content: Path,
    content_size: int,
    override: bool,
    install_path: Path | None,
    recorded_id: int,
    litter: Sequence[str],
) -> Verdict:
    """Whether `content` may go to Steam as `version`, judged against what mod.io serves.

    The rules, in order — the first that applies decides:

    1. An override inside MOD_INSTALL_PATH is refused, whatever its size: that
       folder holds whichever build was left there last.
    2. Finder metadata in the folder (`litter`, from `finder_litter`) is
       refused by name: it would be uploaded, and it changes the size.
    3. A reference `classify_reference` finds unusable — a failed read, a
       malformed modId, or an id other than `recorded_id` — is refused: fail
       closed.
    4. A mod not on mod.io proceeds uncompared, and says so; an override for
       it is refused, since nothing can vouch for one.
    5. A reference that lacks what a successful one has is refused too.
    6. A version mod.io does not have is refused: mod.io comes first, and a
       mod on mod.io does not run ahead of it on Steam.
    7. A version mod.io has but does not serve is refused.
    8. A size other than that modfile's (`reference_modfile`, the live one by
       now) is refused; for a build, the refusal names both possible causes —
       a checkout that is not the released state, or a toolchain that changed
       since — and the override as the repair, since builds of one commit
       reproduce byte for byte.
    9. Otherwise the content matches mod.io and proceeds.

    `content_size` and `litter` are passed in rather than measured here so
    that the rules stay a function of their inputs; `folder_size` and
    `finder_litter` are the measures.
    """
    if override and install_path is not None and _inside(content, install_path):
        return Verdict(
            False,
            f"{content} lies inside MOD_INSTALL_PATH ({install_path}) — MOD_INSTALL_PATH is "
            "never a source: it holds whichever build was left there last, whatever its size. "
            "Point CK_STEAM_CONTENT at the modfile downloaded from mod.io instead.",
        )

    if litter:
        return Verdict(
            False,
            f"{content} holds Finder metadata: {', '.join(litter)}. Finder writes it into a "
            "folder it opens; it is not part of the build, it would be uploaded with the "
            "content, and it changes the folder's size. Remove it and re-run.",
        )

    state, why = classify_reference(ref, recorded_id)
    if state is Reference.UNUSABLE:
        return _refused(why)
    if state is Reference.NOT_ON_MODIO:
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
    if not isinstance(live_version, str):
        return _unreadable("the live modfile carries no version")
    if live_version != version:
        return Verdict(
            False,
            f"mod.io's live version is {live_version}, not {version} (this checkout's "
            "CHANGELOG.md): mod.io has it but does not serve it. Either this checkout is behind "
            f"mod.io — run from a checkout of {live_version} — or an older modfile was made "
            f"live again on mod.io, in which case make {version} live there first.",
        )
    modfile = reference_modfile(ref, version, prefer_live=True)
    expected = modfile.get("filesize_uncompressed") if modfile else None
    if not _is_size(expected):
        return _unreadable("the live modfile carries no size")

    if content_size != expected:
        if override:
            return Verdict(
                False,
                f"the folder does not match what mod.io serves: {content} holds "
                f"{content_size} B, mod.io's {live_version} is {expected} B. Download that "
                "modfile again and point CK_STEAM_CONTENT at it.",
            )
        # Builds of one commit reproduce byte for byte (docs/build-environment.md),
        # so a difference has one of two causes, and nothing here says which.
        # An identity asset brought over from main is a difference only when the
        # release commit had no such file: its path ships in the bundle's
        # .assetbundle.manifest, while its contents — an Editor-only type — do
        # not (docs/ck/steam-workshop.md).
        return Verdict(
            False,
            f"this build ({content_size} B) differs from mod.io's {live_version} "
            f"({expected} B). Possible causes: this checkout is not the released state — a "
            "file added or changed since the release; a <Mod>_Steam.asset brought over from "
            "main to close an id gap is one only if the release commit had no such file at "
            "all, since the asset's path ships in the bundle's .assetbundle.manifest and its "
            "contents do not — or the toolchain changed since the release (an SDK or "
            "game-asset update). Repair with the override: download the modfile, "
            "`CK_STEAM_CONTENT=<dir> upload.sh --steam-only`.",
        )

    return Verdict(True, f"matches mod.io ({content_size} bytes)")


def parse_size_before(raw: str | None) -> int | SizeBefore:
    """CK_STEAM_SIZE_BEFORE as one of its three states: a size, a new item, or unknown.

    `steam-size` prints a positive number, `none` or `unreadable`, and
    upload.sh turns a crash of it into `unreadable` too. Everything else — an
    empty or unset value, a 0, two lines, anything a later change might print
    — is unknown rather than a new item: a new item is the one state allowed to
    conclude a mismatch with no size from before, so it has to be said
    explicitly, never inferred from silence. A value that is none of the three
    tokens is named on stderr, so a producer that changed does not go unseen;
    `unreadable` is one of the three and says nothing.
    """
    text = (raw or "").strip()
    if text.isascii() and text.isdecimal() and int(text) > 0:
        return int(text)
    if text == SizeBefore.NEW_ITEM.value:
        return SizeBefore.NEW_ITEM
    if text != SizeBefore.UNKNOWN.value:  # the valid token needs no warning
        print(
            f"  ! CK_STEAM_SIZE_BEFORE={text!r} is not a size — the item's size before the "
            "upload counts as unknown.",
            file=sys.stderr,
        )
    return SizeBefore.UNKNOWN


def compare_after_upload(
    expected: int | None,
    before: int | SizeBefore | None,
    read_size: Callable[[], int | None],
    *,
    attempts: int = 6,
    interval: float = 5.0,
    sleep: Callable[[float], None] | None = None,
) -> tuple[int, str]:
    """Whether the Workshop item now holds what mod.io serves, as (exit code, sentence).

    `before` is what was known of the item before the upload: its size, a
    new item (`SizeBefore.NEW_ITEM`), or nothing (`SizeBefore.UNKNOWN`) —
    and anything that is neither a positive size nor NEW_ITEM counts as
    unknown, 0 and None included. Steam's size is expected to lag a submit,
    as the Web API's tag reads can (steam_retag.VERIFY_ATTEMPTS), though no
    lag of the size has been measured. So reads are retried up to `attempts`
    times, `interval` seconds apart, and what counts as "not updated yet"
    rather than a verdict is:

    - a failed read (None), and a read equal to the old size;
    - a read of 0, which is never taken as a size: no uploaded build is 0
      bytes, so a 0 is a size Steam is not reporting yet;
    - for a new item, any read but the last — with no old size to tell a
      lagging read from a final one, a wrong nonzero size is concluded only
      once every attempt is used, from the last read;
    - for an unknown old size, every read: a lagging read of the old size
      cannot be told from other content, so a nonzero read that is not
      `expected` is never concluded as 11 — it ends the attempts in 12.

    A read equal to `expected` matches at once, even when it equals the old
    size: a re-upload of the same build changes nothing to wait for. With the
    old size known, a nonzero read that is neither it nor `expected` is final
    — the item changed and holds other content (11). Running out of attempts
    otherwise leaves the comparison unmade (12), and so does an `expected`
    that is no size: nothing to compare with is never a pass.

    `sleep` defaults to `time.sleep` as it is when called, not when this
    function was defined, so a stub of it takes effect.
    """
    if not _is_size(expected):
        return (
            EXIT_UNVERIFIED,
            f"could not verify the Workshop item: mod.io has no size on record to compare it "
            f"with ({expected!r}).",
        )
    if before is not SizeBefore.NEW_ITEM and not _is_size(before):
        before = SizeBefore.UNKNOWN
    known = before if _is_size(before) else None
    pause = time.sleep if sleep is None else sleep
    check_later = (
        f"`steam_guard.py steam-size <mod repo>`, with MOD_NAME set, prints the size Steam "
        f"reports; it should be {expected}."
    )

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
            pause(interval)
        last = read_size()
        if last == expected:
            return 0, f"the Workshop item matches mod.io ({expected} bytes)"
        if known is not None and last not in (None, 0, known):
            return mismatch(last)
    if before is SizeBefore.NEW_ITEM and last not in (None, 0):
        return mismatch(last)
    if last is None and before is SizeBefore.NEW_ITEM:
        why = (
            "its size could not be read (the lines above say what each read got). The item is "
            "new, and a new item is created hidden; the public Web API may not show an item "
            "until it is made visible (unverified). Make it visible, then check by hand: "
            f"{check_later}"
        )
    elif last is None:
        why = (
            "its size could not be read (the lines above say what each read got). Check by "
            f"hand once Steam answers: {check_later}"
        )
    elif last == 0:
        why = f"Steam still reports no size for the item (0 B). Check by hand later: {check_later}"
    elif before is SizeBefore.UNKNOWN:
        why = (
            f"the item reports {last} B, and its size from before the upload is unknown, so "
            f"that may still be the old size. Check by hand later: {check_later}"
        )
    else:
        why = (
            f"the item still reports its size from before the upload ({before} B). Check by "
            f"hand later: {check_later}"
        )
    return (
        EXIT_UNVERIFIED,
        f"could not verify the Workshop item against mod.io ({expected} B) after {attempts} "
        f"reads: {why}",
    )


def combine_exit(steam_rc: int, guard_rc: int) -> int:
    """The one exit code for a run whose Steam stage and guard each ended with their own.

    Only a Steam code after which the upload may have gone through
    (`COMPARABLE_STEAM_CODES`) can be changed; any other is what happened
    first, and passes through as it is — a failure, or a code nobody has
    assigned yet, which must not be masked by a comparison either. Among
    those, a content mismatch (11) outranks everything — the item is live with
    the wrong content, whatever else is also true; 12 outranks only success.
    Any other guard code is a guard that crashed, which is the comparison not
    having been made: 12.
    """
    if steam_rc not in COMPARABLE_STEAM_CODES:
        return steam_rc
    if guard_rc == EXIT_CONTENT_MISMATCH:
        return EXIT_CONTENT_MISMATCH
    if guard_rc != 0 and steam_rc == 0:
        return EXIT_UNVERIFIED
    return steam_rc


def steam_size(file_id: int) -> int | None:
    """The item's size in bytes as the public Web API reports it now, or None when it cannot say.

    The Web API's `file_size`, a string, which for a folder-content item is
    the content's byte total and equals mod.io's `filesize_uncompressed`. Not
    the Steam session's UGC query: its `SizeBytes` measured 0 for the one
    such item it was read on. None covers a failed fetch (network, certificate,
    a broken or truncated response), an entry of the wrong shape, a `result`
    other than 1 — a deleted item, or presumably a hidden one, which the item a
    first publish creates is (unverified: no hidden item has been read) — and
    a `file_size` that is not a whole number. Each of those prints one line on
    stderr naming it, since a None alone cannot tell a lagging Steam from a
    broken read; stdout stays clean for `steam-size`. Anything else — a bug —
    propagates, and the callers turn a crash into an unknown size.
    """
    try:
        details = steam_retag.item_details(file_id)
    except (OSError, ValueError, http.client.HTTPException) as err:
        print(
            f"  ! Workshop item {file_id}: size not readable — {type(err).__name__}: {err}",
            file=sys.stderr,
        )
        return None
    if not isinstance(details, dict):
        print(
            f"  ! Workshop item {file_id}: size not readable — unexpected Web API entry "
            f"{details!r}",
            file=sys.stderr,
        )
        return None
    result = details.get("result")
    if result != 1:
        print(
            f"  ! Workshop item {file_id}: size not readable — the Web API answers result "
            f"{result} (1 is a readable item; a deleted one, and presumably a hidden one, is not)",
            file=sys.stderr,
        )
        return None
    raw = details.get("file_size")
    if _whole_number(raw) and raw >= 0:  # type: ignore[operator]
        return raw  # type: ignore[return-value]
    if isinstance(raw, str) and raw.isascii() and raw.isdecimal():
        return int(raw)
    print(
        f"  ! Workshop item {file_id}: size not readable — file_size is {raw!r}, "
        "not a whole number",
        file=sys.stderr,
    )
    return None


def _version(repo: Path) -> str:
    """The topmost CHANGELOG.md version — what the run labels its release with."""
    version, _ = steam_bundle.parse_changelog((repo / "CHANGELOG.md").read_text(encoding="utf-8"))
    return version


def _recorded_modio_id(repo: Path, mod_name: str) -> tuple[int | None, str]:
    """The mod.io id the checkout's own asset records, or (None, why) when it cannot be read."""
    asset = steam_identity.modio_asset_path(repo, mod_name)
    try:
        return steam_identity.read_modio_id(asset), ""
    except (OSError, ValueError) as err:
        return None, f"{asset} exists but could not be read ({err})"


def _cmd_modio_id(repo: Path, mod_name: str, env: Mapping[str, str]) -> int:
    """`modio-id`: refuse a checkout whose mod.io id is missing or other than main's; else 0.

    Run by upload.sh before anything reaches mod.io, in every mode: on modId 0
    a normal publish creates a second mod.io profile, and on another id it
    uploads to that profile — not a Steam problem a skipped Steam stage could
    contain. The Workshop-id gap is left to the Steam preflight
    (`steam_identity.id_gaps` has both).
    """
    gaps = steam_identity.id_gaps(repo, mod_name, modio_only=True)
    if gaps:
        print("\n".join(gaps), file=sys.stderr)
        return 1
    return 0


def _cmd_unasked_main(repo: Path, mod_name: str, env: Mapping[str, str]) -> int:
    """`unasked-main`: one line when "not on mod.io" rests on a `main` that was never asked; exit 0.

    The mod.io id is the one id whose loss `main` alone can reveal. When git
    could not be asked and the checkout records none, a `--steam-only` run
    publishes uncompared on this checkout's word, and the warning
    `id_gaps` printed about it sits before Unity's whole log — so upload.sh
    asks again at the very end, where the verdict is read. It says nothing
    otherwise: a mod with a recorded id was not taken as "not on mod.io", and
    a `main` that answered has nothing to repeat. Its own failure to read the
    asset is the pre- and post-upload checks' to report, not this line's.
    """
    try:
        recorded = steam_identity.read_modio_id(steam_identity.modio_asset_path(repo, mod_name))
    except (OSError, ValueError):
        return 0
    why = steam_identity.main_unasked(repo, mod_name) if recorded == 0 else None
    if why is not None:
        print(
            f"! This run took {mod_name} for a mod not on mod.io and compared nothing with "
            f"mod.io, on this checkout's word alone: main could not be asked whether it "
            f"records a mod.io id ({why}).",
        )
    return 0


def _cmd_pre_upload(repo: Path, mod_name: str, env: Mapping[str, str]) -> int:
    """`pre-upload`: print the verdict on the content bound for Steam; 0 proceeds, 1 refuses."""
    ref = load_reference(Path(env.get("CK_MODIO_REF", "")))
    try:
        version = _version(repo)
    except (OSError, ValueError) as err:
        print(f"CHANGELOG.md names no version for this run: {err}", file=sys.stderr)
        return 1
    recorded, why = _recorded_modio_id(repo, mod_name)
    if recorded is None:
        print(f"{why} — refusing: without it Unity's mod.io id cannot be checked.", file=sys.stderr)
        return 1
    if not env.get("CK_STEAM_CONTENT"):
        # Path("") is the working directory, which is no content folder.
        print("CK_STEAM_CONTENT is not set — there is no folder to judge.", file=sys.stderr)
        return 1
    content = Path(env["CK_STEAM_CONTENT"])
    override = bool(env.get("CK_STEAM_OVERRIDE"))
    install = env.get("MOD_INSTALL_PATH")
    try:
        size = folder_size(content)
    except OSError as err:
        if classify_reference(ref, recorded)[0] is Reference.READ:
            print(f"the content could not be measured: {err}", file=sys.stderr)
            return 1
        # Not on mod.io, or a reference the verdict refuses anyway: no size is
        # compared, and a missing folder is build_bundle's to report.
        size = 0
    verdict = decide_pre_upload(
        version=version,
        ref=ref,
        content=content,
        content_size=size,
        override=override,
        install_path=Path(install) if install else None,
        recorded_id=recorded,
        litter=finder_litter(content),
    )
    print(verdict.message, file=None if verdict.proceed else sys.stderr)
    return 0 if verdict.proceed else 1


def _cmd_steam_size(repo: Path, mod_name: str, env: Mapping[str, str]) -> int:
    """`steam-size`: print the item's size before the upload, as one of three tokens; exit 0.

    A positive number is the size; `none` is no Workshop id recorded, a new
    item, judged by the new-item rule; `unreadable` is an item whose size is
    unknown — its asset could not be read, or Steam gave no size or 0 — which
    must never end in 11. "No id" has a token of its own rather than an empty
    answer, because an empty answer is also what a crash leaves.
    """
    asset = steam_identity.asset_path(repo, mod_name)
    try:
        file_id = steam_identity.read_file_id(asset)
    except (OSError, ValueError) as err:
        print(f"  ! {asset} exists but could not be read: {err}", file=sys.stderr)
        print(SizeBefore.UNKNOWN.value)
        return 0
    if file_id is None:
        print(SizeBefore.NEW_ITEM.value)
        return 0
    size = steam_size(file_id)
    if size == 0:
        print(
            f"  ! Workshop item {file_id} reports 0 B — no uploaded build is 0 bytes, so its "
            "size before the upload counts as unknown.",
            file=sys.stderr,
        )
    print(size if size else SizeBefore.UNKNOWN.value)
    return 0


def _cmd_post_upload(repo: Path, mod_name: str, env: Mapping[str, str]) -> int:
    """`post-upload`: compare the item with mod.io after the upload; the exit code says how."""
    ref = load_reference(Path(env.get("CK_MODIO_REF", "")))
    recorded, why = _recorded_modio_id(repo, mod_name)
    if recorded is None:
        print(f"could not verify: {why}")
        return EXIT_UNVERIFIED
    state, why = classify_reference(ref, recorded)
    if state is Reference.UNUSABLE:
        print(f"could not verify: {why}")
        return EXIT_UNVERIFIED
    if state is Reference.NOT_ON_MODIO:
        print("not compared: not on mod.io — there is no modfile to check the item against.")
        return 0
    try:
        version = _version(repo)
    except (OSError, ValueError) as err:
        print(f"could not verify: CHANGELOG.md names no version ({err})")
        return EXIT_UNVERIFIED
    # --steam-only held the content against the live modfile before the upload,
    # so the same one counts here; on the normal path this run's own upload does.
    modfile = reference_modfile(ref, version, prefer_live=env.get("CK_STEAM_ONLY") == "1")
    expected = modfile.get("filesize_uncompressed") if modfile else None
    if not _is_size(expected):
        print(f"could not verify: mod.io has no size on record for version {version}")
        return EXIT_UNVERIFIED
    asset = steam_identity.asset_path(repo, mod_name)
    try:
        file_id = steam_identity.read_file_id(asset)
    except (OSError, ValueError) as err:
        print(f"could not verify: {asset} exists but could not be read ({err})")
        return EXIT_UNVERIFIED
    if file_id is None:
        print("could not verify: no Workshop item id is recorded, so there is no item to read")
        return EXIT_UNVERIFIED
    code, message = compare_after_upload(
        expected,
        parse_size_before(env.get("CK_STEAM_SIZE_BEFORE")),
        lambda: steam_size(file_id),
    )
    print(message)
    return code


def main(argv: list[str], env: Mapping[str, str] | None = None) -> int:
    """Dispatch `steam_guard.py <command> <repo>` (or `combine <steam_rc> <guard_rc>`)."""
    env = os.environ if env is None else env
    usage = (
        "usage: steam_guard.py checkout|modio-id|pre-upload|unasked-main|steam-size|post-upload"
        " <repo> | combine <steam_rc> <guard_rc>"
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
        "unasked-main": _cmd_unasked_main,
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
