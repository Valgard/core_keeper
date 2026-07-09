import os
import sys


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
