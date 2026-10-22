"""CLI entry point for jsondiff."""
import argparse
import json
import sys
from typing import Any, List, Optional

from .diff import diff, format_report, format_json, format_stats, parse_ignore


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
        "location)",
    )
    p.add_argument(
        "-s",
        "--stats",
        action="store_true",
        help="print a change-count summary (added/removed/changed/type + total)",
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
    d = diff(a, b, key_field=args.key, ignore=parse_ignore(args.ignore))
    if args.stats:
        print(format_stats(d))
    elif args.compact:
        print(format_json(d))
    else:
        print(format_report(d))
    sys.exit(1 if (args.quiet and d.changes) else 0)


if __name__ == "__main__":
    main()
