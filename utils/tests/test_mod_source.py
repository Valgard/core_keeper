"""Unit tests for resolving a Core Keeper mod name to its source location."""

import json
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
    # higher modfile id is a guess that happens to work.
    cache = _write_cache(
        tmp_path, [(3177992, 7845185, "CoreLib", ["Scripts/CoreLibMod.cs"])]
    )
    stale = cache / "3177992_7710097"
    (stale / "Scripts").mkdir(parents=True)

    mods, _ = mod_source.read_installed(cache)

    assert [m.folder.name for m in mods] == ["3177992_7845185"]


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
