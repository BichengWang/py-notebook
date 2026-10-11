from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from decisioncontrol import DecisionError, Recommendation, RoutingPolicy, TicketStore, export_record, replay


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = TicketStore(Path(self.tmp.name) / "tickets.sqlite3")
        self.addCleanup(self.store.close)
        self.store.create_ticket("t1", "unassigned")
        self.policy = RoutingPolicy("routing/v1", ("technical", "billing"), ("billing",), ("operator",))

    def proposal(self, destination="technical", probability=0.95):
        return Recommendation("reassign_ticket", "t1", destination, probability, "recorded/v1", "route/v1")

    def rehash(self, envelope):
        blob = json.dumps(envelope["record"], sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode()
        envelope["sha256"] = hashlib.sha256(blob).hexdigest()
        return envelope

    def test_completed_replay_reproduces_verdict_without_reexecuting(self):
        submitted = self.store.submit(self.proposal(), self.policy)
        executed = self.store.execute(submitted["id"])
        before = self.store.get_ticket("t1")
        result = replay(export_record(executed))
        self.assertEqual(result, {"valid": True, "decision_id": submitted["id"],
                                  "verdict": "ALLOW", "status": "EXECUTED"})
        self.assertEqual(self.store.get_ticket("t1"), before)
        self.assertEqual(before.revision, 1)

    def test_checksum_covers_mutable_execution_history(self):
        record = self.store.submit(self.proposal(), self.policy)
        envelope = deepcopy(export_record(record))
        envelope["record"]["status"] = "EXECUTED"
        with self.assertRaises(DecisionError):
            replay(envelope)

    def test_recomputed_checksum_does_not_hide_inconsistent_verdict(self):
        record = self.store.submit(self.proposal(), self.policy)
        envelope = deepcopy(export_record(record))
        envelope["record"]["policy"]["min_probability"] = 0.99
        with self.assertRaises(DecisionError):
            replay(self.rehash(envelope))

    def test_denial_cannot_gain_an_execution_event(self):
        record = self.store.submit(self.proposal(destination="administrators"), self.policy)
        envelope = deepcopy(export_record(record))
        raw = envelope["record"]
        raw["events"].append({"event": "EXECUTED", "at": raw["created_at"]})
        raw["status"] = "EXECUTED"
        raw["result"] = {"id": "t1", "department": "administrators", "revision": 1}
        with self.assertRaises(DecisionError):
            replay(self.rehash(envelope))

    def test_recorded_review_must_have_an_authorized_reviewer(self):
        record = self.store.submit(self.proposal(destination="billing"), self.policy)
        approved = self.store.approve(record["id"], "operator", "confirmed")
        envelope = deepcopy(export_record(approved))
        envelope["record"]["review"]["reviewer"] = "attacker"
        with self.assertRaises(DecisionError):
            replay(self.rehash(envelope))

    def test_result_must_match_the_frozen_action_and_single_revision_increment(self):
        record = self.store.submit(self.proposal(), self.policy)
        envelope = deepcopy(export_record(self.store.execute(record["id"])))
        envelope["record"]["result"]["revision"] = 2
        with self.assertRaises(DecisionError):
            replay(self.rehash(envelope))

    def test_unsupported_schema_requires_explicit_migration(self):
        record = self.store.submit(self.proposal(), self.policy)
        envelope = deepcopy(export_record(record))
        envelope["record"]["schema_version"] = 2
        with self.assertRaises(DecisionError):
            replay(self.rehash(envelope))


if __name__ == "__main__":
    unittest.main()
