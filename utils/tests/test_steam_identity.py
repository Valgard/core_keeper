"""Unit tests for reading and writing the Workshop file id.

The asset is the SDK's own <Mod>_Steam.asset, and we address it by path rather
than by the modName field inside it. That field is written from the display
title and looked up by metadata.name, so it goes stale the moment a readable
title is used (CoreKeeperModSDK#11) — reading it would inherit the defect.
"""

import os
import shutil
import subprocess

import pytest
import steam_identity

# git sets GIT_DIR and GIT_INDEX_FILE for the processes it spawns, so any test
# run from a hook inherits them. A `git add` here would then write into the
# REAL repository's index instead of the temp one this test just created —
# which fails the assertion for the right reason and stages temp paths into a
# repository nobody asked it to touch. steam_identity.is_tracked scrubs these
# for exactly this hazard; the tests that prove it has to do the same, first.
GIT_ENV = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}

ASSET = """%YAML 1.1
%TAG !u! tag:unity3d.com,2011:
--- !u!114 &11400000
MonoBehaviour:
  m_Name: DisableDurability_Steam
  fileId: 3790345467
  modOwner: 10000000000000000
  modName: Disable Durability
  selectedPath: /var/folders/x/T/BuiltMods/DisableDurability
  tags:
  - Client
  - Script
"""


def test_reads_the_file_id(tmp_path):
    """The stored `fileId:` line is read back as an int."""
    asset = tmp_path / "DisableDurability_Steam.asset"
    asset.write_text(ASSET)

    assert steam_identity.read_file_id(asset) == 3790345467


# modName is the literal field in the *_Steam.asset YAML (the SDK window's own
# lookup key), not a choice of ours.
def test_a_stale_modName_does_not_affect_the_read(tmp_path):  # noqa: N802
    """A stale modName field must not affect reading the id.

    modName is the SDK window's own lookup key and goes stale by design
    (CoreKeeperModSDK#11) — this module addresses the asset by path, never
    by that field.
    """
    asset = tmp_path / "DisableDurability_Steam.asset"
    asset.write_text(
        ASSET.replace("modName: Disable Durability", "modName: something else entirely")
    )

    assert steam_identity.read_file_id(asset) == 3790345467


def test_a_missing_asset_reads_as_no_id(tmp_path):
    """A missing asset file reads as no id, rather than raising — that is a mod's first publish."""
    assert steam_identity.read_file_id(tmp_path / "absent.asset") is None


def test_a_zero_id_reads_as_no_id(tmp_path):
    """A stored fileId of 0 reads as no id.

    That is the value TEMPLATE writes before anything has ever been
    published.
    """
    asset = tmp_path / "x_Steam.asset"
    asset.write_text(ASSET.replace("fileId: 3790345467", "fileId: 0"))

    assert steam_identity.read_file_id(asset) is None


def test_writing_updates_an_existing_asset_and_leaves_the_rest_alone(tmp_path):
    """Writing a new id to an existing asset updates only the fileId line.

    Every other field (modOwner, m_Name, …) is left exactly as it was.
    """
    asset = tmp_path / "DisableDurability_Steam.asset"
    asset.write_text(ASSET)

    steam_identity.write_file_id(asset, 4242424242)

    text = asset.read_text()
    assert steam_identity.read_file_id(asset) == 4242424242
    assert "modOwner: 10000000000000000" in text
    assert "m_Name: DisableDurability_Steam" in text


def test_writing_creates_the_asset_when_absent(tmp_path):
    """Writing to a path with no asset yet creates one from TEMPLATE.

    The id, the object's own name, and modName are all filled in.
    """
    asset = tmp_path / "NewMod_Steam.asset"

    steam_identity.write_file_id(asset, 99)

    text = asset.read_text()
    assert steam_identity.read_file_id(asset) == 99
    assert text.startswith("%YAML 1.1")
    assert "m_Name: NewMod_Steam" in text
    assert "modName: NewMod" in text


def test_creating_the_asset_also_writes_its_meta(tmp_path):
    """Creating a new asset also writes its .meta, with a fresh GUID and Unity's own importer shape.

    A GUID carrier that only exists after the Editor is next opened is
    one the repo cannot hold.
    """
    asset = tmp_path / "NewMod_Steam.asset"

    steam_identity.write_file_id(asset, 99)

    meta = asset.with_suffix(".asset.meta")
    text = meta.read_text()
    guid = next(line.split("guid: ")[1] for line in text.splitlines() if line.startswith("guid: "))
    assert len(guid) == 32 and int(guid, 16) >= 0, guid
    assert "fileFormatVersion: 2" in text
    assert "mainObjectFileID: 11400000" in text


def test_two_created_assets_do_not_share_a_guid(tmp_path):
    """Two assets created in the same run get distinct GUIDs.

    Not the same one reused across meta files.
    """
    first = tmp_path / "A" / "A_Steam.asset"
    second = tmp_path / "B" / "B_Steam.asset"

    steam_identity.write_file_id(first, 1)
    steam_identity.write_file_id(second, 2)

    assert (
        first.with_suffix(".asset.meta").read_text()
        != second.with_suffix(".asset.meta").read_text()
    )


def test_updating_an_asset_leaves_an_existing_meta_untouched(tmp_path):
    """Updating an existing asset's id leaves an already-existing .meta completely untouched.

    The GUID is Unity's identity for the asset, and once it exists
    something may reference it — a publish must never replace it.
    """
    asset = tmp_path / "DisableDurability_Steam.asset"
    asset.write_text(ASSET)
    meta = asset.with_suffix(".asset.meta")
    meta.write_text("fileFormatVersion: 2\nguid: 0123456789abcdef0123456789abcdef\n")

    steam_identity.write_file_id(asset, 4242424242)

    assert "guid: 0123456789abcdef0123456789abcdef" in meta.read_text()


def test_creating_an_asset_beside_an_existing_meta_keeps_that_meta(tmp_path):
    """Creating an asset where a .meta already exists keeps that meta's GUID, not a new one.

    The asset was deleted, the meta left behind, and Unity still knows
    the old GUID.
    """
    asset = tmp_path / "NewMod_Steam.asset"
    meta = asset.with_suffix(".asset.meta")
    meta.write_text("fileFormatVersion: 2\nguid: 0123456789abcdef0123456789abcdef\n")

    steam_identity.write_file_id(asset, 7)

    assert "guid: 0123456789abcdef0123456789abcdef" in meta.read_text()


def test_creating_fills_every_field_the_sdk_window_reads(tmp_path):
    """Creating a new asset with modOwner, selectedPath and tags supplied writes all three.

    Not just the id — these are the fields only the SDK window reads.
    """
    asset = tmp_path / "NewMod_Steam.asset"

    steam_identity.write_file_id(
        asset,
        99,
        mod_owner=10000000000000000,
        selected_path="/Users/x/Library/Caches/CoreKeeperMods/NewMod",
        tags=["Client", "Script", "Quality of Life"],
    )

    text = asset.read_text()
    assert "modOwner: 10000000000000000" in text
    assert "selectedPath: /Users/x/Library/Caches/CoreKeeperMods/NewMod" in text
    assert "tags:\n  - Client\n  - Script\n  - Quality of Life\n" in text


def test_updating_refreshes_those_fields_too(tmp_path):
    """Updating an existing asset refreshes selectedPath and the tags, but leaves modName alone.

    The SDK window's own values go stale on their own — the build path
    moved once already — and a publish knows the current ones, so it
    corrects them rather than leaving the window pointed at a directory
    that no longer exists. The old tags are replaced, not appended to,
    and modName stays the window's own value, not ours to touch.
    """
    asset = tmp_path / "DisableDurability_Steam.asset"
    asset.write_text(ASSET)

    steam_identity.write_file_id(
        asset,
        4242424242,
        mod_owner=10000000000000000,
        selected_path="/new/path/DisableDurability",
        tags=["Client"],
    )

    text = asset.read_text()
    assert "selectedPath: /new/path/DisableDurability" in text
    assert "tags:\n  - Client\n" in text
    assert "/var/folders" not in text
    assert "- Script" not in text
    assert "modName: Disable Durability" in text


def test_omitted_fields_are_left_exactly_as_they_were(tmp_path):
    """Omitting modOwner, selectedPath and tags on a write must not blank out what is already there.

    A caller without a live Steam session cannot know modOwner at all.
    """
    asset = tmp_path / "DisableDurability_Steam.asset"
    asset.write_text(ASSET)

    steam_identity.write_file_id(asset, 4242424242)

    text = asset.read_text()
    assert "modOwner: 10000000000000000" in text
    assert "selectedPath: /var/folders/x/T/BuiltMods/DisableDurability" in text
    assert "tags:\n  - Client\n  - Script\n" in text


def test_an_empty_selected_path_clears_the_field(tmp_path):
    """An empty selected_path clears the field, which is not the same as omitting it.

    None leaves the stored value alone; "" is a value, and it is what the
    publish passes. The field is written as the scaffold template has it,
    `selectedPath: ` with one trailing space, so a cleared asset does not
    differ from a freshly scaffolded one.
    """
    asset = tmp_path / "DisableDurability_Steam.asset"
    asset.write_text(ASSET)

    steam_identity.write_file_id(asset, 4242424242, selected_path="")

    text = asset.read_text()
    assert "  selectedPath: \n" in text
    assert "/var/folders" not in text
    assert "tags:\n  - Client\n  - Script\n" in text


def test_an_empty_tag_list_is_written_as_the_sdk_writes_it(tmp_path):
    """An empty tag list is written as the single-line `tags: []`, matching the SDK's own shape.

    Not as an empty multi-line sequence.
    """
    asset = tmp_path / "NewMod_Steam.asset"

    steam_identity.write_file_id(asset, 99, tags=[])

    assert "tags: []" in asset.read_text()


def test_writing_refuses_an_existing_file_it_does_not_recognize(tmp_path):
    """An existing file with no `fileId:` line is refused, not silently replaced by a template.

    It is left byte-for-byte unmodified when the refusal happens.
    """
    asset = tmp_path / "Unrecognized_Steam.asset"
    original = "this is not a Steam asset at all\n"
    asset.write_text(original)

    with pytest.raises(ValueError, match="fileId"):
        steam_identity.write_file_id(asset, 99)

    assert asset.read_text() == original


def test_a_permission_error_is_not_read_as_no_id(tmp_path):
    """Only a missing file may read as "no id".

    A permission error on a file that exists is a real problem and must
    propagate, not be folded into "no id" — that would make a publish
    create a second Workshop item over one whose id merely could not be
    read.
    """
    asset = tmp_path / "DisableDurability_Steam.asset"
    asset.write_text(ASSET)
    asset.chmod(0)

    try:
        with pytest.raises(PermissionError):
            steam_identity.read_file_id(asset)
    finally:
        asset.chmod(0o644)  # so tmp_path cleanup can remove it


def test_ensure_recognizable_accepts_a_missing_asset(tmp_path):
    """A missing asset is accepted without complaint.

    A mod's first publish has nothing to recognise yet, and nothing to
    reject.
    """
    steam_identity.ensure_recognizable(tmp_path / "absent.asset")


def test_ensure_recognizable_accepts_a_valid_asset(tmp_path):
    """A valid, recognisable asset passes through ensure_recognizable without raising."""
    asset = tmp_path / "DisableDurability_Steam.asset"
    asset.write_text(ASSET)

    steam_identity.ensure_recognizable(asset)


def test_ensure_recognizable_rejects_what_write_file_id_would_refuse(tmp_path):
    """ensure_recognizable raises on exactly the files write_file_id would refuse.

    Checked before any Steam call, not after, so a bad asset aborts
    before a Workshop item is even created.
    """
    asset = tmp_path / "Unrecognized_Steam.asset"
    asset.write_text("this is not a Steam asset at all\n")

    with pytest.raises(ValueError, match="fileId"):
        steam_identity.ensure_recognizable(asset)


def test_the_id_is_written_even_if_the_template_stops_carrying_it(tmp_path, monkeypatch):
    """The id-substitution step fills in the id even without a `{file_id}` placeholder in TEMPLATE.

    Guards the line that looks redundant on the create path: re.sub is
    silent on a non-match, so nothing else here would notice it stopped
    working.
    """
    monkeypatch.setattr(
        steam_identity,
        "TEMPLATE",
        steam_identity.TEMPLATE.replace("fileId: {file_id}", "fileId: 0"),
    )
    asset = tmp_path / "NewMod_Steam.asset"

    steam_identity.write_file_id(asset, 4242424242)

    assert steam_identity.read_file_id(asset) == 4242424242


def test_the_asset_path_is_where_a_mod_repo_keeps_it(tmp_path):
    """asset_path computes the same unity/<Mod>/<Mod>_Steam.asset layout every mod repo uses."""
    assert (
        steam_identity.asset_path(tmp_path, "DisableDurability")
        == tmp_path / "unity" / "DisableDurability" / "DisableDurability_Steam.asset"
    )


# --- is the id durable, or one `git clean` from gone? ---------------------

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


@pytest.fixture
def repo(tmp_path):
    """A real git repo with the asset in it — untracked until `add` is called.

    Against the real binary rather than a mock: what is being checked here is
    an exit code contract with git itself (0 tracked / 1 untracked / 128 not a
    repo), and a mock would only assert that this file's own assumptions match
    themselves.
    """
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, env=GIT_ENV)
    asset = steam_identity.asset_path(tmp_path, "DisableDurability")
    asset.parent.mkdir(parents=True)
    asset.write_text(ASSET)
    return asset


@needs_git
def test_a_committed_asset_is_seen_as_tracked(repo):
    """A committed (staged) asset is reported as tracked."""
    subprocess.run(["git", "-C", str(repo.parent), "add", repo.name], check=True, env=GIT_ENV)

    assert steam_identity.is_tracked(repo) is True


@needs_git
def test_an_untracked_asset_is_seen_as_untracked(repo):
    """An asset that exists in a repo but was never `git add`-ed is reported as untracked."""
    assert steam_identity.is_tracked(repo) is False


def test_outside_a_repo_the_question_has_no_answer(tmp_path):
    """Outside any git repository, is_tracked answers None, not False.

    Collapsing "git cannot tell us" into "git says no" would report an
    unusual setup as a hazard it is not actually in.
    """
    asset = tmp_path / "Loose_Steam.asset"
    asset.write_text(ASSET)

    assert steam_identity.is_tracked(asset) is None


@needs_git
def test_without_git_the_question_has_no_answer(repo, monkeypatch):
    """With no git binary on PATH, is_tracked answers None even for a genuinely untracked asset.

    Deliberately an asset that IS in a repo and IS untracked, so a real
    False answer is available here and must still be suppressed — a
    non-repo directory, where both paths already return None, could not
    prove that.
    """
    monkeypatch.setattr(steam_identity.shutil, "which", lambda _: None)

    assert steam_identity.is_tracked(repo) is None


@needs_git
# GIT_DIR is git's own environment variable name, not a choice of ours.
def test_an_inherited_GIT_DIR_does_not_answer_for_another_repo(  # noqa: N802
    repo, tmp_path, monkeypatch
):
    """An inherited GIT_DIR/GIT_INDEX_FILE must not make is_tracked answer for a foreign repo.

    GIT_DIR and GIT_INDEX_FILE outrank -C, and could be inherited from
    whatever invoked the publish. The costly wrong answer is a false
    "tracked", which would withhold the warning on the one asset that
    actually needs it. Same defence check_docs_wrapping.markdown_files
    already documents.
    """
    subprocess.run(["git", "-C", str(repo.parent), "add", repo.name], check=True, env=GIT_ENV)
    decoy = tmp_path / "decoy"
    subprocess.run(["git", "init", "-q", str(decoy)], check=True, env=GIT_ENV)
    monkeypatch.setenv("GIT_DIR", str(decoy / ".git"))
    monkeypatch.setenv("GIT_INDEX_FILE", str(decoy / ".git" / "index"))

    assert steam_identity.is_tracked(repo) is True


@needs_git
def test_ensure_recognizable_warns_about_an_untracked_asset(repo, capsys):
    """An untracked asset gets a warning that carries the fix, not just the diagnosis.

    This is read in the middle of a publish, by someone who is not
    thinking about git.
    """
    steam_identity.ensure_recognizable(repo)

    err = capsys.readouterr().err
    assert "not tracked by git" in err
    assert f"git add {repo}" in err


@needs_git
def test_ensure_recognizable_stays_quiet_about_a_tracked_asset(repo, capsys):
    """A tracked asset produces no warning at all."""
    subprocess.run(["git", "-C", str(repo.parent), "add", repo.name], check=True, env=GIT_ENV)

    steam_identity.ensure_recognizable(repo)

    assert capsys.readouterr().err == ""


def test_ensure_recognizable_stays_quiet_when_git_cannot_answer(tmp_path, capsys):
    """When git cannot answer at all (no repository here), ensure_recognizable stays quiet.

    Rather than warning on an unanswerable question.
    """
    asset = tmp_path / "Loose_Steam.asset"
    asset.write_text(ASSET)

    steam_identity.ensure_recognizable(asset)

    assert capsys.readouterr().err == ""


def test_ensure_recognizable_says_nothing_about_an_asset_that_does_not_exist(tmp_path, capsys):
    """A missing asset produces no warning.

    A mod's first publish has no file to track yet, and a warning here
    would be advice about something that does not exist.
    """
    steam_identity.ensure_recognizable(tmp_path / "absent.asset")

    assert capsys.readouterr().err == ""


@needs_git
def test_a_bad_asset_is_refused_before_it_is_judged_on_tracking(repo, capsys):
    """A bad asset (no fileId line) is refused before its tracking status is ever checked.

    Order matters: the bigger problem must not be buried under a git
    note that would read as mere advice.
    """
    repo.write_text("this is not a Steam asset at all\n")

    with pytest.raises(ValueError, match="fileId"):
        steam_identity.ensure_recognizable(repo)

    assert capsys.readouterr().err == ""


# --- does this checkout carry the ids main already has? ---------------------
#
# Release tags commonly predate the commits that record the ids, so a checkout
# of one — the repair route — can lack an id that main has. Built as real
# histories under tmp_path: what is checked is `git show <branch>:<path>`
# against a checkout that is behind it, which a mock could only restate.

MOD = "DisableDurability"
MODIO_ASSET = "MonoBehaviour:\n  m_Name: DisableDurability_modio\n  modId: {mod_id}\n"


def _git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True, env=GIT_ENV
    ).stdout


def _write_ids(root, *, file_id=None, mod_id=None):
    """Write either identity asset into a checkout; None leaves that one alone."""
    if file_id is not None:
        steam = steam_identity.asset_path(root, MOD)
        steam.parent.mkdir(parents=True, exist_ok=True)
        steam.write_text(ASSET.replace("fileId: 3790345467", f"fileId: {file_id}"))
    if mod_id is not None:
        modio = steam_identity.modio_asset_path(root, MOD)
        modio.parent.mkdir(parents=True, exist_ok=True)
        modio.write_text(MODIO_ASSET.format(mod_id=mod_id))


def _history(tmp_path, *commits):
    """A mod repo on `main` with one commit per `(file_id, mod_id)` pair, and each commit's hash."""
    root = tmp_path / "mod"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "Test")
    _git(root, "config", "commit.gpgsign", "false")
    hashes = []
    for index, (file_id, mod_id) in enumerate(commits):
        _write_ids(root, file_id=file_id, mod_id=mod_id)
        (root / "CHANGELOG.md").write_text(f"commit {index}\n")
        _git(root, "add", "-A")
        _git(root, "commit", "-q", "-m", f"commit {index}")
        hashes.append(_git(root, "rev-parse", "HEAD").strip())
    return root, hashes


def _checkout_at(root, commit, tmp_path):
    """A linked worktree detached at `commit` — the shape of a checkout of a release tag."""
    tree = tmp_path / "at-release"
    _git(root, "worktree", "add", "-q", "--detach", str(tree), commit)
    return tree


def test_the_modio_asset_path_is_where_a_mod_repo_keeps_it(tmp_path):
    """modio_asset_path is unity/<Mod>/Editor/<Mod>_modio.asset, where CLIPublishHelper reads it."""
    assert (
        steam_identity.modio_asset_path(tmp_path, MOD)
        == tmp_path / "unity" / MOD / "Editor" / f"{MOD}_modio.asset"
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [(MODIO_ASSET.format(mod_id=6119768), 6119768), (MODIO_ASSET.format(mod_id=0), 0)],
    ids=["id", "zero"],
)
def test_read_modio_id_is_the_recorded_id_or_zero(tmp_path, text, expected):
    """The checkout's own mod.io id, with 0 for "none" — the reference's own spelling of it."""
    asset = steam_identity.modio_asset_path(tmp_path, MOD)
    asset.parent.mkdir(parents=True)
    asset.write_text(text)

    assert steam_identity.read_modio_id(asset) == expected


@pytest.mark.parametrize("text", ["", "x\n", "MonoBehaviour:\n  m_Name: Mod\n"])
def test_read_modio_id_raises_for_an_asset_with_no_id_line(tmp_path, text):
    """An existing asset with no `modId:` line is unreadable, not "no id".

    Empty, truncated, an LFS pointer or reformatted: Unity reads 0 from such a
    file too, and 0 on both sides would pass for "not on mod.io" — an
    uncompared publish that nothing reports.
    """
    asset = steam_identity.modio_asset_path(tmp_path, MOD)
    asset.parent.mkdir(parents=True)
    asset.write_text(text)

    with pytest.raises(ValueError, match="modId"):
        steam_identity.read_modio_id(asset)


def test_read_modio_id_of_a_missing_asset_is_zero(tmp_path):
    """No asset is no id, as for a mod never published to mod.io."""
    assert steam_identity.read_modio_id(steam_identity.modio_asset_path(tmp_path, MOD)) == 0


def test_read_modio_id_raises_for_an_asset_that_exists_but_cannot_be_read(tmp_path):
    """An unreadable asset is not "no id": a mod on mod.io would look as if it were not."""
    asset = steam_identity.modio_asset_path(tmp_path, MOD)
    asset.mkdir(parents=True)

    with pytest.raises(OSError):
        steam_identity.read_modio_id(asset)


@needs_git
def test_id_gap_when_the_checkout_predates_the_steam_id(tmp_path):
    """A Workshop id main recorded after the release this checkout sits on is a gap.

    Published from here, the zero id would create a second Workshop item.
    """
    root, (release, _) = _history(tmp_path, (0, 6119768), (3790345467, None))
    tree = _checkout_at(root, release, tmp_path)

    gaps = steam_identity.id_gaps(tree, MOD)

    assert len(gaps) == 1
    assert "Workshop id" in gaps[0] and "3790345467" in gaps[0] and "main" in gaps[0]
    assert str(steam_identity.asset_path(tree, MOD)) in gaps[0]
    assert f"git checkout main -- unity/{MOD}/{MOD}_Steam.asset" in gaps[0]


@needs_git
def test_id_gap_when_the_checkout_predates_the_modio_id(tmp_path):
    """A mod.io id main has and the checkout lacks is a gap, and the message names its real cost.

    That cost is not a skipped comparison: a normal publish on modId 0 has
    CLIPublishHelper call CreateModProfile, so the mod gets a SECOND mod.io
    profile. The message must say so and tell the operator which file to
    bring over from main.
    """
    root, (release, _) = _history(tmp_path, (3790345467, 0), (None, 6119768))
    tree = _checkout_at(root, release, tmp_path)

    gaps = steam_identity.id_gaps(tree, MOD)

    assert len(gaps) == 1
    assert "mod.io id" in gaps[0] and "6119768" in gaps[0]
    assert "CreateModProfile" in gaps[0] and "SECOND mod.io profile" in gaps[0]
    assert f"Bring {MOD}_modio.asset over from main before publishing" in gaps[0]
    assert f"git checkout main -- unity/{MOD}/Editor/{MOD}_modio.asset" in gaps[0]


@needs_git
def test_id_gap_when_the_checkout_has_no_asset_at_all(tmp_path):
    """A checkout from before the asset existed has no id either: a missing file reads as none."""
    root, (release, _) = _history(tmp_path, (None, None), (3790345467, 6119768))
    tree = _checkout_at(root, release, tmp_path)

    assert len(steam_identity.id_gaps(tree, MOD)) == 2


@needs_git
def test_id_gaps_modio_only_leaves_the_workshop_gap_out(tmp_path):
    """`modio_only` reports the mod.io gap alone, for the check that stops a whole run on it."""
    root, (release, _) = _history(tmp_path, (0, 0), (3790345467, 6119768))
    tree = _checkout_at(root, release, tmp_path)

    gaps = steam_identity.id_gaps(tree, MOD, modio_only=True)

    assert len(gaps) == 1
    assert "mod.io id" in gaps[0] and "6119768" in gaps[0]


@needs_git
def test_no_id_gap_for_a_mod_never_published(tmp_path):
    """Zero on both sides is a mod that is simply new, not a checkout that lost anything."""
    root, _ = _history(tmp_path, (0, 0))

    assert steam_identity.id_gaps(root, MOD) == []


@needs_git
def test_no_id_gap_when_the_checkout_has_the_id_main_lacks(tmp_path, capsys):
    """A first release's branch has its ids and is not merged yet: nothing is missing here."""
    root, _ = _history(tmp_path, (0, 0))
    _git(root, "switch", "-q", "-c", "first-release")
    _write_ids(root, file_id=3790345467, mod_id=6119768)
    _git(root, "commit", "-qam", "record the ids")

    assert steam_identity.id_gaps(root, MOD) == []
    assert capsys.readouterr().err == ""


@needs_git
def test_no_id_gap_when_both_carry_the_id(tmp_path, capsys):
    """The main checkout itself, with both ids: the ordinary case, and nothing to say about it."""
    root, _ = _history(tmp_path, (3790345467, 6119768))

    assert steam_identity.id_gaps(root, MOD) == []
    assert capsys.readouterr().err == ""


@needs_git
def test_id_gap_when_the_checkout_records_another_workshop_id(tmp_path):
    """A Workshop id other than main's is a gap of its own: the publish would update that item.

    The realistic case is a release tag that carries a rehearsal item's id,
    replaced on main since; published from the tag, the update would go to
    the throwaway item instead of the live one.
    """
    root, _ = _history(tmp_path, (3790345467, 6119768))
    _write_ids(root, file_id=111)

    gaps = steam_identity.id_gaps(root, MOD)

    assert len(gaps) == 1
    assert "Workshop id 111" in gaps[0] and "main records 3790345467" in gaps[0]
    assert f"git checkout main -- unity/{MOD}/{MOD}_Steam.asset" in gaps[0]


@needs_git
def test_id_gap_when_the_checkout_records_another_modio_id(tmp_path):
    """A mod.io id other than main's is a gap too, and `modio_only` reports it.

    A normal publish from here would upload the release to that other profile,
    which no skipped Steam stage could prevent — so the check that stops the
    whole run has to see it.
    """
    root, _ = _history(tmp_path, (3790345467, 6119768))
    _write_ids(root, mod_id=222)

    gaps = steam_identity.id_gaps(root, MOD, modio_only=True)

    assert len(gaps) == 1
    assert "mod.io id 222" in gaps[0] and "main records 6119768" in gaps[0]


@needs_git
def test_no_id_gap_without_the_branch_but_a_warning(tmp_path, capsys):
    """No `main` to compare with is no gap — but the run is told the comparison was not made.

    The check only adds a refusal it can justify; staying silent about not
    having checked, though, would hide that a missing id could go unnoticed.
    """
    root, _ = _history(tmp_path, (0, 0))
    _git(root, "branch", "-q", "-m", "main", "trunk")

    assert steam_identity.id_gaps(root, MOD) == []
    err = capsys.readouterr().err
    assert f"could not compare {MOD}_Steam.asset with main" in err
    assert f"could not compare {MOD}_modio.asset with main" in err


def test_no_id_gap_outside_a_repository_but_a_warning(tmp_path, capsys):
    """Where git cannot answer nothing is claimed, and a warning says so, once per asset."""
    _write_ids(tmp_path, file_id=0, mod_id=0)

    assert steam_identity.id_gaps(tmp_path, MOD) == []
    err = capsys.readouterr().err
    assert len([line for line in err.splitlines() if "could not compare" in line]) == 2


@needs_git
def test_id_gaps_does_not_warn_when_main_simply_lacks_the_file(tmp_path, capsys):
    """A main without the asset is a definite "no id on main": no gap, and nothing to warn about.

    The warning is for a git that could not answer; here it answered, and a
    warning that fires on a healthy repository trains the reader to skip the
    one that matters.
    """
    root, _ = _history(tmp_path, (3790345467, None))

    assert steam_identity.id_gaps(root, MOD) == []
    assert capsys.readouterr().err == ""


@needs_git
def test_id_gaps_still_warns_when_git_fails_for_another_reason(tmp_path, capsys, monkeypatch):
    """A git that errors — a timeout, a refused directory — is not an answer, and is said so."""
    root, _ = _history(tmp_path, (3790345467, 6119768))

    def timed_out(*_args, **_kwargs):
        raise subprocess.TimeoutExpired("git", 10)

    monkeypatch.setattr(steam_identity, "run_git", timed_out)

    assert steam_identity.id_gaps(root, MOD) == []
    assert capsys.readouterr().err.count("could not compare") == 2


@needs_git
def test_main_unasked_names_why_main_could_not_be_asked_about_the_modio_id(tmp_path):
    """`main_unasked` is the reason git gave, for the asset the not-on-mod.io verdict rests on."""
    root, _ = _history(tmp_path, (0, 0))
    assert steam_identity.main_unasked(root, MOD) is None
    _git(root, "branch", "-q", "-m", "main", "trunk")

    assert steam_identity.main_unasked(root, MOD)


@needs_git
# GIT_DIR is git's own environment variable name, not a choice of ours.
def test_id_gaps_ignores_an_inherited_GIT_DIR(tmp_path, monkeypatch):  # noqa: N802
    """An inherited GIT_DIR must not make main's ids vanish by asking a decoy repository.

    The costly wrong answer is "no gap": the run would then publish from a
    checkout without a Workshop id and create a second item.
    """
    root, (release, _) = _history(tmp_path, (0, 0), (3790345467, 6119768))
    tree = _checkout_at(root, release, tmp_path)
    decoy = tmp_path / "decoy"
    subprocess.run(["git", "init", "-q", str(decoy)], check=True, env=GIT_ENV)
    monkeypatch.setenv("GIT_DIR", str(decoy / ".git"))

    assert len(steam_identity.id_gaps(tree, MOD)) == 2
