"""The action registry: reassign_ticket and set_ticket_priority run through one pipeline."""
import contextlib
from copy import deepcopy
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from decisioncontrol import (ACTIONS, DecisionError, Recommendation, RoutingPolicy, StateError, Ticket,
                             TicketStore, Verdict, evaluate, export_record, replay)
from decisioncontrol import actions
from decisioncontrol.cli import main
from dc_support import as_schema4, rehash_record


def priority_proposal(priority="high", **changes):
    fields = {"action": "set_ticket_priority", "ticket_id": "t1", "priority": priority,
              "probability": 0.95, "model": "recorded/v1", "question_version": "route/v1"}
    fields.update(changes)
    return Recommendation.from_dict(fields)


class RegistryTests(unittest.TestCase):
    def test_registry_names_both_actions_and_is_read_only(self):
        self.assertEqual(sorted(ACTIONS), ["reassign_ticket", "set_ticket_priority"])
        with self.assertRaises(TypeError):
            ACTIONS["issue_refund"] = actions.REASSIGN_TICKET
        self.assertEqual(sorted(actions.actions_for(4)), ["reassign_ticket"])
        self.assertEqual(sorted(actions.actions_for(5)), ["reassign_ticket", "set_ticket_priority"])

    def test_an_entry_needs_members_that_recommendation_ticket_and_policy_have(self):
        with self.assertRaises(ValueError):
            actions.ActionType("x", "colour", "priority", "allowed_priorities", "review_priorities", "a", "b", "c", "d")

    def test_a_new_action_runs_through_the_shared_pipeline_with_no_other_change(self):
        escalate = actions.ActionType(
            "escalate_ticket", "priority", "priority", "allowed_priorities", "review_priorities",
            "escalation_not_permitted", "already_escalated", "policy_permits_escalation", "escalation_requires_review")
        registry = {**actions.ACTIONS, "escalate_ticket": escalate}
        policy = RoutingPolicy("p", ("a",), (), ("r",), 0.8, ("high", "urgent"), ("urgent",))
        ticket = Ticket("t1", "support", 3, "normal")
        with patch.object(actions, "ACTIONS", registry):
            proposal = Recommendation.from_dict({"action": "escalate_ticket", "ticket_id": "t1", "priority": "high",
                                                 "probability": 0.9, "model": "m", "question_version": "q"})
            self.assertEqual(evaluate(proposal, ticket, policy).reasons, ("policy_permits_escalation",))
            refused = Recommendation.from_dict({"action": "escalate_ticket", "ticket_id": "t1", "priority": "low",
                                                "probability": 0.9, "model": "m", "question_version": "q"})
            self.assertEqual(evaluate(refused, ticket, policy).reasons, ("escalation_not_permitted",))
            self.assertEqual(escalate.apply(ticket, proposal), Ticket("t1", "support", 4, "high"))
        unregistered = Recommendation.from_dict({"action": "escalate_ticket", "ticket_id": "t1", "destination": "a",
                                                 "probability": 0.9, "model": "m", "question_version": "q"})
        self.assertEqual(evaluate(unregistered, ticket, policy).reasons, ("action_not_permitted",))


class PriorityPolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = RoutingPolicy("p", ("support",), (), ("bob",), 0.8, ("low", "normal", "high", "urgent"), ("urgent",))
        self.ticket = Ticket("t1", "support", 2, "normal")

    def test_allowed_priority_is_allowed(self):
        result = evaluate(priority_proposal("high"), self.ticket, self.policy)
        self.assertEqual((result.verdict, result.reasons), (Verdict.ALLOW, ("policy_permits_priority_change",)))

    def test_review_priority_needs_review_even_at_certainty(self):
        result = evaluate(priority_proposal("urgent", probability=1.0), self.ticket, self.policy)
        self.assertEqual((result.verdict, result.reasons), (Verdict.REVIEW, ("priority_requires_review",)))

    def test_unlisted_unchanged_refused_unknown_and_low_confidence_are_not_allowed(self):
        cases = [
            (priority_proposal("critical"), Verdict.DENY, "priority_not_permitted"),
            (priority_proposal("normal"), Verdict.DENY, "priority_unchanged"),
            (priority_proposal("high", refused=True), Verdict.ABSTAIN, "model_refused"),
            (priority_proposal("high", probability=None), Verdict.ABSTAIN, "probability_unknown"),
            (priority_proposal("high", probability=0.79), Verdict.ABSTAIN, "below_probability_threshold"),
            (priority_proposal("high", ticket_id="t2"), Verdict.DENY, "ticket_mismatch"),
        ]
        for proposal, verdict, reason in cases:
            with self.subTest(reason=reason):
                result = evaluate(proposal, self.ticket, self.policy)
                self.assertEqual((result.verdict, result.reasons), (verdict, (reason,)))

    def test_a_policy_without_priorities_permits_no_priority_change(self):
        policy = RoutingPolicy("p", ("support",), (), ("bob",))
        self.assertEqual(evaluate(priority_proposal("high"), self.ticket, policy).reasons, ("priority_not_permitted",))

    def test_ticket_without_a_priority_can_be_given_one(self):
        result = evaluate(priority_proposal("low"), Ticket("t1", "support", 0), self.policy)
        self.assertEqual(result.verdict, Verdict.ALLOW)

    def test_schema_four_semantics_deny_every_action_but_reassign_ticket(self):
        legacy_shape = Recommendation("set_ticket_priority", "t1", "support", 0.95, "m", "q")
        self.assertEqual(evaluate(legacy_shape, Ticket("t1", "intake"), self.policy, schema=4).reasons,
                         ("action_not_permitted",))

    def test_reassign_semantics_are_unchanged(self):
        policy = RoutingPolicy("p", ("support",), (), ("bob",))
        proposal = Recommendation("reassign_ticket", "t1", "support", 0.95, "m", "q")
        self.assertEqual(evaluate(proposal, Ticket("t1", "intake"), policy).reasons, ("policy_permits_reassignment",))
        self.assertEqual(evaluate(proposal, Ticket("t1", "support"), policy).reasons, ("already_assigned",))


class ShapeTests(unittest.TestCase):
    def test_each_action_takes_exactly_the_member_its_entry_names(self):
        base = {"ticket_id": "t1", "model": "m", "question_version": "q"}
        for fields in (
                {"action": "set_ticket_priority", "destination": "support"},
                {"action": "set_ticket_priority", "destination": "support", "priority": "high"},
                {"action": "reassign_ticket", "priority": "high"},
                {"action": "reassign_ticket", "destination": "support", "priority": "high"},
                {"action": "set_ticket_priority"}):
            with self.subTest(fields=fields), self.assertRaises(DecisionError):
                Recommendation.from_dict({**base, **fields})
        with self.assertRaises(DecisionError):
            Recommendation("reassign_ticket", "t1", None, 0.9, "m", "q")
        with self.assertRaises(DecisionError):
            Recommendation("reassign_ticket", "t1", "a", 0.9, "m", "q", priority="high")

    def test_unregistered_action_keeps_the_destination_shape(self):
        proposal = Recommendation.from_dict({"action": "issue_refund", "ticket_id": "t1", "destination": "finance",
                                             "model": "m", "question_version": "q"})
        self.assertEqual(proposal.to_dict()["destination"], "finance")

    def test_schema_four_readers_reject_the_new_members(self):
        base = {"ticket_id": "t1", "model": "m", "question_version": "q"}
        with self.assertRaises(DecisionError):
            Recommendation.from_dict({**base, "action": "set_ticket_priority", "priority": "high"}, 4)
        self.assertEqual(Recommendation.from_dict({**base, "action": "set_ticket_priority", "destination": "x"}, 4).target, "x")
        with self.assertRaises(DecisionError):
            Ticket.from_dict({"id": "t", "department": "d", "revision": 0, "priority": "high"}, 4)
        with self.assertRaises(DecisionError):
            RoutingPolicy.from_dict({"version": "p", "allowed_destinations": ["a"], "review_destinations": [],
                                     "reviewers": ["r"], "allowed_priorities": ["high"]}, 4)

    def test_dictionaries_stay_schema_four_shaped_without_priorities(self):
        self.assertEqual(Ticket("t", "d", 1).to_dict(), {"id": "t", "department": "d", "revision": 1})
        policy = RoutingPolicy("p", ("a",), (), ("r",))
        self.assertEqual(set(policy.to_dict()), {"version", "allowed_destinations", "review_destinations",
                                                 "reviewers", "min_probability"})
        self.assertEqual(RoutingPolicy.from_dict(policy.to_dict()), policy)

    def test_review_priorities_must_be_allowed(self):
        with self.assertRaises(DecisionError):
            RoutingPolicy("p", ("a",), (), ("r",), 0.8, ("low",), ("urgent",))


class PriorityLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db = self.root / "queue.sqlite3"
        self.store = TicketStore(self.db)
        self.addCleanup(self.store.close)
        self.store.create_ticket("t1", "support", "normal")
        self.policy = RoutingPolicy("p", ("support",), (), ("bob",), 0.8, ("low", "normal", "high", "urgent"), ("urgent",))

    def submit(self, priority):
        return self.store.submit(priority_proposal(priority), self.policy, proposed_by="alice")

    def test_allowed_priority_is_executed_replayed_and_recorded_as_schema_five(self):
        record = self.submit("high")
        self.assertEqual((record["schema_version"], record["status"]), (5, "READY"))
        self.assertEqual(record["ticket"], {"id": "t1", "department": "support", "revision": 0, "priority": "normal"})
        executed = self.store.execute(record["id"])
        self.assertEqual(executed["result"], {"id": "t1", "department": "support", "revision": 1, "priority": "high"})
        self.assertEqual(self.store.get_ticket("t1"), Ticket("t1", "support", 1, "high"))
        self.assertEqual(replay(export_record(executed))["status"], "EXECUTED")

    def test_review_priority_waits_for_a_reviewer_other_than_the_proposer(self):
        record = self.submit("urgent")
        self.assertEqual(record["status"], "PENDING_REVIEW")
        with self.assertRaises(StateError):
            self.store.approve(record["id"], "alice")
        self.store.approve(record["id"], "bob", "checked")
        self.assertEqual(self.store.execute(record["id"])["result"]["priority"], "urgent")

    def test_denied_priority_is_recorded_but_never_executed(self):
        record = self.submit("critical")
        self.assertEqual((record["status"], record["evaluation"]["reasons"]), ("DENIED", ["priority_not_permitted"]))
        with self.assertRaises(StateError):
            self.store.execute(record["id"])
        self.assertEqual(self.store.get_ticket("t1").priority, "normal")

    def test_a_ticket_changed_after_freezing_makes_the_decision_stale(self):
        first, second = self.submit("high"), self.submit("low")
        self.store.execute(first["id"])
        self.assertEqual(self.store.execute(second["id"])["status"], "STALE")
        self.assertEqual(self.store.get_ticket("t1").priority, "high")

    def test_forged_priority_result_is_rejected_by_replay(self):
        executed = self.store.execute(self.submit("high")["id"])
        forged = deepcopy(executed)
        forged["result"]["priority"] = "urgent"
        with self.assertRaises(DecisionError):
            replay(rehash_record({"record": forged, "sha256": ""}))

    def test_schema_four_records_never_replay_a_priority_action(self):
        record = self.store.execute(self.submit("high")["id"])
        legacy = as_schema4(record)
        with self.assertRaises(DecisionError):
            replay(rehash_record({"record": legacy, "sha256": ""}))

    def test_reassign_records_downgraded_to_schema_four_still_replay(self):
        self.store.create_ticket("t2", "intake")
        proposal = Recommendation("reassign_ticket", "t2", "support", 0.95, "m", "q")
        plain = RoutingPolicy("p", ("support",), (), ("bob",))
        record = self.store.execute(self.store.submit(proposal, plain, "alice")["id"])
        self.assertTrue(replay(rehash_record({"record": as_schema4(record), "sha256": ""}))["valid"])

    def test_store_schema_one_gains_the_priority_column_without_losing_rows(self):
        old = self.root / "old.sqlite3"
        with sqlite3.connect(old) as connection:
            connection.execute("CREATE TABLE tickets (id TEXT PRIMARY KEY NOT NULL, department TEXT NOT NULL, "
                               "revision INTEGER NOT NULL CHECK (revision >= 0))")
            connection.execute("CREATE TABLE decisions (id TEXT PRIMARY KEY NOT NULL, created_at TEXT NOT NULL, "
                               "status TEXT NOT NULL, record TEXT NOT NULL)")
            connection.execute("INSERT INTO tickets VALUES ('t9', 'intake', 4)")
            connection.execute("PRAGMA user_version = 1")
        with TicketStore(old) as upgraded:
            self.assertEqual(upgraded.get_ticket("t9"), Ticket("t9", "intake", 4))
            self.assertEqual(upgraded.submit(priority_proposal("high", ticket_id="t9"), self.policy, "alice")["status"],
                             "READY")
        with sqlite3.connect(old) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 2)


class PriorityCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db = str(self.root / "queue.sqlite3")
        self.policy = self.root / "policy.json"
        self.policy.write_text(json.dumps({
            "version": "p1", "allowed_destinations": ["support"], "review_destinations": [], "reviewers": ["bob"],
            "min_probability": 0.8, "allowed_priorities": ["low", "high", "urgent"],
            "review_priorities": ["urgent"]}), encoding="utf-8")

    def call(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(["--db", self.db, *args])
        return code, json.loads(stdout.getvalue()) if stdout.getvalue() else None, stderr.getvalue()

    def proposal(self, priority):
        path = self.root / f"proposal-{priority}.json"
        path.write_text(json.dumps({"action": "set_ticket_priority", "ticket_id": "T1", "priority": priority,
                                    "probability": 0.95, "model": "hand-authored", "question_version": "q1"}),
                        encoding="utf-8")
        return str(path)

    def test_set_priority_end_to_end_through_the_cli(self):
        self.assertEqual(self.call("ticket-create", "--ticket-id", "T1", "--department", "support",
                                   "--priority", "low")[1],
                         {"id": "T1", "department": "support", "revision": 0, "priority": "low"})
        code, record, _ = self.call("submit", "--proposal", self.proposal("urgent"), "--policy", str(self.policy),
                                    "--proposed-by", "alice")
        self.assertEqual((code, record["status"]), (0, "PENDING_REVIEW"))
        self.assertEqual(self.call("approve", record["id"], "--reviewer", "bob", "--note", "ok")[0], 0)
        self.assertEqual(self.call("execute", record["id"])[1]["result"]["priority"], "urgent")
        self.assertEqual(self.call("ticket-show", "T1")[1]["priority"], "urgent")
        out = self.root / "record.json"
        self.assertEqual(self.call("export", record["id"], "--out", str(out))[0], 0)
        code, replayed, _ = self.call("replay", "--record", str(out))
        self.assertEqual((code, replayed["valid"], replayed["verdict"]), (0, True, "REVIEW"))
        self.assertNotIn("external_policy", replayed)

    def test_evaluate_command_still_scores_reassign_ticket_only(self):
        cases = self.root / "cases.jsonl"
        cases.write_text("", encoding="utf-8")
        code, _, error = self.call("evaluate", "--cases", str(cases), "--policy", str(self.policy),
                                   "--out", str(self.root / "evaluation"))
        self.assertEqual(code, 2)
        self.assertIn("allowed_priorities", error)


if __name__ == "__main__":
    unittest.main()
