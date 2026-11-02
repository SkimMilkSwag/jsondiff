"""Core diffing logic for jsondiff."""
import json
from typing import Any, Dict, List, NamedTuple, Optional, Tuple


class Change(NamedTuple):
    """A single change record: JSON path, kind, and old/new values.

    Kind is one of ``added``/``removed``/``changed``/``type``; the side that
    does not apply (new for removed, old for added) is None.
    """

    path: str
    kind: str
    old: Any = None
    new: Any = None


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


def _json_equal(a: Any, b: Any) -> bool:
    """Semantic JSON equality: ``1 == 1.0``, dict key order irrelevant.

    bool is checked before number because in Python ``True == 1``; keeping
    them distinct matches the ``_type_name`` split used at the top of
    ``diff`` (a bool/number pair is a ``type`` change, not equality).
    """
    if _type_name(a) != _type_name(b):
        return False
    if isinstance(a, dict):
        if a.keys() != b.keys():
            return False
        return all(_json_equal(a[k], b[k]) for k in a)
    if isinstance(a, list):
        if len(a) != len(b):
            return False
        return all(_json_equal(x, y) for x, y in zip(a, b))
    return a == b


def parse_ignore(raw: Optional[str]) -> Optional[frozenset]:
    """Parse a ``--ignore key1,key2`` argument into a frozenset of keys.

    Returns None when ``raw`` is None/empty (no ignoring), so callers can
    keep the fast path without checking membership against an empty set.
    Whitespace around each key is stripped; empty segments are dropped, so
    ``"a,, b "`` parses to ``frozenset({"a", "b"})``.
    """
    if not raw:
        return None
    keys = {k.strip() for k in raw.split(",") if k.strip()}
    return frozenset(keys) or None


def parse_include(raw: Optional[str]) -> Optional[frozenset]:
    """Parse a ``--include key1,key2`` argument into a frozenset of keys.

    The inverse of :func:`parse_ignore`: only object members whose name (or
    full JSON path) appears in the set are diffed — every other member is
    skipped as if it didn't exist on either side. Returns None when ``raw`` is
    None/empty (no restriction, i.e. diff everything). Whitespace handling and
    empty-segment dropping are identical to ``parse_ignore`` so the two flags
    behave symmetrically: ``"a,, b "`` parses to ``frozenset({"a", "b"})``.
    """
    if not raw:
        return None
    keys = {k.strip() for k in raw.split(",") if k.strip()}
    return frozenset(keys) or None


class Diff:
    """Holds a flat list of change records."""

    def __init__(self) -> None:
        self.changes: List[Change] = []

    def _add(self, path: str, kind: str, old: Any = None, new: Any = None) -> None:
        self.changes.append(Change(path, kind, old, new))

    @staticmethod
    def normalize(v: Any) -> str:
        """Canonical string form of a JSON value for equality comparison.

        Uses ``json.dumps`` with sorted keys so that dict key order does not
        produce spurious differences. Numeric int/float equivalence (1 == 1.0)
        is handled separately by ``_json_equal`` — ``json.dumps`` alone cannot
        express it because ``dumps(1)`` and ``dumps(1.0)`` differ.
        """
        if v is None:
            return "null"
        try:
            return json.dumps(v, sort_keys=True)
        except (TypeError, ValueError):
            return repr(v)

    def _add_normalized(self, path: str, kind: str, old: Any = None, new: Any = None) -> None:
        """Add a change only if old and new differ under semantic equality.

        Uses ``_json_equal`` which treats ``1`` and ``1.0`` as the same JSON
        number and ignores dict key order, so neither produces a record. The
        original (un-normalized) values are stored in the record for display.
        """
        if not _json_equal(old, new):
            self.changes.append(Change(path, kind, old, new))


def _project(obj: Any, keys: List[str]) -> Dict[Any, Any]:
    """Project a dict down to only ``keys`` (missing keys are dropped).

    Used by the include/ignore pruning so that the fast-path semantic
    equality check compares the *kept* sub-objects rather than the full
    documents — otherwise a difference confined to a pruned member would
    defeat the ``_json_equal`` early-exit and force a full re-diff.
    """
    if not isinstance(obj, dict):
        return obj
    return {k: obj[k] for k in keys if k in obj}


def _keyed_pairs(
    items_a: List[Any], items_b: List[Any], key_field: str
) -> Tuple[List[Any], List[Any], List[Tuple[Any, Any]]]:
    """Pair elements of two object arrays by value of `key_field`.

    Returns (added, removed, common) where common is a list of (item_a, item_b)
    pairs matched in b's order. Elements missing the key field are never
    matched and end up in added/removed; the caller decides what to do with
    those. Duplicate key values pair up one-to-one in order of appearance.
    """
    def hashable(v: Any) -> bool:
        return v is None or isinstance(v, (str, int, float, bool))

    ia: Dict[Any, List[Any]] = {}
    for x in items_a:
        if isinstance(x, dict) and key_field in x and hashable(x[key_field]):
            ia.setdefault(x[key_field], []).append(x)

    seen_a = set()
    matched_b = set()
    common: List[Tuple[Any, Any]] = []
    for x in items_b:
        if isinstance(x, dict) and key_field in x and hashable(x[key_field]):
            v = x[key_field]
            if v in ia and ia[v]:
                cand = ia[v].pop(0)
                if id(cand) not in seen_a:
                    seen_a.add(id(cand))
                    matched_b.add(id(x))
                    common.append((cand, x))

    added: List[Any] = [x for x in items_b if id(x) not in matched_b]
    removed: List[Any] = [x for x in items_a if id(x) not in seen_a]
    return added, removed, common


def diff(
    a: Any,
    b: Any,
    path: str = "$",
    key_field: Optional[str] = None,
    ignore: Optional[frozenset] = None,
    include: Optional[frozenset] = None,
    normalize: bool = True,
) -> Diff:
    """Recursively compare two JSON values. Returns a Diff with all differences.

    When `normalize` is true (the default), scalar and object values are
    compared under their canonical JSON form — dict key order is ignored and
    ``1`` equals ``1.0`` — so only semantically meaningful changes are
    reported. Pass ``normalize=False`` (CLI flag ``--no-normalize``) to
    treat key-order swaps and int/float differences as real changes.

    When `key_field` is set and both sides are arrays of objects carrying a
    `key_field`, matching elements are diffed pairwise by key (order- and
    position-insensitive); unmatched elements on either side are reported as
    added/removed with their key value in the path.

    When `ignore` is a frozenset of key names, any object member whose name
    appears in the set is skipped at every level (added/removed/changed/type
    alike) — e.g. ``--ignore "build"`` suppresses a fluctuating ``build``
    field wherever it occurs. To target one specific nested path instead,
    pass its full JSON path (e.g. ``--ignore "$.a.b"`` matches only the child
    ``b`` inside object ``a``, leaving any other ``b`` untouched).

    When `include` is a frozenset (the inverse of `ignore`), ONLY object
    members whose name or full JSON path appears in the set are diffed; every
    other member is skipped as if it didn't exist on either side. This is
    useful for narrowing a huge document down to one or two fields of interest
    (``--include "name,version"``). `ignore` and `include` combine: a member
    must pass the include allowlist AND not appear in the ignore set. When
    `include` is set, arrays are still diffed element-by-element as normal —
    the allowlist only prunes object members.
    """
    d = Diff()

    if _type_name(a) != _type_name(b):
        d._add(path, "type", a, b)
        return d

    if isinstance(a, dict):
        # compute the union of keys once; for the root object with an ignore
        # set, filter out ignored names before diffing.
        all_keys = list(a.keys()) + [k for k in b.keys() if k not in a]
        parent = "" if path == "$" else path + "."
        if ignore:
            # A bare name ("build") suppresses that key at every level; a
            # full path ("$.a.b") suppresses only the matching location.  The
            # candidate JSON path for each member is "parent + .k", so both
            # forms fall out of one membership test.
            all_keys = [k for k in all_keys if (k not in ignore and (parent + k) not in ignore)]
        if normalize:
            # semantic mode: same members, no value differences -> silent.
            # When ignore prunes the key set, compare only the kept sub-objects
            # so a difference confined to a pruned member can't force a diff.
            if _json_equal(_project(a, all_keys), _project(b, all_keys)):
                return d
        else:
            # strict mode: key order is part of the document, so a reorder of
            # present keys is itself a change (reported before member diffs)
            if list(a.keys()) != list(b.keys()):
                d._add(path, "changed", a, b)

        def _included(k: str) -> bool:
            # leaf filter: no include set means everything is reported; with
            # one, only a member whose bare name OR full JSON path is listed
            # produces a record (we still descend through non-matching members
            # so a deeper listed key like "$.cfg.build" can be found).
            if not include:
                return True
            return k in include or (parent + k) in include

        for k in all_keys:
            key = f"{path}.{k}"
            if k not in b:
                if _included(k):
                    d._add(key, "removed", a[k])
            elif k not in a:
                if _included(k):
                    d._add(key, "added", new=b[k])
            else:
                sub = diff(a[k], b[k], key, key_field, ignore, include, normalize)
                # keep the subtree's changes; the leaf filter already gates
                # which member-level records are emitted at this depth
                d.changes.extend(sub.changes)
    elif isinstance(a, list):
        if key_field is not None:
            added, removed, common = _keyed_pairs(a, b, key_field)
            for item in common:
                sub = diff(item[0], item[1], f"{path}<{key_field}>", None, ignore, include, normalize)
                d.changes.extend(sub.changes)
            for item in removed:
                v = item[key_field] if isinstance(item, dict) and key_field in item else None
                d._add(f"{path}[{v!r}]", "removed", item)
            for item in added:
                v = item[key_field] if isinstance(item, dict) and key_field in item else None
                d._add(f"{path}[{v!r}]", "added", new=item)
        else:
            for i in range(max(len(a), len(b))):
                item_path = f"{path}[{i}]"
                if i >= len(b):
                    d._add(item_path, "removed", a[i])
                elif i >= len(a):
                    d._add(item_path, "added", new=b[i])
                else:
                    sub = diff(a[i], b[i], item_path, key_field, ignore, include, normalize)
                    d.changes.extend(sub.changes)
    else:
        # scalar leaf (or a node reached through an included member). The
        # include allowlist is a *leaf* filter: a change at ``path`` is only
        # reported when path's last segment or its full JSON form is listed.
        # No include set -> always report.
        if include:
            seg = path.rsplit(".", 1)[-1] if "." in path else path
            # array elements are addressed [i]; the containing key is the last
            # dotted segment before the bracket (e.g. $.tags[2] -> tags), so a
            # bare key in the allowlist covers its whole element list
            if "[" in seg:
                seg = seg.split("[", 1)[0]
                base = seg.rsplit(".", 1)[-1] if "." in seg else seg
                seg = base
            if seg not in include and path not in include:
                return d
        if normalize:
            d._add_normalized(path, "changed", a, b)
        elif repr(a) != repr(b):
            # strict mode compares the written form: 1 vs 1.0 differ even
            # though Python's == treats them as one and the same number
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


def stats_counts(d: Diff) -> Dict[str, int]:
    """Count changes per kind.

    Returns a dict with every change-kind key (added/removed/changed/type)
    present, zero-filled, plus a ``total`` entry for the overall count.
    Kinds are ordered so the printed report is stable.
    """
    order = ["added", "removed", "changed", "type"]
    counts = {k: 0 for k in order}
    for _, kind, _, _ in d.changes:
        if kind not in counts:
            counts[kind] = 0  # defensive: unknown kinds still get counted
        counts[kind] += 1
    counts["total"] = len(d.changes)
    return counts


def format_stats(d: Diff) -> str:
    """Render a one-line-per-kind change summary, e.g. ``--stats`` output."""
    counts = stats_counts(d)
    lines = [f"  {kind}: {counts[kind]}" for kind in ("added", "removed", "changed", "type")]
    lines.append(f"  total: {counts['total']}")
    return "\n".join(lines)
