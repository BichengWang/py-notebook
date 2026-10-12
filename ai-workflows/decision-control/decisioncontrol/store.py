"""Durable decisions and atomic reassignment of a local SQLite ticket queue."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from threading import RLock
from typing import Iterator
from uuid import uuid4

from .evidence import _validate_record
from .models import (
    DecisionError,
    Recommendation,
    RoutingPolicy,
    StateError,
    Status,
    Ticket,
)
from .policy import INITIAL_STATUS, evaluate


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


class TicketStore:
    """Store local tickets and frozen decision records.

    Each mutation holds a SQLite write transaction, so independent processes or
    connections cannot execute the same decision twice. A lock protects use of
    one instance by multiple threads. Reviewer labels come from the trusted
    caller; membership in the frozen policy is authorization, not authentication.
    """

    def __init__(self, db_path: str | Path):
        self._lock = RLock()
        self._closed = False
        self._connection = sqlite3.connect(
            db_path, timeout=30.0, isolation_level=None, check_same_thread=False,
        )
        self._connection.row_factory = sqlite3.Row
        try:
            with self._transaction() as connection:
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS tickets ("
                    "id TEXT PRIMARY KEY NOT NULL, department TEXT NOT NULL, "
                    "revision INTEGER NOT NULL CHECK (revision >= 0))"
                )
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS decisions ("
                    "id TEXT PRIMARY KEY NOT NULL, created_at TEXT NOT NULL, "
                    "status TEXT NOT NULL, record TEXT NOT NULL)"
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS decisions_pending "
                    "ON decisions (status, created_at, id)"
                )
        except BaseException:
            self.close()
            raise

    def __enter__(self) -> TicketStore:
        with self._lock:
            self._ensure_open()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._connection.close()
                self._closed = True

    def _ensure_open(self) -> None:
        if self._closed:
            raise StateError("TicketStore is closed")

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._ensure_open()
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                yield self._connection
                self._connection.commit()
            except BaseException:
                if self._connection.in_transaction:
                    self._connection.rollback()
                raise

    def create_ticket(self, ticket_id: str, department: str) -> Ticket:
        ticket = Ticket.from_dict({"id": ticket_id, "department": department, "revision": 0})
        with self._transaction() as connection:
            if connection.execute("SELECT 1 FROM tickets WHERE id = ?", (ticket.id,)).fetchone():
                raise DecisionError(f"Ticket already exists: {ticket.id}")
            connection.execute(
                "INSERT INTO tickets (id, department, revision) VALUES (?, ?, ?)",
                (ticket.id, ticket.department, ticket.revision),
            )
        return ticket

    def _get_ticket(self, ticket_id: str) -> Ticket:
        if not isinstance(ticket_id, str) or not ticket_id or ticket_id != ticket_id.strip():
            raise DecisionError("Ticket ID must be a nonempty, stripped string")
        row = self._connection.execute(
            "SELECT id, department, revision FROM tickets WHERE id = ?", (ticket_id,),
        ).fetchone()
        if row is None:
            raise DecisionError(f"Unknown ticket: {ticket_id}")
        return Ticket.from_dict(dict(row))

    def get_ticket(self, ticket_id: str) -> Ticket:
        with self._lock:
            self._ensure_open()
            return self._get_ticket(ticket_id)

    def submit(self, recommendation: Recommendation, policy: RoutingPolicy) -> dict:
        if not isinstance(recommendation, Recommendation) or not isinstance(policy, RoutingPolicy):
            raise DecisionError("submit requires a Recommendation and a RoutingPolicy")
        recommendation = Recommendation.from_dict(recommendation.to_dict())
        policy = RoutingPolicy.from_dict(policy.to_dict())
        with self._transaction() as connection:
            ticket = self._get_ticket(recommendation.ticket_id)
            evaluation = evaluate(recommendation, ticket, policy)
            created_at = _now()
            record = {
                "schema_version": 2,
                "id": str(uuid4()),
                "created_at": created_at,
                "recommendation": recommendation.to_dict(),
                "ticket": ticket.to_dict(),
                "policy": policy.to_dict(),
                "evaluation": evaluation.to_dict(),
                "status": INITIAL_STATUS[evaluation.verdict],
                "review": None,
                "result": None,
                "events": [{"event": "SUBMITTED", "at": created_at}],
            }
            connection.execute(
                "INSERT INTO decisions (id, created_at, status, record) VALUES (?, ?, ?, ?)",
                (record["id"], created_at, record["status"], self._serialize(record)),
            )
        return record

    @staticmethod
    def _serialize(record: dict) -> str:
        return json.dumps(record, ensure_ascii=False, allow_nan=False, separators=(",", ":"))

    @staticmethod
    def _decode(row: sqlite3.Row) -> dict:
        try:
            record = json.loads(row["record"])
        except (json.JSONDecodeError, TypeError) as exc:
            raise DecisionError("Stored decision is not valid JSON") from exc
        _validate_record(record)
        if (
            record["id"] != row["id"]
            or record["created_at"] != row["created_at"]
            or record["status"] != row["status"]
        ):
            raise DecisionError("Stored decision disagrees with its database index")
        return record

    def _get(self, decision_id: str) -> dict:
        if not isinstance(decision_id, str) or not decision_id or decision_id != decision_id.strip():
            raise DecisionError("Decision ID must be a nonempty, stripped string")
        row = self._connection.execute(
            "SELECT id, created_at, status, record FROM decisions WHERE id = ?", (decision_id,),
        ).fetchone()
        if row is None:
            raise DecisionError(f"Unknown decision: {decision_id}")
        return self._decode(row)

    def get(self, decision_id: str) -> dict:
        with self._lock:
            self._ensure_open()
            return self._get(decision_id)

    def pending(self) -> list[dict]:
        with self._lock:
            self._ensure_open()
            rows = self._connection.execute(
                "SELECT id, created_at, status, record FROM decisions "
                "WHERE status = ? ORDER BY created_at, id",
                (Status.PENDING_REVIEW.value,),
            ).fetchall()
            return [self._decode(row) for row in rows]

    def _save(self, record: dict) -> None:
        _validate_record(record)
        self._connection.execute(
            "UPDATE decisions SET status = ?, record = ? WHERE id = ?",
            (record["status"], self._serialize(record), record["id"]),
        )

    @staticmethod
    def _authorize_reviewer(record: dict, reviewer: str, note: str) -> None:
        if not isinstance(reviewer, str) or not reviewer or reviewer != reviewer.strip():
            raise DecisionError("Reviewer must be a nonempty, stripped identifier")
        if not isinstance(note, str):
            raise DecisionError("Review note must be a string")
        # The frozen policy has already been validated by _get.
        if reviewer not in record["policy"]["reviewers"]:
            raise StateError(f"Reviewer is not authorized by this decision's policy: {reviewer}")

    def _review(self, decision_id: str, reviewer: str, note: str, decision: str) -> dict:
        with self._transaction():
            record = self._get(decision_id)
            self._authorize_reviewer(record, reviewer, note)
            previous = record["review"]
            if decision == "APPROVED" and previous is not None and (
                previous["decision"] == decision
                and previous["reviewer"] == reviewer
                and previous["note"] == note
                and record["status"] != Status.CANCELLED.value
            ):
                return record
            if record["status"] != Status.PENDING_REVIEW.value:
                raise StateError(f"Cannot record {decision.lower()} review in state {record['status']}")
            at = _now()
            record["review"] = {"decision": decision, "reviewer": reviewer, "note": note, "at": at}
            record["status"] = Status.READY.value if decision == "APPROVED" else Status.REJECTED.value
            record["events"].append({"event": decision, "at": at})
            self._save(record)
            return record

    def approve(self, decision_id: str, reviewer: str, note: str = "") -> dict:
        return self._review(decision_id, reviewer, note, "APPROVED")

    def reject(self, decision_id: str, reviewer: str, note: str = "") -> dict:
        return self._review(decision_id, reviewer, note, "REJECTED")

    def cancel(self, decision_id: str, reviewer: str, note: str) -> dict:
        """Withdraw an unexecuted decision; retain any prior approval and its provenance."""
        with self._transaction():
            record = self._get(decision_id)
            self._authorize_reviewer(record, reviewer, note)
            if not note.strip():
                raise DecisionError("Cancellation requires a nonempty reason")
            if record["status"] == Status.CANCELLED.value:
                cancellation = record["events"][-1]
                if cancellation["reviewer"] == reviewer and cancellation["note"] == note:
                    return record
                raise StateError("Cancellation is already recorded with a different actor or reason")
            if record["status"] not in (Status.READY.value, Status.PENDING_REVIEW.value):
                raise StateError(f"Cannot cancel decision in state {record['status']}")
            record["schema_version"] = 2
            record["status"] = Status.CANCELLED.value
            record["events"].append({
                "event": "CANCELLED", "at": _now(), "reviewer": reviewer, "note": note,
            })
            self._save(record)
            return record

    def execute(self, decision_id: str) -> dict:
        with self._transaction() as connection:
            record = self._get(decision_id)
            if record["status"] == Status.EXECUTED.value:
                return record
            if record["status"] != Status.READY.value:
                raise StateError(f"Cannot execute decision in state {record['status']}")
            frozen_ticket = Ticket.from_dict(record["ticket"])
            recommendation = Recommendation.from_dict(record["recommendation"])
            current = self._get_ticket(frozen_ticket.id)
            at = _now()
            if current.revision != frozen_ticket.revision or current.department != frozen_ticket.department:
                record["status"] = Status.STALE.value
                record["events"].append({"event": "STALE", "at": at})
            else:
                result = Ticket(current.id, recommendation.destination, current.revision + 1)
                connection.execute(
                    "UPDATE tickets SET department = ?, revision = ? WHERE id = ?",
                    (result.department, result.revision, result.id),
                )
                record["result"] = result.to_dict()
                record["status"] = Status.EXECUTED.value
                record["events"].append({"event": "EXECUTED", "at": at})
            self._save(record)
            return record
