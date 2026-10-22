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
    assert recs["$.limits.storage_mb"]["kind"] == "changed"
    assert recs["$.features[2]"]["kind"] == "added"
    # tags have no key field, so they diff positionally: [beta, us-east] -> [us-east]
    assert recs["$.tags[0]"]["kind"] == "changed"
    assert recs["$.tags[1]"]["kind"] == "removed"
    assert set(recs) == {
        "$.plan", "$.limits.api_calls", "$.limits.storage_mb",
        "$.features[2]", "$.tags[0]", "$.tags[1]",
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
    # -q only controls the exit code (1 when differences exist); the human
    # report is still printed
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "6 difference(s)" in out


def test_fail_on_change_exits_one_when_diffs_exist(tmp_path, capsys):
    import pytest
    from jsondiff.__main__ import main

    old = tmp_path / "old.json"
    new = tmp_path / "new.json"
    old.write_text(open(os.path.join(FIXTURES, "config_old.json")).read())
    new.write_text(open(os.path.join(FIXTURES, "config_new.json")).read())
    with pytest.raises(SystemExit) as exc:
        main([str(old), str(new), "--fail-on-change", "--compact"])
    assert exc.value.code == 1
    # the compact JSON report is still printed alongside the exit code
    recs = json.loads(capsys.readouterr().out)
    assert len(recs) >= 1


def test_fail_on_change_exits_zero_when_clean(tmp_path, capsys):
    import pytest
    from jsondiff.__main__ import main

    f = tmp_path / "same.json"
    f.write_text(open(os.path.join(FIXTURES, "config_old.json")).read())
    with pytest.raises(SystemExit) as exc:
        main([str(f), str(f), "--fail-on-change"])
    assert exc.value.code == 0


def test_fail_on_change_is_an_alias_for_q(capsys):
    # both spellings map to the same flag: exit-code semantics are identical
    import pytest
    from jsondiff.__main__ import main

    with pytest.raises(SystemExit) as exc:
        main(['{"a":1}', '{"a":2}', "--fail-on-change"])
    assert exc.value.code == 1
    capsys.readouterr()
    with pytest.raises(SystemExit) as exc:
        main(['{"a":1}', '{"a":2}', "-q"])
    assert exc.value.code == 1


# --- --ignore (key-name skipping) -----------------------------------------

def test_parse_ignore_basic():
    from jsondiff.diff import parse_ignore

    assert parse_ignore(None) is None
    assert parse_ignore("") is None
    assert parse_ignore("build") == frozenset({"build"})
    assert parse_ignore("a,b,c") == frozenset({"a", "b", "c"})
    # whitespace and empty segments are tolerated
    assert parse_ignore(" a ,, b ") == frozenset({"a", "b"})


def test_ignore_skips_named_keys_everywhere():
    a = {"build": 123, "name": "x", "cfg": {"build": 7, "keep": 1}}
    b = {"build": 456, "name": "y", "cfg": {"build": 8, "keep": 2}}
    full = diff(a, b)
    assert len(full.changes) == 4  # build, name, cfg.build, cfg.keep

    d = diff(a, b, ignore=frozenset({"build"}))
    paths = {c[0] for c in d.changes}
    # both "build" levels are suppressed; everything else still diffs
    assert paths == {"$.name", "$.cfg.keep"}


def test_ignore_handles_added_and_removed_keys():
    a = {"volatile": 1, "stable": 5}
    b = {"other": 9, "stable": 5}
    d = diff(a, b, ignore=frozenset({"volatile", "other"}))
    assert d.changes == []


def test_ignore_dotted_name_targets_one_path_only():
    # "$.cfg.build" suppresses the child inside cfg, but a top-level "build"
    # (or another nested "build") is still diffed.
    a = {"build": 1, "cfg": {"build": 2}, "deep": {"inner": {"build": 3}}}
    b = {"build": 2, "cfg": {"build": 9}, "deep": {"inner": {"build": 4}}}
    d = diff(a, b, ignore=frozenset({"$.cfg.build"}))
    paths = {c[0] for c in d.changes}
    assert paths == {"$.build", "$.deep.inner.build"}


def test_ignore_type_change_suppressed():
    a = {"ts": 1000}
    b = {"ts": "epoch"}
    d = diff(a, b, ignore=frozenset({"ts"}))
    assert d.changes == []
    # without the ignore, it's a type change
    assert any(c[1] == "type" for c in diff(a, b).changes)


def test_cli_ignore_flag(capsys):
    import pytest
    from jsondiff.__main__ import main

    with pytest.raises(SystemExit) as exc:
        main(['{"build":1,"a":1}', '{"build":2,"a":2}', "--ignore", "build", "--compact"])
    assert exc.value.code == 0
    recs = json.loads(capsys.readouterr().out)
    # only the non-ignored key remains; exit 0 because a changed is still
    # reported (exit code only flips with -q/--fail-on-change)
    assert [r["path"] for r in recs] == ["$.a"]


def test_cli_ignore_comma_list_and_q(capsys):
    import pytest
    from jsondiff.__main__ import main

    with pytest.raises(SystemExit) as exc:
        main(
            ['{"b":1,"c":2}', '{"b":9,"c":3}', "--ignore", "b,c", "-q", "-c"]
        )
    assert exc.value.code == 0, "both keys ignored -> clean -> exit 0 with -q"
    out = capsys.readouterr().out
    assert json.loads(out) == []


def test_cli_ignore_does_not_affect_stats_without_flag(capsys):
    # sanity: without --ignore the stats report still sees everything
    import pytest
    from jsondiff.__main__ import main

    with pytest.raises(SystemExit):
        main(['{"build":1}', '{"build":2}', "--stats"])
    out = capsys.readouterr().out
    assert "changed: 1" in out


# --- malformed-input parse errors (line/column) ----------------------------

def test_parse_error_file_reports_line_and_column(tmp_path, capsys):
    import pytest
    from jsondiff.__main__ import main

    bad = tmp_path / "bad.json"
    # second line is where the syntax breaks: missing quote on "name"
    bad.write_text('{"ok": 1,\n  "name": oops\n}\n')
    good = tmp_path / "good.json"
    good.write_text('{"a": 1}')

    with pytest.raises(SystemExit) as exc:
        main([str(bad), str(good)])
    # exit code 2 distinguishes a parse failure from -q's diff-exists exit 1
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "line 2, column 11" in err
    assert "bad.json" in err
    assert "Expecting value" in err


def test_parse_error_second_argument_is_attributed(tmp_path, capsys):
    import pytest
    from jsondiff.__main__ import main

    good = tmp_path / "good.json"
    good.write_text('{"a": 1}')
    bad = tmp_path / "bad.json"
    bad.write_text('[1, 2,\n]')

    with pytest.raises(SystemExit) as exc:
        main([str(good), str(bad)])
    assert exc.value.code == 2
    err = capsys.readouterr().err
    # the error points at the second file (line 2 is the empty continuation)
    assert "bad.json" in err and "line 2" in err


def test_parse_error_literal_json_reports_line_and_column(capsys):
    import pytest
    from jsondiff.__main__ import main

    with pytest.raises(SystemExit) as exc:
        main(['{"a": 1\n"b"}', '{"a": 1}'])
    assert exc.value.code == 2
    err = capsys.readouterr().err
    # literal path: no file name, but the line/column of the syntax break
    assert "line 2, column 1" in err
    assert "literal JSON" in err


def test_parse_error_stdin_reports_position(capsys, monkeypatch):
    import io
    import pytest
    from jsondiff import __main__ as m

    class FakeStdin(io.StringIO):
        # json.load iterates the file object line by line; StringIO supports
        # both the read() and iteration protocols it needs.
        pass

    monkeypatch.setattr(m.sys, "stdin", FakeStdin('{"a": 1,\n"b"}'))
    with pytest.raises(SystemExit) as exc:
        m.main(["-", "{}"])
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "<stdin>" in err and "line 2" in err
