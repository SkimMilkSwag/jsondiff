"""Core diffing logic for jsondiff."""
import json
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Tuple


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
    return a == b  # type: ignore[no-any-return]


def parse_ignore(raw: Optional[str]) -> Tuple[Optional[frozenset[str]], Optional[frozenset[str]]]:
    """Parse a ``--ignore key1,key2`` argument into (exact_keys, wildcards).

    ``exact_keys`` holds bare names and literal full JSON paths — the original
    contract: a bare name (``"build"``) suppresses that key at every level and
    a full path (``"$.a.b"``) suppresses one location. ``wildcards`` holds
    patterns whose last segment is ``*`` (e.g. ``"$.a.*"``) which match any
    member of that object. Returns ``(None, None)`` when ``raw`` is None/empty
    (no ignoring), so callers keep the fast path. Whitespace around each key is
    stripped; empty segments are dropped, so ``"a,, b "`` parses to
    ``(frozenset({"a", "b"}), None)``.
    """
    if not raw:
        return None, None
    keys = {k.strip() for k in raw.split(",") if k.strip()}
    exact = frozenset(k for k in keys if "*" not in k) or None
    wild = frozenset(k for k in keys if "*" in k) or None
    return exact, wild


def parse_include(raw: Optional[str]) -> Tuple[Optional[frozenset[str]], Optional[frozenset[str]]]:
    """Parse a ``--include key1,key2`` argument into (exact_keys, wildcards).

    The inverse of :func:`parse_ignore`: only object members claimed by an
    exact name/path or a wildcard pattern are diffed — everything else is
    skipped as if it didn't exist on either side. Wildcard patterns use the
    same ``$.a.*`` form as ignore. Returns ``(None, None)`` when ``raw`` is
    None/empty (no restriction, i.e. diff everything). Whitespace handling and
    empty-segment dropping are identical to ``parse_ignore`` so the two flags
    behave symmetrically: ``"a,, b "`` parses to
    ``(frozenset({"a", "b"}), None)``.
    """
    if not raw:
        return None, None
    keys = {k.strip() for k in raw.split(",") if k.strip()}
    exact = frozenset(k for k in keys if "*" not in k) or None
    wild = frozenset(k for k in keys if "*" in k) or None
    return exact, wild


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


def _member_matches(wildcards: frozenset[str], name: str, path: str) -> bool:
    """True when a member of the object located at ``path`` is claimed by a
    wildcard pattern.

    A pattern is a full JSON path whose LAST segment is the wildcard ``*``
    (e.g. ``$.a.*`` or ``$.items[1].meta.*``): it claims every direct member of
    the object at that location, and nothing deeper — ``$.a.*`` does not reach
    ``$.a.b.c``. Patterns whose last segment is not exactly ``*`` are literal
    paths and never match here (the caller's exact-name test handles those).
    """
    for pat in wildcards:
        # the final segment of a JSON path is everything after its last ".";
        # a pattern qualifies only when that segment is exactly "*"
        if pat.rpartition(".")[2] != "*":
            continue
        # location prefix: drop the trailing ".<star>" — "$.cfg.*" -> "$.cfg",
        # "$.items[0].meta.*" -> "$.items[0].meta" (brackets are part of it)
        loc = pat[: -len(".*")]
        if path == loc:
            return True
    return False


def _project(obj: Any, keys: List[str]) -> Dict[Any, Any]:
    """Project a dict down to only ``keys`` (missing keys are dropped).

    Used by the include/ignore pruning so that the fast-path semantic
    equality check compares the *kept* sub-objects rather than the full
    documents — otherwise a difference confined to a pruned member would
    defeat the ``_json_equal`` early-exit and force a full re-diff.
    """
    if not isinstance(obj, dict):
        return obj  # type: ignore[no-any-return]
    return {k: obj[k] for k in keys if k in obj}


def _prune_dict(obj: Any, keep: Callable[[str], bool]) -> Any:
    """Project a dict down to the members ``keep(name)`` accepts.

    The include/wildcard version of :func:`_project`: same purpose (make the
    fast-path ``_json_equal`` compare only kept members), but the member test
    is a predicate so wildcard patterns can be applied per location.
    """
    if not isinstance(obj, dict):
        return obj
    return {k: v for k, v in obj.items() if keep(k)}


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
    ignore: Optional[frozenset[str]] = None,
    ignore_wild: Optional[frozenset[str]] = None,
    include: Optional[frozenset[str]] = None,
    include_leaf: Optional[Callable[[str], bool]] = None,
    include_wild: Optional[frozenset[str]] = None,
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

    Wildcard patterns in `ignore` / `include` (via ``ignore_wild`` /
    ``include_wild``, the second half of :func:`parse_ignore` /
    :func:`parse_include`) extend this: a pattern like ``"$.a.*"`` claims every
    member of object ``a`` at that location. The star matches exactly one
    member name — ``"$.a.*"`` does not reach into ``a``'s nested children, and
    patterns with an un-starred last segment are treated as literal paths.

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
        # prefix that turns a member name into its full JSON path. At the root
        # "$" it is "" (a root member's candidate path is just "<name>", which
        # matches bare-name entries in the ignore set); deeper down it is this
        # object's own path + ".".
        parent = "" if path == "$" else path + "."

        # Precompute whether this object has any add/remove members (structural
        # change). Used by the ignore-wildcard rule below: when a wildcard
        # claims all members of a structurally-changed object, value changes
        # to claimed members are still reported.
        _has_structural = any(k not in b for k in a) or any(k not in a for k in b)

        def _member_kept(k: str) -> bool:
            """Whether member ``k`` at ``parent+k`` survives ignore/include.

            ignore wins over include (the documented combination rule): a
            member is dropped when its exact name/path is in the ignore set or
            a wildcard claims it; otherwise, when an include set exists, it is
            kept if its bare name appears at this level (the documented
            every-depth behaviour of --include), its full JSON path is listed,
            or an include wildcard claims it. Wildcards are location-scoped —
            see :func:`_member_matches`.

            For *descent* purposes (members present on both sides), the
            include allowlist does NOT block the walk: we still descend
            through unclaimed containers so a deeper listed key like
            ``"$.cfg.build"`` can be found. The include filter gates only
            added/removed record emission at this level and, at the scalar
            leaf, whether the change is reported (via ``include_leaf``).
            """
            full = parent + k
            # ignore wins over include: an ignored member is dropped entirely
            # (no descent, no record) before the include allowlist can see it.
            if ignore is not None and (k in ignore or full in ignore):
                return False
            if ignore_wild is not None:
                # _member_matches claims a member when a wildcard's location
                # equals this object's own path — "$.cfg.*" drops every child
                # of $.cfg (and nothing deeper: it never reaches
                # $.cfg.nested.x). See :func:`_member_matches`.
                if _member_matches(ignore_wild, k, path):
                    # Wildcard-claimed member: suppressed for add/remove
                    # records always. For value changes (present on both
                    # sides), suppressed UNLESS the object also has
                    # structural changes (add/remove siblings) — in that case
                    # the caller wants to know what else moved.
                    if k in a and k in b:
                        return _has_structural
                    return False
            # No include set: everything survives.
            if include is None and include_wild is None:
                return True
            # Include allowlist active: a member is *claimed* when its bare
            # name, full path, or a wildcard pattern matches. Claimed members
            # are always kept; unclaimed members present on both sides are
            # also kept so the walk descends through them (a deeper listed key
            # like ``"$.cfg.build"`` must be reachable). The caller gates
            # added/removed emission via :func:`_member_claimed`.
            if (include is not None and (k in include or full in include)):
                return True
            if include_wild is not None and _member_matches(include_wild, k, path):
                return True
            # unclaimed: keep for descent if present on both sides
            return k in a and k in b

        def _member_claimed(k: str) -> bool:
            """Whether member ``k`` is claimed by the include allowlist.

            Used to gate added/removed record emission: an unclaimed member
            that appears on only one side is skipped (no record), but we
            still descended through it when present on both sides.
            """
            if include is None and include_wild is None:
                return True
            full = parent + k
            return (
                (include is not None and (k in include or full in include))
                or (include_wild is not None and _member_matches(include_wild, k, path))
            )

        # fast-path comparison must see exactly the members the walk below
        # would report: pruned (ignored) members are dropped on both sides.
        # The include allowlist is NOT applied here — it gates leaf reporting
        # via descent, so pruning a non-claimed container (e.g. "outer" when
        # only "v" is claimed) would swallow the claimed leaves inside it.
        # When wildcard patterns are in play, per-member suppression is
        # location-dependent and the walk's scalar-level reporting (value
        # changes to claimed members that exist on both sides) can't be
        # predicted by a simple prune-and-compare, so skip the shortcut.
        has_wild = ignore_wild is not None or include_wild is not None
        if normalize and not has_wild:
            # semantic mode: same kept members, no value differences -> silent.
            def _fast_kept(k: str) -> bool:
                full = parent + k
                if ignore is not None and (k in ignore or full in ignore):
                    return False
                if ignore_wild is not None and _member_matches(ignore_wild, k, path):
                    return False
                return True

            if _json_equal(_prune_dict(a, _fast_kept), _prune_dict(b, _fast_kept)):
                return d
        elif not normalize:
            # strict mode: key order is part of the document, so a reorder of
            # present keys is itself a change (reported before member diffs).
            if list(a.keys()) != list(b.keys()):
                d._add(path, "changed", a, b)

        for k in all_keys:
            key = f"{path}.{k}"
            # ignore gates the walk entirely; include gates record emission
            # (added/removed) but not descent through present-on-both-sides
            # containers, so a deeper claimed key can still be found.
            if not _member_kept(k):
                continue
            if k not in b:
                # removed: emit only when the member is claimed by include;
                # ignore-wildcard-claimed members are always suppressed.
                if _member_claimed(k):
                    d._add(key, "removed", a[k])
            elif k not in a:
                # added: same claim gate
                if _member_claimed(k):
                    d._add(key, "added", new=b[k])
            else:
                sub = diff(
                    a[k], b[k], key, key_field,
                    ignore, ignore_wild, include, include_leaf, include_wild, normalize,
                )
                d.changes.extend(sub.changes)
    elif isinstance(a, list):
        if key_field is not None:
            added, removed, common = _keyed_pairs(a, b, key_field)
            for item in common:
                sub = diff(
                    item[0], item[1], f"{path}<{key_field}>", None,
                    ignore, ignore_wild, include, include_leaf, include_wild, normalize,
                )
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
                    sub = diff(
                        a[i], b[i], item_path, key_field,
                        ignore, ignore_wild, include, include_leaf, include_wild, normalize,
                    )
                    d.changes.extend(sub.changes)
    else:
        # scalar leaf (or a node reached through an included member). When an
        # include allowlist is active, a change at ``path`` is only reported if
        # it is claimed by the allowlist. The CLI passes a pre-built
        # ``include_leaf`` filter; library callers that set ``include`` but not
        # ``include_leaf`` get the same filtering applied inline (bare-name
        # matching at every depth, full-path matching, and the documented
        # bare-key-covers-its-element-list behaviour for array elements).
        if include_leaf is not None:
            if not include_leaf(path):
                return d
        elif include is not None or include_wild is not None:
            seg = path.rsplit(".", 1)[-1] if "." in path else path
            if "[" in seg:
                seg = seg.split("[", 1)[0]
                base = seg.rsplit(".", 1)[-1] if "." in seg else seg
                seg = base
            claimed = (
                (include is not None and (seg in include or path in include))
                or (include_wild is not None and _member_matches(include_wild, seg, path.rsplit(".", 1)[0] if "." in path else "$"))
            )
            if not claimed:
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


def _top_segment(path: str) -> str:
    """First top-level key of a JSON path like ``$.a.b`` or ``$.items[2].x``.

    Returns the first dotted key after ``$`` (e.g. ``a``, ``items``). Array
    brackets are dropped — a change deep in a top-level array rolls up to the
    array's own name. A path with no leading ``$.`` (or an empty one) yields
    the raw remainder, so nothing is silently dropped.
    """
    p = path
    if p.startswith("$."):
        p = p[2:]
    return p.split(".", 1)[0].split("[", 1)[0] or path


def summary_counts(d: Diff) -> Dict[str, Dict[str, int]]:
    """Count changes per top-level key, grouped by kind.

    For every change, the first top-level segment of its path (see
    :func:`_top_segment`) is used as the row key. The result maps each row to
    a zero-filled ``{added, removed, changed, type}`` counter; rows appear in
    the order their first change is encountered, which follows diff output
    order and is stable for identical inputs. A change whose path does not
    start with ``$`` (shouldn't happen for a well-formed Diff) lands under
    that raw path so nothing is silently dropped.
    """
    order = ["added", "removed", "changed", "type"]
    rows: Dict[str, Dict[str, int]] = {}
    for path, kind, _, _ in d.changes:
        seg = _top_segment(path)
        if seg not in rows:
            rows[seg] = {k: 0 for k in order}
        rows[seg][kind] += 1
    return rows


def format_summary(d: Diff) -> str:
    """Render a per-top-level-key change table, e.g. ``--summary`` output.

    One line per top-level key with added/removed/changed/type counts and a
    per-key total, followed by a grand total over all keys. Useful for CI
    triage of large documents: it answers *which* sections moved, not the
    individual change list. A clean diff prints ``No differences.``.
    """
    if not d.changes:
        return "No differences."
    rows = summary_counts(d)
    lines = ["key                     added  removed  changed  type   total"]
    grand = {k: 0 for k in ("added", "removed", "changed", "type")}
    for seg, counts in rows.items():
        total = sum(counts.values())
        for k in grand:
            grand[k] += counts[k]
        lines.append(
            f"{seg:<23} {counts['added']:<8} {counts['removed']:<9} "
            f"{counts['changed']:<9} {counts['type']:<7} {total}"
        )
    grand_total = sum(grand.values())
    lines.append(
        f"{'TOTAL':<23} {grand['added']:<8} {grand['removed']:<9} "
        f"{grand['changed']:<9} {grand['type']:<7} {grand_total}"
    )
    return "\n".join(lines)
