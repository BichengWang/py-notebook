"""Portable evidence replay without a model call or an action side effect.

A checksum detects corruption, not a malicious writer who can replace the checksum.
"""

from collections.abc import Mapping
from datetime import datetime, timedelta
import hashlib
import json
from uuid import UUID

from .models import DecisionError, Evaluation, Recommendation, RoutingPolicy, Status, Ticket, _fields, _text
from .policy import INITIAL_STATUS, evaluate


RECORD_FIELDS = {"schema_version", "id", "created_at", "recommendation", "ticket", "policy",
                 "evaluation", "status", "review", "result", "events"}


def _canonical(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                          allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise DecisionError(f"evidence must be finite JSON: {error}") from error


def _timestamp(value):
    _text(value, "timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise DecisionError("timestamp must be ISO 8601 UTC") from error
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise DecisionError("timestamp must be ISO 8601 UTC")
    return value


def _validate_record(record):
    raw = _fields(record, RECORD_FIELDS)
    if type(raw["schema_version"]) is not int or raw["schema_version"] not in (1, 2):
        raise DecisionError("unsupported evidence schema_version")
    _text(raw["id"], "decision id")
    try:
        UUID(raw["id"])
    except ValueError as error:
        raise DecisionError("decision id must be a UUID") from error
    _timestamp(raw["created_at"])
    proposal = Recommendation.from_dict(raw["recommendation"])
    ticket = Ticket.from_dict(raw["ticket"])
    policy = RoutingPolicy.from_dict(raw["policy"])
    recorded = Evaluation.from_dict(raw["evaluation"])
    expected = evaluate(proposal, ticket, policy)
    if recorded != expected:
        raise DecisionError("recorded verdict/reasons do not match the frozen inputs and policy")
    try:
        status = Status(raw["status"])
    except (ValueError, TypeError) as error:
        raise DecisionError("unknown lifecycle status") from error
    events = raw["events"]
    if not isinstance(events, list) or not events:
        raise DecisionError("evidence must contain a submission event")
    state = INITIAL_STATUS[expected.verdict]
    review_event = None
    for index, event in enumerate(events):
        name = event.get("event") if isinstance(event, Mapping) else None
        fields = {"event", "at", "reviewer", "note"} if name == "CANCELLED" else {"event", "at"}
        event = _fields(event, fields)
        at = _timestamp(event["at"])
        if index == 0:
            if name != "SUBMITTED" or at != raw["created_at"]:
                raise DecisionError("first event must match submission time")
            continue
        if name in ("APPROVED", "REJECTED") and state == Status.PENDING_REVIEW.value:
            review_event = event
            state = Status.READY.value if name == "APPROVED" else Status.REJECTED.value
        elif name in ("EXECUTED", "STALE") and state == Status.READY.value:
            state = name
        elif (name == "CANCELLED" and raw["schema_version"] == 2
              and state in (Status.READY.value, Status.PENDING_REVIEW.value)):
            if event["reviewer"] not in policy.reviewers:
                raise DecisionError("cancelling reviewer is not authorized by the frozen policy")
            if not isinstance(event["note"], str) or not event["note"].strip():
                raise DecisionError("cancellation must contain a nonempty reason")
            state = Status.CANCELLED.value
        else:
            raise DecisionError("event history contains a prohibited transition")
    if status.value != state:
        raise DecisionError("lifecycle status does not match event history")
    review = raw["review"]
    if review_event is None:
        if review is not None:
            raise DecisionError("review has no corresponding review event")
    else:
        review = _fields(review, {"decision", "reviewer", "note", "at"})
        if review["decision"] != review_event["event"] or review["at"] != review_event["at"]:
            raise DecisionError("review does not match its event")
        if review["reviewer"] not in policy.reviewers:
            raise DecisionError("reviewer is not authorized by the frozen policy")
        if not isinstance(review["note"], str):
            raise DecisionError("review note must be text")
    if status == Status.EXECUTED:
        result = Ticket.from_dict(raw["result"])
        expected_result = Ticket(ticket.id, proposal.destination, ticket.revision + 1)
        if result != expected_result:
            raise DecisionError("execution result does not match the approved action")
    elif raw["result"] is not None:
        raise DecisionError("an unexecuted decision cannot contain an execution result")
    return {"valid": True, "decision_id": raw["id"], "verdict": expected.verdict.value,
            "status": status.value}


def export_record(record: dict) -> dict:
    """Validate and checksum the entire record, including review and execution history."""
    _validate_record(record)
    return {"record": record, "sha256": hashlib.sha256(_canonical(record)).hexdigest()}


def replay(envelope: dict) -> dict:
    """Check integrity and reproduce authorization from frozen inputs; never execute."""
    raw = _fields(envelope, {"record", "sha256"})
    digest = raw["sha256"]
    if not isinstance(digest, str) or len(digest) != 64:
        raise DecisionError("sha256 must be a 64-character digest")
    if hashlib.sha256(_canonical(raw["record"])).hexdigest() != digest:
        raise DecisionError("evidence checksum mismatch")
    return _validate_record(raw["record"])
