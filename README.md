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

# Change-count summary by kind (added/removed/changed/type + total)
jsondiff --stats old.json new.json

# Diff arrays of objects by a key field instead of position
jsondiff --key id old.json new.json
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

### Change-count summary (`--stats`)

`--stats` replaces the change listing with a per-kind count, useful for
dashboards or CI gates that care about *how much* changed rather than *what*:

```
  added: 1
  removed: 1
  changed: 0
  type: 0
  total: 2
```

All four kinds are always shown (zero-filled), plus a `total`. `--stats` takes
precedence over `--compact` if both are given.

### Keyed array diffing (`--key`)

By default arrays are compared positionally, so reordering or inserting an
element makes everything after it look changed. Pass `--key FIELD` (or
`diff(a, b, key_field="FIELD")` in the library) and any array of objects that
carries `FIELD` is matched by its value instead:

```bash
jsondiff --key id old.json new.json
```

```
3 difference(s) found:
  $.u<id>.n: 'b' -> 'c'
  $.u[1]: - {'id': 1, 'n': 'a'}
  $.u[3]: + {'id': 3, 'n': 'd'}
```

Added/removed elements are reported with their key value in the path; pure
reordering produces no differences. Arrays without the field (or non-object
arrays) still fall back to positional comparison.

## Tests

```bash
python -m pytest tests/ -v
```

## License

MIT — see [LICENSE](LICENSE).
