"""Tests for prefab_query.py, the Unity prefab/scene YAML inspection CLI."""

import json

import prefab_query as pq
import pytest


def test_fileid_known_anchors():
    r"""Pin fileid()'s MD4-based hash against script IDs already live in the SDK.

    A change to the hash construction (the "s\0\0\0" prefix, the digest
    truncation, or the signed-int32 interpretation) would surface here
    instead of only as a wrong label in prefab_query's CLI output.
    """
    assert pq.fileid("PugText") == 1873953792
    assert pq.fileid("LinearLayoutUIComponent") == -2136513284
    assert pq.fileid("WrapperUIComponent") == -601971722
    assert pq.fileid("ScrollBar") == -277093456
    assert pq.fileid("ScrollBarHandle") == -1490357010


def test_is_component_transitive():
    """is_component() must classify direct, indirect, dead-end and cyclic base chains correctly.

    A base chain that never reaches MonoBehaviour/ScriptableObject is False,
    and a cycle (A -> B -> A) must terminate as False rather than recursing
    forever.
    """
    base_of = {
        "PugText": "UIComponentMonoBehaviour",
        "UIComponentMonoBehaviour": "MonoBehaviour",  # indirect -> True
        "Direct": "ScriptableObject",  # direct -> True
        "Loose": "SomeInterface",  # never reaches a root -> False
        "SomeInterface": None,
        "A": "B",  # cycle -> False, terminates
        "B": "A",
    }
    assert pq.is_component("PugText", base_of) is True
    assert pq.is_component("Direct", base_of) is True
    assert pq.is_component("MonoBehaviour", base_of) is True
    assert pq.is_component("Loose", base_of) is False
    assert pq.is_component("A", base_of) is False
    assert pq.is_component("Unknown", base_of) is False


def test_parse_decompile_collects_decls(tmp_path):
    """parse_decompile() tracks the enclosing namespace by brace depth, keeping only the first base.

    A namespaced class (Widget) is attributed to "Foo", a top-level class
    (Global) to the empty namespace, and a class with two bases (Global :
    Widget, IThing) records only the first — the token is_component() walks.
    """
    (tmp_path / "Fake.decompiled.cs").write_text(
        "namespace Foo {\n"
        "  public class Widget : MonoBehaviour {\n"
        "  }\n"
        "  public sealed class Helper {\n"
        "  }\n"
        "}\n"
        "public class Global : Widget, IThing {\n"
        "}\n",
        encoding="utf-8",
    )
    decls = pq.parse_decompile(str(tmp_path))
    assert ("Foo", "Widget", "MonoBehaviour") in decls
    assert ("Foo", "Helper", None) in decls
    assert ("", "Global", "Widget") in decls


def test_build_script_ids_components_only():
    """build_script_ids() keeps only classes tracing back to a MonoBehaviour/ScriptableObject root.

    Helper derives from Plain, a non-component, so it is excluded even though
    it is a distinct class from Plain itself — classification follows the
    base chain, not mere absence from the non-component set.
    """
    decls = [
        ("", "Comp", "MonoBehaviour"),
        ("", "Plain", None),
        ("", "Helper", "Plain"),
    ]
    result = pq.build_script_ids(decls)
    assert result == {str(pq.fileid("Comp")): "Comp"}


def test_build_script_ids_same_name_different_namespace():
    """Two same-named components in different namespaces are both kept under their own fileIDs.

    A third class sharing the same name but not deriving from a component
    root is dropped rather than confused with either component variant.
    """
    decls = [
        ("NsA", "Runner", "MonoBehaviour"),
        ("NsB", "Runner", "MonoBehaviour"),
        ("NsC", "Runner", None),
    ]
    result = pq.build_script_ids(decls)
    assert result == {
        str(pq.fileid("Runner", "NsA")): "Runner",
        str(pq.fileid("Runner", "NsB")): "Runner",
    }


def test_build_script_ids_collision_raises(monkeypatch):
    """Two distinct classes forced to the same fileID raise ValueError naming the collision.

    Without this guard, the second class would silently overwrite the
    first's entry in the output map instead of surfacing the hash clash.
    """
    decls = [("", "Foo", "MonoBehaviour"), ("", "Bar", "MonoBehaviour")]
    monkeypatch.setattr(pq, "fileid", lambda name, namespace="": 42)
    with pytest.raises(ValueError, match="collision"):
        pq.build_script_ids(decls)


def test_load_script_ids_missing(tmp_path):
    """A missing ck-script-ids.json is tolerated as an empty map rather than raising.

    Without this, prefab_query would traceback at import before the first
    `refresh-ids` run instead of merely falling back to short guid labels.
    """
    assert pq._load_script_ids(str(tmp_path / "nope.json")) == {}


def test_load_script_ids_corrupt(tmp_path):
    """A corrupt ck-script-ids.json is tolerated as an empty map, not an unhandled JSONDecodeError.

    Tolerating it lets `refresh-ids` overwrite the file instead of every
    command tracebacking at import.
    """
    bad = tmp_path / "corrupt.json"
    bad.write_text("{ not valid json", encoding="utf-8")
    assert pq._load_script_ids(str(bad)) == {}


def test_refresh_ids_end_to_end(tmp_path):
    """refresh_ids() writes the components the decompile scan found; Helper stays out.

    Helper is not a component and must be absent from both the returned
    mapping and the JSON written to disk, which must match the mapping
    exactly.
    """
    decomp = tmp_path / "decomp"
    decomp.mkdir()
    (decomp / "Fake.decompiled.cs").write_text(
        "namespace Foo {\n"
        "  public class Widget : MonoBehaviour {\n"
        "  }\n"
        "  public class Helper {\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
    )
    out = tmp_path / "ids.json"
    mapping = pq.refresh_ids(str(decomp), str(out))
    assert mapping == {str(pq.fileid("Widget", "Foo")): "Widget"}
    assert json.loads(out.read_text(encoding="utf-8")) == mapping


def test_refresh_ids_missing_decompile(tmp_path):
    """refresh_ids() exits (SystemExit) instead of tracebacking on a missing decompile dir."""
    with pytest.raises(SystemExit):
        pq.refresh_ids(str(tmp_path / "absent"), str(tmp_path / "ids.json"))


def test_comp_label_resolves_and_falls_back(monkeypatch):
    """comp_label() resolves a known fileID via SCRIPT_FILEID, else falls back to a short guid.

    An unresolvable fileID (999) must not raise or render blank — it renders
    as "MonoBehaviour[<8-char guid prefix>]" so the CLI output stays usable.
    """
    monkeypatch.setattr(pq, "SCRIPT_FILEID", {"1873953792": "PugText"})
    objs = {
        "10": (
            "114",
            {"MonoBehaviour": {"m_Script": {"fileID": 1873953792, "guid": "abc123"}}},
        ),
        "11": (
            "114",
            {"MonoBehaviour": {"m_Script": {"fileID": 999, "guid": "deadbeefcafe"}}},
        ),
    }
    assert pq.comp_label(objs, "10") == "PugText"
    assert pq.comp_label(objs, "11") == "MonoBehaviour[deadbeef]"


def test_generated_json_covers_known_repo_ids():
    """The committed ck-script-ids.json still maps a handful of fileIDs several mod repos rely on.

    A regeneration that silently dropped or renamed one of these entries
    would be caught here, rather than only when a mod repo's prefab shows a
    guid label or a missing component in-game.
    """
    ids = pq._load_script_ids()
    assert ids.get("1873953792") == "PugText"
    assert ids.get("197547074") == "UIScrollWindow"
    assert ids.get("1139742956") == "PugTextEffectMenuOption"
    assert ids.get("-1334111655") == "InheritPlacementFromUIComponent"
    assert ids.get("1793966478") == "PugTextEffectJuicyAppear"
