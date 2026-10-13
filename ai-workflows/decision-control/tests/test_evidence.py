from contextlib import closing
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
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
        submitted = self.store.submit(self.proposal(), self.policy, proposed_by="proposer")
        executed = self.store.execute(submitted["id"])
        before = self.store.get_ticket("t1")
        result = replay(export_record(executed))
        self.assertEqual(result, {"valid": True, "decision_id": submitted["id"],
                                  "verdict": "ALLOW", "status": "EXECUTED"})
        self.assertEqual(self.store.get_ticket("t1"), before)
        self.assertEqual(before.revision, 1)

    def test_checksum_covers_mutable_execution_history(self):
        record = self.store.submit(self.proposal(), self.policy, proposed_by="proposer")
        envelope = deepcopy(export_record(record))
        envelope["record"]["status"] = "EXECUTED"
        with self.assertRaises(DecisionError):
            replay(envelope)

    def test_recomputed_checksum_does_not_hide_inconsistent_verdict(self):
        record = self.store.submit(self.proposal(), self.policy, proposed_by="proposer")
        envelope = deepcopy(export_record(record))
        envelope["record"]["policy"]["min_probability"] = 0.99
        with self.assertRaises(DecisionError):
            replay(self.rehash(envelope))

    def test_denial_cannot_gain_an_execution_event(self):
        record = self.store.submit(self.proposal(destination="administrators"), self.policy, proposed_by="proposer")
        envelope = deepcopy(export_record(record))
        raw = envelope["record"]
        raw["events"].append({"event": "EXECUTED", "at": raw["created_at"]})
        raw["status"] = "EXECUTED"
        raw["result"] = {"id": "t1", "department": "administrators", "revision": 1}
        with self.assertRaises(DecisionError):
            replay(self.rehash(envelope))

    def test_recorded_review_must_have_an_authorized_reviewer(self):
        record = self.store.submit(self.proposal(destination="billing"), self.policy, proposed_by="proposer")
        approved = self.store.approve(record["id"], "operator", "confirmed")
        envelope = deepcopy(export_record(approved))
        envelope["record"]["review"]["reviewer"] = "attacker"
        with self.assertRaises(DecisionError):
            replay(self.rehash(envelope))

    def test_result_must_match_the_frozen_action_and_single_revision_increment(self):
        record = self.store.submit(self.proposal(), self.policy, proposed_by="proposer")
        envelope = deepcopy(export_record(self.store.execute(record["id"])))
        envelope["record"]["result"]["revision"] = 2
        with self.assertRaises(DecisionError):
            replay(self.rehash(envelope))

    def test_v1_approval_replays_and_its_stored_decision_can_be_cancelled(self):
        fixture = Path(__file__).parent / "fixtures" / "approved-v1.json"
        archived = json.loads(fixture.read_text(encoding="utf-8"))
        self.assertEqual(replay(archived)["status"], "READY")
        raw = archived["record"]
        self.store.create_ticket(raw["ticket"]["id"], raw["ticket"]["department"])
        with closing(sqlite3.connect(Path(self.tmp.name) / "tickets.sqlite3")) as connection, connection:
            connection.execute(
                "INSERT INTO decisions (id, created_at, status, record) VALUES (?, ?, ?, ?)",
                (raw["id"], raw["created_at"], raw["status"], json.dumps(raw)),
            )
        cancelled = self.store.cancel(raw["id"], "operator", "Withdraw historical approval")
        self.assertEqual(cancelled["schema_version"], 2)
        self.assertEqual(cancelled["review"], raw["review"])
        self.assertEqual(replay(export_record(self.store.get(raw["id"])))["status"], "CANCELLED")
        self.assertEqual(self.store.get_ticket(raw["ticket"]["id"]).to_dict(), raw["ticket"])

    def test_cancellation_metadata_is_validated_even_with_a_recomputed_checksum(self):
        record = self.store.submit(self.proposal(destination="billing"), self.policy, proposed_by="proposer")
        self.store.approve(record["id"], "operator", "checked")
        envelope = export_record(self.store.cancel(record["id"], "operator", "Request withdrawn"))
        for field, value in (("reviewer", "attacker"), ("note", None), ("note", " \n ")):
            with self.subTest(field=field, value=value):
                forged = deepcopy(envelope)
                forged["record"]["events"][-1][field] = value
                with self.assertRaises(DecisionError):
                    replay(self.rehash(forged))
        missing_actor = deepcopy(envelope)
        del missing_actor["record"]["events"][-1]["reviewer"]
        with self.assertRaises(DecisionError):
            replay(self.rehash(missing_actor))
        erased_approval = deepcopy(envelope)
        erased_approval["record"]["review"] = None
        with self.assertRaises(DecisionError):
            replay(self.rehash(erased_approval))
        mislabelled_schema = deepcopy(envelope)
        mislabelled_schema["record"]["schema_version"] = 1
        with self.assertRaises(DecisionError):
            replay(self.rehash(mislabelled_schema))

    def test_cancellation_cannot_be_followed_by_execution_in_replay(self):
        record = self.store.submit(self.proposal(), self.policy, proposed_by="proposer")
        cancelled = self.store.cancel(record["id"], "operator", "Request withdrawn")
        envelope = deepcopy(export_record(cancelled))
        raw = envelope["record"]
        raw["events"].append({"event": "EXECUTED", "at": raw["events"][-1]["at"]})
        raw["status"] = "EXECUTED"
        raw["result"] = {"id": "t1", "department": "technical", "revision": 1}
        with self.assertRaises(DecisionError):
            replay(self.rehash(envelope))

    def test_cancellation_cannot_erase_completed_execution_in_replay(self):
        record = self.store.submit(self.proposal(), self.policy, proposed_by="proposer")
        envelope = deepcopy(export_record(self.store.execute(record["id"])))
        raw = envelope["record"]
        raw["events"].append({
            "event": "CANCELLED", "at": raw["events"][-1]["at"],
            "reviewer": "operator", "note": "Fabricated undo",
        })
        raw["status"] = "CANCELLED"
        raw["result"] = None
        with self.assertRaises(DecisionError):
            replay(self.rehash(envelope))

    def test_unsupported_schema_requires_explicit_migration(self):
        record = self.store.submit(self.proposal(), self.policy, proposed_by="proposer")
        envelope = deepcopy(export_record(record))
        envelope["record"]["schema_version"] = 999
        with self.assertRaises(DecisionError):
            replay(self.rehash(envelope))


class HistoricalV2Tests(unittest.TestCase):
    def test_archived_v2_approval_keeps_old_rules(self):
        fixture = Path(__file__).parent / 'fixtures' / 'approved-v2.json'
        archived = json.loads(fixture.read_text(encoding='utf-8'))
        self.assertEqual(replay(archived)['status'], 'READY')
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / 'queue.sqlite3'
            with TicketStore(db) as store:
                record = archived['record']
                store.create_ticket(record['ticket']['id'], record['ticket']['department'])
                with sqlite3.connect(db) as connection:
                    connection.execute('INSERT INTO decisions VALUES (?, ?, ?, ?)',
                        (record['id'], record['created_at'], record['status'], json.dumps(record)))
                cancelled = store.cancel(record['id'], record['review']['reviewer'], 'legacy withdrawal')
                self.assertEqual(cancelled['schema_version'], 2)
                self.assertEqual(replay(export_record(cancelled))['status'], 'CANCELLED')


if __name__ == "__main__":
    unittest.main()
