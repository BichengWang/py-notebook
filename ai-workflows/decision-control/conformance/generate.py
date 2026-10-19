#!/usr/bin/env python3
"""Deterministically generate the decision-control conformance vectors.

Usage: python3 conformance/generate.py [--out DIR]

Records are assembled by hand (fixed ids and timestamps, no clock, no randomness)
so the vectors do not depend on the store that produces real records. Evaluation
reports come from the package's own scorer, which is deterministic. Tampered and
invalid vectors are derived from valid ones by the edits named in each note.
Standard library plus the bundled ``decisioncontrol.jcs`` only.
"""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import sys

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from decisioncontrol.evaluation import EvaluationCase, evaluate_cases  # noqa: E402
from decisioncontrol.jcs import canonicalize  # noqa: E402
from decisioncontrol.models import RoutingPolicy  # noqa: E402

SCHEMA_DIR = "decisioncontrol/schema"
REPLAY = ["decision-control", "replay", "--record", "{path}"]
REPLAY_EVALUATION = ["decision-control", "replay-evaluation", "--record", "{path}"]
EXIT = {"valid": 0, "tampered": 1, "invalid": 2}
RFC8785, PYTHON_JSON = "rfc8785", "python-json-v1"

T0 = "2026-01-15T09:00:00.000000+00:00"
T1 = "2026-01-15T09:05:00.000000+00:00"
T2 = "2026-01-15T09:10:00.000000+00:00"
NOTE = "checked line one\nline two \u2713 \U0001f600"


def python_json_v1(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def canonical(value, form):
    return canonicalize(value) if form == RFC8785 else python_json_v1(value)


def sha256(blob):
    return hashlib.sha256(blob).hexdigest()


def pretty(value):
    return json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n"


# ---------------------------------------------------------------- records

def policy(version="routing-policy-1", minimum=0.8):
    return {"version": version, "allowed_destinations": ["support", "engineering"],
            "review_destinations": ["engineering"], "reviewers": ["alice", "bob"],
            "min_probability": minimum}


def make_record(schema, *, kind, record_id, destination="support", probability=0.95, minimum=0.8,
                policy_version="routing-policy-1", note=""):
    """Build a record for one lifecycle ``kind`` under ``schema`` (1-4)."""
    ticket = {"id": "T-100", "department": "intake", "revision": 0}
    review = None
    result = None
    events = [{"event": "SUBMITTED", "at": T0}]
    if kind == "deny":
        destination = "finance"
        evaluation = {"verdict": "DENY", "reasons": ["destination_not_permitted"]}
        status = "DENIED"
    elif destination == "support":
        evaluation = {"verdict": "ALLOW", "reasons": ["policy_permits_reassignment"]}
        status = "EXECUTED"
        result = {"id": "T-100", "department": "support", "revision": 1}
        events.append({"event": "EXECUTED", "at": T1})
    else:
        evaluation = {"verdict": "REVIEW", "reasons": ["destination_requires_review"]}
        if kind == "pending":
            status = "PENDING_REVIEW"
        elif kind == "cancelled":
            status = "CANCELLED"
            events.append({"event": "CANCELLED", "at": T1, "reviewer": "bob", "note": "request withdrawn"})
        else:
            reviewer = "alice" if kind == "approved-by-proposer" else "bob"
            review = {"decision": "APPROVED", "reviewer": reviewer, "note": note, "at": T1}
            status = "EXECUTED"
            result = {"id": "T-100", "department": "engineering", "revision": 1}
            events.extend([{"event": "APPROVED", "at": T1}, {"event": "EXECUTED", "at": T2}])
    frozen = policy(policy_version, minimum)
    record = {
        "schema_version": schema, "id": record_id, "created_at": T0,
        "recommendation": {"action": "reassign_ticket", "ticket_id": "T-100", "destination": destination,
                           "probability": probability, "model": "hand-authored-fixture",
                           "question_version": "routing-question-1", "refused": False},
        "ticket": ticket, "policy": frozen, "evaluation": evaluation, "status": status,
        "review": review, "result": result, "events": events,
    }
    if schema >= 3:
        form = RFC8785 if schema >= 4 else PYTHON_JSON
        record.update({"produced_by": {"name": "decisioncontrol", "version": "0.1.0"},
                       "proposed_by": "alice", "policy_sha256": sha256(canonical(frozen, form))})
    return record


def record_form(schema):
    return RFC8785 if schema >= 4 else PYTHON_JSON


def envelope(record, form=None):
    form = form or record_form(record["schema_version"])
    return {"record": record, "sha256": sha256(canonical(record, form))}


def uuid(number):
    return f"0f6d5c4b-3a29-4817-9605-{number:012d}"


# (stem, schema, kwargs) for every valid record vector
VALID_RECORDS = [
    ("record-v4-allow-executed", 4, dict(kind="allow", record_id=uuid(401))),
    ("record-v4-review-approved-executed", 4, dict(kind="approved", record_id=uuid(402), destination="engineering", note=NOTE)),
    ("record-v4-review-cancelled", 4, dict(kind="cancelled", record_id=uuid(403), destination="engineering")),
    ("record-v4-review-pending", 4, dict(kind="pending", record_id=uuid(404), destination="engineering")),
    ("record-v4-deny-denied", 4, dict(kind="deny", record_id=uuid(405))),
    ("record-v4-whole-number-float-executed", 4, dict(kind="allow", record_id=uuid(406), probability=1.0, minimum=1.0,
                                                      policy_version="\u8def\u7531\u7b56\u7565-1")),
    ("record-v3-allow-executed", 3, dict(kind="allow", record_id=uuid(301))),
    ("record-v3-review-approved-executed", 3, dict(kind="approved", record_id=uuid(302), destination="engineering", note=NOTE)),
    ("record-v3-whole-number-float-executed", 3, dict(kind="allow", record_id=uuid(303), probability=1.0, minimum=1.0)),
    ("record-v2-review-approved-by-proposer", 2, dict(kind="approved-by-proposer", record_id=uuid(201), destination="engineering", note="self review allowed before schema 3")),
    ("record-v2-review-cancelled", 2, dict(kind="cancelled", record_id=uuid(202), destination="engineering")),
    ("record-v1-allow-executed", 1, dict(kind="allow", record_id=uuid(101))),
    ("record-v1-review-approved-executed", 1, dict(kind="approved", record_id=uuid(102), destination="engineering", note="checked")),
]

VALID_NOTES = {
    "record-v4-allow-executed": "Schema 4 ALLOW decision executed without review; checksum and policy_sha256 are RFC 8785 digests",
    "record-v4-review-approved-executed": "Schema 4 REVIEW decision approved by a reviewer other than the proposer; review note has a newline, a BMP symbol and a non-BMP character",
    "record-v4-review-cancelled": "Schema 4 REVIEW decision cancelled by an authorized reviewer who is not the proposer",
    "record-v4-review-pending": "Schema 4 REVIEW decision still pending, no review and no result",
    "record-v4-deny-denied": "Schema 4 DENY decision for a destination outside the frozen policy",
    "record-v4-whole-number-float-executed": "Schema 4 with whole-number floats (1.0) canonicalized as 1 by RFC 8785, non-ASCII policy version",
    "record-v3-allow-executed": "Schema 3 ALLOW decision; python-json-v1 checksum and policy_sha256",
    "record-v3-review-approved-executed": "Schema 3 REVIEW decision approved by a non-proposer; python-json-v1 keeps non-ASCII text unescaped",
    "record-v3-whole-number-float-executed": "Schema 3 with whole-number floats; python-json-v1 keeps 1.0, which RFC 8785 would write as 1",
    "record-v2-review-approved-by-proposer": "Schema 2 approval by the proposer is valid under the original schema 2 rules; the same edit on schema 3 or 4 is tampered",
    "record-v2-review-cancelled": "Schema 2 cancellation of a REVIEW decision; schema 1 has no cancellation event",
    "record-v1-allow-executed": "Schema 1 ALLOW decision executed; no producer, proposer or policy digest fields",
    "record-v1-review-approved-executed": "Schema 1 approved REVIEW decision under the original schema 1 rules",
}


def record_valid_vector(stem, schema, tree, manifest):
    record = make_record(schema, **dict(VALID_RECORDS_BY_STEM[stem]))
    form = record_form(schema)
    path = f"valid/{stem}.json"
    tree[path] = pretty(envelope(record))
    digests = []
    pairs = [("/sha256", "/record", "record")]
    if schema >= 3:
        pairs.append(("/record/policy_sha256", "/record/policy", "policy"))
    for value, covers, label in pairs:
        target = record if label == "record" else record["policy"]
        file = f"valid/{stem}.{label}.canonical"
        tree[file] = canonical(target, form)
        digests.append({"document": ".", "value": value, "covers": covers, "exclude": [],
                        "canonicalization": form, "canonical_file": file})
    manifest.append({"path": path, "expect": "valid",
                     "verify": {"command": REPLAY, "exit_code": 0},
                     "documents": [{"path": ".", "schema": f"{SCHEMA_DIR}/record.v{schema}.json", "schema_valid": True}],
                     "digests": digests, "note": VALID_NOTES[stem]})


VALID_RECORDS_BY_STEM = {stem: kwargs for stem, _, kwargs in VALID_RECORDS}
SCHEMA_OF = {stem: schema for stem, schema, _ in VALID_RECORDS}


def base_record(stem):
    return make_record(SCHEMA_OF[stem], **VALID_RECORDS_BY_STEM[stem])


def tampered_records():
    """(name, schema, document text, schema_valid, note) for tampered record vectors."""
    out = []

    def add(name, stem, edit, *, recompute, note, form=None):
        record = base_record(stem)
        edit(record)
        schema = record["schema_version"]
        if recompute:
            body = envelope(record, form)
        else:
            body = {"record": record, "sha256": envelope(base_record(stem))["sha256"]}
        out.append((name, schema, pretty(body), True, note))

    def set_path(*path_and_value):
        *path, value = path_and_value
        def edit(record):
            target = record
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value
        return edit

    def last_event(field, value):
        def edit(record):
            record["events"][-1][field] = value
        return edit

    def cascade(*edits):
        def edit(record):
            for each in edits:
                each(record)
        return edit

    def policy_digest(record):
        record["policy_sha256"] = sha256(canonical(record["policy"], record_form(record["schema_version"])))

    add("record-v4-review-note-edit-stale-checksum", "record-v4-review-approved-executed",
        set_path("review", "note", "approved without reading"), recompute=False,
        note="Edit review.note after exporting; the original checksum is left in place")
    add("record-v4-self-approval-recomputed", "record-v4-review-approved-executed",
        set_path("review", "reviewer", "alice"), recompute=True,
        note="Set review.reviewer to the proposer and recompute the RFC 8785 checksum; replay rejects proposer self-approval")
    add("record-v4-self-cancellation-recomputed", "record-v4-review-cancelled",
        last_event("reviewer", "alice"), recompute=True,
        note="Set the cancelling reviewer to the proposer and recompute the checksum; replay rejects proposer self-cancellation of a REVIEW decision")
    add("record-v4-unauthorized-reviewer-recomputed", "record-v4-review-approved-executed",
        set_path("review", "reviewer", "mallory"), recompute=True,
        note="Set review.reviewer to a name outside the frozen policy reviewers and recompute the checksum")
    add("record-v4-frozen-policy-edit-recomputed", "record-v4-allow-executed",
        set_path("policy", "min_probability", 0.99), recompute=True,
        note="Raise policy.min_probability and recompute the checksum but not policy_sha256; replay detects the frozen policy digest mismatch")
    add("record-v4-frozen-policy-and-digest-recomputed", "record-v4-allow-executed",
        cascade(set_path("policy", "min_probability", 0.99), policy_digest), recompute=True,
        note="Raise policy.min_probability, recompute policy_sha256 and the checksum; replay recomputes the verdict from the edited policy and finds ABSTAIN, not ALLOW")
    add("record-v4-forged-execution-result-recomputed", "record-v4-allow-executed",
        set_path("result", "revision", 5), recompute=True,
        note="Change result.revision and recompute the checksum; the execution result no longer matches the approved action")
    add("record-v4-execution-without-approval-recomputed", "record-v4-review-pending",
        cascade(set_path("status", "EXECUTED"),
                lambda r: r["events"].append({"event": "EXECUTED", "at": T2}),
                set_path("result", {"id": "T-100", "department": "engineering", "revision": 1})),
        recompute=True,
        note="Append an EXECUTED event and result to a pending REVIEW decision and recompute the checksum; the transition is prohibited")
    add("record-v4-approval-erased-recomputed", "record-v4-review-approved-executed",
        cascade(set_path("review", None), lambda r: r["events"].pop(1)), recompute=True,
        note="Erase the review object and the APPROVED event and recompute the checksum; the decision can no longer reach EXECUTED without approval")
    add("record-v4-python-json-checksum", "record-v4-whole-number-float-executed",
        lambda record: None, recompute=True, form=PYTHON_JSON,
        note="Checksum computed with python-json-v1 on a schema 4 record; it differs from the RFC 8785 digest because 1.0 is written as 1")
    add("record-v3-review-note-edit-stale-checksum", "record-v3-review-approved-executed",
        set_path("review", "note", "approved without reading"), recompute=False,
        note="Edit review.note after exporting; the original checksum is left in place")
    add("record-v3-self-approval-recomputed", "record-v3-review-approved-executed",
        set_path("review", "reviewer", "alice"), recompute=True,
        note="Set review.reviewer to the proposer and recompute the python-json-v1 checksum; schema 3 replay rejects proposer self-approval")
    add("record-v3-frozen-policy-edit-recomputed", "record-v3-allow-executed",
        set_path("policy", "min_probability", 0.99), recompute=True,
        note="Raise policy.min_probability and recompute the checksum but not policy_sha256; replay detects the frozen policy digest mismatch")
    add("record-v3-rfc8785-checksum", "record-v3-whole-number-float-executed",
        lambda record: None, recompute=True, form=RFC8785,
        note="Checksum computed with RFC 8785 on a schema 3 record; schema 3 is digested as python-json-v1, so replay reports a mismatch")
    add("record-v2-status-edit-stale-checksum", "record-v2-review-cancelled",
        set_path("status", "READY"), recompute=False,
        note="Change status from CANCELLED to READY after exporting; the original checksum is left in place")
    add("record-v2-unauthorized-reviewer-recomputed", "record-v2-review-approved-by-proposer",
        set_path("review", "reviewer", "mallory"), recompute=True,
        note="Set review.reviewer to a name outside the frozen policy reviewers and recompute the checksum")
    add("record-v1-status-edit-stale-checksum", "record-v1-allow-executed",
        set_path("status", "READY"), recompute=False,
        note="Change status from EXECUTED to READY after exporting; the original checksum is left in place")
    add("record-v1-self-label-edit-recomputed", "record-v1-review-approved-executed",
        set_path("review", "reviewer", "mallory"), recompute=True,
        note="Set review.reviewer to a name outside the frozen policy reviewers and recompute the checksum")
    return out


def invalid_records():
    """(name, text, documents) for invalid record vectors (replay exits 2)."""
    out = []
    v4 = base_record("record-v4-allow-executed")
    good = envelope(v4)
    text = pretty(good)
    schema4 = f"{SCHEMA_DIR}/record.v4.json"

    def rehash(record):
        return envelope(record)

    duplicate = text.replace('  "record": {\n', '  "record": {\n    "status": "READY",\n', 1)
    assert duplicate != text
    out.append(("record-v4-duplicate-keys", duplicate, None,
                "Valid schema 4 document with a second status member inside record; schema 4 readers reject duplicate keys"))
    out.append(("record-v4-non-finite-number", text.replace('"probability": 0.95', '"probability": NaN', 1), None,
                "probability replaced by the non-JSON literal NaN; schema 4 canonicalization rejects non-finite numbers"))
    big = text.replace('"revision": 1', '"revision": 9007199254740993', 1)
    assert big != text
    out.append(("record-v4-integer-outside-safe-range", big, None,
                "result.revision replaced by 9007199254740993, an integer beyond 2^53-1 that RFC 8785 cannot represent exactly"))
    surrogate = text.replace('"department": "intake"', '"department": "\\ud800"', 1)
    assert surrogate != text
    out.append(("record-v4-lone-surrogate", surrogate, None,
                "ticket.department replaced by the unpaired surrogate \\ud800, which has no UTF-8 encoding"))
    out.append(("record-v4-not-json", text[: len(text) // 2], None,
                "Valid schema 4 document truncated in the middle"))
    future = deepcopy(v4)
    future["schema_version"] = 5
    out.append(("record-v4-unsupported-schema-version", pretty(rehash_any(future)),
                [{"path": ".", "schema": schema4, "schema_valid": False}],
                "schema_version set to 5 and the checksum recomputed; unknown schemas are rejected, not reinterpreted"))
    string_version = deepcopy(v4)
    string_version["schema_version"] = "4"
    out.append(("record-v4-schema-version-string", pretty(rehash_any(string_version)),
                [{"path": ".", "schema": schema4, "schema_valid": False}],
                "schema_version written as the string \"4\" and the checksum recomputed"))
    extra = deepcopy(v4)
    extra["comment"] = "added after export"
    out.append(("record-v4-unknown-field", pretty(envelope(extra)),
                [{"path": ".", "schema": schema4, "schema_valid": False}],
                "Unknown record member added and the checksum recomputed; readers reject unknown fields"))
    missing = {"record": v4}
    out.append(("record-v4-missing-checksum", pretty(missing),
                [{"path": ".", "schema": schema4, "schema_valid": False}],
                "Envelope without the sha256 member"))
    upper = {"record": v4, "sha256": good["sha256"].upper()}
    out.append(("record-v4-uppercase-checksum", pretty(upper),
                [{"path": ".", "schema": schema4, "schema_valid": False}],
                "Checksum written in uppercase hexadecimal; digests are lowercase"))
    v3 = base_record("record-v3-allow-executed")
    no_producer = deepcopy(v3)
    del no_producer["produced_by"]
    out.append(("record-v3-missing-producer", pretty(envelope(no_producer)),
                [{"path": ".", "schema": f"{SCHEMA_DIR}/record.v3.json", "schema_valid": False}],
                "Schema 3 record without produced_by and the checksum recomputed"))
    return out


def rehash_any(record):
    """Envelope with a JCS checksum, used where the schema version is deliberately bad."""
    return {"record": record, "sha256": sha256(canonicalize(record))}


# ------------------------------------------------------------ evaluations

EVAL_POLICY = policy()


def eval_cases():
    rows = [
        ("case-allow-ok", "support", 0.95, True, False, "support", None),
        ("case-allow-unsafe", "support", 0.9, False, False, "support", None),
        ("case-review-approved", "engineering", 0.95, True, True, "engineering", "APPROVED"),
        ("case-review-rejected", "engineering", 0.9, False, True, "engineering", "REJECTED"),
        ("case-review-pending", "engineering", 0.85, True, True, "engineering", None),
        ("case-abstain-low", "support", 0.4, True, False, "support", None),
        ("case-deny-finance", "finance", 0.99, False, False, "support", None),
        ("case-\u8def\u7531", "support", 0.97, True, False, "support", None),
    ]
    cases = []
    for name, destination, probability, safe, required, correct, outcome in rows:
        ticket_id = f"t-{name}"
        cases.append(EvaluationCase.from_dict({
            "id": name, "ticket": {"id": ticket_id, "department": "intake", "revision": 0},
            "recommendation": {"action": "reassign_ticket", "ticket_id": ticket_id, "destination": destination,
                               "probability": probability, "model": "supplied-test-response",
                               "question_version": "routing-question-1"},
            "labels": {"safe_to_execute": safe, "requires_review": required, "correct_destination": correct},
            "review_outcome": outcome}))
    return cases


FAIL_REQUIREMENTS = {"min_cases": 8, "bounds": {
    "unsafe_auto_allow_rate": {"max": 0, "statistic": "value", "min_denominator": 1},
    "review_observation_rate": {"min": 0.5, "statistic": "lower", "min_denominator": 3}}}
PASS_REQUIREMENTS = {"min_cases": 8, "bounds": {
    "review_rate": {"max": 0.5, "statistic": "value", "min_denominator": 8},
    "deny_rate": {"max": 0.5, "statistic": "upper", "min_denominator": 8}}}

EVAL_VALID = [
    ("evaluation-v2-ungated", 2, None, "UNGATED", "Schema 2 report without requirements; Wilson bounds that are exactly 0 or 1 are written as 0 and 1 in RFC 8785 form"),
    ("evaluation-v2-gate-fail", 2, FAIL_REQUIREMENTS, "FAIL", "Schema 2 report whose unsafe-auto-allow gate fails; replay still verifies the report (exit 0), the FAIL disposition is evidence, not a replay error"),
    ("evaluation-v2-gate-pass", 2, PASS_REQUIREMENTS, "PASS", "Schema 2 report whose gates pass on 8 synthetic cases; not evidence of deployed safety"),
    ("evaluation-v1-ungated", 1, None, "UNGATED", "Schema 1 report; python-json-v1 keeps 0.0 and 1.0 where RFC 8785 writes 0 and 1"),
    ("evaluation-v1-gate-fail", 1, FAIL_REQUIREMENTS, "FAIL", "Schema 1 report with a failed gate under the original python-json-v1 rules"),
]


def make_report(schema, requirements):
    report = evaluate_cases(eval_cases(), RoutingPolicy.from_dict(EVAL_POLICY), deepcopy(requirements), schema)
    return report


def eval_form(schema):
    return RFC8785 if schema >= 2 else PYTHON_JSON


def eval_envelope(report, form=None):
    form = form or eval_form(report["schema_version"])
    return {"report": report, "sha256": sha256(canonical(report, form))}


def eval_valid_vector(entry, tree, manifest):
    stem, schema, requirements, disposition, note = entry
    report = make_report(schema, requirements)
    assert report["disposition"] == disposition, (stem, report["disposition"])
    path = f"valid/{stem}.json"
    file = f"valid/{stem}.report.canonical"
    tree[path] = pretty(eval_envelope(report))
    tree[file] = canonical(report, eval_form(schema))
    manifest.append({"path": path, "expect": "valid",
                     "verify": {"command": REPLAY_EVALUATION, "exit_code": 0},
                     "documents": [{"path": ".", "schema": f"{SCHEMA_DIR}/evaluation.v{schema}.json", "schema_valid": True}],
                     "digests": [{"document": ".", "value": "/sha256", "covers": "/report", "exclude": [],
                                  "canonicalization": eval_form(schema), "canonical_file": file}],
                     "note": note})


def eval_tampered():
    out = []

    def add(name, schema, requirements, edit, *, recompute, note, form=None):
        report = make_report(schema, requirements)
        stale = eval_envelope(deepcopy(report))["sha256"]
        edit(report)
        body = eval_envelope(report, form) if recompute else {"report": report, "sha256": stale}
        out.append((name, schema, pretty(body), note))

    def unsafe_rate_zero(report):
        report["metrics"]["unsafe_auto_allow_rate"]["numerator"] = 0
        report["metrics"]["unsafe_auto_allow_rate"]["value"] = 0.0
        report["metrics"]["unsafe_auto_allow_rate"]["upper"] = 0.0

    def flip_label(report):
        row = next(item for item in report["case_results"] if item["case"]["id"] == "case-allow-unsafe")
        row["case"]["labels"]["safe_to_execute"] = True

    def pass_disposition(report):
        report["disposition"] = "PASS"

    add("evaluation-v2-metric-edit-stale-checksum", 2, FAIL_REQUIREMENTS, unsafe_rate_zero, recompute=False,
        note="Zero the unsafe auto-allow rate after writing; the original checksum is left in place")
    add("evaluation-v2-metric-edit-recomputed", 2, FAIL_REQUIREMENTS, unsafe_rate_zero, recompute=True,
        note="Zero the unsafe auto-allow rate and recompute the RFC 8785 checksum; replay recomputes the metrics from the frozen cases")
    add("evaluation-v2-label-flip-recomputed", 2, FAIL_REQUIREMENTS, flip_label, recompute=True,
        note="Flip a frozen case safety label to hide an unsafe automatic allow and recompute the checksum; recomputed metrics disagree")
    add("evaluation-v2-disposition-edit-recomputed", 2, FAIL_REQUIREMENTS, pass_disposition, recompute=True,
        note="Change disposition FAIL to PASS and recompute the checksum; replay recomputes the gates")
    add("evaluation-v2-python-json-checksum", 2, None, lambda report: None, recompute=True, form=PYTHON_JSON,
        note="Checksum computed with python-json-v1 on a schema 2 report; it differs from the RFC 8785 digest because 0.0 is written as 0")
    add("evaluation-v1-metric-edit-stale-checksum", 1, FAIL_REQUIREMENTS, unsafe_rate_zero, recompute=False,
        note="Zero the unsafe auto-allow rate after writing; the original checksum is left in place")
    add("evaluation-v1-label-flip-recomputed", 1, FAIL_REQUIREMENTS, flip_label, recompute=True,
        note="Flip a frozen case safety label and recompute the python-json-v1 checksum; recomputed metrics disagree")
    add("evaluation-v1-rfc8785-checksum", 1, None, lambda report: None, recompute=True, form=RFC8785,
        note="Checksum computed with RFC 8785 on a schema 1 report; schema 1 is digested as python-json-v1, so replay reports a mismatch")
    return out


def eval_invalid():
    out = []
    schema2 = f"{SCHEMA_DIR}/evaluation.v2.json"
    report = make_report(2, FAIL_REQUIREMENTS)
    good = eval_envelope(report)
    text = pretty(good)
    duplicate = text.replace('    "kind": "policy_evaluation",\n', '    "kind": "policy_evaluation",\n    "kind": "policy_evaluation",\n', 1)
    assert duplicate != text
    out.append(("evaluation-v2-duplicate-keys", duplicate, None,
                "Valid schema 2 document with the kind member repeated; schema 2 readers reject duplicate keys"))
    nan = text.replace('"confidence_level": 0.95', '"confidence_level": NaN', 1)
    assert nan != text
    out.append(("evaluation-v2-non-finite-number", nan, None,
                "confidence_level replaced by the non-JSON literal NaN"))
    out.append(("evaluation-v2-not-json", text[: len(text) // 2], None, "Valid schema 2 document truncated in the middle"))
    future = deepcopy(report)
    future["schema_version"] = 3
    out.append(("evaluation-v2-unsupported-schema-version", pretty(rehash_any_report(future)),
                [{"path": ".", "schema": schema2, "schema_valid": False}],
                "schema_version set to 3 and the checksum recomputed; unknown schemas are rejected"))
    extra = deepcopy(report)
    extra["producer"] = "added after writing"
    out.append(("evaluation-v2-unknown-field", pretty(eval_envelope(extra)),
                [{"path": ".", "schema": schema2, "schema_valid": False}],
                "Unknown report member added and the checksum recomputed; readers reject unknown fields"))
    out.append(("evaluation-v2-missing-checksum", pretty({"report": report}),
                [{"path": ".", "schema": schema2, "schema_valid": False}],
                "Envelope without the sha256 member"))
    empty = deepcopy(report)
    empty["case_results"] = []
    empty["cases"] = 0
    out.append(("evaluation-v2-no-cases", pretty(eval_envelope(empty)),
                [{"path": ".", "schema": schema2, "schema_valid": False}],
                "Report with no case results and the checksum recomputed; an evaluation requires at least one labeled case"))
    return out


def rehash_any_report(report):
    return {"report": report, "sha256": sha256(canonicalize(report))}


# ------------------------------------------------------------------ driver

def generate():
    """Return ({relative path: bytes}, manifest dict) for the whole conformance tree."""
    tree = {}
    vectors = []
    for stem, _, _ in VALID_RECORDS:
        record_valid_vector(stem, SCHEMA_OF[stem], tree, vectors)
    for entry in EVAL_VALID:
        eval_valid_vector(entry, tree, vectors)
    for name, schema, text, _valid, note in tampered_records():
        tree[f"tampered/{name}.json"] = text
        vectors.append({"path": f"tampered/{name}.json", "expect": "tampered",
                        "verify": {"command": REPLAY, "exit_code": 1},
                        "documents": [{"path": ".", "schema": f"{SCHEMA_DIR}/record.v{schema}.json", "schema_valid": True}],
                        "note": note})
    for name, schema, text, note in eval_tampered():
        tree[f"tampered/{name}.json"] = text
        vectors.append({"path": f"tampered/{name}.json", "expect": "tampered",
                        "verify": {"command": REPLAY_EVALUATION, "exit_code": 1},
                        "documents": [{"path": ".", "schema": f"{SCHEMA_DIR}/evaluation.v{schema}.json", "schema_valid": True}],
                        "note": note})
    for name, text, documents, note in invalid_records():
        tree[f"invalid/{name}.json"] = text
        vector = {"path": f"invalid/{name}.json", "expect": "invalid",
                  "verify": {"command": REPLAY, "exit_code": 2}, "note": note}
        if documents:
            vector["documents"] = documents
        vectors.append(vector)
    for name, text, documents, note in eval_invalid():
        tree[f"invalid/{name}.json"] = text
        vector = {"path": f"invalid/{name}.json", "expect": "invalid",
                  "verify": {"command": REPLAY_EVALUATION, "exit_code": 2}, "note": note}
        if documents:
            vector["documents"] = documents
        vectors.append(vector)
    vectors.sort(key=lambda vector: ({"valid": 0, "tampered": 1, "invalid": 2}[vector["expect"]], vector["path"]))
    manifest = {"format": 1, "package": "decisioncontrol", "vectors": vectors}
    tree["manifest.json"] = pretty(manifest)
    return {path: content.encode("utf-8") if isinstance(content, str) else content
            for path, content in tree.items()}


def write(out):
    out = Path(out)
    for name in ("valid", "tampered", "invalid"):
        shutil.rmtree(out / name, ignore_errors=True)
    for path, content in generate().items():
        target = out / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default=str(Path(__file__).resolve().parent),
                        help="output directory (default: this directory)")
    write(parser.parse_args(argv).out)


if __name__ == "__main__":
    main()
