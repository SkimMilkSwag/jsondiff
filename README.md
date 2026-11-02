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

# Self-documenting alias for the CI exit-code flag
jsondiff --fail-on-change old.json new.json

# Machine-parseable output: JSON list of change records
jsondiff --compact old.json new.json

# Change-count summary by kind (added/removed/changed/type + total)
jsondiff --stats old.json new.json

# Diff arrays of objects by a key field instead of position
jsondiff --key id old.json new.json

# Restrict the diff to specific keys (inverse of --ignore); a bare name
# matches at every level, a full path like '$.a.b' targets one location
jsondiff --include name,version old.json new.json

# Strict comparison: dict key order and int/float form (1 vs 1.0) are diffs
jsondiff --no-normalize old.json new.json
```

## Output

Human-readable (default):

```
3 difference(s) found:
  $.b: - 2
  $.c: + 3
  $.nested.x: True -> False
```

### Value normalization

By default jsondiff compares values *semantically*: dict key order is ignored
and `1` equals `1.0` (they are the same JSON number), so a re-serialized or
reordered document that changed nothing produces no diff — which is what you
want when gate-checking rendered artifacts against committed copies. Pass
`--no-normalize` to compare the written form instead, where key reordering and
`1` vs `1.0` are reported as changes:

```bash
jsondiff '{"x": 1, "y": 2}' '{"y": 2, "x": 1}'          # clean (normalized)
jsondiff --no-normalize '{"x": 1, "y": 2}' '{"y": 2, "x": 1}'  # 1 difference
```

`--no-normalize` works with every other flag (`--compact`, `--stats`, `-q`).

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

### Restricting the diff to specific keys (`--include`)

`--ignore` suppresses listed keys; `--include` is its inverse — a *leaf*
allowlist that reports only changes to object members whose name (or full JSON
path) is listed, skipping everything else. It's for narrowing a large document
down to one or two fields of interest:

```bash
jsondiff --include name,version old.json new.json
```

A bare name (`name`) matches that key at **every** nesting depth and also covers
a whole array element list (so `--include tags` reports every `tags[i]`
change). A full JSON path (`$.cfg.build`) targets one specific location only.
We still *descend* through non-matching containers, so a deeper listed key is
found — the allowlist gates which changes are **reported**, not which nodes we
walk. `--ignore` and `--include` combine: a member must be in the include set
**and** not ignored. In the library: `diff(a, b, include=frozenset({...}))`.

```bash
# only $.name is reported; build/other are skipped
jsondiff --include name '{"a":1,"b":2}' '{"a":9,"b":3}'   # [] (a not listed)
jsondiff --include a,b   '{"a":1,"b":2}' '{"a":9,"b":3}'  # $.a + $.b changed
```

## CI (GitHub Actions)

`--fail-on-change` makes the tool CI-friendly: exit code 0 when the two JSON
values are identical, 1 when they differ, 2 when a file fails to parse. Wire it
into a workflow to fail a pipeline when a rendered artifact drifts from its
committed copy (or any other "two configs should match" check):

```yaml
# .github/workflows/jsondiff.yml
name: jsondiff
on: [push, pull_request]
jobs:
  diff:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install .
      - name: Fail if rendered.json drifted from committed.json
        run: jsondiff --fail-on-change committed.json rendered.json
```

The exit codes also make it composable in shell pipelines without parsing the
human-readable output — `--compact` emits JSON when you *do* need to inspect
what changed after the gate fails.

## Tests

```bash
python -m pytest tests/ -v
```

## License

MIT — see [LICENSE](LICENSE).
