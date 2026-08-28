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


def test_keyed_array_diffs_by_key_not_position():
    a = {"users": [{"id": 1, "name": "alice"}, {"id": 2, "name": "bob"}]}
    # bob renamed; carol appended — positional diff would flag index 0 and 1 as changed + index 2 added
    b = {"users": [{"id": 1, "name": "alice"}, {"id": 2, "name": "robert"}, {"id": 3, "name": "carol"}]}
    d = diff(a, b, key_field="id")
    kinds = {c[1] for c in d.changes}
    assert "changed" in kinds and "added" in kinds and "removed" not in kinds
    by_path = {c[0]: c for c in d.changes}
    assert "$.users<id>.name" in by_path
    assert by_path["$.users<id>.name"][1] == "changed"


def test_keyed_array_removed_element():
    a = {"items": [{"sku": "x", "qty": 1}, {"sku": "y", "qty": 2}]}
    b = {"items": [{"sku": "y", "qty": 3}]}
    d = diff(a, b, key_field="sku")
    assert any(c[1] == "removed" and c[0].endswith("['x']") for c in d.changes)
    recs = json.loads(format_json(d))
    removed = [r for r in recs if r["kind"] == "removed"]
    assert len(removed) == 1 and removed[0]["old"]["sku"] == "x"


def test_keyed_array_reordered_is_silent():
    a = {"rows": [{"id": 1}, {"id": 2}, {"id": 3}]}
    b = {"rows": [{"id": 3}, {"id": 2}, {"id": 1}]}
    d = diff(a, b, key_field="id")
    assert d.changes == []


def test_keyless_array_without_key_flag_is_positional():
    a = {"v": [1, 2]}
    b = {"v": [2, 1]}
    # no --key given: pure positional diff reports changes at both indices
    assert len(diff(a, b).changes) == 2


def test_cli_key_flag(capsys):
    import pytest
    from jsondiff.__main__ import main
    with pytest.raises(SystemExit):
        main(['{"u":[{"id":1,"n":"a"},{"id":2,"n":"b"}]}', '{"u":[{"id":2,"n":"c"},{"id":3,"n":"d"}]}', "--key", "id", "--compact"])
    out = json.loads(capsys.readouterr().out)
    kinds = {r["path"]: r["kind"] for r in out}
    assert kinds.get("$.u<id>.n") == "changed"
    assert any(r["kind"] == "removed" and r["path"].endswith("[1]") for r in out)
    assert any(r["kind"] == "added" and r["new"]["id"] == 3 for r in out)


def test_cli_compact_flag(capsys):
    import pytest
    from jsondiff.__main__ import main
    with pytest.raises(SystemExit) as exc:
        main(['{"a":1,"b":[1,2]}', '{"a":2,"b":[1]}', "--compact"])
    assert exc.value.code == 0
    out = json.loads(capsys.readouterr().out)
    assert {r["kind"] for r in out} == {"changed", "removed"}
