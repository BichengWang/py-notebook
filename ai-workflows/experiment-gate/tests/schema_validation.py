"""Validate decision.json files against the packaged JSON Schemas.

    pip install jsonschema==4.26.0      # development and CI only; expgate itself has no dependencies
    python tests/schema_validation.py records/*/decision.json

Exits 1 when any record violates the schema for its ``schema_version``, 2 when a file cannot be read.
"""
import json
import sys
from pathlib import Path

SCHEMA_DIR = Path(__file__).resolve().parents[1] / "expgate" / "schema"


def load_schema(version: int) -> dict:
    return json.loads((SCHEMA_DIR / f"decision.v{version}.json").read_text(encoding="utf-8"))


def validator(version: int):
    from jsonschema import Draft202012Validator  # imported late so tests can skip cleanly without it
    schema = load_schema(version)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def errors(document, version: int) -> list[str]:
    found = validator(version).iter_errors(document)
    return sorted(f"{'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}" for e in found)


def main(paths) -> int:
    result = 0
    for path in map(Path, paths):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"{path}: cannot read: {exc}", file=sys.stderr)
            result = 2
            continue
        version = document.get("schema_version") if isinstance(document, dict) else None
        if version not in (2, 3) or type(version) is not int:
            print(f"{path}: no schema for schema_version {version!r}", file=sys.stderr)
            result = max(result, 1)
            continue
        problems = errors(document, version)
        for problem in problems:
            print(f"{path}: {problem}", file=sys.stderr)
        print(f"{path}: {'schema-valid' if not problems else 'INVALID'} (schema {version})")
        if problems:
            result = max(result, 1)
    return result


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
