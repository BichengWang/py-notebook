"""The LangGraph approval example (examples/langgraph/): a two-node graph whose ``interrupt()``
approval becomes a decision-control review, exported and replayed.

LangGraph is a dev-only dependency of the example: these tests skip when it is not installed.
CI installs examples/langgraph/requirements-dev.txt and sets DECISION_CONTROL_REQUIRE_LANGGRAPH=1,
which turns a missing install into a failure.
"""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from dc_support import rehash_record
from decisioncontrol import DecisionError, Recommendation, RoutingPolicy, StateError, TicketStore
from decisioncontrol.cli import main

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "langgraph"
REQUIRED = os.environ.get("DECISION_CONTROL_REQUIRE_LANGGRAPH") == "1"
HAVE_LANGGRAPH = importlib.util.find_spec("langgraph") is not None

if HAVE_LANGGRAPH:
    sys.path.insert(0, str(EXAMPLE))
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.types import Command

    import decision_approvals as approvals

POLICY = RoutingPolicy("langgraph-test-1", ("support", "engineering"), ("engineering",), ("alice", "bob"), 0.8,
                       ("low", "normal", "high", "urgent"), ("urgent",))


def proposal(priority="urgent"):
    return Recommendation("set_ticket_priority", "T-1", None, 0.95, "hand-authored", "q1",
                          priority=priority).to_dict()


def replay_file(envelope, directory):
    path = Path(directory) / f"record-{len(list(Path(directory).glob('record-*.json')))}.json"
    path.write_text(json.dumps(envelope), encoding="utf-8")
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return main(["replay", "--record", str(path)])


@unittest.skipUnless(HAVE_LANGGRAPH, "langgraph is a dev-only dependency of the example")
class LangGraphApprovalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.db = self.dir / "queue.sqlite3"
        self.store = TicketStore(self.db)
        self.addCleanup(self.store.close)
        self.store.create_ticket("T-1", "support", priority="normal")
        self.saver = InMemorySaver()
        self.graph = approvals.build_graph(self.store, POLICY, self.saver)
        self.config = {"configurable": {"thread_id": "thread-A"}}

    def start(self, priority="urgent", proposer="alice"):
        return self.graph.invoke({"proposal": proposal(priority), "proposed_by": proposer}, self.config)

    def resume(self, decision, reviewer, note="looked at it"):
        return self.graph.invoke(Command(resume=approvals.resume_value(decision, reviewer, note)), self.config)

    def ask_again(self, decision_id, thread_id, value):
        """A new thread for an existing decision: propose skips, review interrupts, `value` answers."""
        config = {"configurable": {"thread_id": thread_id}}
        paused = self.graph.invoke({"decision_id": decision_id}, config)
        self.assertEqual(paused["__interrupt__"][0].value["decision_id"], decision_id)
        return self.graph.invoke(Command(resume=value), config)

    def test_a_different_reviewer_approves_and_the_exported_record_replays(self):
        paused = self.start()
        request = paused["__interrupt__"][0].value
        self.assertEqual(request["kind"], approvals.REQUEST_KIND)
        self.assertEqual((request["verdict"], request["reasons"]), ("REVIEW", ["priority_requires_review"]))
        self.assertEqual(request["recommendation"]["priority"], "urgent")
        self.assertEqual(request["proposed_by"], "alice")
        self.assertEqual(self.store.get(request["decision_id"])["status"], "PENDING_REVIEW")
        snapshot = self.graph.get_state(self.config)
        self.assertEqual(snapshot.next, ("review",))
        self.assertEqual(request["thread_id"], "thread-A")
        self.assertEqual(request["checkpoint_id"], snapshot.config["configurable"]["checkpoint_id"])

        done = self.resume("approve", "bob")
        self.assertEqual(done["status"], "READY")
        self.assertEqual(replay_file(done["record"], self.dir), 0)
        record = done["record"]["record"]
        self.assertEqual((record["proposed_by"], record["review"]["reviewer"]), ("alice", "bob"))
        self.assertEqual(approvals.langgraph_context(record),
                         {"thread_id": "thread-A", "checkpoint_id": request["checkpoint_id"], "note": "looked at it"})
        self.assertEqual(self.store.get_ticket("T-1").priority, "normal")  # approval does not execute

        executed = self.store.execute(request["decision_id"])
        self.assertEqual(self.store.get_ticket("T-1").priority, "urgent")
        self.assertEqual(replay_file(approvals.export_record(executed), self.dir), 0)

    def test_the_proposer_approving_their_own_proposal_is_refused_and_a_forged_record_fails_replay(self):
        decision_id = self.start()["__interrupt__"][0].value["decision_id"]
        refused = self.resume("approve", "alice")
        self.assertEqual(refused["status"], "PENDING_REVIEW")
        self.assertEqual(refused["refusal"]["kind"], "refused")
        self.assertIn("proposer cannot review", refused["refusal"]["message"])
        self.assertNotIn("record", refused)
        self.assertEqual(self.store.get(decision_id)["status"], "PENDING_REVIEW")
        self.assertIsNone(self.store.get(decision_id)["review"])

        # The refused value is not replayed to the next reviewer: a new thread asks again.
        honest = self.ask_again(decision_id, "thread-A2", approvals.resume_value("approve", "bob"))["record"]
        self.assertEqual(replay_file(honest, self.dir), 0)
        forged = json.loads(json.dumps(honest))
        forged["record"]["review"]["reviewer"] = "alice"
        self.assertEqual(replay_file(rehash_record(forged), self.dir), 1)  # replay catches it even re-hashed

    def test_example_script_exits_1_for_the_proposer_and_0_for_another_reviewer(self):
        def run(*args):
            return subprocess.run([sys.executable, str(EXAMPLE / "run_example.py"), *args], capture_output=True,
                                  text=True, env={**os.environ, "PYTHONPATH": str(EXAMPLE.parents[1])})
        out = self.dir / "example-record.json"
        approved = run("--out", str(out))
        self.assertEqual(approved.returncode, 0, approved.stderr)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["replay", "--record", str(out)]), 0)
        refused = run("--reviewer", "alice")
        self.assertEqual(refused.returncode, 1)
        self.assertIn("proposer cannot review", refused.stderr)

    def test_an_unlisted_reviewer_is_refused(self):
        self.start()
        refused = self.resume("approve", "mallory")
        self.assertEqual(refused["refusal"]["kind"], "refused")
        self.assertIn("not authorized", refused["refusal"]["message"])

    def test_rejection_is_exported_and_replays(self):
        self.start()
        done = self.resume("reject", "bob", "wrong queue")
        self.assertEqual(done["status"], "REJECTED")
        self.assertEqual(replay_file(done["record"], self.dir), 0)
        self.assertEqual(approvals.langgraph_context(done["record"]["record"])["note"], "wrong queue")

    def test_a_malformed_resume_value_is_reported_and_the_decision_stays_pending(self):
        decision_id = self.start()["__interrupt__"][0].value["decision_id"]
        values = ("approve", {"decision": "maybe", "reviewer": "bob"}, {"decision": "approve"},
                  {"decision": "approve", "reviewer": "bob", "extra": 1},
                  {"decision": "approve", "reviewer": "bob", "note": 3})
        for index, value in enumerate(values):
            with self.subTest(value=value):
                done = self.ask_again(decision_id, f"thread-bad-{index}", value)
                self.assertEqual(done["refusal"]["kind"], "invalid")
                self.assertEqual(self.store.get(decision_id)["status"], "PENDING_REVIEW")
        done = self.ask_again(decision_id, "thread-good", approvals.resume_value("approve", "bob"))
        self.assertEqual(done["status"], "READY")

    def test_a_proposal_that_needs_no_review_does_not_interrupt(self):
        done = self.start(priority="high")
        self.assertNotIn("__interrupt__", done)
        self.assertEqual((done["verdict"], done["status"]), ("ALLOW", "READY"))
        self.assertIsNone(done["record"]["record"]["review"])
        self.assertEqual(replay_file(done["record"], self.dir), 0)
        denied = self.graph.invoke({"proposal": proposal("critical"), "proposed_by": "alice"},
                                   {"configurable": {"thread_id": "thread-B"}})
        self.assertEqual((denied["verdict"], denied["status"]), ("DENY", "DENIED"))
        self.assertEqual(replay_file(denied["record"], self.dir), 0)

    def test_resume_after_a_restart_with_a_new_store_and_graph_object(self):
        request = self.start()["__interrupt__"][0].value
        self.store.close()
        with TicketStore(self.db) as reopened:
            graph = approvals.build_graph(reopened, POLICY, self.saver)
            done = graph.invoke(Command(resume=approvals.resume_value("approve", "bob")), self.config)
        self.assertEqual(done["status"], "READY")
        self.assertEqual(done["decision_id"], request["decision_id"])
        self.assertEqual(replay_file(done["record"], self.dir), 0)

    def test_the_pinned_requirement_is_the_installed_langgraph(self):
        from importlib.metadata import version
        pins = (EXAMPLE / "requirements-dev.txt").read_text(encoding="utf-8").splitlines()
        self.assertIn(f"langgraph=={version('langgraph')}", pins)


@unittest.skipUnless(REQUIRED, "CI sets DECISION_CONTROL_REQUIRE_LANGGRAPH=1 so that a missing install fails loudly")
class RequiredLangGraphTests(unittest.TestCase):
    def test_langgraph_is_installed(self):
        self.assertTrue(HAVE_LANGGRAPH, "pip install -r examples/langgraph/requirements-dev.txt")


if __name__ == "__main__":
    unittest.main()
