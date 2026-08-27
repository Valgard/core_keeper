"""Unit tests for assembling a Steam publish from sources that already exist.

Every value here has exactly one home in the repository, and the point of the
bundle is that none of them is retyped: a title that differs from mod.io, a tag
set that drifts, a changelog that says something else — each is a defect this
module exists to make impossible.
"""

import new_mod
import pytest
import steam_bundle

# A verbatim copy of disable-durability's real ModBuilderSettings asset, with
# only its dependency list emptied so the tests below can substitute their own.
#
# It used to be an eight-line stub holding just the four keys the parsers read,
# which made every test in this file agree with a document no Unity Editor would
# ever write: no YAML header, no `guid:`, no `files: []`, no `m_Name:` — and the
# parsers are regexes over the whole document, so everything around those four
# keys is input too.
#
# Being honest about what this does and does not buy, because it is less than it
# looks: it does NOT catch a `name` lookup that strays onto `m_Name:`, since a
# real asset holds the mod's internal name in both and the wrong match returns
# the right string. What it buys is that every assertion here is now measured
# against the shape a publish really reads. The guard against a parser that
# works on this one document and not on the family's is
# `test_the_parsers_hold_against_every_real_mod_asset` at the bottom.
ASSET = """%YAML 1.1
%TAG !u! tag:unity3d.com,2011:
--- !u!114 &11400000
MonoBehaviour:
  m_ObjectHideFlags: 0
  m_CorrespondingSourceObject: {fileID: 0}
  m_PrefabInstance: {fileID: 0}
  m_PrefabAsset: {fileID: 0}
  m_GameObject: {fileID: 0}
  m_Enabled: 1
  m_EditorHideFlags: 0
  m_Script: {fileID: 11500000, guid: bc43e4983a160e543856e5ba0421c9e1, type: 3}
  m_Name: DisableDurability
  m_EditorClassIdentifier:
  metadata:
    guid: 45103bfded4742c2b747b83c2c2da350
    name: DisableDurability
    displayName: Disable Durability
    skipSafetyChecks: 0
    disableScripts: 0
    accessesExtraAssemblies: 1
    disableHarmonyPatching: 0
    requiredOn: 3
    files: []
    dependencies: []
  modPath: Assets/DisableDurability
  forceReimport: 1
  buildBundles: 1
  cacheBundles: 0
  buildLinux: 1
  assets: []
  lastBuildLinux: 0
"""

CHANGELOG = """# Changelog

Some preamble that is not an entry.

## [1.1.1] - 2026-08-08

### Added

- A thing.
- Another thing.

## [1.1.0] - 2026-07-01

### Added

- Older, must not be picked.
"""


def _repo(tmp_path, asset=ASSET, changelog=CHANGELOG, description="[b]Bold[/b]"):
    (tmp_path / "unity").mkdir()
    (tmp_path / "unity" / "DisableDurability.asset").write_text(asset)
    (tmp_path / "CHANGELOG.md").write_text(changelog)
    if description is not None:
        (tmp_path / "steam-description.txt").write_text(description)
    logo_dir = tmp_path / "unity" / "DisableDurability" / "Editor"
    logo_dir.mkdir(parents=True)
    from PIL import Image

    Image.new("RGBA", (256, 256), (10, 80, 90, 255)).save(logo_dir / "logo.png")
    return tmp_path


def _env(tmp_path, **overrides):
    content = tmp_path / "build" / "DisableDurability"
    content.mkdir(parents=True, exist_ok=True)
    env = {
        "MOD_NAME": "DisableDurability",
        "CK_MODIO_TYPE": "Item|Overhaul|Quality of Life",
        "MOD_INSTALL_PATH": str(tmp_path / "build"),
    }
    env.update(overrides)
    return env


def test_the_topmost_changelog_entry_is_the_version():
    version, body = steam_bundle.parse_changelog(CHANGELOG)

    assert version == "1.1.1"
    assert "A thing." in body
    assert "Older, must not be picked." not in body


def test_the_title_is_the_display_name_not_the_internal_name(tmp_path):
    bundle = steam_bundle.build_bundle(
        _repo(tmp_path), _env(tmp_path), tmp_path / "p.png"
    )

    assert bundle["title"] == "Disable Durability"


def test_the_title_falls_back_to_the_internal_name(tmp_path):
    repo = _repo(
        tmp_path, asset=ASSET.replace("    displayName: Disable Durability\n", "")
    )

    bundle = steam_bundle.build_bundle(repo, _env(tmp_path), tmp_path / "p.png")

    assert bundle["title"] == "DisableDurability"


def test_tags_combine_all_three_groups(tmp_path):
    bundle = steam_bundle.build_bundle(
        _repo(tmp_path), _env(tmp_path), tmp_path / "p.png"
    )

    assert set(bundle["tags"]) == {
        "Item",
        "Overhaul",
        "Quality of Life",
        "Client",
        "Server",
        "Script",
    }


def test_requiredOn_1_is_client_only():
    tags = steam_bundle.derive_tags({"requiredOn": 1, "skipSafetyChecks": 0}, "Visual")

    assert "Client" in tags and "Server" not in tags


def test_requiredOn_0_produces_no_application_type_tag():
    tags = steam_bundle.derive_tags({"requiredOn": 0, "skipSafetyChecks": 0}, "Visual")

    assert "Client" not in tags and "Server" not in tags


def test_an_empty_field_reads_as_absent_not_as_the_next_line():
    # A key with no value must not swallow the newline and capture whatever
    # follows. displayName is the one that matters most: the SDK's settings GUI
    # cannot set it, so empty is the normal state of a freshly created mod —
    # and build_bundle uses it as the Workshop item's TITLE. Reading the line
    # below would publish an item titled "skipSafetyChecks: 0".
    asset = (
        "MonoBehaviour:\n"
        "  metadata:\n"
        "    name: NewMod\n"
        "    displayName: \n"
        "    skipSafetyChecks: 0\n"
        "    requiredOn: 3\n"
    )

    metadata = steam_bundle._read_metadata(asset)

    assert "displayName" not in metadata
    assert metadata["name"] == "NewMod"
    assert metadata["skipSafetyChecks"] == 0
    assert metadata["requiredOn"] == 3


def test_requiredOn_is_read_bitwise_not_looked_up():
    # The SDK's own settings GUI writes -1 ("Everything") when "Client and
    # Server" is picked, and the mod.io side reads the field bitwise, so it
    # tags both. Anything that maps whole values instead drops the tags for
    # that one input — and Steam discards a missing tag without a word.
    tags = steam_bundle.derive_tags({"requiredOn": -1, "skipSafetyChecks": 0}, "Visual")

    assert "Client" in tags and "Server" in tags


def test_an_unknown_application_type_warns_instead_of_going_out_silently(capsys):
    # 0 is legitimate — a mod that gates nothing — but it is also what an unset
    # field reads as, and only the author can tell the two apart. mod.io says so
    # on its own path; saying it on one platform only is how they diverge.
    steam_bundle.derive_tags({"requiredOn": 0, "skipSafetyChecks": 0}, "Visual")

    err = capsys.readouterr().err
    assert "Application Type" in err and "requiredOn" in err


def test_elevated_access_changes_the_access_tag():
    tags = steam_bundle.derive_tags({"requiredOn": 1, "skipSafetyChecks": 1}, "Library")

    assert "Script (Elevated Access)" in tags and "Script" not in tags


def test_a_new_mod_gets_hidden_visibility_and_no_file_id(tmp_path):
    bundle = steam_bundle.build_bundle(
        _repo(tmp_path), _env(tmp_path), tmp_path / "p.png"
    )

    assert bundle["fileId"] == 0
    assert bundle["visibility"] == "hidden"


def test_an_existing_mod_keeps_its_visibility(tmp_path):
    repo = _repo(tmp_path)
    asset = repo / "unity" / "DisableDurability" / "DisableDurability_Steam.asset"
    import steam_identity

    steam_identity.write_file_id(asset, 3790345467)

    bundle = steam_bundle.build_bundle(repo, _env(tmp_path), tmp_path / "p.png")

    assert bundle["fileId"] == 3790345467
    assert bundle["visibility"] == "unchanged"


def test_check_prerequisites_passes_without_a_built_content_folder(tmp_path):
    # The whole point: this must be callable BEFORE the mod.io build runs,
    # when MOD_INSTALL_PATH/<mod> does not exist yet.
    repo = _repo(tmp_path)
    env = {"MOD_NAME": "DisableDurability", "CK_MODIO_TYPE": "Item"}

    steam_bundle.check_prerequisites(repo, env)


def test_check_prerequisites_reports_a_missing_description_by_name(tmp_path):
    repo = _repo(tmp_path, description=None)
    env = {"MOD_NAME": "DisableDurability", "CK_MODIO_TYPE": "Item"}

    with pytest.raises(ValueError, match="steam-description.txt"):
        steam_bundle.check_prerequisites(repo, env)


def test_check_prerequisites_reports_an_unrecognized_identity_asset(tmp_path):
    repo = _repo(tmp_path)
    identity = repo / "unity" / "DisableDurability" / "DisableDurability_Steam.asset"
    identity.write_text("this is not a Steam asset at all\n")
    env = {"MOD_NAME": "DisableDurability", "CK_MODIO_TYPE": "Item"}

    with pytest.raises(ValueError, match="fileId"):
        steam_bundle.check_prerequisites(repo, env)


def test_check_prerequisites_reports_an_unresolvable_required_dependency(tmp_path):
    repo = _repo(
        tmp_path,
        asset=ASSET.replace(
            "    dependencies: []",
            "    dependencies:\n    - modName: CoreLib\n      required: 1",
        ),
    )
    env = {"MOD_NAME": "DisableDurability", "CK_MODIO_TYPE": "Item"}

    with pytest.raises(ValueError, match="CoreLib"):
        steam_bundle.check_prerequisites(repo, env)


def test_build_bundle_calls_check_prerequisites_first(tmp_path):
    # A missing description must surface even though the content folder is
    # ALSO missing (build_bundle checks that one itself) — check_prerequisites
    # runs first, so its error is the one that surfaces.
    repo = _repo(tmp_path, description=None)
    env = _env(tmp_path, MOD_INSTALL_PATH=str(tmp_path / "nowhere"))

    with pytest.raises(ValueError, match="steam-description.txt"):
        steam_bundle.build_bundle(repo, env, tmp_path / "p.png")


def test_an_unrecognized_identity_asset_aborts_before_any_upload(tmp_path):
    # steam_identity's guard, called from here: an existing _Steam.asset without
    # a 'fileId:' line must be caught before the bundle is even assembled, not
    # discovered only after a Workshop item was already created from it.
    repo = _repo(tmp_path)
    identity = repo / "unity" / "DisableDurability" / "DisableDurability_Steam.asset"
    identity.parent.mkdir(parents=True, exist_ok=True)
    identity.write_text("this is not a Steam asset at all\n")

    with pytest.raises(ValueError, match="fileId"):
        steam_bundle.build_bundle(repo, _env(tmp_path), tmp_path / "p.png")


def test_a_missing_description_is_reported_by_name(tmp_path):
    repo = _repo(tmp_path, description=None)

    with pytest.raises(ValueError, match="steam-description.txt"):
        steam_bundle.build_bundle(repo, _env(tmp_path), tmp_path / "p.png")


def test_the_content_is_the_build_modio_published_when_one_is_reported(tmp_path):
    # CLIPublishHelper builds into a fresh temporary directory and publishes
    # THAT to mod.io. Steam has to upload the same one, or the two platforms
    # ship different code under the same version number.
    repo = _repo(tmp_path)
    published = tmp_path / "published-build"
    published.mkdir()
    env = _env(tmp_path, CK_STEAM_CONTENT=str(published))

    bundle = steam_bundle.build_bundle(repo, env, tmp_path / "p.png")

    assert bundle["contentPath"] == str(published)


def test_without_a_reported_build_the_local_install_is_used(tmp_path):
    # --steam-only runs no mod.io build, so there is no fresh directory to
    # point at and the last local build is the only thing there is to publish.
    repo = _repo(tmp_path)
    env = _env(tmp_path)

    bundle = steam_bundle.build_bundle(repo, env, tmp_path / "p.png")

    assert bundle["contentPath"] == str(tmp_path / "build" / "DisableDurability")


def test_a_missing_content_folder_is_reported(tmp_path):
    repo = _repo(tmp_path)
    env = _env(tmp_path, MOD_INSTALL_PATH=str(tmp_path / "nowhere"))

    # Matched against the message's own wording, not against words that also
    # occur in the interpolated path: `content` is in pytest's tmp_path name
    # (derived from this test's own name) and `nowhere` is in the path passed
    # in, so the previous pattern passed even for an unrelated message.
    with pytest.raises(ValueError, match="no built content at"):
        steam_bundle.build_bundle(repo, env, tmp_path / "p.png")


def test_dependencies_come_from_the_asset_not_hardcoded_empty():
    # The interface promises "list[tuple[str, bool]]" — a fixture whose asset
    # always declares zero dependencies (as ASSET does above) cannot tell an
    # implementation that reads metadata.dependencies apart from one that just
    # returns []. disable-durability itself already depends on CoreLib and
    # ModSettingsMenu, so this is not a hypothetical case.
    asset = ASSET.replace(
        "    dependencies: []\n",
        "    dependencies:\n    - modName: CoreLib\n      required: 1\n    - modName: ModSettingsMenu\n      required: 0\n",
    )

    assert steam_bundle.parse_dependencies(asset) == [
        ("CoreLib", True),
        ("ModSettingsMenu", False),
    ]


def test_a_declared_dependency_is_resolved_from_the_cache(tmp_path):
    repo = _repo(
        tmp_path,
        asset=ASSET.replace(
            "    dependencies: []",
            "    dependencies:\n    - modName: CoreLib\n      required: 1",
        ),
    )
    cache = tmp_path / "deps.json"
    cache.write_text('{"CoreLib": 3000000001}')
    env = _env(tmp_path, STEAM_DEPS_MAP=str(cache))

    bundle = steam_bundle.build_bundle(repo, env, tmp_path / "p.png")

    assert bundle["dependencies"] == [
        {"name": "CoreLib", "fileId": 3000000001, "required": True}
    ]


def test_an_unresolvable_required_dependency_aborts(tmp_path):
    repo = _repo(
        tmp_path,
        asset=ASSET.replace(
            "    dependencies: []",
            "    dependencies:\n    - modName: CoreLib\n      required: 1",
        ),
    )
    cache = tmp_path / "deps.json"
    cache.write_text("{}")
    env = _env(tmp_path, STEAM_DEPS_MAP=str(cache))

    with pytest.raises(ValueError, match="CoreLib"):
        steam_bundle.build_bundle(repo, env, tmp_path / "p.png")


def test_an_unresolvable_required_dependency_with_no_cache_names_the_env_var(tmp_path):
    # Distinct from the case above: here STEAM_DEPS_MAP itself is unset, so
    # there is no cache_path to name. The message must say so instead of
    # rendering "None" as if it were a real, actionable file path.
    repo = _repo(
        tmp_path,
        asset=ASSET.replace(
            "    dependencies: []",
            "    dependencies:\n    - modName: CoreLib\n      required: 1",
        ),
    )
    env = _env(tmp_path)

    with pytest.raises(ValueError, match="STEAM_DEPS_MAP"):
        steam_bundle.build_bundle(repo, env, tmp_path / "p.png")


def test_an_unresolvable_optional_dependency_does_not_abort_the_publish(tmp_path):
    # Severity follows the .asset's own `required` flag: optional means the
    # publish goes ahead without it, where required aborts. What the resulting
    # dependency list should say is a separate question, asked below by
    # test_declared_but_unresolved_dependencies_are_not_reported_as_none — this
    # one used to assert [] there, which was the wipe.
    repo = _repo(
        tmp_path,
        asset=ASSET.replace(
            "    dependencies: []",
            "    dependencies:\n    - modName: SomeOptional\n      required: 0",
        ),
    )
    cache = tmp_path / "deps.json"
    cache.write_text("{}")
    env = _env(tmp_path, STEAM_DEPS_MAP=str(cache))

    bundle = steam_bundle.build_bundle(repo, env, tmp_path / "p.png")

    assert bundle["version"] == "1.1.1"


def test_the_optional_skip_warning_goes_to_stderr_not_stdout(tmp_path, capsys):
    # upload.sh captures the caller's whole stdout as the JSON bundle for the
    # .NET tool. A warning line printed to stdout ahead of that JSON would
    # corrupt the capture and fail the entire publish over a merely-skipped
    # dependency.
    repo = _repo(
        tmp_path,
        asset=ASSET.replace(
            "    dependencies: []",
            "    dependencies:\n    - modName: SomeOptional\n      required: 0",
        ),
    )
    cache = tmp_path / "deps.json"
    cache.write_text("{}")
    env = _env(tmp_path, STEAM_DEPS_MAP=str(cache))

    steam_bundle.build_bundle(repo, env, tmp_path / "p.png")

    out, err = capsys.readouterr()
    assert out == ""
    assert "SomeOptional" in err


def test_a_malformed_dependency_cache_is_reported_by_name(tmp_path):
    repo = _repo(
        tmp_path,
        asset=ASSET.replace(
            "    dependencies: []",
            "    dependencies:\n    - modName: CoreLib\n      required: 1",
        ),
    )
    cache = tmp_path / "deps.json"
    cache.write_text("not json")
    env = _env(tmp_path, STEAM_DEPS_MAP=str(cache))

    with pytest.raises(ValueError, match=r"deps\.json"):
        steam_bundle.build_bundle(repo, env, tmp_path / "p.png")


def test_a_non_numeric_cached_id_is_reported_by_mod_and_file(tmp_path):
    repo = _repo(
        tmp_path,
        asset=ASSET.replace(
            "    dependencies: []",
            "    dependencies:\n    - modName: CoreLib\n      required: 1",
        ),
    )
    cache = tmp_path / "deps.json"
    cache.write_text('{"CoreLib": "not-a-number"}')
    env = _env(tmp_path, STEAM_DEPS_MAP=str(cache))

    with pytest.raises(ValueError, match=r"CoreLib") as excinfo:
        steam_bundle.build_bundle(repo, env, tmp_path / "p.png")
    assert "deps.json" in str(excinfo.value)


def test_declared_dependencies_are_parsed_with_their_required_flag():
    deps = steam_bundle.parse_dependencies(
        "    dependencies:\n    - modName: CoreLib\n      required: 1\n"
        "    - modName: Other\n      required: 0\n  modPath: x\n"
    )

    assert deps == [("CoreLib", True), ("Other", False)]


def test_the_bundle_is_exactly_these_values(tmp_path):
    # The one test that pins the whole dict. Every other test here reads a
    # single key, which leaves the rest free to be wrong: a preview that is
    # never derived, a previewPath aimed at the 1024² logo, a description taken
    # from CHANGELOG.md, version and changelog swapped, or a contentPath at the
    # install ROOT — which would upload every mod in the family into one
    # Workshop item. All five survived the per-key tests; none survives this.
    repo = _repo(tmp_path)
    env = _env(tmp_path)
    preview = tmp_path / "preview.png"

    bundle = steam_bundle.build_bundle(repo, env, preview)

    assert bundle == {
        "fileId": 0,
        "title": "Disable Durability",
        "description": "[b]Bold[/b]",
        "tags": ["Item", "Overhaul", "Quality of Life", "Client", "Server", "Script"],
        "changelog": "### Added\n\n- A thing.\n- Another thing.",
        "version": "1.1.1",
        "contentPath": str(tmp_path / "build" / "DisableDurability"),
        "previewPath": str(preview),
        "visibility": "hidden",
        "dependencies": [],
    }
    # previewPath is a promise about a file, and the dict alone cannot tell a
    # derived preview from a path that was merely spelled correctly.
    assert preview.is_file(), "previewPath names a file that was never written"


def test_check_prerequisites_reports_a_missing_mod_name(tmp_path):
    with pytest.raises(ValueError, match="MOD_NAME"):
        steam_bundle.check_prerequisites(_repo(tmp_path), {})


def test_check_prerequisites_reports_a_missing_logo(tmp_path):
    # The logo is the only source the preview has. Missing, the publish would
    # get as far as deriving one and fail there — with the mod.io release for
    # this same run already out, which is exactly what the preflight prevents.
    repo = _repo(tmp_path)
    (repo / "unity" / "DisableDurability" / "Editor" / "logo.png").unlink()
    env = {"MOD_NAME": "DisableDurability", "CK_MODIO_TYPE": "Item"}

    with pytest.raises(ValueError, match="logo"):
        steam_bundle.check_prerequisites(repo, env)


def test_check_prerequisites_reports_a_missing_changelog(tmp_path):
    repo = _repo(tmp_path)
    (repo / "CHANGELOG.md").unlink()
    env = {"MOD_NAME": "DisableDurability", "CK_MODIO_TYPE": "Item"}

    with pytest.raises(ValueError, match="CHANGELOG.md"):
        steam_bundle.check_prerequisites(repo, env)


def test_check_prerequisites_reports_a_changelog_with_no_entry(tmp_path):
    # Distinct from the file being absent: it is there and unreadable as a
    # version. The preflight parses rather than merely stat-ing it, because the
    # version and the change note both come out of that parse — and until this
    # test, no test in the suite reached parse_changelog's own error at all.
    repo = _repo(tmp_path, changelog="# Changelog\n\nNothing released yet.\n")
    env = {"MOD_NAME": "DisableDurability", "CK_MODIO_TYPE": "Item"}

    with pytest.raises(ValueError, match=r"## \[x\.y\.z\]"):
        steam_bundle.check_prerequisites(repo, env)


def test_check_prerequisites_requires_a_mod_type(tmp_path):
    # On the normal path CLIPublishHelper aborts on an empty CK_MODIO_TYPE, but
    # --steam-only never runs it, and derive_tags turns an empty value into an
    # empty category list without a word. Steam then discards nothing, because
    # nothing was sent: the item goes up with no category tags at all.
    repo = _repo(tmp_path)

    with pytest.raises(ValueError, match="CK_MODIO_TYPE"):
        steam_bundle.check_prerequisites(repo, {"MOD_NAME": "DisableDurability"})


def test_a_mod_type_of_only_separators_is_refused(tmp_path):
    # "|" splits into empty parts that derive_tags drops, so a value can be
    # non-empty and still name no category. Checking for a set value would pass
    # this; the check has to be that a category actually comes out.
    repo = _repo(tmp_path)
    env = {"MOD_NAME": "DisableDurability", "CK_MODIO_TYPE": " | "}

    with pytest.raises(ValueError, match="CK_MODIO_TYPE"):
        steam_bundle.check_prerequisites(repo, env)


def test_no_declared_dependencies_means_sync_an_empty_list(tmp_path):
    # Nothing declared is a complete picture of "this mod has none", so the
    # full sync on the other side should run and remove anything stale.
    bundle = steam_bundle.build_bundle(
        _repo(tmp_path), _env(tmp_path), tmp_path / "p.png"
    )

    assert bundle["dependencies"] == []


def test_declared_but_unresolved_dependencies_are_not_reported_as_none(tmp_path):
    # The dangerous case. ck-workshop treats the list as authoritative and
    # removes every dependency not in it, then reports success — so an empty
    # list from "declared two, resolved neither" wipes the item's dependencies
    # while saying the publish went fine. null is the one value that means
    # "unknown": Program.cs early-returns on it and skips the sync entirely.
    repo = _repo(
        tmp_path,
        asset=ASSET.replace(
            "    dependencies: []",
            "    dependencies:\n    - modName: SomeOptional\n      required: 0",
        ),
    )
    cache = tmp_path / "deps.json"
    cache.write_text("{}")
    env = _env(tmp_path, STEAM_DEPS_MAP=str(cache))

    bundle = steam_bundle.build_bundle(repo, env, tmp_path / "p.png")

    assert bundle["dependencies"] is None


def test_a_partly_resolved_dependency_list_is_not_a_full_sync(tmp_path):
    # Same hazard one step subtler: CoreLib resolves, the other does not. The
    # list is now a floor rather than a picture, and syncing it would still
    # remove an item a human had attached for the entry that failed to resolve.
    # Sync only what is complete; the skipped entry has already been warned about.
    repo = _repo(
        tmp_path,
        asset=ASSET.replace(
            "    dependencies: []",
            "    dependencies:\n    - modName: CoreLib\n      required: 0"
            "\n    - modName: SomeOptional\n      required: 0",
        ),
    )
    cache = tmp_path / "deps.json"
    cache.write_text('{"CoreLib": 3000000001}')
    env = _env(tmp_path, STEAM_DEPS_MAP=str(cache))

    bundle = steam_bundle.build_bundle(repo, env, tmp_path / "p.png")

    assert bundle["dependencies"] is None


def test_the_optional_skip_warning_is_printed_once_per_run(tmp_path, capsys):
    # build_bundle calls check_prerequisites, and both used to resolve the
    # dependencies themselves, so one bundle printed the same warning twice.
    # A warning repeated without anything having happened in between reads as
    # two separate skips and teaches the operator to skim past it.
    repo = _repo(
        tmp_path,
        asset=ASSET.replace(
            "    dependencies: []",
            "    dependencies:\n    - modName: SomeOptional\n      required: 0",
        ),
    )
    cache = tmp_path / "deps.json"
    cache.write_text("{}")
    env = _env(tmp_path, STEAM_DEPS_MAP=str(cache))

    steam_bundle.build_bundle(repo, env, tmp_path / "p.png")

    assert capsys.readouterr().err.count("SomeOptional") == 1


def test_the_preflight_still_raises_on_the_first_missing_required_dependency(tmp_path):
    # The guard on the fix above: resolving once must not be achieved by having
    # check_prerequisites stop resolving. It is the preflight's job to refuse a
    # required dependency it cannot map, before the mod.io release goes out.
    repo = _repo(
        tmp_path,
        asset=ASSET.replace(
            "    dependencies: []",
            "    dependencies:\n    - modName: CoreLib\n      required: 1",
        ),
    )
    cache = tmp_path / "deps.json"
    cache.write_text("{}")
    env = {
        "MOD_NAME": "DisableDurability",
        "CK_MODIO_TYPE": "Item",
        "STEAM_DEPS_MAP": str(cache),
    }

    with pytest.raises(ValueError, match="CoreLib"):
        steam_bundle.check_prerequisites(repo, env)


def _real_mod_assets():
    """Every sibling mod repo's real ModBuilderSettings asset, as (name, text).

    Enumerated live from the mod repos rather than listed, for the reason
    test_new_mod_parity.py gives at length: a hardcoded roster of mods is the
    thing this repo has repeatedly found stale. `resolve_mods_dir()` is shared
    with the generator, so this finds the family from a worktree too.
    """
    found = []
    for git_entry in sorted(new_mod.resolve_mods_dir().glob("*/.git")):
        repo = git_entry.parent
        if repo.name == "CoreKeeperModSDK":
            continue
        for asset in sorted((repo / "unity").glob("*.asset")):
            text = asset.read_text()
            if "metadata:" in text:
                found.append((asset.stem, text))
    return found


REAL_ASSETS = _real_mod_assets()


@pytest.mark.skipif(
    not REAL_ASSETS,
    reason=(
        "no sibling mod repos beside this checkout, so the parsers were NOT "
        "measured against a real ModBuilderSettings asset"
    ),
)
def test_the_parsers_hold_against_every_real_mod_asset():
    """The fixture at the top of this file is one asset, frozen. This is all of
    them, as they are today.

    A regex over a whole YAML document is only as good as the documents it has
    met, and the fixture cannot grow a field while the real ones do: the Editor
    rewrites these files, and a mod added next month brings whatever it brings.
    So this asserts properties rather than values -- asserting the values would
    only restate the files -- and each property is one a parser reading the
    wrong key, or stopping early, would violate.
    """
    for name, text in REAL_ASSETS:
        metadata = steam_bundle._read_metadata(text)

        # The asset is named for its mod, so a `name` that is anything else was
        # read off a neighbouring key rather than out of `metadata:`.
        assert metadata.get("name") == name, (
            f"{name}: read name {metadata.get('name')!r}"
        )
        # It becomes the Workshop item's title, and an item titled
        # "skipSafetyChecks: 0" is what reading past an empty value looks like.
        assert metadata.get("displayName"), f"{name}: no displayName"
        assert ":" not in str(metadata["displayName"]), f"{name}: displayName ran on"
        # requiredOn drives the Application Type tags bitwise, and every mod in
        # the family gates at least one side.
        assert int(metadata.get("requiredOn", 0)) & 3, (
            f"{name}: requiredOn gates nothing"
        )

        # Counted independently of the parser: `modName:` appears nowhere else
        # in this schema, so that line count is what the parse must come to. A
        # regex that stopped after the first entry passes "did it find any" and
        # fails this.
        declared = steam_bundle.parse_dependencies(text)
        assert len(declared) == text.count("- modName:"), f"{name}: missed an entry"
        for dep_name, _ in declared:
            assert dep_name.isidentifier(), f"{name}: parsed {dep_name!r} as a mod name"
