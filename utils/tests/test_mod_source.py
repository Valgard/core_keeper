"""Unit tests for resolving a Core Keeper mod name to its source location."""

import dataclasses
import hashlib
import io
import json
import shutil
import urllib.parse
import zipfile
from pathlib import Path

import mod_source
import pytest


def test_normalise_is_casefold_and_alphanumeric():
    assert mod_source.normalise("Mod Settings Menu") == "modsettingsmenu"


def test_normalise_keeps_non_latin_titles_distinct():
    # An [^a-z0-9] filter collapses every Cyrillic title onto the empty key,
    # which is how three unrelated mods became one ambiguous entry.
    assert mod_source.normalise("БКК") != ""
    assert mod_source.normalise("Какауси") != ""
    assert mod_source.normalise("БКК") != mod_source.normalise("Какауси")


def test_normalise_empty_for_punctuation_only():
    assert mod_source.normalise("---") == ""
    assert mod_source.normalise("   ") == ""


def test_index_collects_origins_per_mod():
    index = mod_source.NameIndex()
    index.add("CoreLib", 3177992, mod_source.ORIGIN_INTERNAL)
    index.add("corelib", 3177992, mod_source.ORIGIN_SLUG)

    assert index.lookup("Core Lib") == {
        3177992: {mod_source.ORIGIN_INTERNAL, mod_source.ORIGIN_SLUG}
    }


def test_index_reports_every_mod_under_an_ambiguous_key():
    index = mod_source.NameIndex()
    index.add("Tool Resizer", 6041499, mod_source.ORIGIN_TITLE)
    index.add("ToolResizer", 4799620, mod_source.ORIGIN_TITLE)

    assert set(index.lookup("toolresizer")) == {6041499, 4799620}


def test_index_never_stores_an_empty_key():
    index = mod_source.NameIndex()
    index.add("---", 1, mod_source.ORIGIN_TITLE)

    assert index.lookup("---") == {}


def _installed_row(entry):
    """One _write_cache row, with the two optional name fields filled in.

    A row is (mod_id, modfile_id, internal_name, files) or, when a test needs
    the three names to DIFFER, (mod_id, modfile_id, internal_name, files,
    title, slug). The short form derives title and slug from the internal
    name, which is convenient and was also why ~30 installed-mod tests could
    not touch this tool's central case: NameChests ships as "More Labels" on
    mod.io, and a fixture whose three names all agree cannot tell an index
    that covers all three from one that indexes the internal name alone.
    """
    mod_id, modfile_id, name, files = entry[:4]
    title, slug = entry[4:6] if len(entry) > 4 else (name, name.lower())
    return mod_id, modfile_id, name, files, title, slug


def _write_cache(root, mods, state_disabled=()):
    """Build a synthetic mod.io cache: folders, manifests and state.json."""
    cache = root / "mods"
    cache.mkdir(parents=True)
    rows = [_installed_row(entry) for entry in mods]
    for mod_id, modfile_id, name, files, _, _ in rows:
        folder = cache / f"{mod_id}_{modfile_id}"
        (folder / "Scripts").mkdir(parents=True)
        (folder / "ModManifest.json").write_text(
            json.dumps({"name": name, "files": [{"path": p} for p in files]})
        )
    entries = {}
    for mod_id, modfile_id, _, _, title, slug in rows:
        entries[str(mod_id)] = {
            "currentModfile": {"id": modfile_id},
            "modObject": {"id": mod_id, "name": title, "name_id": slug},
        }
    (root / "state.json").write_text(
        json.dumps(
            {
                "mods": entries,
                "existingUsers": {
                    "u": {
                        "subscribedMods": [{"id": int(m)} for m in entries],
                        "disabledMods": list(state_disabled),
                    }
                },
            }
        )
    )
    return cache


def _write_repo(workspace, repo, mod_name, mod_id, fake_id=None):
    """Build a synthetic mod repository with asset and optional .envrc."""
    editor = workspace / repo / "unity" / mod_name / "Editor"
    editor.mkdir(parents=True)
    (editor / f"{mod_name}_modio.asset").write_text(
        f"MonoBehaviour:\n  m_Name: {mod_name}_modio\n  modId: {mod_id}\n"
    )
    (workspace / repo / "unity" / mod_name / f"{mod_name}Mod.cs").write_text("// mod")
    if fake_id is not None:
        (workspace / repo / ".envrc").write_text(f'export FAKE_MOD_ID="{fake_id}"\n')
    return workspace / repo


def test_reads_an_installed_mod_with_its_three_names(tmp_path):
    cache = _write_cache(tmp_path, [(3177992, 7845185, "CoreLib", ["Scripts/CoreLibMod.cs"])])

    mods, warnings = mod_source.read_installed(cache)

    assert warnings == []
    assert len(mods) == 1
    assert mods[0].mod_id == 3177992
    assert mods[0].internal_name == "CoreLib"
    assert mods[0].folder.name == "3177992_7845185"
    assert mods[0].source_files == ["Scripts/CoreLibMod.cs"]


def test_ignores_a_superseded_folder(tmp_path):
    # The cache keeps old folders; state.json names the live one. Taking the
    # higher modfile id is a guess that happens to work, but only by luck.
    # This fixture inverts the ids intentionally so the current folder carries
    # the lower id and the stale one the higher. "Highest id wins" would pick
    # the stale folder; reading state.json picks the right one.
    cache = _write_cache(tmp_path, [(3177992, 7710097, "CoreLib", ["Scripts/CoreLibMod.cs"])])
    stale = cache / "3177992_7845185"
    (stale / "Scripts").mkdir(parents=True)

    mods, _ = mod_source.read_installed(cache)

    assert [m.folder.name for m in mods] == ["3177992_7710097"]


def test_a_disabled_mod_is_still_found(tmp_path):
    cache = _write_cache(
        tmp_path,
        [(6065466, 8079348, "DisableDurability", ["Scripts/Mod.cs"])],
        state_disabled=["6065466"],
    )

    mods, _ = mod_source.read_installed(cache)

    assert len(mods) == 1
    assert mods[0].enabled is False


def test_truncated_state_json_warns_instead_of_crashing(tmp_path):
    # The running game rewrites state.json, so a read can land mid-write.
    cache = _write_cache(tmp_path, [(1, 2, "X", ["Scripts/X.cs"])])
    (tmp_path / "state.json").write_text('{"mods": {"1": {"curren')

    mods, warnings = mod_source.read_installed(cache)

    assert mods == []
    assert any("state.json" in w for w in warnings)


def test_missing_cache_directory_names_the_override(tmp_path):
    with pytest.raises(FileNotFoundError) as excinfo:
        mod_source.read_installed(tmp_path / "nope" / "mods")

    assert "CK_BOTTLE_PATH" in str(excinfo.value)


def test_bottle_path_uses_explicit_override_first(tmp_path, monkeypatch):
    # CK_BOTTLE_PATH wins outright; CK_BOTTLE_NAME is only checked if the
    # explicit override is not set.
    monkeypatch.setenv("CK_BOTTLE_PATH", str(tmp_path / "explicit"))
    monkeypatch.setenv("CK_BOTTLE_NAME", "Ignored")

    path = mod_source.bottle_path()

    assert path == tmp_path / "explicit"


def test_bottle_path_defaults_to_core_keeper_when_name_not_set(monkeypatch):
    # When CK_BOTTLE_PATH is not set and CK_BOTTLE_NAME is not set, the default
    # name "Core Keeper" is used.
    monkeypatch.delenv("CK_BOTTLE_PATH", raising=False)
    monkeypatch.delenv("CK_BOTTLE_NAME", raising=False)

    path = mod_source.bottle_path()

    assert path.name == "Core Keeper"


def test_reads_the_real_mod_id_from_the_tracked_asset(tmp_path):
    _write_repo(tmp_path, "faster-talents", "FasterTalents", 6065498)

    own = mod_source.read_own_mods(tmp_path)

    assert len(own) == 1
    assert own[0].mod_name == "FasterTalents"
    assert own[0].mod_id == 6065498
    assert own[0].fake_id is None
    assert own[0].source_path.name == "FasterTalents"


def test_reads_the_fake_id_when_the_envrc_is_present(tmp_path):
    _write_repo(tmp_path, "mod-settings-menu", "ModSettingsMenu", 6211950, fake_id=9999991)

    own = mod_source.read_own_mods(tmp_path)

    assert own[0].fake_id == 9999991


def test_a_directory_without_a_modio_asset_is_not_a_mod_repo(tmp_path):
    (tmp_path / "CoreKeeperModDocs" / "docs").mkdir(parents=True)

    assert mod_source.read_own_mods(tmp_path) == []


def test_an_unpublished_mod_id_of_zero_is_not_an_identity(tmp_path):
    # new_mod.py scaffolds `modId: 0`, so every unpublished mod carries one.
    # Treating 0 as an id would make two such repos collide on the same key.
    _write_repo(tmp_path, "brand-new-mod", "BrandNewMod", 0)

    own = mod_source.read_own_mods(tmp_path)

    assert len(own) == 1
    assert own[0].mod_id is None
    assert own[0].mod_name == "BrandNewMod"


def test_a_fake_id_below_the_threshold_is_rejected(tmp_path):
    # .envrc is gitignored and maintained by hand, so a typo or a copy-paste
    # error could put a real mod.io id there. Accepting such a value would
    # claim this workspace's repo as foreign mod, a silent wrong answer.
    # Only dev-build ids (>= FAKE_ID_MIN) are trusted; below-threshold values
    # are treated as absent.
    _write_repo(tmp_path, "faster-talents", "FasterTalents", 6065498, fake_id=6065466)

    own = mod_source.read_own_mods(tmp_path)

    assert len(own) == 1
    assert own[0].mod_id == 6065498
    assert own[0].fake_id is None


def test_reads_a_mirrored_catalogue(tmp_path):
    mirror = tmp_path / "catalogue.json"
    mirror.write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "id": 4584153,
                        "name": "General Mod Config Menu",
                        "name_id": "generalconfigmenu",
                        "modfile": 7840263,
                    }
                ]
            }
        )
    )

    entries = mod_source.read_catalogue(mirror)

    assert len(entries) == 1
    assert entries[0].mod_id == 4584153
    assert entries[0].slug == "generalconfigmenu"


def test_a_truncated_mirror_reads_as_absent(tmp_path):
    # An interrupted fetch leaves half a file. Failing every lookup until
    # someone deletes it by hand would be worse than fetching again.
    mirror = tmp_path / "catalogue.json"
    mirror.write_text('{"entries": [{"id": 458')

    assert mod_source.read_catalogue(mirror) == []


def test_a_missing_mirror_reads_as_empty(tmp_path):
    assert mod_source.read_catalogue(tmp_path / "nothing.json") == []


def test_cache_root_honours_the_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("CK_MOD_SOURCE_CACHE", str(tmp_path / "somewhere"))

    assert mod_source.cache_root() == tmp_path / "somewhere"


def test_fetch_catalogue_follows_pagination_to_the_last_page(tmp_path, monkeypatch):
    # The _limit/_offset loop is the one part of this module that never runs
    # against a real multi-page listing in this suite otherwise -- against the
    # live API the catalogue is 312 entries at a page size of 100, so it loops
    # four times in production and zero times if a test only ever hands back
    # one page. Two fake pages, with the first announcing a result_total the
    # first page alone does not cover, force the loop to run more than once.
    monkeypatch.setattr(
        mod_source, "_modio_config", lambda sdk_path: ("https://fake.modio", 1, "key")
    )

    page_one = {
        "data": [{"id": 1, "name": "Mod One", "name_id": "modone", "modfile": {"id": 10}}],
        "result_total": 2,
    }
    page_two = {
        "data": [{"id": 2, "name": "Mod Two", "name_id": "modtwo", "modfile": {"id": 20}}],
        "result_total": 2,
    }
    seen_offsets = []

    def fake_curl(url):
        offset = int(urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["_offset"][0])
        seen_offsets.append(offset)
        return json.dumps(page_two if offset else page_one).encode()

    monkeypatch.setattr(mod_source, "_curl", fake_curl)

    mirror = tmp_path / "catalogue.json"
    entries = mod_source.fetch_catalogue(tmp_path / "sdk", mirror)

    assert seen_offsets == [0, mod_source._PAGE]
    assert {e.mod_id for e in entries} == {1, 2}
    assert {e.modfile_id for e in entries} == {10, 20}

    mirrored = json.loads(mirror.read_text())
    assert [e["id"] for e in mirrored["entries"]] == [1, 2]


def test_a_catalogue_of_the_wrong_shape_reads_as_absent(tmp_path):
    # Valid JSON, wrong shape: "entries" is a list of ints rather than of
    # objects. Membership-testing "id in 1" raises TypeError -- a shape the
    # writer of this file never produces, but a damaged read of it could.
    mirror = tmp_path / "catalogue.json"
    mirror.write_text(json.dumps({"entries": [1, 2, 3]}))

    assert mod_source.read_catalogue(mirror) == []


def test_fetch_catalogue_gives_up_rather_than_looping_forever(tmp_path, monkeypatch):
    # A server that keeps sending a non-empty page while perpetually
    # reporting a result_total the running count never reaches must not hang
    # the tool forever -- it must fail loudly instead, within a bounded
    # number of requests.
    monkeypatch.setattr(
        mod_source, "_modio_config", lambda sdk_path: ("https://fake.modio", 1, "key")
    )
    calls: list[str] = []

    def fake_curl(url):
        calls.append(url)
        return json.dumps({"data": [{"id": len(calls)}], "result_total": 10**9}).encode()

    monkeypatch.setattr(mod_source, "_curl", fake_curl)

    mirror = tmp_path / "catalogue.json"
    with pytest.raises(ValueError, match="incomplete"):
        mod_source.fetch_catalogue(tmp_path / "sdk", mirror)

    assert len(calls) == mod_source._MAX_PAGES
    assert not mirror.exists()


def test_fetch_catalogue_tolerates_a_present_but_null_page(tmp_path, monkeypatch):
    # .get(key, default) only substitutes for an ABSENT key. A server that
    # sends the key with an explicit null -- a real API violation, but one a
    # network client cannot rule out -- used to raise TypeError from
    # "entries += None" / "len(entries) >= None" instead of reading as an
    # empty, complete page.
    monkeypatch.setattr(
        mod_source, "_modio_config", lambda sdk_path: ("https://fake.modio", 1, "key")
    )
    monkeypatch.setattr(
        mod_source,
        "_curl",
        lambda url: json.dumps({"data": None, "result_total": None}).encode(),
    )

    entries = mod_source.fetch_catalogue(tmp_path / "sdk", tmp_path / "catalogue.json")

    assert entries == []


def _catalogue_row(entry):
    """One mirrored catalogue entry: (id, title, slug, modfile) or + md5.

    The md5 is optional because most tests do not care what --download would
    check the bytes against, and a mirror written before this tool captured
    the field omits it entirely -- which must keep reading as "unknown"
    rather than as a damaged mirror.
    """
    mod_id, title, slug, modfile = entry[:4]
    md5 = entry[4] if len(entry) > 4 else ""
    return {
        "id": mod_id,
        "name": title,
        "name_id": slug,
        "modfile": modfile,
        "md5": md5,
    }


def _workspace(tmp_path, installed=(), own=(), catalogue=()):
    """Build a Workspace from synthetic sources, skipping any source unused by the test."""
    cache = _write_cache(tmp_path / "bottle", list(installed)) if installed else None
    repos = tmp_path / "repos"
    repos.mkdir(exist_ok=True)
    for repo, mod_name, mod_id, fake_id in own:
        _write_repo(repos, repo, mod_name, mod_id, fake_id)
    mirror = tmp_path / "catalogue.json"
    mirror.write_text(json.dumps({"entries": [_catalogue_row(entry) for entry in catalogue]}))
    return mod_source.Workspace.build(cache_dir=cache, workspace=repos, catalogue_path=mirror)


def test_an_own_mod_resolves_to_its_repository(tmp_path):
    ws = _workspace(
        tmp_path,
        installed=[(6211950, 7958010, "ModSettingsMenu", ["Scripts/M.cs"])],
        own=[("mod-settings-menu", "ModSettingsMenu", 6211950, 9999991)],
        catalogue=[(6211950, "Mod Settings Menu", "mod-settings-menu", 7958010)],
    )

    result = ws.resolve("Mod Settings Menu")

    assert result.kind == mod_source.KIND_OWN
    assert result.source_path.name == "ModSettingsMenu"
    assert result.internal_name == "ModSettingsMenu"


def test_a_dev_build_beside_its_subscription_is_one_mod(tmp_path):
    # Both cache entries map to the same repo, so this is two locations for
    # one mod -- not two candidates to choose between. If Workspace grouped
    # by raw mod id instead of by owning repo (dropping _group's owner-aware
    # key), this would come back as a two-candidate list instead of one
    # Resolution, and the isinstance check below would fail.
    ws = _workspace(
        tmp_path,
        installed=[
            (6065466, 8079348, "DisableDurability", ["Scripts/D.cs"]),
            (9999999, 1, "DisableDurability", ["Scripts/D.cs"]),
        ],
        own=[("disable-durability", "DisableDurability", 6065466, 9999999)],
    )

    result = ws.resolve("DisableDurability")

    assert isinstance(result, mod_source.Resolution)
    assert result.kind == mod_source.KIND_OWN
    assert any("dev build" in n for n in result.notes)


def test_two_distinct_mods_return_candidates(tmp_path):
    ws = _workspace(
        tmp_path,
        catalogue=[
            (6041499, "Tool Resizer", "tool-resizer", 1),
            (4799620, "ToolResizer", "toolresizer", 2),
        ],
    )

    result = ws.resolve("ToolResizer")

    assert isinstance(result, list)
    assert {r.mod_id for r in result} == {6041499, 4799620}


def test_a_foreign_fake_id_is_flagged_temporary(tmp_path):
    ws = _workspace(
        tmp_path,
        installed=[(9999986, 1, "GeneralConfigMenu", ["Scripts/G.cs"])],
    )

    result = ws.resolve("GeneralConfigMenu")

    assert result.kind == mod_source.KIND_PARKED
    assert any("temporary" in n.lower() for n in result.notes)


def test_a_catalogue_only_hit_is_provisional(tmp_path):
    ws = _workspace(
        tmp_path,
        catalogue=[(4584153, "General Mod Config Menu", "generalconfigmenu", 7840263)],
    )

    result = ws.resolve("General Mod Config Menu")

    assert result.kind == mod_source.KIND_CATALOGUE
    assert result.identity == mod_source.IDENTITY_UNCHECKED
    assert result.internal_name is None


def test_an_empty_query_is_refused(tmp_path):
    ws = _workspace(tmp_path)

    with pytest.raises(ValueError):
        ws.resolve("---")


def test_a_resolution_carries_the_modfile_id_from_the_catalogue(tmp_path):
    # modfile_id has no source of its own -- it is only ever copied out of a
    # matched CatalogueEntry. A Resolution built without reading `entry` here
    # would leave the field at its None default and this would fail.
    ws = _workspace(
        tmp_path,
        catalogue=[(4584153, "General Mod Config Menu", "generalconfigmenu", 7840263)],
    )

    result = ws.resolve("General Mod Config Menu")

    assert result.modfile_id == 7840263


def test_an_own_mod_with_no_catalogue_entry_has_no_modfile_id(tmp_path):
    # The own-mod branch also runs `entry.modfile_id if entry else None` --
    # this pins the "else None" half, which the catalogue-present test above
    # cannot exercise.
    ws = _workspace(
        tmp_path,
        own=[("faster-talents", "FasterTalents", 6065498, None)],
    )

    result = ws.resolve("FasterTalents")

    assert result.kind == mod_source.KIND_OWN
    assert result.modfile_id is None


def test_a_query_matching_nothing_raises_lookup_error(tmp_path):
    ws = _workspace(tmp_path, catalogue=[(1, "Some Mod", "somemod", 2)])

    with pytest.raises(LookupError):
        ws.resolve("NoSuchMod")


def test_an_unpublished_own_mod_is_still_findable_by_name(tmp_path):
    # new_mod.py scaffolds modId: 0 for every mod that has not shipped yet,
    # which read_own_mods maps to None; with no local dev build installed
    # either, this mod claims no id at all going into the index. That is the
    # state of every mod someone is actively developing, and read_own_mods's
    # own docstring already promises it: "They stay findable by name, which
    # is all the identity they have yet."
    ws = _workspace(
        tmp_path,
        own=[("brand-new-mod", "BrandNewMod", 0, None)],
    )

    result = ws.resolve("BrandNewMod")

    assert result.kind == mod_source.KIND_OWN
    assert result.mod_id is None


def test_an_ambiguous_own_mod_still_finds_its_own_catalogue_entry(tmp_path):
    # Regression: the candidates branch used to describe each candidate from
    # only the first id it happened to see in hits' dict-insertion order,
    # not from the id list `_group` had already collected for it. Here the
    # own mod's FAKE id is the one inserted first (it comes from the
    # installed loop, which runs before the own loop touches the real id)
    # while the catalogue entry -- carrying its OWN, different title, slug
    # and modfile_id -- is keyed by the REAL id. A single-id description of
    # this candidate can only ever see the dev build's own manifest, not the
    # catalogue entry, so it silently substitutes the dev build's internal
    # title/slug for the catalogue's and drops modfile_id outright, even
    # though the resolution is correctly grouped and correctly flagged as
    # KIND_OWN throughout. The catalogue title is deliberately spelled
    # differently from the dev build's manifest name so the three assertions
    # below cannot pass by coincidence -- a fixture where every name reads
    # "Widget" would let the buggy fallback produce the right-looking text
    # for the wrong reason.
    ws = _workspace(
        tmp_path,
        installed=[(9999500, 1, "Widget", ["Scripts/W.cs"])],
        own=[("widget-mod", "Widget", 5000000, 9999500)],
        catalogue=[
            (5000000, "Widget Deluxe Edition", "widget-deluxe-edition", 42),
            (7000001, "Widget", "widget", 99),
        ],
    )

    result = ws.resolve("Widget")

    assert isinstance(result, list)
    own_candidate = next(r for r in result if r.kind == mod_source.KIND_OWN)
    assert own_candidate.mod_id == 5000000
    assert own_candidate.title == "Widget Deluxe Edition"
    assert own_candidate.slug == "widget-deluxe-edition"
    assert own_candidate.modfile_id == 42


def test_two_unpublished_mods_in_one_repo_stay_distinct(tmp_path):
    # Regression: the synthetic id for an own mod with no real or fake id
    # used to be derived from the REPOSITORY path. read_own_mods yields one
    # entry per identity asset, and a repo can hold more than one mod
    # directory under unity/ -- so two unpublished mods (modId: 0, no dev
    # build) in the same repo derived the SAME synthetic id and silently
    # overwrote each other in owner_of and the index. Deriving it from each
    # mod's own source_path instead keeps them distinct.
    ws = _workspace(
        tmp_path,
        own=[
            ("multi-mod-repo", "ModAlpha", 0, None),
            ("multi-mod-repo", "ModBeta", 0, None),
        ],
    )

    alpha = ws.resolve("ModAlpha")
    beta = ws.resolve("ModBeta")

    assert alpha.kind == mod_source.KIND_OWN
    assert beta.kind == mod_source.KIND_OWN
    assert alpha.source_path.name == "ModAlpha"
    assert beta.source_path.name == "ModBeta"
    assert alpha.source_path != beta.source_path


def test_two_same_normalised_mods_in_one_repo_stay_separate_candidates(tmp_path):
    # Regression: _group used to key an own mod's candidate on owner.repo,
    # not owner.source_path. "ToolResizer" and "Tool-Resizer" both normalise
    # to "toolresizer", so a single query matches both -- and since they
    # share a repo, the old key merged their two ids into ONE group instead
    # of reporting a genuine two-way ambiguity. One of the two mods
    # disappeared from the result entirely.
    ws = _workspace(
        tmp_path,
        own=[
            ("multi-mod-repo", "ToolResizer", 0, None),
            ("multi-mod-repo", "Tool-Resizer", 0, None),
        ],
    )

    result = ws.resolve("ToolResizer")

    assert isinstance(result, list)
    assert len(result) == 2
    assert {r.source_path.name for r in result} == {"ToolResizer", "Tool-Resizer"}


def test_a_dev_build_still_collapses_with_its_subscription_after_source_path_keying(
    tmp_path,
):
    # The property _group exists for must survive the source_path-keyed fix
    # above: an own mod's real id and its dev-build fake id both resolve to
    # the SAME OwnMod object (see Workspace.__init__'s owner_of loop), so
    # they carry the identical source_path and must still collapse into one
    # group rather than being reported as two candidates. This is the same
    # scenario as test_a_dev_build_beside_its_subscription_is_one_mod, kept
    # here as a second, independent witness specifically for the source_path
    # key (that other test would also catch a full regression, but pins the
    # behaviour rather than the mechanism).
    ws = _workspace(
        tmp_path,
        installed=[
            (6065466, 8079348, "DisableDurability", ["Scripts/D.cs"]),
            (9999999, 1, "DisableDurability", ["Scripts/D.cs"]),
        ],
        own=[("disable-durability", "DisableDurability", 6065466, 9999999)],
    )

    result = ws.resolve("DisableDurability")

    assert isinstance(result, mod_source.Resolution)
    assert result.kind == mod_source.KIND_OWN


def test_file_mode_answers_an_installed_mod_from_the_manifest(tmp_path):
    ws = _workspace(
        tmp_path,
        installed=[
            (
                3177992,
                7845185,
                "CoreLib",
                [
                    "Scripts/Scripts/Util/Data/ConfigFile/ConfigScope.cs",
                    "Scripts/CoreLibMod.cs",
                ],
            )
        ],
    )
    result = ws.resolve("CoreLib")

    found = mod_source.find_file(result, "ConfigScope")

    # Assert the FULL path to catch a regressed join base (source_path instead of parent).
    # Manifest paths are relative to Scripts/, so ConfigScope.cs joins to source_path.parent.
    # Checking only found.parent.name is invariant to join-base errors (both produce ConfigFile
    # as the immediate parent), so pin the whole tail from a fixture-known anchor instead.
    assert found.name == "ConfigScope.cs"
    assert found.is_absolute()
    assert found.as_posix().endswith(
        "3177992_7845185/Scripts/Scripts/Util/Data/ConfigFile/ConfigScope.cs"
    )


def test_file_mode_returns_candidates_when_several_match(tmp_path):
    ws = _workspace(
        tmp_path,
        installed=[(1, 2, "X", ["Scripts/ConfigFile.cs", "Scripts/ConfigScope.cs"])],
    )
    result = ws.resolve("X")

    found = mod_source.find_file(result, "Config")

    assert isinstance(found, list)
    assert len(found) == 2
    assert all(isinstance(p, Path) for p in found)
    # Both branches of find_file promise an ABSOLUTE path (the docstring
    # says so for either count) -- the single-match branch called .resolve(),
    # the multi-match one did not, and nothing here used to catch that.
    assert all(p.is_absolute() for p in found)
    assert {p.name for p in found} == {"ConfigFile.cs", "ConfigScope.cs"}


def test_file_mode_walks_an_own_mods_repository(tmp_path):
    # An own mod resolves to its repo, and no repo contains a ModManifest.json
    # -- that file is build-generated.
    ws = _workspace(tmp_path, own=[("faster-talents", "FasterTalents", 6065498, None)])
    result = ws.resolve("FasterTalents")

    found = mod_source.find_file(result, "FasterTalentsMod")

    assert found.name == "FasterTalentsMod.cs"


def test_file_mode_raises_when_mod_not_installed(tmp_path):
    ws = _workspace(
        tmp_path,
        catalogue=[(4584153, "General Mod Config Menu", "generalconfigmenu", 7840263)],
    )
    result = ws.resolve("General Mod Config Menu")

    with pytest.raises(LookupError, match="not installed"):
        mod_source.find_file(result, "ConfigScope")


def test_file_mode_raises_when_no_file_matches(tmp_path):
    ws = _workspace(
        tmp_path,
        installed=[(3177992, 7845185, "CoreLib", ["Scripts/CoreLibMod.cs"])],
    )
    result = ws.resolve("CoreLib")

    with pytest.raises(LookupError, match="no .cs file matching"):
        mod_source.find_file(result, "NonExistentFile")


def test_download_verifies_the_manifest_name_against_the_query(tmp_path, monkeypatch):
    # The catalogue-only case: the hit is provisional because the internal name
    # is unknowable until the manifest arrives. Once it does, it either agrees
    # with the query or it does not, and silence would be the wrong answer.
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("ModManifest.json", json.dumps({"name": "SomethingElse"}))
        zf.writestr("Scripts/A.cs", "// code")

    monkeypatch.setattr(mod_source, "_modio_config", lambda p: ("https://x", 5289, "KEY"))
    monkeypatch.setattr(mod_source, "_curl", lambda url: archive.getvalue())

    resolution = mod_source.Resolution(
        kind=mod_source.KIND_CATALOGUE,
        mod_id=4584153,
        internal_name=None,
        title="General Mod Config Menu",
        slug="generalconfigmenu",
        source_path=None,
        identity=mod_source.IDENTITY_UNCHECKED,
    )

    path, warnings = mod_source.download(resolution, tmp_path / "sdk", tmp_path / "dl")

    assert (path / "Scripts" / "A.cs").is_file()
    assert any("SomethingElse" in w for w in warnings)
    # The point of the check: the mismatch is recorded on the RESOLUTION, not
    # only in the returned warnings. main() prints those warnings once to
    # stderr and drops them, while the resolution is what both renderers
    # carry and what a dispatched agent acts on. The pre-fix code set
    # `provisional = False` -- "identity confirmed" -- unconditionally and
    # ran the comparison afterwards, so this same download rendered as a
    # clean, settled answer with an empty notes list.
    assert resolution.internal_name == "SomethingElse"
    assert resolution.identity == mod_source.IDENTITY_CONTRADICTED
    assert any("SomethingElse" in note for note in resolution.notes)


def test_download_matches_via_the_slug_when_the_title_differs(tmp_path, monkeypatch):
    # The manifest name is checked against EITHER the queried title OR its
    # slug. An implementation that only compared against the title would warn
    # here even though the mod that arrived is unambiguously the right one --
    # title and slug diverge (as they routinely do), and only the slug agrees.
    #
    # This is also the suite's one fully clean download: the mirror knows the
    # md5, the bytes match it, and the name agrees. Asserting NO warnings at
    # all is only meaningful while that stays true -- if the hash were left
    # out of the fixture, the "could not be verified" warning would sit here
    # and the assertion would have to be weakened to a substring check.
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("ModManifest.json", json.dumps({"name": "GeneralConfigMenu"}))

    monkeypatch.setattr(mod_source, "_modio_config", lambda p: ("https://x", 5289, "KEY"))
    monkeypatch.setattr(mod_source, "_curl", lambda url: archive.getvalue())

    resolution = mod_source.Resolution(
        kind=mod_source.KIND_CATALOGUE,
        mod_id=4584153,
        internal_name=None,
        title="General Mod Config Menu",
        slug="generalconfigmenu",
        source_path=None,
        modfile_md5=hashlib.md5(archive.getvalue()).hexdigest(),
        identity=mod_source.IDENTITY_UNCHECKED,
    )

    _, warnings = mod_source.download(resolution, tmp_path / "sdk", tmp_path / "dl")

    assert warnings == []
    assert resolution.identity == mod_source.IDENTITY_CONFIRMED
    assert resolution.notes == []


def test_download_refuses_paths_outside_the_target(tmp_path, monkeypatch):
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../escaped.cs", "// nope")

    monkeypatch.setattr(mod_source, "_modio_config", lambda p: ("https://x", 5289, "KEY"))
    monkeypatch.setattr(mod_source, "_curl", lambda url: archive.getvalue())

    resolution = mod_source.Resolution(
        kind=mod_source.KIND_CATALOGUE,
        mod_id=1,
        internal_name=None,
        title="Evil",
        slug="evil",
        source_path=None,
        identity=mod_source.IDENTITY_UNCHECKED,
    )

    with pytest.raises(ValueError):
        mod_source.download(resolution, tmp_path / "sdk", tmp_path / "dl")

    assert not (tmp_path / "escaped.cs").exists()


def test_download_refuses_an_absolute_path_member(tmp_path, monkeypatch):
    # A relative "../" is one way to escape the target; a member that is
    # already absolute is another, and pathlib's own join rule makes it look
    # different internally -- `target / member` DISCARDS target outright when
    # member is absolute, rather than raising. The is_relative_to check must
    # still catch it, because the joined result is then just as reliably
    # outside `target` as the "../" case.
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("/etc/absolute.cs", "// nope")

    monkeypatch.setattr(mod_source, "_modio_config", lambda p: ("https://x", 5289, "KEY"))
    monkeypatch.setattr(mod_source, "_curl", lambda url: archive.getvalue())

    resolution = mod_source.Resolution(
        kind=mod_source.KIND_CATALOGUE,
        mod_id=1,
        internal_name=None,
        title="Evil",
        slug="evil",
        source_path=None,
        identity=mod_source.IDENTITY_UNCHECKED,
    )

    with pytest.raises(ValueError):
        mod_source.download(resolution, tmp_path / "sdk", tmp_path / "dl")

    assert not (tmp_path / "dl" / "etc" / "absolute.cs").exists()
    assert not Path("/etc/absolute.cs").exists()


def test_download_survives_the_call_with_no_cleanup(tmp_path, monkeypatch):
    # steam_backfill's download_release deletes its own scratch directory once
    # the bytes are re-uploaded -- it only ever needed the bytes. Here the
    # unpacked copy IS the answer, so nothing may remove it before an agent
    # gets a chance to read it. Checked as a directory listing rather than a
    # single file, so a wrong implementation that unpacks into a throwaway
    # temp dir and copies only ONE file back would still be caught.
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("ModManifest.json", json.dumps({"name": "Widget"}))
        zf.writestr("Scripts/A.cs", "// a")
        zf.writestr("Scripts/B.cs", "// b")

    monkeypatch.setattr(mod_source, "_modio_config", lambda p: ("https://x", 5289, "KEY"))
    monkeypatch.setattr(mod_source, "_curl", lambda url: archive.getvalue())

    resolution = mod_source.Resolution(
        kind=mod_source.KIND_CATALOGUE,
        mod_id=1,
        internal_name=None,
        title="Widget",
        slug="widget",
        source_path=None,
        identity=mod_source.IDENTITY_UNCHECKED,
    )

    path, _ = mod_source.download(resolution, tmp_path / "sdk", tmp_path / "dl")

    assert path.is_dir()
    assert sorted(p.name for p in (path / "Scripts").iterdir()) == ["A.cs", "B.cs"]


def test_download_survives_an_unparseable_manifest(tmp_path, monkeypatch):
    # Fix round 1, finding 1: the archive already unpacked successfully by the
    # time the manifest is read -- the files the caller asked for are on disk
    # and readable. A manifest that is not valid JSON must not throw that
    # success away; it can only mean the provisional-hit check itself cannot
    # run, which is a narrower failure than "the download failed".
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("ModManifest.json", "{not valid json")
        zf.writestr("Scripts/A.cs", "// code")

    monkeypatch.setattr(mod_source, "_modio_config", lambda p: ("https://x", 5289, "KEY"))
    monkeypatch.setattr(mod_source, "_curl", lambda url: archive.getvalue())

    resolution = mod_source.Resolution(
        kind=mod_source.KIND_CATALOGUE,
        mod_id=1,
        internal_name=None,
        title="Widget",
        slug="widget",
        source_path=None,
        identity=mod_source.IDENTITY_UNCHECKED,
    )

    path, warnings = mod_source.download(resolution, tmp_path / "sdk", tmp_path / "dl")

    assert (path / "Scripts" / "A.cs").is_file()
    assert any("could not" in w.lower() for w in warnings)
    # A name that could not be read is not evidence either way. The download
    # must neither settle the identity nor claim it was refuted -- those are
    # the two neighbouring states, and this is the one between them.
    assert resolution.identity == mod_source.IDENTITY_UNCONFIRMABLE


def test_download_survives_a_manifest_that_is_not_an_object(tmp_path, monkeypatch):
    # Valid JSON, wrong shape: a top-level list has no .get(), the same class
    # of defect read_catalogue already guards against for the mirrored file.
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("ModManifest.json", json.dumps(["not", "an", "object"]))

    monkeypatch.setattr(mod_source, "_modio_config", lambda p: ("https://x", 5289, "KEY"))
    monkeypatch.setattr(mod_source, "_curl", lambda url: archive.getvalue())

    resolution = mod_source.Resolution(
        kind=mod_source.KIND_CATALOGUE,
        mod_id=1,
        internal_name=None,
        title="Widget",
        slug="widget",
        source_path=None,
        identity=mod_source.IDENTITY_UNCHECKED,
    )

    path, warnings = mod_source.download(resolution, tmp_path / "sdk", tmp_path / "dl")

    assert path.is_dir()
    assert any("could not" in w.lower() for w in warnings)
    assert resolution.identity == mod_source.IDENTITY_UNCONFIRMABLE


def test_download_survives_a_null_manifest_name(tmp_path, monkeypatch):
    # "name": null parses fine and .get("name", "") returns None (the key IS
    # present, so the default never applies) -- a naive fix that mutates
    # resolution before checking the type would leave internal_name set to
    # None while recording the identity as settled, even though nothing was
    # actually verified. Asserting the identity stays UNCONFIRMABLE catches
    # exactly that half-applied mutation, not just the crash.
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("ModManifest.json", json.dumps({"name": None}))

    monkeypatch.setattr(mod_source, "_modio_config", lambda p: ("https://x", 5289, "KEY"))
    monkeypatch.setattr(mod_source, "_curl", lambda url: archive.getvalue())

    resolution = mod_source.Resolution(
        kind=mod_source.KIND_CATALOGUE,
        mod_id=1,
        internal_name=None,
        title="Widget",
        slug="widget",
        source_path=None,
        identity=mod_source.IDENTITY_UNCHECKED,
    )

    path, warnings = mod_source.download(resolution, tmp_path / "sdk", tmp_path / "dl")

    assert path.is_dir()
    assert any("could not" in w.lower() for w in warnings)
    assert resolution.identity == mod_source.IDENTITY_UNCONFIRMABLE
    assert resolution.internal_name is None


def test_download_leaves_no_directory_behind_when_rejected(tmp_path, monkeypatch):
    # Fix round 1, finding 2: mkdir used to run before the archive was opened
    # or validated, so a traversal rejection left an empty `into` directory on
    # disk -- litter in the cache that the next run could mistake for a
    # completed download. The directory must only appear once every member is
    # known-safe.
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../escaped.cs", "// nope")

    monkeypatch.setattr(mod_source, "_modio_config", lambda p: ("https://x", 5289, "KEY"))
    monkeypatch.setattr(mod_source, "_curl", lambda url: archive.getvalue())

    resolution = mod_source.Resolution(
        kind=mod_source.KIND_CATALOGUE,
        mod_id=1,
        internal_name=None,
        title="Evil",
        slug="evil",
        source_path=None,
        identity=mod_source.IDENTITY_UNCHECKED,
    )

    with pytest.raises(ValueError):
        mod_source.download(resolution, tmp_path / "sdk", tmp_path / "dl")

    assert not (tmp_path / "dl").exists()


# ---------------------------------------------------------------------------
# render / render_json / main
# ---------------------------------------------------------------------------


def test_render_names_every_known_name_and_an_absolute_path(tmp_path):
    ws = _workspace(
        tmp_path,
        installed=[(3177992, 7845185, "CoreLib", ["Scripts/CoreLibMod.cs"])],
    )
    text = mod_source.render(ws.resolve("CoreLib"))

    assert "CoreLib" in text
    assert "3177992" in text
    assert str(tmp_path) in text
    assert "1 .cs" in text or "1 source file" in text


def test_render_says_when_the_internal_name_is_unknown(tmp_path):
    ws = _workspace(tmp_path, catalogue=[(4584153, "General Mod Config Menu", "gcm", 7840263)])
    text = mod_source.render(ws.resolve("General Mod Config Menu"))

    # Specifically the INTERNAL name. Searching the whole render for the word
    # passes on any line that happens to carry it -- the slug or the title
    # could be the unknown one, or a note could merely use the word -- so it
    # would stay green even if the field this test is named for were filled
    # in with something. _names_line renders the field as "internal <value>".
    names = next(line for line in text.splitlines() if "Names" in line)
    assert "internal unknown" in names


def test_render_reports_an_own_mods_file_count_by_walking_its_directory(tmp_path):
    # An own mod carries no manifest -- ModManifest.json is build-generated,
    # per read_own_mods's own docstring -- so source_files is always empty for
    # KIND_OWN and the .cs count can only come from walking the repository.
    # _write_repo creates exactly one .cs file (<mod_name>Mod.cs), so "1 .cs
    # file" is right only if that walk actually ran; an implementation that
    # only ever reads source_files would print no Size line at all here.
    ws = _workspace(tmp_path, own=[("faster-talents", "FasterTalents", 6065498, None)])

    text = mod_source.render(ws.resolve("FasterTalents"))

    assert "own mod" in text.lower()
    assert "1 .cs file" in text


def test_render_states_an_asset_only_installed_mod_ships_no_source(tmp_path):
    # _write_cache always creates a Scripts/ directory; removing it after the
    # fact is what makes this a genuine asset-only install (ships_source
    # False), the case the design's failure-mode table names explicitly.
    ws = _workspace(tmp_path, installed=[(1, 2, "AssetPack", [])])
    (tmp_path / "bottle" / "mods" / "1_2" / "Scripts").rmdir()

    text = mod_source.render(ws.resolve("AssetPack"))

    assert "no source shipped" in text.lower()
    assert "ships no scripts" in text.lower()


def test_json_output_is_machine_readable(tmp_path):
    ws = _workspace(tmp_path, installed=[(1, 2, "X", ["Scripts/X.cs"])])
    payload = json.loads(mod_source.render_json(ws.resolve("X")))

    assert payload["mod_id"] == 1
    assert payload["kind"] == mod_source.KIND_INSTALLED


def test_json_output_stringifies_the_source_path(tmp_path):
    # dataclasses.asdict alone leaves source_path as a Path object, which
    # json.dumps cannot encode -- parsing the result at all is half the
    # check, the other half is that the string still names the right,
    # absolute folder rather than e.g. repr()'d Path("...").
    ws = _workspace(tmp_path, installed=[(1, 2, "X", ["Scripts/X.cs"])])

    payload = json.loads(mod_source.render_json(ws.resolve("X")))

    assert payload["source_path"] == str(tmp_path / "bottle" / "mods" / "1_2" / "Scripts")


def _write_bottle(tmp_path, mods=()):
    """A synthetic CrossOver bottle at the path main() expects to find one.

    _installed_mods_dir() appends drive_c/users/Public/mod.io/5289/mods to
    bottle_path()'s result -- the same suffix utils/server.sh's own
    MODIO_CACHE uses -- so building the cache there with the existing
    _write_cache helper, then handing back the bottle root, is enough for
    monkeypatch.setattr(mod_source, "bottle_path", lambda: <this>) to make
    main() see it.
    """
    bottle = tmp_path / "bottle"
    _write_cache(bottle / "drive_c/users/Public/mod.io/5289", list(mods))
    return bottle


def _write_main_catalogue(tmp_path, entries=()):
    """The catalogue mirror at the one path main() reads it from by default."""
    mirror = tmp_path / "cache" / "catalogue.json"
    mirror.parent.mkdir(parents=True, exist_ok=True)
    mirror.write_text(json.dumps({"entries": [_catalogue_row(entry) for entry in entries]}))
    return mirror


def test_main_exits_non_zero_on_ambiguity(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("CK_MOD_SOURCE_CACHE", str(tmp_path / "cache"))
    _write_main_catalogue(
        tmp_path,
        [
            (1, "Tool Resizer", "tool-resizer", 1),
            (2, "ToolResizer", "toolresizer", 2),
        ],
    )
    # An empty but EXISTING cache directory, not a missing bottle_path: the
    # subject here is ambiguity, and read_installed raises FileNotFoundError
    # for a missing cache directory by design (that path has its own test,
    # test_main_exits_one_when_the_bottle_path_does_not_exist below) -- a
    # nonexistent bottle here would fail for the wrong reason and never reach
    # the ambiguity this test is meant to exercise.
    bottle = _write_bottle(tmp_path)
    monkeypatch.setattr(mod_source, "bottle_path", lambda: bottle)

    code = mod_source.main(["ToolResizer", "--workspace", str(tmp_path)])

    assert code != 0
    assert "Tool Resizer" in capsys.readouterr().out


def test_main_resolves_a_single_installed_mod_and_prints_source(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("CK_MOD_SOURCE_CACHE", str(tmp_path / "cache"))
    _write_main_catalogue(tmp_path)
    bottle = _write_bottle(tmp_path, [(3177992, 7845185, "CoreLib", ["Scripts/CoreLibMod.cs"])])
    monkeypatch.setattr(mod_source, "bottle_path", lambda: bottle)

    code = mod_source.main(["CoreLib", "--workspace", str(tmp_path)])

    out = capsys.readouterr().out
    assert code == 0
    assert "3177992_7845185" in out
    assert "CoreLib" in out


def test_main_exits_one_on_a_lookup_error(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("CK_MOD_SOURCE_CACHE", str(tmp_path / "cache"))
    _write_main_catalogue(tmp_path)
    bottle = _write_bottle(tmp_path)
    monkeypatch.setattr(mod_source, "bottle_path", lambda: bottle)

    code = mod_source.main(["NoSuchMod", "--workspace", str(tmp_path)])

    assert code == 1
    assert "NoSuchMod" in capsys.readouterr().err


def test_main_exits_one_when_the_bottle_path_does_not_exist(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("CK_MOD_SOURCE_CACHE", str(tmp_path / "cache"))
    _write_main_catalogue(tmp_path)
    monkeypatch.setattr(mod_source, "bottle_path", lambda: tmp_path / "no-such-bottle")

    code = mod_source.main(["CoreLib", "--workspace", str(tmp_path)])

    assert code == 1
    assert "CK_BOTTLE_PATH" in capsys.readouterr().err


def test_main_file_argument_prints_the_resolved_absolute_path(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("CK_MOD_SOURCE_CACHE", str(tmp_path / "cache"))
    _write_main_catalogue(tmp_path)
    bottle = _write_bottle(
        tmp_path, [(3177992, 7845185, "CoreLib", ["Scripts/Util/ConfigScope.cs"])]
    )
    monkeypatch.setattr(mod_source, "bottle_path", lambda: bottle)

    code = mod_source.main(["CoreLib", "ConfigScope", "--workspace", str(tmp_path)])

    out = capsys.readouterr().out.strip()
    assert code == 0
    # Pinned whole, against the fixture's own known root, for the same reason
    # test_file_mode_answers_an_installed_mod_from_the_manifest is: a tail
    # check cannot see a regressed join base. Manifest paths are relative to
    # the mod FOLDER, so the right answer ends
    # .../3177992_7845185/Scripts/Util/ConfigScope.cs, while joining onto
    # source_path (that folder's own Scripts/) ends
    # .../3177992_7845185/Scripts/Scripts/Util/ConfigScope.cs -- and an
    # endswith on the last three segments is satisfied by both. That defect
    # was fixed at the unit layer and left uncaught here.
    assert out == str(
        bottle
        / "drive_c/users/Public/mod.io/5289/mods/3177992_7845185"
        / "Scripts/Util/ConfigScope.cs"
    )
    assert Path(out).is_absolute()


def test_main_file_argument_exits_one_when_nothing_matches(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("CK_MOD_SOURCE_CACHE", str(tmp_path / "cache"))
    _write_main_catalogue(tmp_path)
    bottle = _write_bottle(tmp_path, [(1, 2, "X", ["Scripts/X.cs"])])
    monkeypatch.setattr(mod_source, "bottle_path", lambda: bottle)

    code = mod_source.main(["X", "NoSuchFile", "--workspace", str(tmp_path)])

    assert code == 1
    assert "NoSuchFile" in capsys.readouterr().err


def test_main_json_flag_emits_parseable_json_for_a_single_resolution(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("CK_MOD_SOURCE_CACHE", str(tmp_path / "cache"))
    _write_main_catalogue(tmp_path)
    bottle = _write_bottle(tmp_path, [(1, 2, "X", ["Scripts/X.cs"])])
    monkeypatch.setattr(mod_source, "bottle_path", lambda: bottle)

    code = mod_source.main(["X", "--json", "--workspace", str(tmp_path)])

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["mod_id"] == 1
    assert isinstance(payload["source_path"], str)


def test_main_warns_and_proceeds_when_the_mirror_is_missing_and_sdk_path_is_unset(
    tmp_path, capsys, monkeypatch
):
    # The design's own failure-mode table: "catalogue fetch fails, or
    # SDK_PATH is unset -> proceed with cache and repos only, warn". No
    # catalogue.json is written here on purpose -- that absence, combined
    # with no SDK_PATH, is exactly the case this test targets, and an
    # installed mod must still resolve despite it.
    monkeypatch.setenv("CK_MOD_SOURCE_CACHE", str(tmp_path / "cache"))
    monkeypatch.delenv("SDK_PATH", raising=False)
    bottle = _write_bottle(tmp_path, [(1, 2, "X", ["Scripts/X.cs"])])
    monkeypatch.setattr(mod_source, "bottle_path", lambda: bottle)

    code = mod_source.main(["X", "--workspace", str(tmp_path)])

    captured = capsys.readouterr()
    assert code == 0
    assert "SDK_PATH" in captured.err
    assert "X" in captured.out


def test_main_download_flag_fetches_an_uninstalled_mod(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("CK_MOD_SOURCE_CACHE", str(tmp_path / "cache"))
    monkeypatch.setenv("SDK_PATH", str(tmp_path / "sdk"))
    _write_main_catalogue(
        tmp_path, [(4584153, "General Mod Config Menu", "generalconfigmenu", 7840263)]
    )
    bottle = _write_bottle(tmp_path)
    monkeypatch.setattr(mod_source, "bottle_path", lambda: bottle)

    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("ModManifest.json", json.dumps({"name": "GeneralModConfigMenu"}))
        zf.writestr("Scripts/Menu.cs", "// code")
    monkeypatch.setattr(mod_source, "_modio_config", lambda p: ("https://x", 5289, "KEY"))
    monkeypatch.setattr(mod_source, "_curl", lambda url: archive.getvalue())

    code = mod_source.main(["General Mod Config Menu", "--download", "--workspace", str(tmp_path)])

    out = capsys.readouterr().out
    assert code == 0
    # The manifest name verifies cleanly against the query, so this is a
    # settled, downloaded-this-run mod -- neither "not installed" (it now is)
    # nor "installed" (nothing was already there; THIS run fetched it). The
    # pre-fix code selected the phrase on the identity flag alone, which a
    # verified download sets to confirmed -- landing on "installed, source
    # available" here, indistinguishable from a mod that had been sitting
    # installed all along. Asserting the exact phrase catches that;
    # "not installed" not in out could not, since "installed, ..." also
    # satisfies it.
    assert "downloaded, source available" in out
    downloaded = tmp_path / "cache" / "downloads" / "4584153_7840263" / "Scripts" / "Menu.cs"
    assert downloaded.is_file()
    assert str(downloaded.parent) in out


def test_main_download_flag_flags_an_unconfirmed_identity(tmp_path, capsys, monkeypatch):
    # The other half of the same branch: the archive's manifest cannot settle
    # the identity check (unparseable JSON here, same as
    # test_download_survives_an_unparseable_manifest), so the identity stays
    # UNCONFIRMABLE. The output must say BOTH facts -- that this run
    # downloaded the mod, and that its identity could not be confirmed --
    # rather than collapsing onto whichever single phrase one flag would pick.
    monkeypatch.setenv("CK_MOD_SOURCE_CACHE", str(tmp_path / "cache"))
    monkeypatch.setenv("SDK_PATH", str(tmp_path / "sdk"))
    _write_main_catalogue(
        tmp_path, [(4584153, "General Mod Config Menu", "generalconfigmenu", 7840263)]
    )
    bottle = _write_bottle(tmp_path)
    monkeypatch.setattr(mod_source, "bottle_path", lambda: bottle)

    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("ModManifest.json", "{not valid json")
        zf.writestr("Scripts/Menu.cs", "// code")
    monkeypatch.setattr(mod_source, "_modio_config", lambda p: ("https://x", 5289, "KEY"))
    monkeypatch.setattr(mod_source, "_curl", lambda url: archive.getvalue())

    code = mod_source.main(["General Mod Config Menu", "--download", "--workspace", str(tmp_path)])

    out = capsys.readouterr().out
    assert code == 0
    assert "downloaded, identity unconfirmed, source available" in out


# ---------------------------------------------------------------------------
# Fix round 1
# ---------------------------------------------------------------------------


def test_main_resolves_a_relative_workspace_to_an_absolute_source_path(
    tmp_path, capsys, monkeypatch
):
    # Finding 1: an own mod's Source line is derived from args.workspace, so
    # a relative --workspace used to flow straight through to it -- a path an
    # agent cannot paste into a dispatch prompt unchanged (AC2), since it
    # would resolve against whatever directory that agent happens to start
    # in, or not at all.
    monkeypatch.setenv("CK_MOD_SOURCE_CACHE", str(tmp_path / "cache"))
    _write_main_catalogue(tmp_path)
    bottle = _write_bottle(tmp_path)
    monkeypatch.setattr(mod_source, "bottle_path", lambda: bottle)
    _write_repo(tmp_path, "faster-talents", "FasterTalents", 6065498)
    monkeypatch.chdir(tmp_path)

    code = mod_source.main(["FasterTalents", "--workspace", "."])

    out = capsys.readouterr().out
    assert code == 0
    source_line = next(line for line in out.splitlines() if "Source" in line)
    printed_path = source_line.split(None, 1)[1].strip()
    assert Path(printed_path).is_absolute()


def test_download_raises_a_value_error_for_a_corrupt_archive(tmp_path, monkeypatch):
    # Finding 2: zipfile.BadZipFile is neither a ValueError nor an OSError --
    # main()'s download branch only catches those two, so an uncaught
    # BadZipFile from a truncated or corrupted response would have escaped as
    # a raw traceback instead of "error: download failed (...)". download()
    # re-raises it as ValueError so every caller gets one uniform error type.
    monkeypatch.setattr(mod_source, "_modio_config", lambda p: ("https://x", 5289, "KEY"))
    monkeypatch.setattr(mod_source, "_curl", lambda url: b"not a zip file at all")

    resolution = mod_source.Resolution(
        kind=mod_source.KIND_CATALOGUE,
        mod_id=1,
        internal_name=None,
        title="Widget",
        slug="widget",
        source_path=None,
        identity=mod_source.IDENTITY_UNCHECKED,
    )

    with pytest.raises(ValueError):
        mod_source.download(resolution, tmp_path / "sdk", tmp_path / "dl")


def test_main_json_flag_on_ambiguity_emits_only_json(tmp_path, capsys, monkeypatch):
    # Finding 3: the file-ambiguity branch already gates its "N files match"
    # preamble to the non-json case; the mod-ambiguity branch printed its own
    # preamble unconditionally, which is exactly the case a machine consumer
    # of --json most needs to parse cleanly. json.loads on the FULL captured
    # stdout fails outright if any text precedes the array.
    monkeypatch.setenv("CK_MOD_SOURCE_CACHE", str(tmp_path / "cache"))
    _write_main_catalogue(
        tmp_path,
        [
            (1, "Tool Resizer", "tool-resizer", 1),
            (2, "ToolResizer", "toolresizer", 2),
        ],
    )
    bottle = _write_bottle(tmp_path)
    monkeypatch.setattr(mod_source, "bottle_path", lambda: bottle)

    code = mod_source.main(["ToolResizer", "--json", "--workspace", str(tmp_path)])

    payload = json.loads(capsys.readouterr().out)
    assert code == 2
    assert {entry["mod_id"] for entry in payload} == {1, 2}


def test_render_json_includes_an_own_mods_walked_cs_files(tmp_path):
    # Finding 4: render_json's docstring claims "the same facts as render()",
    # but asdict() alone left source_files at [] for KIND_OWN (no manifest to
    # have populated it from) while render() prints a nonzero .cs count for
    # the same resolution via a directory walk. Pin the walked result itself,
    # not just its length, so a fix that only patches the count elsewhere
    # (e.g. adds a separate "source_count" field) still fails this.
    ws = _workspace(tmp_path, own=[("faster-talents", "FasterTalents", 6065498, None)])

    payload = json.loads(mod_source.render_json(ws.resolve("FasterTalents")))

    assert payload["source_files"] == ["FasterTalentsMod.cs"]


# ---------------------------------------------------------------------------
# Final whole-branch review fixes
# ---------------------------------------------------------------------------


def test_default_workspace_resolves_a_worktree_to_the_main_checkout(tmp_path, monkeypatch):
    # Important 1: from inside a git worktree, `git rev-parse
    # --git-common-dir` answers with the MAIN checkout's .git directory, not
    # a worktree-private one -- that is the one directory every worktree of a
    # repository shares. Its parent is the main checkout, which is where the
    # sibling mod repos this default is FOR actually live; a worktree itself
    # never contains them (separate git repos, excluded by the parent
    # .gitignore, never checked out into a worktree). Pre-fix, this exact
    # shape -- _default_workspace() falling back to __file__'s own directory
    # -- is what made read_own_mods() find nothing from a worktree and report
    # this workspace's own dev builds as foreign mods parked locally.
    main_checkout = tmp_path / "core_keeper"
    (main_checkout / ".git").mkdir(parents=True)
    monkeypatch.setattr(mod_source, "_git_common_dir", lambda start: str(main_checkout / ".git"))

    assert mod_source._default_workspace() == main_checkout


def test_default_workspace_falls_back_when_git_cannot_answer(monkeypatch):
    # Important 1's explicit requirement: no git binary, not a repository, a
    # timeout -- all of these reach _git_common_dir() returning None, and
    # this tool must keep resolving mods without git exactly as it always
    # could, rather than crashing on argparse construction.
    monkeypatch.setattr(mod_source, "_git_common_dir", lambda start: None)

    assert mod_source._default_workspace() == Path(mod_source.__file__).resolve().parent.parent


def test_default_workspace_falls_back_when_the_answer_is_not_a_git_dir(tmp_path, monkeypatch):
    # Important 1's other explicit requirement: git answers, but with
    # something that does not look like a real .git directory (wrong name
    # here; a nonexistent path is the other half of the same check). Trusting
    # it blindly could point the default at an arbitrary directory instead of
    # falling back safely.
    not_a_git_dir = tmp_path / "somewhere-else"
    not_a_git_dir.mkdir()
    monkeypatch.setattr(mod_source, "_git_common_dir", lambda start: str(not_a_git_dir))

    assert mod_source._default_workspace() == Path(mod_source.__file__).resolve().parent.parent


def test_main_warns_with_the_weaker_fallback_when_the_mirror_already_exists(
    tmp_path, capsys, monkeypatch
):
    # Minor 2: "proceeding with the cache and repos only, a mod that is not
    # installed cannot be resolved" is false when a mirror already exists --
    # Workspace.build reads catalogue_path regardless of whether the refresh
    # attempted here succeeds, so the existing (possibly stale) mirror is
    # still used and an uninstalled mod still resolves through it. --refresh
    # forces this branch to run even though the mirror is present, and
    # SDK_PATH being unset makes it fail immediately -- exactly the case
    # where the old wording overclaimed.
    monkeypatch.setenv("CK_MOD_SOURCE_CACHE", str(tmp_path / "cache"))
    monkeypatch.delenv("SDK_PATH", raising=False)
    _write_main_catalogue(
        tmp_path, [(4584153, "General Mod Config Menu", "generalconfigmenu", 7840263)]
    )
    bottle = _write_bottle(tmp_path)
    monkeypatch.setattr(mod_source, "bottle_path", lambda: bottle)

    code = mod_source.main(["General Mod Config Menu", "--refresh", "--workspace", str(tmp_path)])

    captured = capsys.readouterr()
    assert code == 0
    assert "proceeding with the mirror as it stands" in captured.err
    assert "cannot be resolved" not in captured.err


# ---------------------------------------------------------------------------
# Review gate fixes
# ---------------------------------------------------------------------------


def _catalogue_resolution(**overrides):
    """A catalogue-only resolution, the one shape download() accepts.

    Only the fields a test actually varies are worth spelling out at each
    call site; everything else is the state Workspace._describe produces for
    a hit that exists in the mirror and nowhere else.
    """
    fields = {
        "kind": mod_source.KIND_CATALOGUE,
        "mod_id": 4584153,
        "internal_name": None,
        "title": "General Mod Config Menu",
        "slug": "generalconfigmenu",
        "source_path": None,
        "modfile_id": 7840263,
        "identity": mod_source.IDENTITY_UNCHECKED,
    }
    fields.update(overrides)
    return mod_source.Resolution(**fields)


def _archive(members):
    """A zip archive as bytes, built from {member path: content}."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        for name, content in members.items():
            zf.writestr(name, content)
    return buffer.getvalue()


def test_a_contradicted_identity_reaches_both_renderers(tmp_path, monkeypatch):
    # THE critical one. download() detects that the archive is a different
    # mod, and that finding has to survive into what a dispatched agent is
    # handed -- which is the resolution, not the warning list main() prints
    # once to stderr and drops. Pre-fix, `provisional = False` was set
    # unconditionally one line before the comparison ran, so render() printed
    # "downloaded, source available" with no notes at all and render_json()
    # emitted "provisional": false with "notes": [] -- a clean bill of health
    # for a download the tool had already proved wrong.
    payload = _archive(
        {
            "ModManifest.json": json.dumps({"name": "SomethingElse"}),
            "Scripts/A.cs": "// code",
        }
    )
    monkeypatch.setattr(mod_source, "_modio_config", lambda p: ("https://x", 5289, "KEY"))
    monkeypatch.setattr(mod_source, "_curl", lambda url: payload)
    resolution = _catalogue_resolution(
        modfile_md5=hashlib.md5(payload).hexdigest(),
    )

    target, _ = mod_source.download(resolution, tmp_path / "sdk", tmp_path / "dl")

    # main() does exactly this much after a download; do it here so render()
    # sees the same resolution the CLI would hand it.
    resolution.source_path = target / "Scripts"
    resolution.downloaded = True

    text = mod_source.render(resolution)
    assert "identity mismatch" in text
    assert "SomethingElse" in text

    payload_json = json.loads(mod_source.render_json(resolution))
    assert payload_json["identity"] == mod_source.IDENTITY_CONTRADICTED
    assert any("SomethingElse" in note for note in payload_json["notes"])


def test_main_download_renders_a_name_mismatch_in_both_output_modes(tmp_path, capsys, monkeypatch):
    # The same defect at the layer that matters: this is the exact command a
    # session runs before dispatching an agent, and its whole output used to
    # read as a settled answer. Both output modes are checked, because a
    # caller reading --json never sees stderr at all.
    payload = _archive(
        {
            "ModManifest.json": json.dumps({"name": "SomethingElse"}),
            "Scripts/Menu.cs": "// code",
        }
    )
    monkeypatch.setenv("CK_MOD_SOURCE_CACHE", str(tmp_path / "cache"))
    monkeypatch.setenv("SDK_PATH", str(tmp_path / "sdk"))
    _write_main_catalogue(
        tmp_path,
        [
            (
                4584153,
                "General Mod Config Menu",
                "generalconfigmenu",
                7840263,
                hashlib.md5(payload).hexdigest(),
            )
        ],
    )
    bottle = _write_bottle(tmp_path)
    monkeypatch.setattr(mod_source, "bottle_path", lambda: bottle)
    monkeypatch.setattr(mod_source, "_modio_config", lambda p: ("https://x", 5289, "KEY"))
    monkeypatch.setattr(mod_source, "_curl", lambda url: payload)

    code = mod_source.main(["General Mod Config Menu", "--download", "--workspace", str(tmp_path)])

    human = capsys.readouterr().out
    assert code == 2
    assert "downloaded, identity mismatch, source available" in human
    assert "SomethingElse" in human

    code = mod_source.main(
        [
            "General Mod Config Menu",
            "--download",
            "--json",
            "--workspace",
            str(tmp_path),
        ]
    )

    machine = json.loads(capsys.readouterr().out)
    assert code == 2
    assert machine["identity"] == mod_source.IDENTITY_CONTRADICTED
    assert any("SomethingElse" in note for note in machine["notes"])


def test_the_not_installed_note_is_dropped_without_dropping_the_mismatch(
    tmp_path, capsys, monkeypatch
):
    # main() strips the stale "not installed" note after a download. It used
    # to strip any note CONTAINING that phrase, which was harmless while
    # download() wrote nothing into notes -- and would silently swallow the
    # mismatch note now that it does, if that note ever phrased itself with
    # those words. Both halves are asserted together: the stale note gone,
    # the new one still there.
    payload = _archive(
        {
            "ModManifest.json": json.dumps({"name": "SomethingElse"}),
            "Scripts/Menu.cs": "// code",
        }
    )
    monkeypatch.setenv("CK_MOD_SOURCE_CACHE", str(tmp_path / "cache"))
    monkeypatch.setenv("SDK_PATH", str(tmp_path / "sdk"))
    _write_main_catalogue(
        tmp_path,
        [(4584153, "General Mod Config Menu", "generalconfigmenu", 7840263)],
    )
    bottle = _write_bottle(tmp_path)
    monkeypatch.setattr(mod_source, "bottle_path", lambda: bottle)
    monkeypatch.setattr(mod_source, "_modio_config", lambda p: ("https://x", 5289, "KEY"))
    monkeypatch.setattr(mod_source, "_curl", lambda url: payload)

    code = mod_source.main(
        [
            "General Mod Config Menu",
            "--download",
            "--json",
            "--workspace",
            str(tmp_path),
        ]
    )

    machine = json.loads(capsys.readouterr().out)
    assert code == 2
    assert not any(note.startswith("not installed") for note in machine["notes"])
    assert any("SomethingElse" in note for note in machine["notes"])


def test_download_verifies_the_archive_against_the_catalogues_md5(tmp_path, monkeypatch):
    # The check the design mandates twice and the module did not have: an
    # archive whose bytes are not what mod.io says they are is not this mod's
    # source, whatever it happens to unpack into, so it is not unpacked at
    # all. Nothing may be left on disk either -- the next run would find the
    # directory and take it for a completed download.
    monkeypatch.setattr(mod_source, "_modio_config", lambda p: ("https://x", 5289, "KEY"))
    monkeypatch.setattr(
        mod_source,
        "_curl",
        lambda url: _archive({"ModManifest.json": json.dumps({"name": "Widget"})}),
    )
    resolution = _catalogue_resolution(modfile_md5="0" * 32)

    with pytest.raises(ValueError, match="md5"):
        mod_source.download(resolution, tmp_path / "sdk", tmp_path / "dl")

    assert not (tmp_path / "dl").exists()


def test_download_says_when_it_cannot_verify_the_bytes(tmp_path, monkeypatch):
    # A mirror written before this tool captured the hash, or an entry mod.io
    # sends without one, cannot be checked. That is not an error -- an old
    # mirror resolves names exactly as well as a new one, and forcing a
    # refetch to download anything would be worse. But it must not pass in
    # silence: "verified" and "unverifiable" are different answers, and the
    # note is what carries the difference into the payload.
    payload = _archive({"ModManifest.json": json.dumps({"name": "GeneralConfigMenu"})})
    monkeypatch.setattr(mod_source, "_modio_config", lambda p: ("https://x", 5289, "KEY"))
    monkeypatch.setattr(mod_source, "_curl", lambda url: payload)
    resolution = _catalogue_resolution(modfile_md5="")

    target, warnings = mod_source.download(resolution, tmp_path / "sdk", tmp_path / "dl")

    assert target.is_dir()
    assert any("no md5" in w for w in warnings)
    assert any("no md5" in note for note in resolution.notes)
    # The bytes being uncheckable says nothing about the NAME, which was
    # checked and agreed -- the two verdicts are independent.
    assert resolution.identity == mod_source.IDENTITY_CONFIRMED


def test_download_refuses_a_resolution_it_is_not_for(tmp_path):
    # Every line after the guard assumes a catalogue-only hit with no source
    # of its own: called on an own mod, this would unpack a foreign archive
    # straight over a repository in this workspace. One `if` in main() is
    # what used to stand between those two facts.
    own = _catalogue_resolution(
        kind=mod_source.KIND_OWN,
        internal_name="FasterTalents",
        source_path=tmp_path / "repo",
    )
    with pytest.raises(ValueError, match="catalogue-only"):
        mod_source.download(own, tmp_path / "sdk", tmp_path / "dl")

    already_fetched = _catalogue_resolution(source_path=tmp_path / "somewhere")
    with pytest.raises(ValueError, match="catalogue-only"):
        mod_source.download(already_fetched, tmp_path / "sdk", tmp_path / "dl")


def test_fetch_catalogue_captures_each_modfiles_md5(tmp_path, monkeypatch):
    monkeypatch.setattr(
        mod_source, "_modio_config", lambda sdk_path: ("https://fake.modio", 1, "key")
    )
    monkeypatch.setattr(
        mod_source,
        "_curl",
        lambda url: json.dumps(
            {
                "data": [
                    {
                        "id": 1,
                        "name": "Mod One",
                        "name_id": "modone",
                        "modfile": {"id": 10, "filehash": {"md5": "a" * 32}},
                    },
                    # A mod with no published build: mod.io sends `modfile`
                    # as null, and steam_backfill reads the same field
                    # through the same two `or {}` guards for that reason.
                    {"id": 2, "name": "Mod Two", "name_id": "modtwo", "modfile": None},
                ],
                "result_total": 2,
            }
        ).encode(),
    )

    entries = mod_source.fetch_catalogue(tmp_path / "sdk", tmp_path / "catalogue.json")

    assert {e.mod_id: e.md5 for e in entries} == {1: "a" * 32, 2: ""}


def test_a_mirror_written_before_md5_was_captured_still_reads(tmp_path):
    # Schema change, not a schema break: the field is simply absent from an
    # older mirror. Reading that as damaged would discard a perfectly good
    # catalogue and force a refetch for a field no lookup needs.
    mirror = tmp_path / "catalogue.json"
    mirror.write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "id": 4584153,
                        "name": "General Mod Config Menu",
                        "name_id": "generalconfigmenu",
                        "modfile": 7840263,
                    }
                ]
            }
        )
    )

    entries = mod_source.read_catalogue(mirror)

    assert len(entries) == 1
    assert entries[0].md5 == ""


def test_a_resolution_carries_the_modfile_md5_from_the_catalogue(tmp_path):
    # The hash has to travel the same route modfile_id does, or download()
    # can never check anything: the mirror is the only place it exists.
    ws = _workspace(
        tmp_path,
        catalogue=[(4584153, "General Mod Config Menu", "generalconfigmenu", 7840263, "b" * 32)],
    )

    result = ws.resolve("General Mod Config Menu")

    assert result.modfile_md5 == "b" * 32


def test_fetch_catalogue_refuses_an_early_empty_page(tmp_path, monkeypatch):
    # The function's own docstring promised it raises rather than mirroring a
    # short catalogue, and only the never-ending-page case was guarded. A
    # server that reports 9 mods and then sends an empty page used to break
    # out of the loop and write the one entry it had -- after which every
    # missing mod reads as "that mod does not exist", which is the one answer
    # this tool must never give.
    monkeypatch.setattr(
        mod_source, "_modio_config", lambda sdk_path: ("https://fake.modio", 1, "key")
    )

    def fake_curl(url):
        offset = int(urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["_offset"][0])
        page = (
            {"data": [], "result_total": 9}
            if offset
            else {
                "data": [{"id": 1, "name": "Mod One", "name_id": "modone", "modfile": None}],
                "result_total": 9,
            }
        )
        return json.dumps(page).encode()

    monkeypatch.setattr(mod_source, "_curl", fake_curl)

    mirror = tmp_path / "catalogue.json"
    with pytest.raises(ValueError, match="empty page"):
        mod_source.fetch_catalogue(tmp_path / "sdk", mirror)

    assert not mirror.exists()


def test_two_mod_directories_claiming_one_id_are_reported_not_merged(tmp_path):
    # Copying a repo is how a mod gets started here, and a <Mod>_modio.asset
    # that was never reset leaves both copies claiming one mod.io id. The id
    # then mapped to whichever directory the loop reached last, so a query
    # for ModAlpha answered with ModBeta's path AND ModBeta's name -- a
    # confident wrong answer, not an ambiguity report. A contested id
    # identifies neither mod, so each stays findable under its own name.
    ws = _workspace(
        tmp_path,
        own=[
            ("mod-alpha", "ModAlpha", 6065498, None),
            ("mod-beta", "ModBeta", 6065498, None),
        ],
    )

    assert any("6065498" in w for w in ws.warnings)
    assert any("ModAlpha" in w and "ModBeta" in w for w in ws.warnings)

    alpha = ws.resolve("ModAlpha")
    beta = ws.resolve("ModBeta")

    assert alpha.source_path.name == "ModAlpha"
    assert alpha.internal_name == "ModAlpha"
    assert beta.source_path.name == "ModBeta"
    assert beta.internal_name == "ModBeta"


def test_a_shared_dev_build_id_is_contested_the_same_way(tmp_path):
    # FAKE_MOD_ID lives in a hand-maintained .envrc, so the same copy-paste
    # produces the same collision there. Nothing about the id's origin makes
    # one of the two claimants the right answer.
    ws = _workspace(
        tmp_path,
        own=[
            ("mod-alpha", "ModAlpha", 0, 9999991),
            ("mod-beta", "ModBeta", 0, 9999991),
        ],
    )

    assert any("9999991" in w for w in ws.warnings)
    assert ws.resolve("ModAlpha").source_path.name == "ModAlpha"
    assert ws.resolve("ModBeta").source_path.name == "ModBeta"


def test_a_current_folder_without_a_manifest_is_reported(tmp_path):
    # The state the design's own failure table describes, and the one the
    # superseded CoreLib folder was in. Dropping it without a word makes the
    # mod read as "not installed" when the truth is "installed, but its
    # identity cannot be read" -- a wrong answer standing in for a missing
    # one. The folder still exists, which is what tells this case apart from
    # a subscription that has simply not been downloaded yet.
    cache = _write_cache(tmp_path, [(3177992, 7845185, "CoreLib", ["Scripts/C.cs"])])
    (cache / "3177992_7845185" / "ModManifest.json").unlink()

    mods, warnings = mod_source.read_installed(cache)

    assert mods == []
    assert any("3177992_7845185" in w and "ModManifest.json" in w for w in warnings)


def test_a_subscribed_but_undownloaded_mod_stays_silent(tmp_path):
    # The other half of the same branch: state.json lists every subscribed
    # mod, including ones whose folder does not exist yet. Warning about
    # those would put a line of noise on every ordinary run, which is how a
    # warning channel stops being read.
    cache = _write_cache(tmp_path, [(3177992, 7845185, "CoreLib", ["Scripts/C.cs"])])
    shutil.rmtree(cache / "3177992_7845185")

    mods, warnings = mod_source.read_installed(cache)

    assert mods == []
    assert warnings == []


_THREE_NAMES = (
    7146470,
    8100000,
    "NameChests",
    ["Scripts/NameChestsMod.cs"],
    "More Labels",
    "chest-labels",
)


def _three_name_workspace(tmp_path):
    """One installed mod whose internal name, title and slug all differ.

    NameChests ships as "More Labels" on mod.io, and every installed-mod test
    in this suite used to derive title and slug FROM the internal name -- so
    all three keys were one string, and the index could have covered the
    internal name alone without a single test noticing.

    The guard below is not decoration. The first version of this fixture used
    the mod's real slug, "more-labels", which normalises to "morelabels" --
    the same key as the title "More Labels", since normalise() strips the
    hyphen and casefolds. The title and slug tests were then one test wearing
    two names: either could be deleted without turning anything red. A
    fixture meant to prove three name spaces are indexed has to be checked
    for producing three keys, because it can look right and discriminate
    nothing.
    """
    internal, title, slug = _THREE_NAMES[2], _THREE_NAMES[4], _THREE_NAMES[5]
    assert len({mod_source.normalise(n) for n in (internal, title, slug)}) == 3, (
        "the fixture's three names must normalise apart, or these tests overlap"
    )
    return _workspace(tmp_path, installed=[_THREE_NAMES])


def test_an_installed_mod_resolves_by_its_internal_name(tmp_path):
    # The name the mod calls itself, readable only from its ModManifest.json.
    ws = _three_name_workspace(tmp_path)

    result = ws.resolve("NameChests")

    assert result.mod_id == 7146470
    assert result.internal_name == "NameChests"
    assert result.title == "More Labels"
    assert result.slug == "chest-labels"


def test_an_installed_mod_resolves_by_its_modio_title(tmp_path):
    # The tool's opening example, and the one a human actually types: the
    # title is the only one of the three names shown in the game's mod menu
    # or on the mod.io page.
    ws = _three_name_workspace(tmp_path)

    result = ws.resolve("More Labels")

    assert result.mod_id == 7146470
    assert result.internal_name == "NameChests"
    assert result.source_path.name == "Scripts"


def test_an_installed_mod_resolves_by_its_slug(tmp_path):
    # The third name space, which is what a mod.io URL carries -- so it is
    # what gets pasted from a browser.
    ws = _three_name_workspace(tmp_path)

    result = ws.resolve("chest-labels")

    assert result.mod_id == 7146470
    assert result.internal_name == "NameChests"


def test_render_tells_an_uninstalled_mod_how_to_obtain_it(tmp_path):
    # AC1 asks the report to name the way to obtain a mod that is not
    # installed, and nothing pinned the clause that does it -- deleting it
    # left all 78 tests green. An agent handed a Source line that says only
    # "not installed" has nothing to act on.
    ws = _workspace(
        tmp_path,
        catalogue=[(4584153, "General Mod Config Menu", "generalconfigmenu", 7840263)],
    )

    text = mod_source.render(ws.resolve("General Mod Config Menu"))

    source = next(line for line in text.splitlines() if "Source" in line)
    assert "--download" in source


def test_status_phrase_refuses_a_kind_it_does_not_know(tmp_path):
    # A silent "installed" used to sit at the end of that chain, which is
    # plausible for any input and therefore the wrong default: it would
    # report an unknown kind, and a catalogue hit that acquired a source_path
    # without a download, as an ordinary installed mod.
    source = tmp_path / "somewhere"
    source.mkdir()
    resolution = _catalogue_resolution(kind="something-new", source_path=source)

    with pytest.raises(ValueError, match="something-new"):
        mod_source._status_phrase(resolution)


def test_display_name_falls_back_to_the_mod_id_but_not_past_it(tmp_path):
    # The mod-id fallback is reachable: an installed mod whose manifest name
    # and whose state.json profile name are both empty has neither name and
    # always has an id. What sat below it -- a fixed "(unpublished mod)" for
    # an own mod with no id -- was not: an own mod's internal name is its own
    # directory name, so that case returns one check earlier. Verified by
    # building the exact scenario the docstring named.
    nameless = mod_source.Resolution(
        kind=mod_source.KIND_INSTALLED,
        mod_id=77,
        internal_name="",
        title="",
        slug="",
        source_path=None,
    )
    assert mod_source._display_name(nameless) == "mod 77"

    unpublished = _workspace(tmp_path, own=[("brand-new-mod", "BrandNewMod", 0, None)]).resolve(
        "BrandNewMod"
    )
    assert unpublished.mod_id is None
    assert mod_source._display_name(unpublished) == "BrandNewMod"

    with pytest.raises(ValueError, match="cannot be named"):
        mod_source._display_name(dataclasses.replace(nameless, mod_id=None))


# ---------------------------------------------------------------------------
# Re-review residuals
# ---------------------------------------------------------------------------


def test_a_contested_id_is_admitted_in_the_resolution_itself(tmp_path):
    # The Critical's shape, a second time and smaller: the wrong-mod hit is
    # gone, but the surviving answer still printed the contested id as this
    # mod's own with an empty notes list, and the only trace was a stderr
    # warning main() prints and drops. A dispatched agent reads the payload,
    # so what the tool knows has to be in the payload.
    ws = _workspace(
        tmp_path,
        own=[
            ("mod-alpha", "ModAlpha", 6065498, None),
            ("mod-beta", "ModBeta", 6065498, None),
        ],
    )

    alpha = ws.resolve("ModAlpha")

    assert alpha.mod_id == 6065498
    assert any("6065498" in note and "ModBeta" in note for note in alpha.notes)
    # Both renderers, because they are two different readers of one fact.
    assert "6065498" in mod_source.render(alpha)
    payload = json.loads(mod_source.render_json(alpha))
    assert any("ModBeta" in note for note in payload["notes"])


def test_a_contested_dev_build_id_is_admitted_too(tmp_path):
    # The note is attached per claimed id, not once per mod, so the fake id
    # has to carry it as well -- an own mod can have a clean real id and a
    # dev-build id that a sibling repo's .envrc duplicates.
    ws = _workspace(
        tmp_path,
        own=[
            ("mod-alpha", "ModAlpha", 6065498, 9999991),
            ("mod-beta", "ModBeta", 6211950, 9999991),
        ],
    )

    alpha = ws.resolve("ModAlpha")

    assert alpha.mod_id == 6065498
    assert any("9999991" in note and "ModBeta" in note for note in alpha.notes)


def test_an_uncontested_own_mod_says_nothing_about_ids(tmp_path):
    # The negative control: the note must appear because an id IS contested,
    # not on every own mod. A note that is always there says nothing.
    ws = _workspace(tmp_path, own=[("faster-talents", "FasterTalents", 6065498, None)])

    result = ws.resolve("FasterTalents")

    assert result.notes == []


def test_main_exits_two_on_a_refuted_identity(tmp_path, capsys, monkeypatch):
    # Sven's decision: exit 2, the same code an ambiguous query returns,
    # because both mean "resolved, but a human has to decide". This is the
    # channel that reaches a caller which never parses the payload -- a shell
    # step in a dispatch -- and it must stop rather than carry on with a mod
    # proved to be the wrong one.
    payload = _archive(
        {
            "ModManifest.json": json.dumps({"name": "SomethingElse"}),
            "Scripts/Menu.cs": "// code",
        }
    )
    monkeypatch.setenv("CK_MOD_SOURCE_CACHE", str(tmp_path / "cache"))
    monkeypatch.setenv("SDK_PATH", str(tmp_path / "sdk"))
    _write_main_catalogue(
        tmp_path,
        [(4584153, "General Mod Config Menu", "generalconfigmenu", 7840263)],
    )
    bottle = _write_bottle(tmp_path)
    monkeypatch.setattr(mod_source, "bottle_path", lambda: bottle)
    monkeypatch.setattr(mod_source, "_modio_config", lambda p: ("https://x", 5289, "KEY"))
    monkeypatch.setattr(mod_source, "_curl", lambda url: payload)

    code = mod_source.main(["General Mod Config Menu", "--download", "--workspace", str(tmp_path)])

    assert code == 2
    assert "identity mismatch" in capsys.readouterr().out

    # File mode too, and for the same reason: a path into the wrong mod is
    # the most expensive thing this tool can hand over, so it must not be the
    # one branch that still reports success.
    code = mod_source.main(
        ["General Mod Config Menu", "Menu", "--download", "--workspace", str(tmp_path)]
    )

    assert code == 2
    assert capsys.readouterr().out.strip().endswith("Menu.cs")


def test_main_exits_zero_when_the_download_verifies(tmp_path, capsys, monkeypatch):
    # The control for the code above: the same command on a mod whose
    # manifest agrees must still be a plain success, or the exit code stops
    # distinguishing anything.
    payload = _archive(
        {
            "ModManifest.json": json.dumps({"name": "GeneralConfigMenu"}),
            "Scripts/Menu.cs": "// code",
        }
    )
    monkeypatch.setenv("CK_MOD_SOURCE_CACHE", str(tmp_path / "cache"))
    monkeypatch.setenv("SDK_PATH", str(tmp_path / "sdk"))
    _write_main_catalogue(
        tmp_path,
        [(4584153, "General Mod Config Menu", "generalconfigmenu", 7840263)],
    )
    bottle = _write_bottle(tmp_path)
    monkeypatch.setattr(mod_source, "bottle_path", lambda: bottle)
    monkeypatch.setattr(mod_source, "_modio_config", lambda p: ("https://x", 5289, "KEY"))
    monkeypatch.setattr(mod_source, "_curl", lambda url: payload)

    code = mod_source.main(["General Mod Config Menu", "--download", "--workspace", str(tmp_path)])

    assert code == 0
    assert "downloaded, source available" in capsys.readouterr().out


def test_main_does_not_resolve_a_default_workspace_it_was_given(tmp_path, capsys, monkeypatch):
    # _default_workspace() shells out to git. As argparse's own `default=` it
    # was evaluated at add_argument time, so that subprocess ran on every
    # single invocation -- including the ones that pass --workspace and never
    # look at the answer. Recording the calls rather than asserting on timing
    # is what makes this checkable at all.
    calls = []
    monkeypatch.setattr(
        mod_source,
        "_default_workspace",
        lambda: calls.append(1) or tmp_path,
    )
    monkeypatch.setenv("CK_MOD_SOURCE_CACHE", str(tmp_path / "cache"))
    _write_main_catalogue(tmp_path)
    bottle = _write_bottle(tmp_path, [(1, 2, "X", ["Scripts/X.cs"])])
    monkeypatch.setattr(mod_source, "bottle_path", lambda: bottle)

    code = mod_source.main(["X", "--workspace", str(tmp_path)])

    assert code == 0
    assert calls == []


def test_main_still_resolves_a_default_workspace_when_none_is_given(tmp_path, capsys, monkeypatch):
    # The other half: made lazy, not removed. Without --workspace the default
    # must still be computed, or every unqualified run stops finding this
    # repository's own mods -- which is the defect the git resolution was
    # added to fix in the first place.
    calls = []
    monkeypatch.setattr(
        mod_source,
        "_default_workspace",
        lambda: calls.append(1) or tmp_path,
    )
    monkeypatch.setenv("CK_MOD_SOURCE_CACHE", str(tmp_path / "cache"))
    _write_main_catalogue(tmp_path)
    bottle = _write_bottle(tmp_path)
    monkeypatch.setattr(mod_source, "bottle_path", lambda: bottle)
    _write_repo(tmp_path, "faster-talents", "FasterTalents", 6065498)

    code = mod_source.main(["FasterTalents"])

    assert code == 0
    assert calls == [1]
    assert "FasterTalents" in capsys.readouterr().out
