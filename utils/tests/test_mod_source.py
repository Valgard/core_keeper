"""Unit tests for resolving a Core Keeper mod name to its source location."""

import json
import urllib.parse

import pytest

import mod_source


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


def _write_cache(root, mods, state_mods=None, state_disabled=()):
    """Build a synthetic mod.io cache: folders, manifests and state.json."""
    cache = root / "mods"
    cache.mkdir(parents=True)
    for mod_id, modfile_id, name, files in mods:
        folder = cache / f"{mod_id}_{modfile_id}"
        (folder / "Scripts").mkdir(parents=True)
        (folder / "ModManifest.json").write_text(
            json.dumps({"name": name, "files": [{"path": p} for p in files]})
        )
    entries = {}
    for mod_id, modfile_id, name, _ in state_mods or mods:
        entries[str(mod_id)] = {
            "currentModfile": {"id": modfile_id},
            "modObject": {"id": mod_id, "name": name, "name_id": name.lower()},
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
    cache = _write_cache(
        tmp_path, [(3177992, 7845185, "CoreLib", ["Scripts/CoreLibMod.cs"])]
    )

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
    cache = _write_cache(
        tmp_path, [(3177992, 7710097, "CoreLib", ["Scripts/CoreLibMod.cs"])]
    )
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
    _write_repo(
        tmp_path, "mod-settings-menu", "ModSettingsMenu", 6211950, fake_id=9999991
    )

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
        "data": [
            {"id": 1, "name": "Mod One", "name_id": "modone", "modfile": {"id": 10}}
        ],
        "result_total": 2,
    }
    page_two = {
        "data": [
            {"id": 2, "name": "Mod Two", "name_id": "modtwo", "modfile": {"id": 20}}
        ],
        "result_total": 2,
    }
    seen_offsets = []

    def fake_curl(url):
        offset = int(
            urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["_offset"][0]
        )
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
        return json.dumps(
            {"data": [{"id": len(calls)}], "result_total": 10**9}
        ).encode()

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


def _workspace(tmp_path, installed=(), own=(), catalogue=()):
    """Build a Workspace from synthetic sources, skipping any source unused by the test."""
    cache = _write_cache(tmp_path / "bottle", list(installed)) if installed else None
    repos = tmp_path / "repos"
    repos.mkdir(exist_ok=True)
    for repo, mod_name, mod_id, fake_id in own:
        _write_repo(repos, repo, mod_name, mod_id, fake_id)
    mirror = tmp_path / "catalogue.json"
    mirror.write_text(
        json.dumps(
            {
                "entries": [
                    {"id": i, "name": n, "name_id": s, "modfile": f}
                    for i, n, s, f in catalogue
                ]
            }
        )
    )
    return mod_source.Workspace.build(
        cache_dir=cache, workspace=repos, catalogue_path=mirror
    )


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
    assert result.provisional is True
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
