import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import prefab_query as pq  # noqa: E402


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


def test_parse_decompile_namespace_and_base(tmp_path):
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
    base_of, ns_of = pq.parse_decompile(str(tmp_path))
    assert base_of["Widget"] == "MonoBehaviour"
    assert base_of["Helper"] is None
    assert base_of["Global"] == "Widget"
    assert ns_of["Widget"] == "Foo"
    assert ns_of["Global"] == ""


def test_build_script_ids_components_only():
    base_of = {"Comp": "MonoBehaviour", "Plain": None, "Helper": "Plain"}
    ns_of = {"Comp": "", "Plain": "", "Helper": ""}
    result = pq.build_script_ids(base_of, ns_of)
    assert result == {str(pq.fileid("Comp")): "Comp"}


def test_build_script_ids_collision_raises(monkeypatch):
    base_of = {"Foo": "MonoBehaviour", "Bar": "MonoBehaviour"}
    ns_of = {"Foo": "", "Bar": ""}
    monkeypatch.setattr(pq, "fileid", lambda name, namespace="": 42)
    with pytest.raises(ValueError, match="collision"):
        pq.build_script_ids(base_of, ns_of)
