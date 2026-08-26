import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from jsondiff.diff import diff, format_report


def test_identical():
    d = diff({"a": 1, "b": [1, 2]}, {"a": 1, "b": [1, 2]})
    assert d.changes == []
    assert format_report(d) == "No differences."


def test_scalar_change():
    d = diff({"x": 1}, {"x": 2})
    assert any(c[1] == "changed" and c[3] == 2 for c in d.changes)


def test_added_key():
    d = diff({}, {"new": 5})
    assert any(c[1] == "added" for c in d.changes)


def test_removed_key():
    d = diff({"old": 5}, {})
    assert any(c[1] == "removed" for c in d.changes)


def test_type_change():
    d = diff({"v": "str"}, {"v": 3})
    assert any(c[1] == "type" for c in d.changes)


def test_nested_and_list():
    a = {"list": [1, 2, 3], "nested": {"x": True}}
    b = {"list": [1, 4], "nested": {"x": False}}
    d = diff(a, b)
    kinds = {c[1] for c in d.changes}
    assert "changed" in kinds
    assert "removed" in kinds  # list index 2 removed
