# jsondiff

A small CLI tool that diffs two JSON values (files or literals) and prints a
human-readable summary of exactly what changed — added keys, removed keys,
type changes, and value changes, with full path traces.

## Install

```bash
pip install -e .
```

## Usage

```bash
# Two files
jsondiff old.json new.json

# Literal JSON strings
jsondiff '{"a":1,"b":2}' '{"a":1,"c":3}'

# Exit code 1 when differences exist (useful in CI)
jsondiff -q before.json after.json && echo "identical" || echo "changed"

# Machine-parseable output: JSON list of change records
jsondiff --compact old.json new.json
```

## Output

Human-readable (default):

```
3 difference(s) found:
  $.b: - 2
  $.c: + 3
  $.nested.x: True -> False
```

`--compact` prints a JSON array instead, for scripting or piping into other
tools. Each record carries the path, change kind, and old/new values (type
changes also include the old/new type names):

```json
[
  {
    "path": "$.c",
    "kind": "added",
    "new": 3
  },
  {
    "path": "$.nested.x",
    "kind": "changed",
    "old": true,
    "new": false
  }
]
```

An identical pair serializes to `[]`.

## Tests

```bash
python -m pytest tests/ -v
```

## License

MIT — see [LICENSE](LICENSE).
