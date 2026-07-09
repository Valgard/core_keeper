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
