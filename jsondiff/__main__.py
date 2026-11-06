"""CLI entry point for jsondiff."""
import argparse
import json
import sys
from typing import Any, Callable, List, Optional

from .diff import (
    diff,
    format_report,
    format_json,
    format_stats,
    format_summary,
    parse_ignore,
    parse_include,
)


class ParseError(Exception):
    """A JSON input could not be parsed. Carries the parse error's
    ``line`` / ``column`` (from ``json.JSONDecodeError``) plus a short
    human-readable ``where`` label in the message."""

    def __init__(self, where: str, exc: "json.JSONDecodeError"):
        self.where = where
        self.msg = exc.msg
        self.line = exc.lineno
        self.column = exc.colno
        super().__init__(f"{where}: line {exc.lineno}, column {exc.colno} — {exc.msg}")


def _load(src: str) -> Any:
    if src == "-":
        try:
            return json.load(sys.stdin)
        except json.JSONDecodeError as e:
            raise ParseError("<stdin>", e) from None
    try:
        with open(src) as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        raise ParseError(src, e) from None


def _leaf_filter(include: Optional[frozenset[str]], include_wild: Optional[frozenset[str]] = None) -> Optional[Callable[[str], bool]]:
    """Build the leaf-reporting filter for an ``--include`` set.

    A change at ``path`` is reported when its last dotted segment (array
    brackets stripped — ``$.tags[2]`` -> ``tags``, so a bare key covers its
    whole element list) or the full path appears in ``include``, or an
    include wildcard pattern claims it (same location-scoped semantics as
    object-member claiming: ``"$.a.*"`` reaches array elements under ``a``'s
    claimed members). Returns None when neither half of the include set is
    set, meaning report everything.
    """

    def _filter(path: str) -> bool:
        seg = path.rsplit(".", 1)[-1] if "." in path else path
        if "[" in seg:
            seg = seg.split("[", 1)[0]
            base = seg.rsplit(".", 1)[-1] if "." in seg else seg
            seg = base
        if include and (seg in include or path in include):
            return True
        if include_wild is not None:
            # same location check as _member_matches: a pattern claims a
            # member when its location equals the object containing that
            # member — the path up to (not including) the last dot, with any
            # array-index suffix ("items[3]") stripped off.
            parent = path.rsplit(".", 1)[0] if "." in path else "$"
            if "[" in parent:
                parent = parent.split("[", 1)[0]
            from .diff import _member_matches
            if _member_matches(include_wild, seg, parent):
                return True
        return False

    return _filter if (include or include_wild) else None


def main(argv: Optional[List[str]] = None) -> None:
    p = argparse.ArgumentParser(
        prog="jsondiff",
        description="Diff two JSON files or JSON strings and print a human-readable summary.",
    )
    p.add_argument("a", help="first JSON file, '-' for stdin, or a literal JSON string")
    p.add_argument("b", help="second JSON file, '-' for stdin, or a literal JSON string")
    p.add_argument(
        "-q",
        "--quiet",
        "--fail-on-change",
        dest="quiet",
        action="store_true",
        help="exit 1 when differences exist, 0 when clean (CI-friendly); "
             "--fail-on-change is a self-documenting alias for -q",
    )
    p.add_argument(
        "-c",
        "--compact",
        action="store_true",
        help="print machine-parseable output: a JSON list of change records",
    )
    p.add_argument(
        "-k",
        "--key",
        metavar="FIELD",
        help="match array elements by FIELD value instead of position "
        "(applies to every array of objects that carries the field)",
    )
    p.add_argument(
        "-i",
        "--ignore",
        metavar="KEYS",
        help="comma-separated key names to skip in the diff (applies at "
        "every nesting level; a full JSON path like '$.a.b' targets only that "
        "location; a trailing '*' like '$.a.*' matches every member of object "
        "'a' at that location)",
    )
    p.add_argument(
        "--include",
        metavar="KEYS",
        help="comma-separated key names to RESTRICT the diff to (the inverse "
        "of --ignore): only object members whose name or full JSON path is in "
        "the list are compared; everything else is skipped. A bare name applies "
        "at every level; a full path like '$.a.b' targets one location; a "
        "trailing '*' like '$.a.*' matches every member of object 'a'",
    )
    p.add_argument(
        "-s",
        "--stats",
        action="store_true",
        help="print a change-count summary (added/removed/changed/type + total)",
    )
    p.add_argument(
        "--summary",
        action="store_true",
        help="print a per-top-level-key table of added/removed/changed/type "
             "counts for quick CI triage (takes precedence over --stats/--compact)",
    )
    p.add_argument(
        "-N",
        "--no-normalize",
        action="store_true",
        help="compare values exactly as written: dict key order and the "
             "int/float distinction (1 vs 1.0) are treated as differences",
    )
    args = p.parse_args(argv)

    def load_arg(name: str, src: str) -> Any:
        """Load one CLI argument as JSON.

        Literal-looking strings (starting with ``{`` or ``[``) are parsed in
        place; everything else is treated as a file path (``-`` for stdin).
        A malformed input raises ``ParseError`` carrying the line and column
        of the syntax problem, so the caller can point the user at it.
        """
        if src.startswith("{") or src.startswith("["):
            try:
                return json.loads(src)
            except json.JSONDecodeError as e:
                raise ParseError(f"literal JSON ({name})", e) from None
        return _load(src)

    try:
        a = load_arg("a", args.a)
    except ParseError as e:
        print(f"jsondiff: error parsing {e.where}: line {e.line}, column {e.column} — {e.msg}", file=sys.stderr)
        sys.exit(2)
    try:
        b = load_arg("b", args.b)
    except ParseError as e:
        print(f"jsondiff: error parsing {e.where}: line {e.line}, column {e.column} — {e.msg}", file=sys.stderr)
        sys.exit(2)
    inc_exact, inc_wild = parse_include(args.include)
    d = diff(
        a, b, key_field=args.key,
        ignore=parse_ignore(args.ignore)[0], ignore_wild=parse_ignore(args.ignore)[1],
        include=inc_exact, include_leaf=_leaf_filter(inc_exact, inc_wild), include_wild=inc_wild,
        normalize=not args.no_normalize,
    )
    if args.summary:
        print(format_summary(d))
    elif args.stats:
        print(format_stats(d))
    elif args.compact:
        print(format_json(d))
    else:
        print(format_report(d))
    sys.exit(1 if (args.quiet and d.changes) else 0)


if __name__ == "__main__":
    main()
