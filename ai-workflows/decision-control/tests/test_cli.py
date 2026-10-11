import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from decisioncontrol.cli import main
from decisioncontrol.store import TicketStore


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db = str(self.root / "queue.sqlite3")
        self.policy = self.root / "policy.json"
        self.policy.write_text(json.dumps({
            "version": "p1", "allowed_destinations": ["support", "engineering"],
            "review_destinations": ["engineering"], "reviewers": ["alice"],
            "min_probability": 0.8}), encoding="utf-8")
        self.proposal = self.root / "proposal.json"
        self.proposal.write_text(json.dumps({
            "action": "reassign_ticket", "ticket_id": "T1", "destination": "engineering",
            "probability": 0.95, "model": "hand-authored", "question_version": "q1"}),
            encoding="utf-8")

    def call(self, *args, db=True):
        stdout, stderr = io.StringIO(), io.StringIO()
        argv = (["--db", self.db] if db else []) + list(args)
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(argv)
        return code, json.loads(stdout.getvalue()) if stdout.getvalue() else None, stderr.getvalue()

    def create_review(self):
        self.assertEqual(self.call("ticket-create", "--ticket-id", "T1", "--department", "intake")[0], 0)
        code, record, _ = self.call("submit", "--proposal", str(self.proposal), "--policy", str(self.policy))
        self.assertEqual(code, 0)
        self.assertEqual(record["status"], "PENDING_REVIEW")
        return record["id"]

    def test_persisted_review_execution_export_and_replay(self):
        decision = self.create_review()
        self.assertEqual(self.call("pending")[1][0]["id"], decision)
        code, _, _ = self.call("approve", decision, "--reviewer", "alice", "--note", "checked")
        self.assertEqual(code, 0)
        code, first, _ = self.call("execute", decision)
        self.assertEqual(code, 0)
        self.assertEqual(first["status"], "EXECUTED")
        self.assertEqual(self.call("execute", decision)[1], first)
        self.assertEqual(self.call("ticket-show", "T1")[1],
                         {"id": "T1", "department": "engineering", "revision": 1})
        exported = self.root / "record.json"
        self.assertEqual(self.call("export", decision, "--out", str(exported))[0], 0)
        code, replayed, _ = self.call("replay", "--record", str(exported), db=False)
        self.assertEqual(code, 0)
        self.assertTrue(replayed["valid"])
        self.assertEqual(replayed["decision_id"], decision)
        before = exported.read_bytes()
        self.assertEqual(self.call("export", decision, "--out", str(exported))[0], 2)
        self.assertEqual(exported.read_bytes(), before)

    def test_unauthorized_and_premature_actions_do_not_mutate(self):
        decision = self.create_review()
        for args in (("approve", decision, "--reviewer", "mallory"), ("execute", decision)):
            code, output, error = self.call(*args)
            self.assertEqual(code, 1)
            self.assertIsNone(output)
            self.assertTrue(error)
        with TicketStore(self.db) as store:
            self.assertEqual(store.get(decision)["status"], "PENDING_REVIEW")
            self.assertEqual(store.get_ticket("T1").revision, 0)
        self.assertEqual(self.call("reject", decision, "--reviewer", "alice")[0], 0)
        self.assertEqual(self.call("execute", decision)[0], 1)
        self.assertEqual(self.call("show", decision)[1]["status"], "REJECTED")

    def test_input_and_io_errors(self):
        self.assertEqual(self.call("pending", db=False)[0], 2)
        self.assertEqual(self.call("ticket-show", "unknown")[0], 2)
        self.call("ticket-create", "--ticket-id", "T1", "--department", "intake")
        self.proposal.write_text("{broken", encoding="utf-8")
        self.assertEqual(self.call("submit", "--proposal", str(self.proposal), "--policy", str(self.policy))[0], 2)
        self.assertEqual(self.call("pending")[1], [])
        self.assertEqual(self.call("replay", "--record", str(self.root / "missing.json"), db=False)[0], 2)

    def test_demo_real_queue_and_saved_evidence(self):
        out = self.root / "demo"
        code, summary, _ = self.call("demo", "--out", str(out), db=False)
        self.assertEqual(code, 0)
        self.assertTrue(summary["repeat_execution_same_record"])
        self.assertTrue(summary["pending_before_approval"])
        self.assertEqual({v["verdict"] for v in summary["decisions"].values()},
                         {"ALLOW", "REVIEW", "DENY", "ABSTAIN"})
        with TicketStore(out / "tickets.sqlite3") as store:
            for name, expected_department, expected_revision in (
                    ("allow", "support", 1), ("review", "engineering", 1),
                    ("deny", "intake", 0), ("abstain", "intake", 0)):
                ticket = store.get_ticket(f"demo-{name}")
                self.assertEqual((ticket.department, ticket.revision),
                                 (expected_department, expected_revision))
                self.assertEqual(self.call("replay", "--record", str(out / f"record-{name}.json"), db=False)[0], 0)
        saved = (out / "summary.json").read_bytes()
        self.assertEqual(self.call("demo", "--out", str(out), db=False)[0], 2)
        self.assertEqual((out / "summary.json").read_bytes(), saved)


if __name__ == "__main__":
    unittest.main()
