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
```

## Output

```
3 difference(s) found:
  $.b: - 2
  $.c: + 3
  $.nested.x: True -> False
```

## Tests

```bash
python -m pytest tests/ -v
```

## License

MIT — see [LICENSE](LICENSE).
