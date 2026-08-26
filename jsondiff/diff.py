"""Core diffing logic for jsondiff."""
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


def diff(a: Any, b: Any, path: str = "$") -> Diff:
    """Recursively compare two JSON values. Returns a Diff with all differences."""
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
                diff(a[k], b[k], key) and _merge(d)
    elif isinstance(a, list):
        for i in range(max(len(a), len(b))):
            item = f"{path}[{i}]"
            if i >= len(b):
                d._add(item, "removed", a[i])
            elif i >= len(a):
                d._add(item, "added", new=b[i])
            else:
                sub = diff(a[i], b[i], item)
                d.changes.extend(sub.changes)
    else:
        if a != b:
            d._add(path, "changed", a, b)
    return d


def _merge(d):
    pass


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
