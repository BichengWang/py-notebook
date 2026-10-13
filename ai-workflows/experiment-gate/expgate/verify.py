"""Re-evaluate schema-2 decision records offline with the running version."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .decision import evaluate
from .records import canonical_json, input_digest


def verify_record(record: dict) -> list[str]:
    """Return mismatched fields; raise ValueError for invalid or legacy records."""
    if not isinstance(record, dict):
        raise ValueError("decision record must be a JSON object")
    schema = record.get("schema_version", 1)
    if schema == 1:
        raise ValueError("schema 1 cannot be verified: no embedded input")
    if type(schema) is not int or schema != 2:
        raise ValueError("unsupported schema_version; expected 2")
    producer = record.get("produced_by")
    if (not isinstance(producer, dict) or producer.get("name") != "expgate"
            or not isinstance(producer.get("version"), str)):
        raise ValueError("invalid produced_by")
    if not isinstance(record.get("input"), dict) or not isinstance(record.get("input_sha256"), str):
        raise ValueError("record needs input and input_sha256")
    for field in ("decision", "reasons", "metrics", "experiment", "policy", "sample_ratio"):
        if field not in record:
            raise ValueError(f"record missing {field}")
    mismatches = []
    if record["input_sha256"] != input_digest(record["input"]):
        mismatches.append("input_sha256")
    try:
        replay = evaluate(record["input"])
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        if mismatches:
            return mismatches + ["input (cannot replay)"]
        raise ValueError(f"invalid embedded input: {exc}") from exc
    for field in ("decision", "reasons", "metrics", "experiment", "policy", "sample_ratio", "sequential"):
        if canonical_json(record.get(field)) != canonical_json(replay.get(field)):
            mismatches.append(field)
    return mismatches


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("records", type=Path, nargs="+", metavar="DECISION_JSON")
    args = parser.parse_args(argv)
    result = 0
    for path in args.records:
        try:
            mismatches = verify_record(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError, OverflowError) as exc:
            print(f"{path}: cannot verify: {exc}", file=sys.stderr)
            result = 2
            continue
        if mismatches:
            print(f"{path}: mismatch: {', '.join(mismatches)}")
            result = max(result, 1)
        else:
            print(f"{path}: verified")
    return result


if __name__ == "__main__":
    raise SystemExit(main())
