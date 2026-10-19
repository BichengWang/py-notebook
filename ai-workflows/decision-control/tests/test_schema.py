"""Shipped JSON Schemas describe what the producers write and the readers accept."""
import contextlib
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest

from decisioncontrol import __version__
from decisioncontrol.cli import main
from decisioncontrol.demo import run_demo
from dc_support import (ID_PREFIX, as_schema3, jsonschema, load_schema, rehash_record,
                        schema_names, validator)

FIXTURES = Path(__file__).parent / "fixtures"
EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


class SchemaFileTests(unittest.TestCase):
    def test_every_supported_version_ships_a_schema(self):
        for name in schema_names():
            with self.subTest(name=name):
                schema = load_schema(name)
                self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
                self.assertEqual(schema["$id"], ID_PREFIX + name)
                self.assertFalse(schema["additionalProperties"])
                self.assertRegex(schema["$comment"], "RFC 8785|python-json-v1")

    def test_schema_version_constants_match_the_reader_versions(self):
        for name in schema_names():
            kind, version = name.split(".")[0], int(name.split(".")[1][1:])
            schema = load_schema(name)
            body = schema["properties"]["record" if kind == "record" else "report"]
            self.assertEqual(body["properties"]["schema_version"], {"const": version})


@unittest.skipIf(jsonschema is None, "jsonschema is a dev/CI-only dependency")
class SchemaValidationTests(unittest.TestCase):
    def test_schemas_are_valid_2020_12(self):
        for name in schema_names():
            with self.subTest(name=name):
                validator(name)

    def test_demo_records_validate_as_schema_four(self):
        check = validator("record.v4.json")
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "demo"
            run_demo(out)
            records = sorted(out.glob("record-*.json"))
            self.assertEqual(len(records), 4)
            for path in records:
                document = json.loads(path.read_text(encoding="utf-8"))
                with self.subTest(path=path.name):
                    check.validate(document)
                    self.assertEqual(document["record"]["schema_version"], 4)
                    self.assertEqual(document["record"]["produced_by"]["version"], __version__)

    def test_evaluation_output_validates_as_schema_two(self):
        check = validator("evaluation.v2.json")
        with tempfile.TemporaryDirectory() as tmp:
            for requirements in (None, EXAMPLES / "evaluation-requirements.json"):
                out = Path(tmp) / ("gated" if requirements else "ungated")
                argv = ["evaluate", "--cases", str(EXAMPLES / "evaluation-cases.jsonl"),
                        "--policy", str(EXAMPLES / "policy.json"), "--out", str(out)]
                if requirements:
                    argv += ["--require", str(requirements)]
                with contextlib.redirect_stdout(io.StringIO()):
                    main(argv)
                document = json.loads((out / "evaluation.json").read_text(encoding="utf-8"))
                with self.subTest(requirements=bool(requirements)):
                    check.validate(document)
                    self.assertEqual(document["report"]["schema_version"], 2)

    def test_archived_records_validate_under_their_own_schema_only(self):
        for version in (1, 2):
            document = json.loads((FIXTURES / f"approved-v{version}.json").read_text(encoding="utf-8"))
            validator(f"record.v{version}.json").validate(document)
            for other in (3, 4):
                with self.subTest(fixture=version, schema=other):
                    self.assertFalse(validator(f"record.v{other}.json").is_valid(document))

    def test_schema_rejects_what_the_reader_rejects(self):
        document = json.loads((FIXTURES / "approved-v2.json").read_text(encoding="utf-8"))
        v4 = deepcopy(document)
        v4["record"].update({"schema_version": 4, "proposed_by": "proposer", "policy_sha256": "0" * 64,
                             "produced_by": {"name": "decisioncontrol", "version": "0.2.0"}})
        check = validator("record.v4.json")
        self.assertTrue(check.is_valid(rehash_record(deepcopy(v4))))
        legacy = rehash_record({"record": as_schema3(v4["record"]), "sha256": ""})
        self.assertTrue(validator("record.v3.json").is_valid(legacy))
        edits = {
            "unknown top-level field": lambda r: r.update(extra=1),
            "missing proposer": lambda r: r.pop("proposed_by"),
            "unknown producer": lambda r: r["produced_by"].update(name="other"),
            "bad status": lambda r: r.update(status="DONE"),
            "bad uuid": lambda r: r.update(id="not-a-uuid"),
            "non-UTC timestamp": lambda r: r.update(created_at="2026-01-15T09:00:00+01:00"),
            "padded text": lambda r: r["ticket"].update(department=" intake"),
            "bad probability": lambda r: r["recommendation"].update(probability=1.5),
            "duplicate reviewers": lambda r: r["policy"].update(reviewers=["a", "a"]),
            "first event not SUBMITTED": lambda r: r["events"][0].update(event="APPROVED"),
            "empty events": lambda r: r.update(events=[]),
        }
        for name, edit in edits.items():
            candidate = deepcopy(v4)
            edit(candidate["record"])
            with self.subTest(edit=name):
                self.assertFalse(check.is_valid(candidate))
        extra_envelope = deepcopy(v4)
        extra_envelope["comment"] = "x"
        self.assertFalse(check.is_valid(extra_envelope))
        upper = deepcopy(v4)
        upper["sha256"] = upper["sha256"].upper()
        self.assertFalse(check.is_valid(upper))


if __name__ == "__main__":
    unittest.main()
