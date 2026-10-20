"""Portable evidence replay without a model call or an action side effect.

A checksum detects corruption, not a malicious writer who can replace the checksum.
Record schemas 1-3 digest Python's sorted compact JSON; schemas 4 and later digest RFC 8785
(JCS) canonical bytes and reject duplicate object keys when parsing. Schema 5 adds the
action registry and an optional frozen OPA or Cedar decision (``external_policy``). Schemas 4 and later also
require the decision id in its canonical lowercase hyphenated form; schemas 1-3 accept any id ``uuid.UUID`` parses.
"""

from collections.abc import Mapping
from datetime import datetime, timedelta
import hashlib
import json
from uuid import UUID

from . import jcs
from .actions import actions_for
from .adapters import engine_for
from .models import (DecisionError, Evaluation, Recommendation, RecordMismatch, RoutingPolicy, Status,
                     Ticket, _fields, _text)
from .policy import INITIAL_STATUS, combine, evaluate


RECORD_FIELDS = {"schema_version", "id", "created_at", "recommendation", "ticket", "policy",
                 "evaluation", "status", "review", "result", "events"}


LEGACY_SCHEMAS = (1, 2, 3)
JCS_SCHEMA = 4
EXTERNAL_SCHEMA = 5
SCHEMAS = LEGACY_SCHEMAS + (JCS_SCHEMA, EXTERNAL_SCHEMA)


def _canonical(value):
    """Canonical bytes of schemas 1-3 (python-json-v1); kept so old records verify."""
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                          allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise DecisionError(f"evidence must be finite JSON: {error}") from error


def _canonical_jcs(value):
    try:
        return jcs.canonicalize(value)
    except ValueError as error:
        raise DecisionError(f"evidence must be RFC 8785 canonicalizable JSON: {error}") from error


def canonical_bytes(value, *, jcs):
    """Return RFC 8785 bytes when ``jcs`` is true, else the python-json-v1 bytes."""
    return _canonical_jcs(value) if jcs else _canonical(value)


def digest(value, *, jcs):
    """Lowercase hexadecimal SHA-256 of the canonical bytes."""
    return hashlib.sha256(canonical_bytes(value, jcs=jcs)).hexdigest()


def _schema_version(record):
    """Return a supported schema version or reject before any digest is computed."""
    version = record.get("schema_version") if isinstance(record, Mapping) else None
    if type(version) is not int or version not in SCHEMAS:
        raise DecisionError("unsupported evidence schema_version")
    return version


def parse_json(text):
    """Parse JSON, returning ``(value, has_duplicate_keys)``; the last duplicate wins."""
    duplicates = False

    def pairs(items):
        nonlocal duplicates
        members = {}
        for key, value in items:
            if key in members:
                duplicates = True
            members[key] = value
        return members

    value = json.loads(text, object_pairs_hook=pairs)
    return value, duplicates


def parse_record(text):
    """Parse an exported record or stored row; schemas 4 and later reject duplicate object keys."""
    value, duplicates = parse_json(text)
    if duplicates:
        record = value.get("record", value) if isinstance(value, Mapping) else None
        version = record.get("schema_version") if isinstance(record, Mapping) else None
        if type(version) is int and version >= JCS_SCHEMA:
            raise DecisionError("duplicate object keys are not allowed in evidence schema 4 and later")
    return value


def _timestamp(value):
    _text(value, "timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise DecisionError("timestamp must be ISO 8601 UTC") from error
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise DecisionError("timestamp must be ISO 8601 UTC")
    return value


def _external(raw, schema, proposal, ticket):
    """Validate the frozen external decision; return ``(adapter, frozen, Evaluation)`` or ``None``."""
    external, recorded_digest = raw["external_policy"], raw["external_policy_sha256"]
    if external is None:
        if recorded_digest is not None:
            raise DecisionError("external_policy_sha256 requires an external_policy")
        return None
    adapter = engine_for(external)
    adapter.validate(external)
    if recorded_digest != digest(external, jcs=True):
        raise RecordMismatch("external_policy_sha256 does not match the frozen external policy decision")
    adapter.bind(external, proposal, ticket, raw["proposed_by"])
    return adapter, external, adapter.evaluation(external)


def _check_record(record):
    """Offline checks of one record; returns the summary and the external decision to re-evaluate."""
    schema = _schema_version(record)
    fields = RECORD_FIELDS | {"produced_by", "proposed_by", "policy_sha256"} if schema >= 3 else RECORD_FIELDS
    if schema >= EXTERNAL_SCHEMA:
        fields = fields | {"external_policy", "external_policy_sha256"}
    raw = _fields(record, fields)
    _text(raw["id"], "decision id")
    try:
        identifier = UUID(raw["id"])
    except ValueError as error:
        raise DecisionError("decision id must be a UUID") from error
    if schema >= JCS_SCHEMA and str(identifier) != raw["id"]:
        raise DecisionError("decision id must be a lowercase hyphenated UUID")
    _timestamp(raw["created_at"])
    proposal = Recommendation.from_dict(raw["recommendation"], schema)
    ticket = Ticket.from_dict(raw["ticket"], schema)
    policy = RoutingPolicy.from_dict(raw["policy"], schema)
    if schema >= 3:
        _text(raw["proposed_by"], "proposed_by")
        producer = _fields(raw["produced_by"], {"name", "version"})
        if producer["name"] != "decisioncontrol":
            raise DecisionError("unexpected evidence producer")
        _text(producer["version"], "producer version")
        if raw["policy_sha256"] != digest(raw["policy"], jcs=schema >= JCS_SCHEMA):
            raise RecordMismatch("policy_sha256 does not match the frozen policy")
    recorded = Evaluation.from_dict(raw["evaluation"])
    expected = evaluate(proposal, ticket, policy, schema=schema)
    external = _external(raw, schema, proposal, ticket) if schema >= EXTERNAL_SCHEMA else None
    if external is not None:
        expected = combine(expected, external[2])
    if recorded != expected:
        raise RecordMismatch("recorded verdict/reasons do not match the frozen inputs and policy")
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
        elif (name == "CANCELLED" and raw["schema_version"] >= 2
              and state in (Status.READY.value, Status.PENDING_REVIEW.value)):
            if (schema >= 3 and expected.verdict.value == "REVIEW"
                    and event["reviewer"] == raw["proposed_by"]):
                raise RecordMismatch("proposer cannot cancel their own REVIEW decision")
            if event["reviewer"] not in policy.reviewers:
                raise RecordMismatch("cancelling reviewer is not authorized by the frozen policy")
            if not isinstance(event["note"], str) or not event["note"].strip():
                raise DecisionError("cancellation must contain a nonempty reason")
            state = Status.CANCELLED.value
        else:
            raise RecordMismatch("event history contains a prohibited transition")
    if status.value != state:
        raise RecordMismatch("lifecycle status does not match event history")
    review = raw["review"]
    if review_event is None:
        if review is not None:
            raise RecordMismatch("review has no corresponding review event")
    else:
        review = _fields(review, {"decision", "reviewer", "note", "at"})
        if review["decision"] != review_event["event"] or review["at"] != review_event["at"]:
            raise RecordMismatch("review does not match its event")
        if schema >= 3 and review["reviewer"] == raw["proposed_by"]:
            raise RecordMismatch("proposer cannot review their own REVIEW decision")
        if review["reviewer"] not in policy.reviewers:
            raise RecordMismatch("reviewer is not authorized by the frozen policy")
        if not isinstance(review["note"], str):
            raise DecisionError("review note must be text")
    if status == Status.EXECUTED:
        result = Ticket.from_dict(raw["result"], schema)
        action = actions_for(schema).get(proposal.action)
        if action is None or result != action.apply(ticket, proposal):
            raise RecordMismatch("execution result does not match the approved action")
    elif raw["result"] is not None:
        raise RecordMismatch("an unexecuted decision cannot contain an execution result")
    summary = {"valid": True, "decision_id": raw["id"], "verdict": expected.verdict.value,
               "status": status.value}
    return summary, external


def _validate_record(record):
    return _check_record(record)[0]


def export_record(record: dict) -> dict:
    """Validate and checksum the entire record, including review and execution history."""
    _validate_record(record)
    return {"record": record, "sha256": digest(record, jcs=record["schema_version"] >= JCS_SCHEMA)}


def _verify_external(adapter, frozen, reevaluate):
    """Re-evaluate a frozen external decision when its tool is installed; else digest-only."""
    version = adapter.reevaluate(frozen) if reevaluate else None
    if version is not None:
        return {"engine": adapter.NAME, "verification": "reevaluated", "tool": version}
    reason = f"{adapter.NAME} was not found on PATH" if reevaluate else "re-evaluation was disabled"
    return {"engine": adapter.NAME, "verification": "digest-only", "reason": reason}


def replay(envelope: dict, *, reevaluate: bool = True) -> dict:
    """Check integrity and reproduce authorization from frozen inputs; never execute.

    A record with a frozen OPA or Cedar decision is also re-evaluated when ``opa`` or
    ``cedar`` is on PATH. The result then carries ``external_policy`` with ``verification``
    ``"reevaluated"`` (and the tool version) or ``"digest-only"`` (and the reason): digests,
    the input binding and the decision mapping were checked, but the policy was not run.
    """
    raw = _fields(envelope, {"record", "sha256"})
    expected = raw["sha256"]
    if (not isinstance(expected, str) or len(expected) != 64
            or any(character not in "0123456789abcdef" for character in expected)):
        raise DecisionError("sha256 must be a 64-character digest")
    if digest(raw["record"], jcs=_schema_version(raw["record"]) >= JCS_SCHEMA) != expected:
        raise RecordMismatch("evidence checksum mismatch")
    summary, external = _check_record(raw["record"])
    if external is not None:
        adapter, frozen, _ = external
        summary["external_policy"] = _verify_external(adapter, frozen, reevaluate)
    return summary
