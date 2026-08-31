"""CLI entry point for jsondiff."""
import argparse
import json
import sys
from typing import Any, List, Optional, Tuple

from .diff import diff, format_report, format_json, format_stats


def _load(src: str) -> Any:
    if src == "-":
        return json.load(sys.stdin)
    with open(src) as f:
        return json.load(f)


def main(argv: Optional[List[str]] = None) -> None:
    p = argparse.ArgumentParser(
        prog="jsondiff",
        description="Diff two JSON files or JSON strings and print a human-readable summary.",
    )
    p.add_argument("a", help="first JSON file, '-' for stdin, or a literal JSON string")
    p.add_argument("b", help="second JSON file, '-' for stdin, or a literal JSON string")
    p.add_argument("-q", "--quiet", action="store_true", help="exit 0 if no differences, 1 if any")
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
        "-s",
        "--stats",
        action="store_true",
        help="print a change-count summary (added/removed/changed/type + total)",
    )
    args = p.parse_args(argv)

    def try_literal(s: str) -> Tuple[Any, bool]:
        try:
            return json.loads(s), True
        except Exception:
            return None, False

    a = _load(args.a) if (not args.a.startswith("{") and not args.a.startswith("[")) else json.loads(args.a)
    b = _load(args.b) if (not args.b.startswith("{") and not args.b.startswith("[")) else json.loads(args.b)
    d = diff(a, b, key_field=args.key)
    if args.stats:
        print(format_stats(d))
    elif args.compact:
        print(format_json(d))
    else:
        print(format_report(d))
    sys.exit(1 if (args.quiet and d.changes) else 0)


if __name__ == "__main__":
    main()
