import json

import prefab_query as pq
import pytest


def test_fileid_known_anchors():
    assert pq.fileid("PugText") == 1873953792
    assert pq.fileid("LinearLayoutUIComponent") == -2136513284
    assert pq.fileid("WrapperUIComponent") == -601971722
    assert pq.fileid("ScrollBar") == -277093456
    assert pq.fileid("ScrollBarHandle") == -1490357010


def test_is_component_transitive():
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
    decls = [
        ("", "Comp", "MonoBehaviour"),
        ("", "Plain", None),
        ("", "Helper", "Plain"),
    ]
    result = pq.build_script_ids(decls)
    assert result == {str(pq.fileid("Comp")): "Comp"}


def test_build_script_ids_same_name_different_namespace():
    # Both are components (different namespaces -> different fileIDs) => both kept.
    # A non-component sharing the name (base None) is excluded, not confused with
    # the component variant.
    decls = [
        ("NsA", "Runner", "MonoBehaviour"),
        ("NsB", "Runner", "MonoBehaviour"),
        ("NsC", "Runner", None),  # not a component -> dropped, no false positive
    ]
    result = pq.build_script_ids(decls)
    assert result == {
        str(pq.fileid("Runner", "NsA")): "Runner",
        str(pq.fileid("Runner", "NsB")): "Runner",
    }


def test_build_script_ids_collision_raises(monkeypatch):
    decls = [("", "Foo", "MonoBehaviour"), ("", "Bar", "MonoBehaviour")]
    monkeypatch.setattr(pq, "fileid", lambda name, namespace="": 42)
    with pytest.raises(ValueError, match="collision"):
        pq.build_script_ids(decls)


def test_load_script_ids_missing(tmp_path):
    assert pq._load_script_ids(str(tmp_path / "nope.json")) == {}


def test_load_script_ids_corrupt(tmp_path):
    bad = tmp_path / "corrupt.json"
    bad.write_text("{ not valid json", encoding="utf-8")
    assert pq._load_script_ids(str(bad)) == {}


def test_refresh_ids_end_to_end(tmp_path):
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
    with pytest.raises(SystemExit):
        pq.refresh_ids(str(tmp_path / "absent"), str(tmp_path / "ids.json"))


def test_comp_label_resolves_and_falls_back(monkeypatch):
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
    ids = pq._load_script_ids()
    assert ids.get("1873953792") == "PugText"
    assert ids.get("197547074") == "UIScrollWindow"
    assert ids.get("1139742956") == "PugTextEffectMenuOption"
    assert ids.get("-1334111655") == "InheritPlacementFromUIComponent"
    assert ids.get("1793966478") == "PugTextEffectJuicyAppear"
