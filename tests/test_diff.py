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


def test_stats_counts_empty():
    from jsondiff.diff import diff, stats_counts
    d = diff({"a": 1}, {"a": 1})
    c = stats_counts(d)
    assert c == {"added": 0, "removed": 0, "changed": 0, "type": 0, "total": 0}


def test_stats_counts_mixed():
    from jsondiff.diff import diff, stats_counts
    # a: changed, b: removed, gone: removed, c: added, flag: type (bool->int), num: type (int->str)
    a = {"a": 1, "b": "x", "gone": 9, "flag": True, "num": 5}
    b = {"a": 2, "c": 3, "flag": 1, "num": "5"}
    d = diff(a, b)
    c = stats_counts(d)
    assert c["added"] == 1 and c["removed"] == 2
    assert c["changed"] == 1 and c["type"] == 2
    assert c["total"] == 6


def test_format_stats_zero_filled_and_total():
    from jsondiff.diff import diff, format_stats
    d = diff({"a": 1}, {"a": 2})  # single changed value
    out = format_stats(d)
    lines = out.splitlines()
    assert lines[0].strip() == "added: 0"
    assert lines[1].strip() == "removed: 0"
    assert lines[2].strip() == "changed: 1"
    assert lines[3].strip() == "type: 0"
    assert lines[4].strip() == "total: 1"


def test_cli_stats_flag(capsys):
    import pytest
    from jsondiff.__main__ import main
    with pytest.raises(SystemExit) as exc:
        main(['{"a":1,"gone":9}', '{"a":2,"c":3}', "--stats"])
    assert exc.value.code == 0
    out = capsys.readouterr().out.strip()
    # stats output is line-oriented, not JSON
    parsed = dict(l.strip().split(": ") for l in out.splitlines())
    # a changed, gone removed, c added
    assert parsed["added"] == "1" and parsed["removed"] == "1"
    assert parsed["changed"] == "1" and parsed["total"] == "3"


def test_cli_stats_takes_precedence_over_compact(capsys):
    import pytest
    from jsondiff.__main__ import main
    with pytest.raises(SystemExit):
        main(['{"a":1}', '{"a":2}', "--stats", "--compact"])
    out = capsys.readouterr().out
    # --stats wins: human summary, not JSON array
    assert "total" in out and not out.lstrip().startswith("[")


# --- integration: two fixture files read from disk -------------------------

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def test_cli_diff_fixture_files_from_disk(tmp_path, capsys):
    import pytest
    from jsondiff.__main__ import main

    # copy the checked-in fixtures to a temp dir so the test exercises real
    # file I/O paths (not the literal-JSON shortcut) without touching repo state
    old = tmp_path / "old.json"
    new = tmp_path / "new.json"
    old.write_text(open(os.path.join(FIXTURES, "config_old.json")).read())
    new.write_text(open(os.path.join(FIXTURES, "config_new.json")).read())

    with pytest.raises(SystemExit) as exc:
        main([str(old), str(new), "--compact"])
    assert exc.value.code == 0  # no -q flag: exit 0 even when diffs exist
    out = json.loads(capsys.readouterr().out)
    recs = {r["path"]: r for r in out}
    assert "$" not in recs  # top-level object persists, not itself a change
    assert recs["$.plan"]["kind"] == "changed"
    assert recs["$.plan"]["old"] == "pro" and recs["$.plan"]["new"] == "enterprise"
    assert recs["$.limits.api_calls"]["kind"] == "changed"
    assert recs["$.features[2]"]["kind"] == "added"
    # tags have no key field, so they diff positionally: [beta, us-east] -> [us-east]
    assert recs["$.tags[0]"]["kind"] == "changed"
    assert recs["$.tags[1]"]["kind"] == "removed"
    assert set(recs) == {
        "$.plan", "$.limits.api_calls", "$.features[2]", "$.tags[0]", "$.tags[1]"
    }


def test_cli_fixture_files_identical_exit_zero(tmp_path, capsys):
    import pytest
    from jsondiff.__main__ import main

    f = tmp_path / "same.json"
    f.write_text(open(os.path.join(FIXTURES, "config_old.json")).read())
    with pytest.raises(SystemExit) as exc:
        main([str(f), str(f)])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == "No differences."


def test_cli_fixture_files_quiet_exits_one_on_diff(tmp_path, capsys):
    import pytest
    from jsondiff.__main__ import main

    old = tmp_path / "old.json"
    new = tmp_path / "new.json"
    old.write_text(open(os.path.join(FIXTURES, "config_old.json")).read())
    new.write_text(open(os.path.join(FIXTURES, "config_new.json")).read())
    with pytest.raises(SystemExit) as exc:
        main([str(old), str(new), "-q"])
    assert exc.value.code == 1  # -q: 1 when differences exist, and no report printed
    assert capsys.readouterr().out == ""
