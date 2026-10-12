import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
WORKSPACE_SPEC = importlib.util.spec_from_file_location("workspace", SCRIPTS / "workspace.py")
workspace = importlib.util.module_from_spec(WORKSPACE_SPEC)
WORKSPACE_SPEC.loader.exec_module(workspace)
SPEC = importlib.util.spec_from_file_location("publication_evidence", SCRIPTS / "publication_evidence.py")
evidence = importlib.util.module_from_spec(SPEC)
with patch.dict(sys.modules, {"workspace": workspace}):
    SPEC.loader.exec_module(evidence)


class EvidenceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.out = Path(self.temp.name)
        result = {"gate_report": {"release_decision": "PASS"},
                  "incremental_cycle": {"decision": "REJECT_UPDATE_KEEP_CURRENT_REFERENCE"}, "summary": {}}
        for run in ("a", "b"):
            self.save(f"relia/repro-{run}/results.json", result)
            self.save(f"relia/repro-{run}/MANIFEST.json", {"results_sha256": "fixture"})
        for name, decision in evidence.SCENARIOS.items():
            self.save(f"experiment-gate/{name}/decision.json", {"decision": decision})
        self.save("jev-decision/evaluation.json", {"source": "replay", "status": "PASS", "cases": 12})
        self.save("jev-ungated/evaluation.json", {"status": "UNGATED"})
        states = {"allow": ("ALLOW", "EXECUTED", "support", 1),
                  "review": ("REVIEW", "EXECUTED", "engineering", 1),
                  "deny": ("DENY", "DENIED", "intake", 0),
                  "abstain": ("ABSTAIN", "ABSTAINED", "intake", 0)}
        self.demo = {"decisions": {name: {"verdict": verdict, "status": status}
                                   for name, (verdict, status, _, _) in states.items()},
                     "tickets": {name: {"department": department, "revision": revision}
                                 for name, (_, _, department, revision) in states.items()},
                     "repeat_execution_same_record": True, "reopened_before_approval": True}
        self.save("decision-control/summary.json", self.demo)
        self.save("decision-control-gated/evaluation.json", {"report": {"disposition": "FAIL"}})

    def save(self, name, value):
        path = self.out / name
        path.parent.mkdir(parents=True, exist_ok=True)
        evidence.save(path, value)

    def test_adverse_decisions_must_not_become_shipping_success(self):
        for path, content, message in (
            ("experiment-gate/guardrail-breach/decision.json", {"decision": "SHIP"}, "experiment dispositions"),
            ("decision-control-gated/evaluation.json", {"report": {"disposition": "PASS"}}, "adverse"),
        ):
            with self.subTest(path=path):
                original = (self.out / path).read_bytes()
                self.save(path, content)
                with self.assertRaisesRegex(ValueError, message):
                    evidence.observe(self.out)
                (self.out / path).write_bytes(original)

    def test_repeated_results_must_match_bytes_not_just_parsed_values(self):
        path = self.out / "relia/repro-b/results.json"
        path.write_bytes(path.read_bytes() + b"\n")
        with self.assertRaisesRegex(ValueError, "repeat mismatch"):
            evidence.observe(self.out)

    def test_denied_ticket_must_remain_unmodified(self):
        self.demo["tickets"]["deny"]["revision"] = 1
        self.save("decision-control/summary.json", self.demo)
        with self.assertRaisesRegex(ValueError, "state: deny"):
            evidence.observe(self.out)

    def test_ungated_fixture_cannot_be_reported_as_quality_pass(self):
        self.save("jev-ungated/evaluation.json", {"status": "PASS"})
        with self.assertRaisesRegex(ValueError, "mislabeled"):
            evidence.observe(self.out)

    def test_verification_rejects_modified_missing_and_unsafe_artifacts(self):
        artifact = self.out / "retained.txt"
        artifact.write_text("original", encoding="utf-8")
        record = {"verified": True, "artifacts": {"retained.txt": evidence.sha256(artifact)}}
        self.save("EVIDENCE.json", record)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(evidence.verify(self.out), 0)
        artifact.write_text("modified", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "changed"):
            evidence.verify(self.out)
        artifact.unlink()
        with self.assertRaisesRegex(ValueError, "missing"):
            evidence.verify(self.out)
        self.save("EVIDENCE.json", {"verified": True, "artifacts": {"../outside": "fixture"}})
        with self.assertRaisesRegex(ValueError, "unsafe"):
            evidence.verify(self.out)

    def test_unsuccessful_record_never_verifies_as_success(self):
        self.save("EVIDENCE.json", {"verified": False, "artifacts": {}})
        with self.assertRaisesRegex(ValueError, "unsuccessful"):
            evidence.verify(self.out)


if __name__ == "__main__":
    unittest.main()
