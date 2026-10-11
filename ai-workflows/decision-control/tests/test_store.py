"""Behavioral checks for durable local decisions; no external executor is used."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from threading import Barrier
import unittest

from decisioncontrol.evidence import export_record, replay
from decisioncontrol.models import DecisionError, Recommendation, RoutingPolicy, StateError, Ticket
from decisioncontrol.store import TicketStore


class TicketStoreTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.db_path = Path(directory.name) / "tickets.sqlite3"
        self.store = TicketStore(self.db_path)
        self.addCleanup(self.store.close)
        self.ticket = self.store.create_ticket("ticket-1", "intake")
        self.policy = RoutingPolicy(
            version="routing-2026-10",
            allowed_destinations=("support", "legal", "finance", "intake"),
            review_destinations=("legal",),
            reviewers=("alice", "bob"),
            min_probability=0.8,
        )

    def proposal(self, **changes):
        proposal = Recommendation(
            action="reassign_ticket",
            ticket_id="ticket-1",
            destination="support",
            probability=0.95,
            model="recorded-test-model",
            question_version="routing-question-3",
        )
        return replace(proposal, **changes)

    def submit(self, **changes):
        return self.store.submit(self.proposal(**changes), self.policy)

    def reopen(self):
        self.store.close()
        self.store = TicketStore(self.db_path)
        self.addCleanup(self.store.close)

    @staticmethod
    def event_names(record):
        return [event["event"] for event in record["events"]]

    def race(self, operations):
        barrier = Barrier(len(operations))

        def perform(operation):
            with TicketStore(self.db_path) as store:
                barrier.wait(timeout=10)
                return operation(store)

        with ThreadPoolExecutor(max_workers=len(operations)) as executor:
            futures = [executor.submit(perform, operation) for operation in operations]
            return [future.result(timeout=35) for future in futures]

    def replace_stored_record(self, record):
        with closing(sqlite3.connect(self.db_path)) as connection, connection:
            connection.execute(
                "UPDATE decisions SET status = ?, record = ? WHERE id = ?",
                (record["status"], json.dumps(record), record["id"]),
            )

    def test_ticket_validation_duplicates_unknown_ids_and_context_manager(self):
        self.assertEqual(self.store.get_ticket("ticket-1"), Ticket("ticket-1", "intake", 0))
        with self.assertRaises(DecisionError):
            self.store.create_ticket("ticket-1", "finance")
        self.assertEqual(self.store.get_ticket("ticket-1"), self.ticket)
        for ticket_id, department in (("", "intake"), (" ticket ", "intake"), ("new", "")):
            with self.subTest(ticket_id=ticket_id, department=department):
                with self.assertRaises(DecisionError):
                    self.store.create_ticket(ticket_id, department)
        for invalid_id in ("unknown", "", [], None):
            with self.subTest(invalid_id=invalid_id):
                with self.assertRaises(DecisionError):
                    self.store.get_ticket(invalid_id)
                with self.assertRaises(DecisionError):
                    self.store.get(invalid_id)
        with TicketStore(self.db_path) as reopened:
            self.assertEqual(reopened.get_ticket("ticket-1"), self.ticket)
        reopened.close()
        with self.assertRaises(StateError):
            reopened.get_ticket("ticket-1")
        with self.assertRaises(StateError):
            reopened.__enter__()

    def test_submission_freezes_inputs_and_only_execution_mutates_the_ticket(self):
        proposal = self.proposal()
        record = self.store.submit(proposal, self.policy)
        self.assertEqual(self.store.get_ticket("ticket-1"), self.ticket)
        decision_id = record["id"]
        record["recommendation"]["destination"] = "finance"
        record["policy"]["reviewers"].append("mallory")
        record["events"].clear()
        executed = self.store.execute(decision_id)
        self.assertEqual(self.store.get_ticket("ticket-1"), Ticket("ticket-1", "support", 1))
        self.assertEqual(executed["result"], Ticket("ticket-1", "support", 1).to_dict())
        self.assertEqual(self.event_names(executed), ["SUBMITTED", "EXECUTED"])
        self.assertEqual(replay(export_record(executed))["status"], "EXECUTED")

    def test_unknown_ticket_and_wrong_submission_types_store_no_decision(self):
        with self.assertRaises(DecisionError):
            self.submit(ticket_id="unknown")
        for recommendation, policy in (({}, self.policy), (self.proposal(), {})):
            with self.subTest(recommendation=recommendation, policy=policy):
                with self.assertRaises(DecisionError):
                    self.store.submit(recommendation, policy)
        with closing(sqlite3.connect(self.db_path)) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM decisions").fetchone()[0], 0)
        self.assertEqual(self.store.get_ticket("ticket-1"), self.ticket)

    def test_review_approval_and_execution_survive_restarts(self):
        submitted = self.submit(destination="legal")
        decision_id = submitted["id"]
        self.assertEqual(submitted["status"], "PENDING_REVIEW")
        self.assertEqual(self.store.pending(), [submitted])
        self.reopen()
        self.assertEqual(self.store.pending(), [submitted])
        approved = self.store.approve(decision_id, "alice", "Reviewed constraints.\nApprouvé")
        self.assertEqual(approved["status"], "READY")
        self.assertEqual(self.event_names(approved), ["SUBMITTED", "APPROVED"])
        self.assertEqual(approved["review"], {
            "decision": "APPROVED", "reviewer": "alice",
            "note": "Reviewed constraints.\nApprouvé", "at": approved["events"][1]["at"],
        })
        self.assertEqual(self.store.pending(), [])
        self.assertEqual(self.store.get_ticket("ticket-1"), self.ticket)
        self.reopen()
        self.assertEqual(self.store.get(decision_id), approved)
        executed = self.store.execute(decision_id)
        self.reopen()
        self.assertEqual(self.store.get(decision_id), executed)
        self.assertEqual(self.store.execute(decision_id), executed)
        self.assertEqual(self.store.get_ticket("ticket-1"), Ticket("ticket-1", "legal", 1))
        self.assertEqual(self.event_names(executed), ["SUBMITTED", "APPROVED", "EXECUTED"])
        self.assertEqual(replay(export_record(executed))["status"], "EXECUTED")

    def test_deny_and_abstain_are_terminal_and_cannot_be_overridden(self):
        cases = (
            ({"action": "delete_ticket"}, "DENIED", "action_not_permitted"),
            ({"destination": "forbidden"}, "DENIED", "destination_not_permitted"),
            ({"destination": "intake"}, "DENIED", "already_assigned"),
            ({"refused": True}, "ABSTAINED", "model_refused"),
            ({"probability": None}, "ABSTAINED", "probability_unknown"),
            ({"probability": 0.79}, "ABSTAINED", "below_probability_threshold"),
        )
        for changes, status, reason in cases:
            with self.subTest(changes=changes):
                record = self.submit(**changes)
                self.assertEqual(record["status"], status)
                self.assertEqual(record["evaluation"]["reasons"], [reason])
                for operation in (
                    lambda: self.store.execute(record["id"]),
                    lambda: self.store.approve(record["id"], "alice"),
                    lambda: self.store.reject(record["id"], "alice"),
                ):
                    with self.assertRaises(StateError):
                        operation()
                self.assertEqual(self.store.get(record["id"]), record)
                self.assertEqual(self.store.get_ticket("ticket-1"), self.ticket)
                self.assertEqual(replay(export_record(record))["status"], status)
        self.assertEqual(self.store.pending(), [])

    def test_pending_review_cannot_execute_and_unauthorized_review_cannot_change_it(self):
        pending = self.submit(destination="legal")
        with self.assertRaises(StateError):
            self.store.execute(pending["id"])
        for reviewer in ("mallory", "Alice"):
            for operation in (self.store.approve, self.store.reject):
                with self.subTest(reviewer=reviewer, operation=operation.__name__):
                    with self.assertRaises(StateError):
                        operation(pending["id"], reviewer, "not authorized")
                    self.assertEqual(self.store.get(pending["id"]), pending)
        for reviewer, note in (("", ""), (" alice ", ""), (None, ""), ("alice", None)):
            with self.subTest(reviewer=reviewer, note=note):
                with self.assertRaises(DecisionError):
                    self.store.approve(pending["id"], reviewer, note)
        self.assertEqual(self.store.get_ticket("ticket-1"), self.ticket)
        self.assertEqual(self.store.pending(), [pending])

    def test_same_approval_is_idempotent_but_conflicting_reviews_are_rejected(self):
        pending = self.submit(destination="legal")
        decision_id = pending["id"]
        approved = self.store.approve(decision_id, "alice", "checked")
        self.assertEqual(self.store.approve(decision_id, "alice", "checked"), approved)
        self.reopen()
        self.assertEqual(self.store.approve(decision_id, "alice", "checked"), approved)
        for reviewer, note in (("alice", "changed"), ("bob", "checked")):
            with self.subTest(reviewer=reviewer, note=note):
                with self.assertRaises(StateError):
                    self.store.approve(decision_id, reviewer, note)
        with self.assertRaises(StateError):
            self.store.reject(decision_id, "alice", "checked")
        executed = self.store.execute(decision_id)
        self.assertEqual(self.store.approve(decision_id, "alice", "checked"), executed)
        self.assertEqual(self.store.execute(decision_id), executed)
        self.assertEqual(self.event_names(executed), ["SUBMITTED", "APPROVED", "EXECUTED"])
        self.assertEqual(self.store.get_ticket("ticket-1"), Ticket("ticket-1", "legal", 1))

    def test_rejection_is_durable_and_prevents_approval_or_execution(self):
        pending = self.submit(destination="legal")
        rejected = self.store.reject(pending["id"], "bob", "Do not route this ticket")
        self.assertEqual(rejected["status"], "REJECTED")
        self.assertEqual(self.event_names(rejected), ["SUBMITTED", "REJECTED"])
        self.assertEqual(rejected["review"]["reviewer"], "bob")
        self.reopen()
        self.assertEqual(self.store.get(pending["id"]), rejected)
        self.assertEqual(self.store.pending(), [])
        with self.assertRaises(StateError):
            self.store.execute(pending["id"])
        with self.assertRaises(StateError):
            self.store.approve(pending["id"], "bob", "Do not route this ticket")
        with self.assertRaises(StateError):
            self.store.reject(pending["id"], "alice", "Different rejection")
        self.assertEqual(self.store.get_ticket("ticket-1"), self.ticket)
        self.assertEqual(replay(export_record(rejected))["status"], "REJECTED")

    def test_frozen_policy_not_a_later_policy_controls_review_and_action(self):
        pending = self.submit(destination="legal")
        new_policy = RoutingPolicy("routing-revoked", ("finance",), (), ("carol",), 0.9)
        newer = self.store.submit(self.proposal(destination="legal"), new_policy)
        self.assertEqual(newer["status"], "DENIED")
        with self.assertRaises(StateError):
            self.store.approve(pending["id"], "carol")
        self.store.approve(pending["id"], "alice")
        executed = self.store.execute(pending["id"])
        self.assertEqual(executed["policy"], self.policy.to_dict())
        self.assertEqual(self.store.get_ticket("ticket-1"), Ticket("ticket-1", "legal", 1))

    def test_stale_revision_is_terminal_without_an_additional_ticket_mutation(self):
        obsolete = self.submit(destination="legal")
        self.store.approve(obsolete["id"], "alice", "approved original snapshot")
        competing = self.submit(destination="support")
        self.store.execute(competing["id"])
        before = self.store.get_ticket("ticket-1")
        stale = self.store.execute(obsolete["id"])
        self.assertEqual(stale["status"], "STALE")
        self.assertIsNone(stale["result"])
        self.assertEqual(self.event_names(stale), ["SUBMITTED", "APPROVED", "STALE"])
        self.assertEqual(self.store.get_ticket("ticket-1"), before)
        self.assertEqual(
            self.store.approve(obsolete["id"], "alice", "approved original snapshot"), stale,
        )
        with self.assertRaises(StateError):
            self.store.execute(obsolete["id"])
        self.reopen()
        self.assertEqual(self.store.get(obsolete["id"]), stale)
        self.assertEqual(replay(export_record(stale))["status"], "STALE")

    def test_department_mismatch_alone_marks_a_proposal_stale(self):
        record = self.submit()
        with closing(sqlite3.connect(self.db_path)) as connection, connection:
            connection.execute("UPDATE tickets SET department = 'finance' WHERE id = 'ticket-1'")
        stale = self.store.execute(record["id"])
        self.assertEqual(stale["status"], "STALE")
        self.assertEqual(self.event_names(stale), ["SUBMITTED", "STALE"])
        self.assertEqual(self.store.get_ticket("ticket-1"), Ticket("ticket-1", "finance", 0))
        self.assertIsNone(stale["result"])

    def test_revision_mismatch_alone_marks_a_proposal_stale(self):
        record = self.submit()
        with closing(sqlite3.connect(self.db_path)) as connection, connection:
            connection.execute("UPDATE tickets SET revision = 1 WHERE id = 'ticket-1'")
        stale = self.store.execute(record["id"])
        self.assertEqual(stale["status"], "STALE")
        self.assertEqual(self.store.get_ticket("ticket-1"), Ticket("ticket-1", "intake", 1))
        self.assertIsNone(stale["result"])

    def test_new_proposal_uses_current_trusted_revision(self):
        self.store.execute(self.submit()["id"])
        proposal = self.proposal(destination="finance", question_version="routing-question-4")
        record = self.store.submit(proposal, self.policy)
        self.assertEqual(record["ticket"], Ticket("ticket-1", "support", 1).to_dict())
        self.assertEqual(record["recommendation"], proposal.to_dict())
        executed = self.store.execute(record["id"])
        self.assertEqual(executed["result"], Ticket("ticket-1", "finance", 2).to_dict())

    def test_duplicate_execution_returns_its_original_result_after_later_decisions(self):
        original = self.store.execute(self.submit()["id"])
        second = self.store.execute(self.submit(destination="finance")["id"])
        self.assertEqual(second["result"]["revision"], 2)
        self.reopen()
        self.assertEqual(self.store.execute(original["id"]), original)
        self.assertEqual(self.store.get_ticket("ticket-1"), Ticket("ticket-1", "finance", 2))

    def test_decision_write_failure_rolls_back_the_ticket_update(self):
        record = self.submit()
        with closing(sqlite3.connect(self.db_path)) as connection, connection:
            connection.execute(
                "CREATE TRIGGER fail_execution BEFORE UPDATE ON decisions "
                "WHEN NEW.status = 'EXECUTED' BEGIN "
                "SELECT RAISE(ABORT, 'injected decision write failure'); END"
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.execute(record["id"])
        self.reopen()
        self.assertEqual(self.store.get_ticket("ticket-1"), self.ticket)
        self.assertEqual(self.store.get(record["id"]), record)
        with closing(sqlite3.connect(self.db_path)) as connection, connection:
            connection.execute("DROP TRIGGER fail_execution")
        executed = self.store.execute(record["id"])
        self.assertEqual(self.event_names(executed), ["SUBMITTED", "EXECUTED"])
        self.assertEqual(self.store.execute(record["id"]), executed)
        self.assertEqual(self.store.get_ticket("ticket-1"), Ticket("ticket-1", "support", 1))

    def test_racing_independent_executors_mutate_a_ticket_once(self):
        record = self.submit()
        outcomes = self.race([
            lambda store: store.execute(record["id"]),
            lambda store: store.execute(record["id"]),
        ])
        self.assertEqual(outcomes[0], outcomes[1])
        self.assertEqual(self.event_names(outcomes[0]), ["SUBMITTED", "EXECUTED"])
        self.reopen()
        self.assertEqual(self.store.get(record["id"]), outcomes[0])
        self.assertEqual(self.store.get_ticket("ticket-1"), Ticket("ticket-1", "support", 1))

    def test_racing_executors_can_share_one_store_instance(self):
        record = self.submit()
        barrier = Barrier(2)

        def execute():
            barrier.wait(timeout=10)
            return self.store.execute(record["id"])

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(execute) for _ in range(2)]
            outcomes = [future.result(timeout=35) for future in futures]
        self.assertEqual(outcomes[0], outcomes[1])
        self.assertEqual(self.store.get_ticket("ticket-1"), Ticket("ticket-1", "support", 1))
        self.assertEqual(self.event_names(outcomes[0]), ["SUBMITTED", "EXECUTED"])

    def test_racing_distinct_decisions_have_one_execution_and_one_stale_result(self):
        support = self.submit(destination="support")
        finance = self.submit(destination="finance")
        outcomes = self.race([
            lambda store: store.execute(support["id"]),
            lambda store: store.execute(finance["id"]),
        ])
        self.assertCountEqual([record["status"] for record in outcomes], ["EXECUTED", "STALE"])
        executed = next(record for record in outcomes if record["status"] == "EXECUTED")
        stale = next(record for record in outcomes if record["status"] == "STALE")
        self.assertEqual(self.store.get_ticket("ticket-1").to_dict(), executed["result"])
        self.assertEqual(executed["result"]["revision"], 1)
        self.assertIsNone(stale["result"])
        self.assertEqual(self.event_names(stale), ["SUBMITTED", "STALE"])

    def test_racing_identical_approvals_have_one_event(self):
        pending = self.submit(destination="legal")
        outcomes = self.race([
            lambda store: store.approve(pending["id"], "alice", "checked"),
            lambda store: store.approve(pending["id"], "alice", "checked"),
        ])
        self.assertEqual(outcomes[0], outcomes[1])
        self.assertEqual(self.event_names(outcomes[0]), ["SUBMITTED", "APPROVED"])
        self.assertEqual(self.store.get_ticket("ticket-1"), self.ticket)

    def test_racing_conflicting_reviews_commit_only_one_transition(self):
        pending = self.submit(destination="legal")

        def attempt(store, action):
            try:
                return getattr(store, action)(pending["id"], "alice", "reviewed")
            except StateError:
                return None

        outcomes = self.race([
            lambda store: attempt(store, "approve"),
            lambda store: attempt(store, "reject"),
        ])
        committed = [record for record in outcomes if record is not None]
        self.assertEqual(len(committed), 1)
        saved = self.store.get(pending["id"])
        self.assertEqual(saved, committed[0])
        self.assertEqual(len(saved["events"]), 2)
        self.assertIn(saved["status"], ("READY", "REJECTED"))
        self.assertEqual(self.store.get_ticket("ticket-1"), self.ticket)

    def test_corrupt_frozen_snapshots_evaluation_or_history_do_not_authorize_execution(self):
        def change_destination(record):
            record["recommendation"]["destination"] = "forbidden"

        def change_evaluation(record):
            record["evaluation"]["reasons"] = ["fabricated permission"]

        def append_false_event(record):
            record["events"].append({"event": "APPROVED", "at": record["created_at"]})

        def change_snapshot_type(record):
            record["ticket"]["revision"] = True

        for corrupt in (change_destination, change_evaluation, append_false_event, change_snapshot_type):
            with self.subTest(corrupt=corrupt.__name__):
                record = self.submit()
                corrupt(record)
                self.replace_stored_record(record)
                with self.assertRaises(DecisionError):
                    self.store.execute(record["id"])
                self.assertEqual(self.store.get_ticket("ticket-1"), self.ticket)

    def test_changing_a_terminal_status_to_ready_does_not_override_the_policy(self):
        denied = self.submit(destination="forbidden")
        denied["status"] = "READY"
        self.replace_stored_record(denied)
        with self.assertRaises(DecisionError):
            self.store.execute(denied["id"])
        self.assertEqual(self.store.get_ticket("ticket-1"), self.ticket)

    def test_corrupt_review_authorization_cannot_execute(self):
        pending = self.submit(destination="legal")
        approved = self.store.approve(pending["id"], "alice")
        approved["review"]["reviewer"] = "mallory"
        self.replace_stored_record(approved)
        with self.assertRaises(DecisionError):
            self.store.execute(approved["id"])
        self.assertEqual(self.store.get_ticket("ticket-1"), self.ticket)

    def test_corrupt_database_index_is_not_used_as_authorization(self):
        record = self.submit()
        with closing(sqlite3.connect(self.db_path)) as connection, connection:
            connection.execute(
                "UPDATE decisions SET status = 'PENDING_REVIEW' WHERE id = ?", (record["id"],),
            )
        with self.assertRaises(DecisionError):
            self.store.pending()
        with self.assertRaises(DecisionError):
            self.store.execute(record["id"])
        self.assertEqual(self.store.get_ticket("ticket-1"), self.ticket)


if __name__ == "__main__":
    unittest.main()
