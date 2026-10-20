#!/usr/bin/env python3
"""Regenerate the decision-record conformance vectors (standard library only, deterministic).

    python3 conformance/generate.py            # rewrite valid/, tampered/, invalid/ and manifest.json
    python3 conformance/generate.py --check    # exit 1 if the committed tree differs from a fresh generation

Valid vectors are real records: ``experiment-gate`` output for the synthetic scenarios and examples, in
schema 3 (RFC 8785) and schema 2 (python-json-v1). Tampered and invalid vectors are derived from them by the
named edits recorded in each vector's ``note``. There are no timestamps or random values; the records carry
the producer version, so regenerate after a version bump or any change to the statistics.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from expgate.decision import evaluate  # noqa: E402
from expgate.generator import generate  # noqa: E402
from expgate.jcs import canonicalize  # noqa: E402
from expgate.records import canonical_json  # noqa: E402
from expgate.run import record_bytes  # noqa: E402
from expgate.verify import _agree  # noqa: E402

SCHEMAS = {2: "expgate/schema/decision.v2.json", 3: "expgate/schema/decision.v3.json"}
CANONICALIZATION = {2: "python-json-v1", 3: "rfc8785"}
VERIFY = ["experiment-gate-verify", "{path}"]
EXIT = {"valid": 0, "tampered": 1, "invalid": 2}


def edge_summary() -> dict:
    """An input where RFC 8785 and python-json-v1 disagree.

    ``40.0``-style numbers, ``1e-7`` exponents, and member names whose UTF-16 order differs from their code
    point order (U+FF5E sorts after U+1F600 in UTF-16 but before it by code point).
    """
    def arm(units, primary_mean, guardrail_mean):
        return {"units": units, "metrics": {
            "\uff5e": {"mean": primary_mean, "sd": 12.5},
            "\U0001f600": {"mean": guardrail_mean, "sd": 3e-7},
        }}
    return {
        "experiment": "jcs-edge \U0001f600",
        "description": "Escapes and non-ASCII text: <&> \u2028 \u00e9 \U0001f600 / \" \\ \u0007",
        "seed": 7,
        "metrics": {
            "\uff5e": {"type": "mean", "role": "primary", "direction": "increase"},
            "\U0001f600": {"type": "mean", "role": "guardrail", "direction": "decrease", "margin": 5.0},
        },
        "arms": {"control": arm(20000, 40.0, 1e-7), "treatment": arm(20000, 40.5, 2e-7)},
    }


def pretty(record: dict) -> str:
    return record_bytes(record).decode("utf-8")


def digest(value: object, schema: int) -> str:
    data = canonicalize(value) if schema == 3 else canonical_json(value).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def sources() -> dict[str, dict]:
    """Experiment summaries behind the valid vectors, keyed by vector stem."""
    ratio = json.loads((ROOT / "examples" / "ratio.json").read_text(encoding="utf-8"))
    return {
        "ship": generate("win"),
        "hold": generate("flat"),
        "rollback": generate("guardrail-breach"),
        "regression": generate("regression"),
        "srm": generate("srm"),
        "sequential": generate("early-regression"),
        "cuped": generate("cuped"),
        "ratio": ratio,
        "jcs-edge": edge_summary(),
    }


# Which sources each schema version publishes. Schema 2 keeps the 0.1.0 tail formulas (the srm vector has
# p_value 0.0); both schemas replay with the same 1e-9 relative tolerance, so multi-guardrail and sequential
# records verify on any platform.
VALID = {
    3: ["ship", "hold", "rollback", "srm", "cuped", "sequential", "ratio", "jcs-edge"],
    2: ["ship", "hold", "rollback", "regression", "srm", "sequential", "jcs-edge"],
}

NOTES = {
    "ship": "SHIP on the win scenario",
    "hold": "HOLD on the flat scenario",
    "rollback": "ROLLBACK on the guardrail-breach scenario",
    "regression": "ROLLBACK on the regression scenario",
    "srm": "INVALID decision (sample-ratio mismatch) on the srm scenario",
    "cuped": "CUPED-adjusted mean metric with covariates",
    "sequential": "interim look of a sequentially monitored test",
    "ratio": "ratio metric from examples/ratio.json",
    "jcs-edge": "input with integral floats, 1e-7 exponents, escapes and members whose UTF-16 order differs from code point order",
}


class Tree:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.vectors: list[dict] = []

    def add(self, path: str, data: bytes | str, expect: str, note: str, schema: int | None, *,
            schema_valid: bool | None = None, digests: list[dict] | None = None) -> None:
        self.files[path] = data.encode("utf-8") if isinstance(data, str) else data
        vector = {"path": path, "expect": expect, "verify": {"command": VERIFY, "exit_code": EXIT[expect]}}
        if schema is not None and schema_valid is not None:
            vector["documents"] = [{"path": ".", "schema": SCHEMAS[schema], "schema_valid": schema_valid}]
        if digests:
            vector["digests"] = digests
        vector["note"] = note
        self.vectors.append(vector)


def build() -> dict[str, bytes]:
    tree = Tree()
    summaries = sources()
    records: dict[tuple[int, str], dict] = {}

    for schema, stems in VALID.items():
        for stem in stems:
            record = evaluate(summaries[stem], schema_version=schema)
            records[(schema, stem)] = record
            name = f"decision-v{schema}-{stem}"
            canonical = f"valid/{name}.input.canonical"
            tree.files[canonical] = (canonicalize(record["input"]) if schema == 3
                                     else canonical_json(record["input"]).encode("utf-8"))
            tree.add(f"valid/{name}.json", record_bytes(record), "valid",
                     f"schema {schema}: {NOTES[stem]}; "
                     f"input digest is {CANONICALIZATION[schema]}", schema,
                     schema_valid=True, digests=[{
                         "document": ".", "value": "/input_sha256", "covers": "/input", "exclude": [],
                         "canonicalization": CANONICALIZATION[schema], "canonical_file": canonical}])

    for schema in (3, 2):
        base = records[(schema, "ship")]
        label = f"schema {schema}"

        def derive(edit, redigest=False):
            record = copy.deepcopy(base)
            edit(record)
            if redigest:
                record["input_sha256"] = digest(record["input"], schema)
            return record

        def more_treatment_successes(record):
            record["input"]["arms"]["treatment"]["metrics"]["conversion"]["successes"] += 400

        def decision_to_hold(record):
            record["decision"] = "HOLD"

        def inflate_lower_bound(record):
            record["metrics"][0]["improvement_bounds"][0] += 0.01

        tampered = [
            ("input-edited", derive(more_treatment_successes),
             "treatment successes +400 in input, input_sha256 left stale"),
            ("input-redigested", derive(more_treatment_successes, redigest=True),
             "treatment successes +400 in input and input_sha256 recomputed; the stored decision and metrics no longer replay"),
            ("decision-edited", derive(decision_to_hold),
             "decision changed from SHIP to HOLD, input digest still consistent"),
            ("metric-edited", derive(inflate_lower_bound),
             "primary metric lower bound +0.01, input digest still consistent"),
        ]
        for stem, record, note in tampered:
            tree.add(f"tampered/decision-v{schema}-{stem}.json", record_bytes(record), "tampered",
                     f"{label}, ship vector: {note}", schema, schema_valid=True)

        # The digest of the right input under the other schema's canonicalization.
        edge = records[(schema, "jcs-edge")]
        other = 5 - schema
        wrong = copy.deepcopy(edge)
        wrong["input_sha256"] = digest(wrong["input"], other)
        tree.add(f"tampered/decision-v{schema}-digest-{CANONICALIZATION[other]}.json", record_bytes(wrong), "tampered",
                 f"{label}, jcs-edge vector: input_sha256 computed with {CANONICALIZATION[other]} instead of "
                 f"{CANONICALIZATION[schema]}", schema, schema_valid=True)

    # Invalid vectors: exit 2.
    ship3, ship2 = records[(3, "ship")], records[(2, "ship")]
    for schema, ship in ((3, ship3), (2, ship2)):
        text = pretty(ship)
        label = f"schema {schema}, ship vector"
        tree.add(f"invalid/decision-v{schema}-malformed-json.json", text[: text.index('  "input_sha256"')], "invalid",
                 f"{label}: file cut off after the input member", None)
        unknown = copy.deepcopy(ship)
        unknown["schema_version"] = 4
        tree.add(f"invalid/decision-v{schema}-unknown-schema.json", record_bytes(unknown), "invalid",
                 f"{label}: schema_version set to 4", schema, schema_valid=False)
        missing = {k: v for k, v in ship.items() if k != "input"}
        tree.add(f"invalid/decision-v{schema}-missing-input.json", record_bytes(missing), "invalid",
                 f"{label}: input member removed", schema, schema_valid=False)
        nan = copy.deepcopy(ship)
        nan["input"]["assignment"]["expected_treatment_share"] = float("nan")
        nan["input_sha256"] = digest(nan["input"], 2)  # json.dumps writes the NaN literal; JCS cannot encode it
        nan_text = json.dumps({"expgate_version": ship["produced_by"]["version"], **nan}, indent=2,
                              sort_keys=True, ensure_ascii=False, allow_nan=True)
        tree.add(f"invalid/decision-v{schema}-non-finite.json", nan_text, "invalid",
                 f"{label}: input.assignment.expected_treatment_share is the literal NaN (not JSON); python-json-v1 digest recomputed", None)

    v3_text = pretty(ship3)
    top = v3_text.replace("{\n", '{\n  "decision": "HOLD",\n', 1)
    tree.add("invalid/decision-v3-duplicate-key.json", top, "invalid",
             "schema 3, ship vector: a first \"decision\": \"HOLD\" member precedes the real one; the later "
             "value wins in lenient parsers and the document would otherwise verify", 3, schema_valid=True)
    nested_key = f'"units": {ship3["input"]["arms"]["control"]["units"]}'
    nested = v3_text.replace(nested_key, '"units": 1,\n        ' + nested_key, 1)
    assert nested != v3_text
    tree.add("invalid/decision-v3-duplicate-key-in-input.json", nested, "invalid",
             "schema 3, ship vector: input.arms.control repeats \"units\" (first 1, then the real value)", 3,
             schema_valid=True)
    big = copy.deepcopy(ship3)
    big["input"]["arms"]["control"]["units"] = 2 ** 60
    tree.add("invalid/decision-v3-integer-out-of-range.json", record_bytes(big), "invalid",
             "schema 3, ship vector: input.arms.control.units set to 2^60, outside the RFC 8785 safe integer range "
             "(digest cannot be computed)", 3, schema_valid=True)

    ignored = copy.deepcopy(ship3)
    ignored["note"] = 2 ** 53
    tree.add("invalid/decision-v3-unsafe-integer-in-ignored-member.json", record_bytes(ignored), "invalid",
             "schema 3, ship vector: an unknown top-level member \"note\" holds 2^53; the verifier ignores the member "
             "but RFC 8785 cannot encode the document", 3, schema_valid=True)

    legacy = {k: v for k, v in ship3.items() if k not in ("schema_version", "produced_by", "input", "input_sha256")}
    tree.add("invalid/decision-v1-legacy.json", record_bytes(legacy), "invalid",
             "schema 1: no schema_version, embedded input or digest (ship vector with those members removed); "
             "inspectable but cannot be verified", None)

    manifest = {"format": 1, "package": "expgate", "vectors": tree.vectors}
    tree.files["manifest.json"] = (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    tree.files[".gitattributes"] = b"* -text\n"
    return tree.files


def existing() -> dict[str, bytes]:
    found = {}
    for sub in ("valid", "tampered", "invalid"):
        for path in sorted((HERE / sub).rglob("*")):
            if path.is_file():
                found[path.relative_to(HERE).as_posix()] = path.read_bytes()
    for name in ("manifest.json", ".gitattributes"):
        if (HERE / name).is_file():
            found[name] = (HERE / name).read_bytes()
    return found


def differences(fresh: dict[str, bytes], current: dict[str, bytes]) -> list[str]:
    """Paths whose committed content is not a fresh generation.

    Record files are equal when ``input``, ``input_sha256``, ``schema_version`` and ``produced_by`` match
    exactly and every other member matches within the schema-3 replay tolerance: derived floats come from the
    platform libm, so a tree generated on macOS differs in the last digits from one generated on Linux. All
    other files, including canonical bytes and the manifest, must match byte for byte.
    """
    def record_equal(a: bytes, b: bytes) -> bool:
        try:
            x, y = json.loads(a), json.loads(b)
        except ValueError:
            return False
        if not (isinstance(x, dict) and isinstance(y, dict)) or x.keys() != y.keys():
            return False
        exact = ("input", "input_sha256", "schema_version", "produced_by")
        return all(json.dumps(x.get(k), sort_keys=True) == json.dumps(y.get(k), sort_keys=True) for k in exact) \
            and all(_agree(x[k], y[k], (k,)) for k in x if k not in exact)

    stale = []
    for path in sorted(fresh.keys() | current.keys()):
        a, b = fresh.get(path), current.get(path)
        if a == b:
            continue
        is_record = path.endswith(".json") and path.split("/")[0] in ("valid", "tampered", "invalid")
        if a is None or b is None or not (is_record and record_equal(a, b)):
            stale.append(path)
    return stale


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--check", action="store_true", help="compare with the committed tree instead of writing")
    args = parser.parse_args(argv)
    fresh, current = build(), existing()
    if args.check:
        stale = differences(fresh, current)
        for path in stale:
            print(f"differs: {path}", file=sys.stderr)
        return 1 if stale else 0
    for path in current.keys() - fresh.keys():
        (HERE / path).unlink()
    for path, data in fresh.items():
        target = HERE / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    print(f"wrote {len(fresh)} files under {HERE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
