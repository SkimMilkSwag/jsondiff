import json
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from jsondiff.diff import diff, format_report, format_json


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


def test_format_json_empty():
    d = diff({"a": 1}, {"a": 1})
    assert json.loads(format_json(d)) == []


def test_format_json_records():
    a = {"a": 1, "b": "x", "gone": 9}
    b = {"a": 2, "c": 3}
    recs = {r["path"]: r for r in json.loads(format_json(diff(a, b)))}
    assert recs["$.a"]["kind"] == "changed" and recs["$.a"]["old"] == 1 and recs["$.a"]["new"] == 2
    assert recs["$.b"]["kind"] == "removed"
    assert recs["$.c"]["kind"] == "added" and recs["$.c"]["new"] == 3


def test_format_json_type_change_includes_types():
    d = diff({"v": "str"}, {"v": 3})
    (rec,) = json.loads(format_json(d))
    assert rec["kind"] == "type"
    assert rec["old_type"] == "string" and rec["new_type"] == "number"


def test_cli_compact_flag(capsys):
    import pytest
    from jsondiff.__main__ import main
    with pytest.raises(SystemExit) as exc:
        main(['{"a":1,"b":[1,2]}', '{"a":2,"b":[1]}', "--compact"])
    assert exc.value.code == 0
    out = json.loads(capsys.readouterr().out)
    assert {r["kind"] for r in out} == {"changed", "removed"}
