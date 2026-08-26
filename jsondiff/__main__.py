"""CLI entry point for jsondiff."""
import argparse
import json
import sys

from .diff import diff, format_report


def _load(src):
    if src == "-":
        return json.load(sys.stdin)
    with open(src) as f:
        return json.load(f)


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="jsondiff",
        description="Diff two JSON files or JSON strings and print a human-readable summary.",
    )
    p.add_argument("a", help="first JSON file, '-' for stdin, or a literal JSON string")
    p.add_argument("b", help="second JSON file, '-' for stdin, or a literal JSON string")
    p.add_argument("-q", "--quiet", action="store_true", help="exit 0 if no differences, 1 if any")
    args = p.parse_args(argv)

    def try_literal(s):
        try:
            return json.loads(s), True
        except Exception:
            return None, False

    a = _load(args.a) if (not args.a.startswith("{") and not args.a.startswith("[")) else json.loads(args.a)
    b = _load(args.b) if (not args.b.startswith("{") and not args.b.startswith("[")) else json.loads(args.b)
    d = diff(a, b)
    print(format_report(d))
    sys.exit(1 if (args.quiet and d.changes) else 0)


if __name__ == "__main__":
    main()
