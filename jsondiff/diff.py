"""Core diffing logic for jsondiff."""
import json
from typing import Any


def _type_name(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, (int, float)):
        return "number"
    if isinstance(v, str):
        return "string"
    if isinstance(v, list):
        return "array"
    if isinstance(v, dict):
        return "object"
    return type(v).__name__


class Diff:
    """Holds a flat list of change records."""

    def __init__(self):
        self.changes = []  # list of (path, kind, old, new)

    def _add(self, path, kind, old=None, new=None):
        self.changes.append((path, kind, old, new))


def _keyed_pairs(items_a: list, items_b: list, key_field: str):
    """Pair elements of two object arrays by value of `key_field`.

    Returns (added, removed, common) where common is a list of (item_a, item_b)
    pairs matched in b's order. Elements missing the key field are never
    matched and end up in added/removed; the caller decides what to do with
    those. Duplicate key values pair up one-to-one in order of appearance.
    """
    def hashable(v):
        return v is None or isinstance(v, (str, int, float, bool))

    ia = {}
    for x in items_a:
        if isinstance(x, dict) and key_field in x and hashable(x[key_field]):
            ia.setdefault(x[key_field], []).append(x)

    seen_a = set()
    matched_b = set()
    common = []
    for x in items_b:
        if isinstance(x, dict) and key_field in x and hashable(x[key_field]):
            v = x[key_field]
            if v in ia and ia[v]:
                cand = ia[v].pop(0)
                if id(cand) not in seen_a:
                    seen_a.add(id(cand))
                    matched_b.add(id(x))
                    common.append((cand, x))

    added = [x for x in items_b if id(x) not in matched_b]
    removed = [x for x in items_a if id(x) not in seen_a]
    return added, removed, common


def diff(a: Any, b: Any, path: str = "$", key_field: str = None) -> Diff:
    """Recursively compare two JSON values. Returns a Diff with all differences.

    When `key_field` is set and both sides are arrays of objects carrying a
    `key_field`, matching elements are diffed pairwise by key (order- and
    position-insensitive); unmatched elements on either side are reported as
    added/removed with their key value in the path.
    """
    d = Diff()

    if _type_name(a) != _type_name(b):
        d._add(path, "type", a, b)
        return d

    if isinstance(a, dict):
        for k in list(a.keys()) + [k for k in b.keys() if k not in a]:
            key = f"{path}.{k}"
            if k not in b:
                d._add(key, "removed", a[k])
            elif k not in a:
                d._add(key, "added", new=b[k])
            else:
                sub = diff(a[k], b[k], key, key_field)
                d.changes.extend(sub.changes)
    elif isinstance(a, list):
        if key_field is not None:
            added, removed, common = _keyed_pairs(a, b, key_field)
            for item in common:
                sub = diff(item[0], item[1], f"{path}<{key_field}>")
                d.changes.extend(sub.changes)
            for item in removed:
                v = item[key_field] if isinstance(item, dict) and key_field in item else None
                d._add(f"{path}[{v!r}]", "removed", item)
            for item in added:
                v = item[key_field] if isinstance(item, dict) and key_field in item else None
                d._add(f"{path}[{v!r}]", "added", new=item)
        else:
            for i in range(max(len(a), len(b))):
                item = f"{path}[{i}]"
                if i >= len(b):
                    d._add(item, "removed", a[i])
                elif i >= len(a):
                    d._add(item, "added", new=b[i])
                else:
                    sub = diff(a[i], b[i], item, key_field)
                    d.changes.extend(sub.changes)
    else:
        if a != b:
            d._add(path, "changed", a, b)
    return d


def format_json(d: Diff) -> str:
    """Serialize a Diff as a JSON list of change records.

    Each record has: path, kind (added/removed/changed/type), and the
    old/new values (one or both may be null). Empty diff serializes to [].
    """
    out = []
    for path, kind, old, new in d.changes:
        rec = {"path": path, "kind": kind}
        if kind == "added":
            rec["new"] = new
        elif kind == "removed":
            rec["old"] = old
        else:  # changed or type
            rec["old"] = old
            rec["new"] = new
            if kind == "type":
                rec["old_type"] = _type_name(old)
                rec["new_type"] = _type_name(new)
        out.append(rec)
    return json.dumps(out, indent=2)


def format_report(d: Diff) -> str:
    """Render a Diff as human-readable text."""
    if not d.changes:
        return "No differences."
    lines = []
    for path, kind, old, new in d.changes:
        if kind == "type":
            lines.append(f"  {path}: type changed ({_type_name(old)} -> {_type_name(new)})")
        elif kind == "added":
            lines.append(f"  {path}: + {new!r}")
        elif kind == "removed":
            lines.append(f"  {path}: - {old!r}")
        else:
            lines.append(f"  {path}: {old!r} -> {new!r}")
    header = f"{len(d.changes)} difference(s) found:"
    return header + "\n" + "\n".join(lines)
