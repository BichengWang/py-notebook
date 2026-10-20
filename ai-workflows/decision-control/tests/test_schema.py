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

    def test_demo_records_validate_as_schema_five(self):
        check = validator("record.v5.json")
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "demo"
            run_demo(out)
            records = sorted(out.glob("record-*.json"))
            self.assertEqual(len(records), 4)
            for path in records:
                document = json.loads(path.read_text(encoding="utf-8"))
                with self.subTest(path=path.name):
                    check.validate(document)
                    self.assertEqual(document["record"]["schema_version"], 5)
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
            for other in (3, 4, 5):
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

    def test_schema_five_rejects_what_the_reader_rejects(self):
        recorded = FIXTURES.parent.parent / "fixtures" / "policy-engines" / "records"
        envelope = json.loads((recorded / "opa-priority-allow-executed.json").read_text(encoding="utf-8"))
        record = envelope["record"]
        check = validator("record.v5.json")
        self.assertTrue(check.is_valid(envelope))
        self.assertFalse(validator("record.v4.json").is_valid(envelope))
        edits = {
            "missing external digest": lambda r: r.pop("external_policy_sha256"),
            "missing external policy": lambda r: r.pop("external_policy"),
            "no target member": lambda r: r["recommendation"].pop("priority"),
            "two target members": lambda r: r["recommendation"].update(destination="support"),
            "unknown engine": lambda r: r["external_policy"].update(engine="rego"),
            "unknown external member": lambda r: r["external_policy"].update(extra=1),
            "missing modules": lambda r: r["external_policy"].pop("modules"),
            "empty modules": lambda r: r["external_policy"].update(modules={}),
            "module outside the policy directory": lambda r: r["external_policy"].update(
                modules={"../x.rego": "package x"}),
            "non-rego module": lambda r: r["external_policy"].update(modules={"x.txt": "package x"}),
            "bundle revision not text": lambda r: r["external_policy"].update(bundles={"b": {"revision": 1}}),
            "slash-only path": lambda r: r["external_policy"].update(path="//"),
            "padded priority": lambda r: r["ticket"].update(priority=" normal"),
            "duplicate priority allowlist": lambda r: r["policy"].update(allowed_priorities=["a", "a"]),
        }
        for name, edit in edits.items():
            candidate = deepcopy(record)
            edit(candidate)
            with self.subTest(edit=name):
                self.assertFalse(check.is_valid({"record": candidate, "sha256": "0" * 64}))
        cedar = json.loads((recorded / "cedar-reassign-forbidden.json").read_text(encoding="utf-8"))["record"]
        self.assertTrue(check.is_valid({"record": cedar, "sha256": "0" * 64}))
        cedar_edits = {
            "unknown decision": lambda r: r["external_policy"].update(decision="Permit"),
            "duplicate determining policy": lambda r: r["external_policy"]["diagnostics"].update(reason=["a", "a"]),
            "error without policy id": lambda r: r["external_policy"]["diagnostics"].update(errors=[{"error": "x"}]),
            "policies of unknown format": lambda r: r["external_policy"].update(policies={"format": "yaml", "text": ""}),
            "request without context": lambda r: r["external_policy"]["request"].pop("context"),
            "entities not a list": lambda r: r["external_policy"].update(entities={}),
        }
        for name, edit in cedar_edits.items():
            candidate = deepcopy(cedar)
            edit(candidate)
            with self.subTest(cedar_edit=name):
                self.assertFalse(check.is_valid({"record": candidate, "sha256": "0" * 64}))


if __name__ == "__main__":
    unittest.main()
