import json
import sys, os
import pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from jsondiff.diff import diff, format_report, format_json, format_stats, format_summary


def _leaf_filter(include):
    """Build a leaf-reporting filter for an ``--include`` set.

    A change at ``path`` is reported when its last dotted segment (array
    brackets stripped — ``$.tags[2]`` -> ``tags``, so a bare key covers its
    whole element list) or the full path appears in ``include``. Returns None
    when there is no include set, meaning report everything.

    Accepts either a set/frozenset of claimed names/paths or a single string
    (the convenience form used by some tests); the membership test treats a
    bare name as claiming it at every depth.
    """
    if isinstance(include, str):
        include = frozenset([include])

    def _filter(path: str) -> bool:
        seg = path.rsplit(".", 1)[-1] if "." in path else path
        if "[" in seg:
            seg = seg.split("[", 1)[0]
            base = seg.rsplit(".", 1)[-1] if "." in seg else seg
            seg = base
        return seg in include or path in include

    return _filter if include else None


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

    assert parse_ignore(None) == (None, None)
    assert parse_ignore("") == (None, None)
    assert parse_ignore("build") == (frozenset({"build"}), None)
    assert parse_ignore("a,b,c") == (frozenset({"a", "b", "c"}), None)
    # whitespace and empty segments are tolerated
    assert parse_ignore(" a ,, b ") == (frozenset({"a", "b"}), None)


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


# --- --include (key-name allowlist, inverse of --ignore) ------------------

def test_parse_include_basic():
    from jsondiff.diff import parse_include

    assert parse_include(None) == (None, None)
    assert parse_include("") == (None, None)
    assert parse_include("name") == (frozenset({"name"}), None)
    assert parse_include("a,b,c") == (frozenset({"a", "b", "c"}), None)
    # whitespace and empty segments are tolerated, same as --ignore
    assert parse_include(" a ,, b ") == (frozenset({"a", "b"}), None)


def test_include_restricts_to_named_keys():
    a = {"name": "x", "version": 1, "build": 123, "cfg": {"build": 7, "keep": 1}}
    b = {"name": "y", "version": 2, "build": 456, "cfg": {"build": 8, "keep": 2}}
    # without include: every changed key is reported
    full = diff(a, b)
    assert len(full.changes) == 5
    # with include="name": only $.name diffs; version/build/cfg.* are skipped
    d = diff(a, b, include=frozenset({"name"}))
    paths = {c[0] for c in d.changes}
    assert paths == {"$.name"}


def test_include_applies_at_every_level():
    # a bare name in the allowlist matches at every nesting depth
    a = {"outer": {"v": 1, "other": 2}, "inner": {"v": 3}}
    b = {"outer": {"v": 9, "other": 5}, "inner": {"v": 7}}
    d = diff(a, b, include=frozenset({"v"}), include_leaf=_leaf_filter({"v"}))
    paths = {c[0] for c in d.changes}
    # both "v" members (outer.v and inner.v) are kept; "other" is skipped
    assert paths == {"$.outer.v", "$.inner.v"}


def test_include_handles_added_and_removed_keys():
    a = {"keep": 1, "volatile": 9}
    b = {"keep": 2, "other": 3}
    # include only "keep": the change to keep is reported; volatile (removed)
    # and other (added) are skipped because they're not in the allowlist
    d = diff(a, b, include=frozenset({"keep"}))
    paths = {c[0] for c in d.changes}
    assert paths == {"$.keep"}
    assert all(c[1] == "changed" for c in d.changes)


def test_include_dotted_name_targets_one_path_only():
    # a full JSON path in the allowlist matches only that location, not other
    # members with the same bare name elsewhere
    a = {"build": 1, "cfg": {"build": 2}, "deep": {"build": 3}}
    b = {"build": 5, "cfg": {"build": 9}, "deep": {"build": 7}}
    d = diff(a, b, include=frozenset({"$.cfg.build"}), include_leaf=_leaf_filter("$.cfg.build"))
    paths = {c[0] for c in d.changes}
    # only cfg.build is kept; the top-level build and deep.build are skipped
    assert paths == {"$.cfg.build"}


def test_include_and_ignore_combine():
    # a member must pass BOTH: be in the include allowlist AND not be ignored
    a = {"name": "x", "build": 1, "other": 2}
    b = {"name": "y", "build": 9, "other": 8}
    d = diff(a, b, include=frozenset({"name", "build"}), ignore=frozenset({"build"}))
    paths = {c[0] for c in d.changes}
    # name is included and not ignored -> reported; build is included but
    # ignored -> skipped; other is not included -> skipped
    assert paths == {"$.name"}


def test_include_does_not_prune_array_elements():
    # the allowlist is a leaf filter: it gates *reporting* of changes, but we
    # still descend through containers to find matching leaves. Listing a bare
    # key covers its whole element list; listing the inner leaf name reports it.
    a = {"tags": [1, 2, 3], "meta": {"v": 1}}
    b = {"tags": [1, 4], "meta": {"v": 9}}
    # "tags" (covers its element list) + "v" (the inner leaf) are both allowed
    d = diff(a, b, include=frozenset({"tags", "v"}), include_leaf=_leaf_filter({"tags", "v"}))
    paths = {c[0] for c in d.changes}
    assert "$.tags[1]" in paths and "$.tags[2]" in paths and "$.meta.v" in paths


def test_include_container_key_covers_element_list():
    # a bare key in the allowlist covers its entire array: element changes are
    # reported even though the elements aren't individually listed
    a = {"tags": [1, 2]}
    b = {"tags": [1, 9]}
    d = diff(a, b, include=frozenset({"tags"}))
    assert {c[0] for c in d.changes} == {"$.tags[1]"}


def test_include_normalizes_pruned_differences():
    # a difference confined to a pruned member must NOT force a diff when the
    # included members are semantically equal (the _project fast path)
    a = {"keep": 1, "skip": {"x": 1}}
    b = {"keep": 1, "skip": {"x": 99}}
    d = diff(a, b, include=frozenset({"keep"}))
    assert d.changes == []


def test_cli_include_flag(capsys):
    import pytest
    from jsondiff.__main__ import main

    with pytest.raises(SystemExit) as exc:
        main(['{"a":1,"b":2}', '{"a":9,"b":3}', "--include", "a", "--compact"])
    assert exc.value.code == 0
    recs = json.loads(capsys.readouterr().out)
    # only the included key is reported
    assert [r["path"] for r in recs] == ["$.a"]


def test_cli_include_comma_list_and_q(capsys):
    import pytest
    from jsondiff.__main__ import main

    with pytest.raises(SystemExit) as exc:
        main(['{"a":1,"b":2,"c":3}', '{"a":9,"b":5,"c":7}', "--include", "a,c", "-q", "-c"])
    # both a and c change -> -q flips the exit code to 1
    assert exc.value.code == 1
    recs = json.loads(capsys.readouterr().out)
    assert sorted(r["path"] for r in recs) == ["$.a", "$.c"]


def test_cli_include_clean_exit_zero_with_q(capsys):
    import pytest
    from jsondiff.__main__ import main

    with pytest.raises(SystemExit) as exc:
        main(['{"a":1,"b":2}', '{"a":1,"b":9}', "--include", "a", "-q", "-c"])
    # only b differs but b is not included -> clean -> exit 0 with -q
    assert exc.value.code == 0
    assert json.loads(capsys.readouterr().out) == []


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


def test_normalize_silences_key_order_swap():
    # dict key order is not a semantic change by default
    a = {"x": 1, "y": [3, 2, 1], "z": {"m": True}}
    b = {"z": {"m": True}, "y": [3, 2, 1], "x": 1}
    assert diff(a, b).changes == []


def test_normalize_silences_int_float_equivalence():
    # 1 and 1.0 are the same JSON number; bool stays distinct from number
    assert diff({"n": 1}, {"n": 1.0}).changes == []
    assert diff({"n": 1.5}, {"n": 1.50}).changes == []
    # bool vs number is a real type change (type check runs before normalization)
    d = diff({"b": True}, {"b": 1})
    assert len(d.changes) == 1 and d.changes[0].kind == "type"


def test_no_normalize_flags_key_order_swap():
    a = {"x": 1, "y": [3, 2, 1]}
    b = {"y": [3, 2, 1], "x": 1}
    d = diff(a, b, normalize=False)
    assert len(d.changes) == 1 and d.changes[0].kind == "changed"


def test_no_normalize_flags_int_float_difference():
    d = diff({"n": 1}, {"n": 1.0}, normalize=False)
    assert len(d.changes) == 1 and d.changes[0].kind == "changed"


def test_normalize_applies_at_every_depth():
    # nested key-order swap inside arrays and objects is silenced
    a = {"rows": [{"id": 1, "tags": {"b": 2, "a": 1}}]}
    b = {"rows": [{"tags": {"a": 1, "b": 2}, "id": 1}]}
    assert diff(a, b).changes == []


def test_normalize_equal_nested_values_still_record_originals():
    # a genuine change under normalization keeps the original values in the record
    d = diff({"n": 1.0}, {"n": 2})
    assert len(d.changes) == 1
    rec = d.changes[0]
    assert rec.kind == "changed" and rec.old == 1.0 and rec.new == 2


def test_cli_no_normalize_flag(capsys):
    import pytest
    from jsondiff.__main__ import main

    with pytest.raises(SystemExit):
        main(["--no-normalize", '{"x": 1, "y": 2}', '{"y": 2, "x": 1}'])
    out = capsys.readouterr().out
    assert "1 difference" in out


def test_cli_no_normalize_with_compact(capsys):
    import pytest
    from jsondiff.__main__ import main

    with pytest.raises(SystemExit):
        main(["--no-normalize", "--compact", '{"x": 1}', '{"x": 1.0}'])
    out = capsys.readouterr().out
    records = __import__("json").loads(out)
    assert len(records) == 1 and records[0]["kind"] == "changed"


def test_cli_normalize_clean_by_default(capsys):
    import pytest
    from jsondiff.__main__ import main

    with pytest.raises(SystemExit):
        main(["--compact", '{"x": 1, "y": 2}', '{"y": 2, "x": 1}'])
    out = capsys.readouterr().out
    assert __import__("json").loads(out) == []


# --- --summary: per-top-level-key counts ------------------------------------

def test_summary_counts_mixed_kinds():
    from jsondiff.diff import diff, summary_counts

    a = {"a": 1, "gone": 9, "cfg": {"x": 1}, "items": [1, 2]}
    b = {"a": 2, "cfg": {"x": 2, "y": 3}, "items": [1, 3], "brand": 4}
    d = diff(a, b)
    rows = summary_counts(d)
    assert set(rows) == {"a", "gone", "cfg", "items", "brand"}
    assert rows["a"] == {"added": 0, "removed": 0, "changed": 1, "type": 0}
    assert rows["gone"]["removed"] == 1
    assert rows["cfg"]["changed"] == 1 and rows["cfg"]["added"] == 1
    assert rows["items"]["changed"] == 1
    assert rows["brand"]["added"] == 1


def test_summary_counts_empty_diff():
    from jsondiff.diff import diff, summary_counts

    rows = summary_counts(diff({"a": 1}, {"a": 1}))
    assert rows == {}


def test_summary_counts_deep_path_rolls_to_top_key():
    from jsondiff.diff import diff, summary_counts

    a = {"svc": {"db": {"host": "x"}}}
    b = {"svc": {"db": {"host": "y"}, "pool": 5}}
    rows = summary_counts(diff(a, b))
    # both deep changes roll up to the single top-level key 'svc'
    assert list(rows) == ["svc"]
    assert rows["svc"]["changed"] == 1 and rows["svc"]["added"] == 1


def test_summary_counts_array_top_level():
    from jsondiff.diff import diff, summary_counts

    a = [[1, 2], [3]]
    b = [[1, 9]]
    rows = summary_counts(diff(a, b))
    # top-level array members ($[0]/$[1]) roll up to the array itself:
    # a single row whose index is the path's own top segment, "$"
    assert list(rows) == ["$"]
    assert rows["$"]["changed"] == 1 and rows["$"]["removed"] == 1


def test_format_summary_table_shape():
    from jsondiff.diff import diff, format_summary

    d = diff({"a": 1, "gone": 9}, {"a": 2, "new": 3})
    out = format_summary(d)
    lines = out.splitlines()
    # header + one row per top-level key + TOTAL line
    assert lines[0].startswith("key")
    assert len(lines) == 1 + 3 + 1
    a_row = [l for l in lines if l.startswith("a ") or l.startswith("a\t")]
    assert a_row and a_row[0].split()[-1] == "1"  # one change under 'a'


def test_format_summary_empty():
    from jsondiff.diff import diff, format_summary

    assert format_summary(diff({"a": 1}, {"a": 1})) == "No differences."


def test_cli_summary_flag(capsys):
    import pytest
    from jsondiff.__main__ import main

    with pytest.raises(SystemExit) as exc:
        main(['{"a":1,"gone":9,"cfg":{"x":1}}', '{"a":2,"cfg":{"x":2},"new":3}', "--summary"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    lines = out.strip().splitlines()
    assert lines[0].startswith("key")
    assert "TOTAL" in out
    # 'a' row: one changed, total 1; 'gone' row: one removed; 'new' row: one added
    rows = {l.split()[0]: l for l in lines[1:]}
    assert rows["a"].split()[-1] == "1"
    assert rows["gone"].split()[-1] == "1"
    assert rows["cfg"].split()[-1] == "1"
    assert rows["new"].split()[-1] == "1"
    # grand total line sums to 4
    assert rows["TOTAL"].split()[-1] == "4"


def test_cli_summary_takes_precedence(capsys):
    import pytest
    from jsondiff.__main__ import main

    with pytest.raises(SystemExit):
        main(['{"a":1}', '{"a":2}', "--summary", "--stats", "--compact"])
    out = capsys.readouterr().out.strip()
    lines = out.splitlines()
    # summary wins: table shape, not stats lines or a JSON array
    assert lines[0].startswith("key") and "TOTAL" in out
    assert not out.lstrip().startswith("[")


# --- wildcard patterns ('$.a.*') in --ignore / --include ---------------------

def test_parse_ignore_splits_wildcards():
    from jsondiff.diff import parse_ignore

    exact, wild = parse_ignore("$.cfg.*,build,$.items[0].meta.*")
    assert exact == frozenset({"build"})
    assert wild == frozenset({"$.cfg.*", "$.items[0].meta.*"})


def test_parse_include_splits_wildcards():
    from jsondiff.diff import parse_include

    exact, wild = parse_include("name,$.server.*")
    assert exact == frozenset({"name"})
    assert wild == frozenset({"$.server.*"})


def test_ignore_wildcard_suppresses_object_members():
    a = {"build": 1, "cfg": {"host": "h", "port": 80}, "deep": {"build": 2}}
    b = {"build": 9, "cfg": {"host": "H", "port": 81}, "deep": {"build": 3}}
    d = diff(a, b, ignore_wild=frozenset({"$.cfg.*"}))
    paths = {c[0] for c in d.changes}
    # every member of cfg is suppressed; 'build' anywhere else still diffs
    assert paths == {"$.build", "$.deep.build"}


def test_ignore_wildcard_one_level_deep_only():
    # '$.a.*' claims a's members, not the children of those members
    a = {"a": {"b": {"c": 1}}, "x": 1}
    b = {"a": {"b": {"c": 9}}, "x": 2}
    d = diff(a, b, ignore_wild=frozenset({"$.a.*"}))
    paths = {c[0] for c in d.changes}
    # a's own member 'b' is claimed (the whole b subtree rolls under it),
    # so only x is reported
    assert paths == {"$.x"}


def test_ignore_wildcard_added_and_removed_members():
    a = {"cfg": {"old": 1, "keep": 2}}
    b = {"cfg": {"new": 9, "keep": 3}}
    d = diff(a, b, ignore_wild=frozenset({"$.cfg.*"}))
    paths = {c[0] for c in d.changes}
    # old removed + new added are both suppressed; keep changed is not
    assert paths == {"$.cfg.keep"}


def test_include_wildcard_restricts_to_object_members():
    a = {"name": "x", "server": {"host": "h", "port": 1}, "build": 7}
    b = {"name": "y", "server": {"host": "H", "port": 2}, "build": 8}
    d = diff(a, b, include_wild=frozenset({"$.server.*"}))
    paths = {c[0] for c in d.changes}
    # only server's members are reported; name and build are skipped
    assert paths == {"$.server.host", "$.server.port"}


def test_include_wildcard_descends_for_deeper_claimed_keys():
    # the walk descends through non-claimed containers, so a deeper listed
    # path under an unclaimed object is still found (documented --include rule)
    a = {"name": "x", "deep": {"cfg": {"build": 1}}}
    b = {"name": "y", "deep": {"cfg": {"build": 9}}}
    d = diff(a, b, include=frozenset({"$.deep.cfg.build"}),
             include_leaf=_leaf_filter("$.deep.cfg.build"))
    paths = {c[0] for c in d.changes}
    assert paths == {"$.deep.cfg.build"}


def test_ignore_wildcard_combines_with_exact_ignore_and_include():
    # ignore wins over include; exact and wildcard ignores stack additively
    a = {"cfg": {"build": 1, "host": "h"}, "name": "x", "other": 1}
    b = {"cfg": {"build": 9, "host": "H"}, "name": "y", "other": 2}
    d = diff(
        a, b,
        ignore=frozenset({"$.cfg.host"}),
        include=frozenset({"name", "$.cfg.build"}),
        include_leaf=_leaf_filter({"name", "$.cfg.build"}),
        ignore_wild=frozenset({"$.cfg.*"}),
    )
    paths = {c[0] for c in d.changes}
    # host: exact-ignored; build: included but claimed by the wildcard -> gone;
    # name: included, unclaimed -> reported; other: not included -> skipped
    assert paths == {"$.name"}


def test_ignore_wildcard_nested_location():
    a = {"items": [{"meta": {"v": 1}}, {"meta": {"v": 2}}]}
    b = {"items": [{"meta": {"v": 9}}, {"meta": {"v": 8}}]}
    d = diff(a, b, ignore_wild=frozenset({"$.items[0].meta.*"}))
    paths = {c[0] for c in d.changes}
    # only the first element's meta members are claimed
    assert paths == {"$.items[1].meta.v"}


def test_ignore_wildcard_keeps_fast_path_silent():
    # a difference confined to a wildcard-pruned member must not defeat the
    # normalized fast path (no full re-diff, no spurious record)
    a = {"cfg": {"host": "h"}, "stable": 1}
    b = {"cfg": {"host": "H"}, "stable": 1}
    assert diff(a, b, ignore_wild=frozenset({"$.cfg.*"})).changes == []


def test_no_normalize_wildcard_still_reports_reorder():
    # strict mode: the key-order record is still emitted when a wildcard is
    # in play (the per-member walk handles value-level suppression)
    a = {"cfg": {"host": "h", "port": 1}}
    b = {"cfg": {"port": 2, "host": "H"}}
    d = diff(a, b, normalize=False, ignore_wild=frozenset({"$.cfg.*"}))
    kinds = {c[1] for c in d.changes}
    assert "changed" in kinds  # the container reorder itself


def test_cli_ignore_wildcard_flag(capsys):
    import pytest
    from jsondiff.__main__ import main

    with pytest.raises(SystemExit) as exc:
        main(
            ['{"build":1,"cfg":{"host":"h","port":80},"x":1}',
             '{"build":9,"cfg":{"host":"H","port":81},"x":2}',
             "--ignore", "$.cfg.*", "--compact"],
        )
    assert exc.value.code == 0
    recs = json.loads(capsys.readouterr().out)
    assert sorted(r["path"] for r in recs) == ["$.build", "$.x"]


def test_cli_include_wildcard_flag(capsys):
    import pytest
    from jsondiff.__main__ import main

    with pytest.raises(SystemExit):
        main(
            ['{"name":"x","server":{"host":"h","port":1},"build":7}',
             '{"name":"y","server":{"host":"H","port":2},"build":8}',
             "--include", "$.server.*,name", "--compact"],
        )
    recs = json.loads(capsys.readouterr().out)
    paths = {r["path"] for r in recs}
    assert paths == {"$.server.host", "$.server.port", "$.name"}


def test_cli_wildcard_with_q_exit_code(capsys):
    import pytest
    from jsondiff.__main__ import main

    # a change confined to the wildcard-ignored object -> clean under -q
    with pytest.raises(SystemExit) as exc:
        main(
            ['{"cfg":{"a":1},"ok":1}', '{"cfg":{"a":2},"ok":1}',
             "--ignore", "$.cfg.*", "-q"],
        )
    assert exc.value.code == 0
    # ...and a change outside it still fails the gate
    with pytest.raises(SystemExit) as exc:
        main(
            ['{"cfg":{"a":1},"ok":1}', '{"cfg":{"a":2},"ok":9}',
             "--ignore", "$.cfg.*", "-q"],
        )
    assert exc.value.code == 1


# --- exit-code contract (0 identical / 1 changes / 2 parse / 3 usage) -------
#
# Pins the four-way exit-code contract end to end, so a refactor that lets a
# usage error bleed into 2 (or vice versa) is caught here.

def test_exit_code_contract_full_matrix(capsys):
    import pytest
    from jsondiff.__main__ import main

    def code(args):
        with pytest.raises(SystemExit) as exc:
            main(args)
        return exc.value.code

    # 0 -- identical documents (with and without -q; the report still prints)
    assert code(['{"a":1,"b":[1,2]}', '{"a":1,"b":[1,2]}']) == 0
    assert code(['{"a":1}', '{"a":1}', "-q"]) == 0

    # 1 -- changes exist, only when -q / --fail-on-change is given (otherwise
    # the diff still exits 0 so the human report can be consumed)
    assert code(['{"a":1}', '{"a":2}']) == 0
    assert code(['{"a":1}', '{"a":2}', "-q"]) == 1
    assert code(['{"a":1}', '{"a":2}', "--fail-on-change", "--compact"]) == 1

    # 2 -- a JSON parse failure (line/column reported, not conflated with 3)
    assert code(['{"a": oops}', '{"a":1}']) == 2
    assert code(['{"a":1}', '{"a": oops}']) == 2

    # 3 -- usage errors: unknown flag, missing positional, extra positional,
    # and an invalid --format choice all land on 3
    assert code(['{"a":1}', '{"a":2}', "--no-such-flag"]) == 3
    assert code(['{"a":1}']) == 3
    assert code(['{"a":1}', '{"a":1}', '{"a":1}']) == 3
    assert code(['{"a":1}', '{"a":1}', "-s", "--format", "xml"]) == 3


def test_usage_error_message_goes_to_stderr(capsys):
    import pytest
    from jsondiff.__main__ import main

    with pytest.raises(SystemExit) as exc:
        main(['{"a":1}', '{"a":2}', "--no-such-flag"])
    assert exc.value.code == 3
    err = capsys.readouterr().err
    # argparse's own phrasing is preserved, and nothing leaked to stdout
    assert "unrecognized arguments" in err or "error:" in err


def test_parse_error_still_exits_two_not_three(tmp_path, capsys):
    import pytest
    from jsondiff.__main__ import main

    bad = tmp_path / "bad.json"
    bad.write_text('{"a": 1,')
    good = tmp_path / "good.json"
    good.write_text('{"a": 1}')

    with pytest.raises(SystemExit) as exc:
        main([str(bad), str(good)])
    # the documented 2-vs-3 split: a parse failure is NOT a usage error
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "bad.json" in err and "line" in err


# ---------------------------------------------------------------------------
# --limit: cap the number of reported changes (library Diff.truncate + CLI)
# ---------------------------------------------------------------------------

def test_truncate_caps_changes_and_records_overflow():
    d = diff({"a": 1, "b": 2, "c": 3}, {"a": 9, "b": 8, "c": 7})
    assert len(d.changes) == 3
    assert d.truncated == 0
    d.truncate(2)
    assert len(d.changes) == 2
    assert d.truncated == 1
    # keeps the first records in diff order
    assert [c.path for c in d.changes] == ["$.a", "$.b"]


def test_truncate_zero_or_negative_is_a_noop():
    d = diff({"a": 1, "b": 2}, {"a": 2, "b": 3})
    # 0 is the documented "no limit" sentinel: it does not cap, and it clears
    # a previous cap's overflow counter (dropped records stay dropped)
    d.truncate(1)
    assert d.truncated == 1
    d.truncate(0)
    assert len(d.changes) == 1 and d.truncated == 0
    d2 = diff({"a": 1, "b": 2}, {"a": 2, "b": 3})
    d2.truncate(-5)
    assert len(d2.changes) == 2 and d2.truncated == 0


def test_truncate_at_or_above_count_is_silent():
    d = diff({"a": 1}, {"a": 2})
    d.truncate(1)   # exactly the change count: no overflow
    assert len(d.changes) == 1 and d.truncated == 0
    d3 = diff({"a": 1, "b": 2}, {"a": 2, "b": 3}).truncate(10)
    assert len(d3.changes) == 2 and d3.truncated == 0


def test_format_report_shows_truncation_note():
    d = diff({"a": 1, "b": 2, "c": 3}, {"a": 9, "b": 8, "c": 7}).truncate(1)
    out = format_report(d)
    assert out.splitlines()[0] == "1 difference(s) found:"
    assert "$.a" in out and "$.b" not in out
    assert "... and 2 more change(s) not shown (diff capped by --limit)" in out


def test_format_report_no_note_when_not_capped():
    d = diff({"a": 1}, {"a": 2}).truncate(5)
    out = format_report(d)
    assert "not shown" not in out
    assert out == "1 difference(s) found:\n  $.a: 1 -> 2"


def test_format_stats_shows_truncation_note():
    # 3 changes total: $.a changed, $.b removed, $.c added; keep one
    d = diff({"a": 1, "b": 2}, {"a": 9, "c": 3}).truncate(1)
    out = format_stats(d)
    # counts cover only the reported (kept) changes
    assert "  changed: 1" in out and "  removed: 0" in out
    assert "  total: 1" in out
    assert "... and 2 more change(s) not shown (diff capped by --limit)" in out


def test_format_summary_shows_truncation_note():
    d = diff({"x": {"a": 1, "b": 2}, "y": {"c": 3}},
             {"x": {"a": 9, "b": 8}, "y": {"c": 7}}).truncate(2)
    out = format_summary(d)
    # rows cover only kept changes; the cap is still visible
    assert "... and 1 more change(s) not shown (diff capped by --limit)" in out
    assert "TOTAL" in out


def test_format_json_stays_pure_json_when_capped():
    d = diff({"a": 1, "b": 2}, {"a": 9, "b": 8}).truncate(1)
    recs = json.loads(format_json(d))
    assert len(recs) == 1 and recs[0]["path"] == "$.a"
    # no trailing note line breaks the JSON parse (verified by loads above);
    # and the note text itself never appears inside a record
    assert not any("not shown" in json.dumps(r) for r in recs)


def test_cli_limit_flag(capsys):
    from jsondiff.__main__ import main

    with pytest.raises(SystemExit) as exc:
        main(['{"a":1,"b":2,"c":3}', '{"a":9,"b":8,"c":7}', "--limit", "2", "-q"])
    assert exc.value.code == 1
    out = capsys.readouterr().out
    lines = out.strip().splitlines()
    assert lines[0] == "2 difference(s) found:"
    assert "$.c" not in out
    assert "... and 1 more change(s) not shown (diff capped by --limit)" in out


def test_cli_limit_short_flag_and_q_exit_one(capsys):
    from jsondiff.__main__ import main

    with pytest.raises(SystemExit) as exc:
        main(['{"a":1,"b":2}', '{"a":9,"b":8}', "-l", "1", "-q"])
    out = capsys.readouterr().out
    assert "... and 1 more change(s)" in out
    # -q exits 1 even though only one of two changes was shown
    assert exc.value.code == 1


def test_cli_limit_zero_is_unlimited(capsys):
    from jsondiff.__main__ import main

    with pytest.raises(SystemExit) as exc:
        main(['{"a":1,"b":2}', '{"a":9,"b":8}', "-l", "0", "-q"])
    out = capsys.readouterr().out
    assert "2 difference(s) found:" in out
    assert "not shown" not in out
    assert exc.value.code == 1


# ---------------------------------------------------------------------------
# --limit edge cases: boundary limits, precedence, and output-mode interactions
# ---------------------------------------------------------------------------

def test_limit_exceeding_change_count_is_silent():
    d = diff({"a": 1}, {"a": 2})
    d.truncate(99)
    assert len(d.changes) == 1 and d.truncated == 0
    for fmt in (format_report, format_stats, format_summary):
        out = fmt(d)
        assert "not shown" not in out


def test_limit_one_keeps_first_change_in_diff_order():
    # added + removed + changed all present; limit=1 keeps only the first
    d = diff({"a": 1, "b": 2, "c": 3}, {"x": 9, "b": 8, "c": 7})
    kinds_before = [c.kind for c in d.changes]
    d.truncate(1)
    assert len(d.changes) == 1
    assert d.truncated == len(kinds_before) - 1
    # the survivor is diff-order-first, whatever kind that is
    assert d.changes[0].path == "$.a"


def test_limit_applies_after_ignore_pruning():
    # 3 real changes; --ignore b leaves 2, and limit caps those 2 to 1
    a = {"a": 1, "b": 2, "c": 3}
    b = {"a": 9, "b": 8, "c": 7}
    d = diff(a, b, ignore=frozenset({"b"}))
    assert len(d.changes) == 2
    d.truncate(1)
    assert len(d.changes) == 1 and d.truncated == 1
    assert d.changes[0].path == "$.a"


def test_limit_with_keyed_arrays_caps_pairs_and_elements():
    # 2 changed members across keyed pairs + one added element; cap at 2
    a = {"u": [{"id": 1, "n": "x"}, {"id": 2, "n": "y"}]}
    b = {"u": [{"id": 2, "n": "z"}, {"id": 1, "n": "w"}, {"id": 3, "n": "v"}]}
    d = diff(a, b, key_field="id")
    before = len(d.changes)
    assert before >= 2
    d.truncate(2)
    assert len(d.changes) == 2
    assert d.truncated == before - 2


def test_limit_with_no_normalize_strict_mode():
    # strict mode reports a key-order swap as one change; limit==count is a no-op
    a = {"x": 1, "y": 2}
    b = {"y": 2, "x": 1}
    d = diff(a, b, normalize=False)
    assert len(d.changes) == 1
    d.truncate(1)
    assert len(d.changes) == 1 and d.truncated == 0


def test_cli_limit_precedence_with_all_output_flags(capsys):
    # --limit combines with every output mode; --summary wins precedence
    from jsondiff.__main__ import main

    args = ['{"a":{"p":1,"q":2},"b":{"r":3}}',
            '{"a":{"p":9,"q":8},"b":{"r":7}}',
            "--limit", "1", "--summary", "-q"]
    with pytest.raises(SystemExit) as exc:
        main(args)
    out = capsys.readouterr().out
    # summary table rendered (not the report), capped, note present
    assert "TOTAL" in out and "key" in out.splitlines()[0]
    assert "... and 2 more change(s) not shown (diff capped by --limit)" in out
    assert exc.value.code == 1

    # --stats with --limit: counts cover only kept changes
    with pytest.raises(SystemExit) as exc:
        main(['{"a":{"p":1,"q":2},"b":{"r":3}}',
              '{"a":{"p":9,"q":8},"b":{"r":7}}',
              "--limit", "1", "-s", "-q"])
    out = capsys.readouterr().out
    assert "  total: 1" in out
    assert "... and 2 more change(s) not shown (diff capped by --limit)" in out

    # --compact with --limit: pure JSON of the kept records, no note line
    with pytest.raises(SystemExit) as exc:
        main(['{"a":{"p":1,"q":2},"b":{"r":3}}',
              '{"a":{"p":9,"q":8},"b":{"r":7}}',
              "--limit", "1", "-c", "-q"])
    out = capsys.readouterr().out
    recs = json.loads(out)
    assert isinstance(recs, list) and len(recs) == 1
    assert "not shown" not in out


def test_cli_limit_negative_value_is_unlimited(capsys):
    # negative N is treated as the no-limit sentinel, like 0
    from jsondiff.__main__ import main

    with pytest.raises(SystemExit) as exc:
        main(['{"a":1,"b":2}', '{"a":9,"b":8}', "--limit", "-3", "-q"])
    out = capsys.readouterr().out
    assert "2 difference(s) found:" in out
    assert "not shown" not in out
    assert exc.value.code == 1


def test_cli_limit_one_with_type_change_and_added(capsys):
    # mixed kinds: type change + added key; limit=1 keeps only the first
    from jsondiff.__main__ import main

    with pytest.raises(SystemExit) as exc:
        main(['{"a":1,"b":"x"}', '{"a":[1],"c":5}', "--limit", "1", "-q"])
    out = capsys.readouterr().out
    assert out.strip().splitlines()[0] == "1 difference(s) found:"
    # 3 changes total (type + removed + added); the cap reports the rest
    assert "... and 2 more change(s) not shown (diff capped by --limit)" in out
    # both kinds were suppressed beyond the first record
    assert exc.value.code == 1
