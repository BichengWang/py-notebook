"""Offline policy evaluation on independently labeled, supplied recommendations.

No model is called and no action is executed. Wilson intervals assume independent
Bernoulli observations; synthetic or correlated cases do not validate deployment.
Report schema 1 digests Python's sorted compact JSON; schema 2 digests RFC 8785
(JCS) canonical bytes and rejects duplicate object keys when parsing.
"""

from dataclasses import dataclass
import json
import math
from pathlib import Path

from ._outputs import staged_output
from .actions import LEGACY_ACTIONS_SCHEMA as ACTIONS_SCHEMA
from .evidence import canonical_bytes, digest, parse_json
from .models import (DecisionError, Recommendation, RecordMismatch, RoutingPolicy, Ticket, Verdict,
                     _fields, _probability, _text)
from .policy import evaluate


LEGACY_REPORT_SCHEMA = 1
REPORT_SCHEMA = 2
REPORT_SCHEMAS = (LEGACY_REPORT_SCHEMA, REPORT_SCHEMA)

METRICS = (
    "auto_allow_rate", "unsafe_auto_allow_rate", "auto_route_error_rate",
    "review_rate", "abstain_rate", "deny_rate", "required_review_recall",
    "review_precision", "incorrect_approval_rate", "review_observation_rate",
)


@dataclass(frozen=True)
class EvaluationCase:
    id: str
    ticket: Ticket
    recommendation: Recommendation
    safe_to_execute: bool
    requires_review: bool
    correct_destination: str
    review_outcome: str | None = None

    def __post_init__(self):
        _text(self.id, "case id")
        if not isinstance(self.ticket, Ticket) or not isinstance(self.recommendation, Recommendation):
            raise DecisionError("case requires a Ticket and a Recommendation")
        if type(self.safe_to_execute) is not bool or type(self.requires_review) is not bool:
            raise DecisionError("safe_to_execute and requires_review labels must be booleans")
        _text(self.correct_destination, "correct_destination")
        if self.review_outcome is not None and self.review_outcome not in ("APPROVED", "REJECTED"):
            raise DecisionError("review_outcome must be APPROVED, REJECTED, or null")

    def to_dict(self):
        return {"id": self.id, "ticket": self.ticket.to_dict(),
                "recommendation": self.recommendation.to_dict(),
                "labels": {"safe_to_execute": self.safe_to_execute,
                           "requires_review": self.requires_review,
                           "correct_destination": self.correct_destination},
                "review_outcome": self.review_outcome}

    @classmethod
    def from_dict(cls, value):
        raw = _fields(value, {"id", "ticket", "recommendation", "labels"}, {"review_outcome"})
        labels = _fields(raw["labels"], {"safe_to_execute", "requires_review", "correct_destination"})
        return cls(raw["id"], Ticket.from_dict(raw["ticket"], ACTIONS_SCHEMA),
                   Recommendation.from_dict(raw["recommendation"], ACTIONS_SCHEMA), **labels,
                   review_outcome=raw.get("review_outcome"))


def load_cases(path):
    """Load JSON Lines, rejecting malformed cases instead of excluding them from scores."""
    cases = []
    with Path(path).open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                cases.append(EvaluationCase.from_dict(json.loads(line)))
            except (DecisionError, json.JSONDecodeError) as error:
                raise DecisionError(f"{path}:{line_number}: {error}") from error
    return cases


def _rate(numerator, denominator):
    if denominator == 0:
        return {"numerator": numerator, "denominator": 0, "value": None, "lower": None, "upper": None}
    value = numerator / denominator
    z = 1.959963984540054
    z_squared = z * z
    divisor = 1 + z_squared / denominator
    center = (value + z_squared / (2 * denominator)) / divisor
    half = z * math.sqrt(value * (1 - value) / denominator + z_squared / (4 * denominator ** 2)) / divisor
    return {"numerator": numerator, "denominator": denominator, "value": value,
            "lower": 0.0 if numerator == 0 else max(0.0, center - half),
            "upper": 1.0 if numerator == denominator else min(1.0, center + half)}


def _positive_int(value, name):
    if type(value) is not int or value < 1:
        raise DecisionError(f"{name} must be a positive integer")
    return value


def _requirements(value):
    if value is None:
        return None
    raw = _fields(value, {"min_cases", "bounds"})
    minimum = _positive_int(raw["min_cases"], "min_cases")
    if not isinstance(raw["bounds"], dict) or not raw["bounds"]:
        raise DecisionError("bounds must contain at least one metric requirement")
    bounds = {}
    for name, bound in raw["bounds"].items():
        if name not in METRICS:
            raise DecisionError(f"unknown metric: {name}")
        bound = _fields(bound, (), {"min", "max", "statistic", "min_denominator"})
        if not ("min" in bound or "max" in bound):
            raise DecisionError(f"{name} needs a min or max bound")
        statistic = bound.get("statistic", "value")
        if statistic not in ("value", "lower", "upper"):
            raise DecisionError(f"{name}: statistic must be value, lower, or upper")
        normalized = {"statistic": statistic,
                      "min_denominator": _positive_int(bound.get("min_denominator", 1), "min_denominator")}
        for side in ("min", "max"):
            if side in bound:
                normalized[side] = _probability(bound[side], f"{name}.{side}")
        if normalized.get("min", 0) > normalized.get("max", 1):
            raise DecisionError(f"{name}: min exceeds max")
        bounds[name] = normalized
    return {"min_cases": minimum, "bounds": bounds}


def _gates(metrics, count, requirements):
    if requirements is None:
        return []
    enough_cases = count >= requirements["min_cases"]
    gates = [{"metric": "cases", "statistic": "value", "observed": count,
              "min": requirements["min_cases"], "max": None,
              "denominator": count, "min_denominator": requirements["min_cases"],
              "passed": enough_cases, "reason": None if enough_cases else "insufficient_cases"}]
    for name, bound in sorted(requirements["bounds"].items()):
        metric = metrics[name]
        observed = metric[bound["statistic"]]
        reason = None
        if observed is None:
            reason = "unmeasured"
        elif metric["denominator"] < bound["min_denominator"]:
            reason = "insufficient_denominator"
        elif observed < bound.get("min", 0) or observed > bound.get("max", 1):
            reason = "outside_bound"
        gates.append({"metric": name, "statistic": bound["statistic"], "observed": observed,
                      "min": bound.get("min"), "max": bound.get("max"),
                      "denominator": metric["denominator"], "min_denominator": bound["min_denominator"],
                      "passed": reason is None, "reason": reason})
    return gates


def evaluate_cases(cases, policy: RoutingPolicy, requirements=None,
                   schema_version: int = REPORT_SCHEMA) -> dict:
    """Evaluate policy recommendations, not real execution or unauthenticated reviewers.

    Unsafe automatic allowance means ALLOW despite a negative safety label or a
    required-review label. Incorrect approval means an observed APPROVED outcome
    on a REVIEW case with a negative safety label or an incorrect destination.
    ``schema_version`` selects the report schema; replay of schema 1 reports needs 1.
    """
    if type(schema_version) is not int or schema_version not in REPORT_SCHEMAS:
        raise DecisionError("unsupported evaluation schema_version")
    if not isinstance(policy, RoutingPolicy):
        raise DecisionError("policy must be a RoutingPolicy")
    if policy.allowed_priorities:
        raise DecisionError("evaluation reports score reassign_ticket only; use a policy without priorities")
    requirements = _requirements(requirements)
    seen = set()
    results = []
    verdict_counts = {verdict: 0 for verdict in Verdict}
    unsafe = wrong_route = required = reviewed_required = observed_reviews = approvals = incorrect_approvals = 0
    for case in cases:
        if not isinstance(case, EvaluationCase):
            raise DecisionError("cases must contain EvaluationCase instances")
        if case.id in seen:
            raise DecisionError(f"duplicate case id: {case.id}")
        seen.add(case.id)
        evaluation = evaluate(case.recommendation, case.ticket, policy, schema=ACTIONS_SCHEMA)
        verdict = evaluation.verdict
        verdict_counts[verdict] += 1
        automatic = verdict == Verdict.ALLOW
        reviewing = verdict == Verdict.REVIEW
        incorrect_destination = case.recommendation.destination != case.correct_destination
        auto_unsafe = automatic and (not case.safe_to_execute or case.requires_review)
        auto_incorrect = automatic and incorrect_destination
        observed = reviewing and case.review_outcome is not None
        approved = reviewing and case.review_outcome == "APPROVED"
        approval_incorrect = approved and (not case.safe_to_execute or incorrect_destination)
        unsafe += auto_unsafe
        wrong_route += auto_incorrect
        required += case.requires_review
        reviewed_required += reviewing and case.requires_review
        observed_reviews += observed
        approvals += approved
        incorrect_approvals += approval_incorrect
        results.append({"case": case.to_dict(), "evaluation": evaluation.to_dict(),
                        "auto_allow_unsafe": auto_unsafe, "auto_route_incorrect": auto_incorrect,
                        "approval_incorrect": approval_incorrect if approved else None})
    count = len(results)
    if count == 0:
        raise DecisionError("evaluation requires at least one labeled case")
    allowed = verdict_counts[Verdict.ALLOW]
    reviewed = verdict_counts[Verdict.REVIEW]
    metrics = {
        "auto_allow_rate": _rate(allowed, count),
        "unsafe_auto_allow_rate": _rate(unsafe, allowed),
        "auto_route_error_rate": _rate(wrong_route, allowed),
        "review_rate": _rate(reviewed, count),
        "abstain_rate": _rate(verdict_counts[Verdict.ABSTAIN], count),
        "deny_rate": _rate(verdict_counts[Verdict.DENY], count),
        "required_review_recall": _rate(reviewed_required, required),
        "review_precision": _rate(reviewed_required, reviewed),
        "incorrect_approval_rate": _rate(incorrect_approvals, approvals),
        "review_observation_rate": _rate(observed_reviews, reviewed),
    }
    gates = _gates(metrics, count, requirements)
    disposition = "UNGATED" if requirements is None else ("PASS" if all(g["passed"] for g in gates) else "FAIL")
    return {"schema_version": schema_version, "kind": "policy_evaluation", "source": "supplied_recommendations",
            "cases": count, "confidence_level": 0.95, "policy": policy.to_dict(),
            "requirements": requirements, "metrics": metrics, "gates": gates,
            "disposition": disposition, "case_results": results}


def _report_schema(report):
    """Return a supported report schema or reject before any digest is computed."""
    version = report.get("schema_version") if isinstance(report, dict) else None
    if type(version) is not int or version not in REPORT_SCHEMAS:
        raise DecisionError("unsupported evaluation schema_version")
    return version


def parse_envelope(text):
    """Parse an evaluation file; schema 2 rejects duplicate object keys."""
    value, duplicates = parse_json(text)
    if duplicates:
        report = value.get("report") if isinstance(value, dict) else None
        version = report.get("schema_version") if isinstance(report, dict) else None
        if type(version) is int and version >= REPORT_SCHEMA:
            raise DecisionError("duplicate object keys are not allowed in evaluation schema 2")
    return value


def replay_evaluation(envelope: dict) -> dict:
    """Check the complete report and independently recompute metrics/gates from frozen cases."""
    raw = _fields(envelope, {"report", "sha256"})
    report = raw["report"]
    expected = raw["sha256"]
    if (not isinstance(expected, str) or len(expected) != 64
            or any(character not in "0123456789abcdef" for character in expected)):
        raise DecisionError("sha256 must be a lowercase hexadecimal SHA-256 digest")
    jcs = _report_schema(report) >= REPORT_SCHEMA
    if digest(report, jcs=jcs) != expected:
        raise RecordMismatch("evaluation checksum mismatch")
    report = _fields(report, {"schema_version", "kind", "source", "cases", "confidence_level", "policy",
                              "requirements", "metrics", "gates", "disposition", "case_results"})
    if not isinstance(report["case_results"], list):
        raise DecisionError("case_results must be a list")
    cases = []
    for row in report["case_results"]:
        row = _fields(row, {"case", "evaluation", "auto_allow_unsafe", "auto_route_incorrect", "approval_incorrect"})
        cases.append(EvaluationCase.from_dict(row["case"]))
    recomputed = evaluate_cases(cases, RoutingPolicy.from_dict(report["policy"], ACTIONS_SCHEMA), report["requirements"],
                                report["schema_version"])
    if canonical_bytes(recomputed, jcs=jcs) != canonical_bytes(report, jcs=jcs):
        raise RecordMismatch("evaluation report disagrees with its frozen cases, policy, or requirements")
    return {"valid": True, "cases": recomputed["cases"], "disposition": recomputed["disposition"]}


def _number(value):
    return "unmeasured" if value is None else f"{value:.6g}"


def render_evaluation(report, digest):
    lines = [f"# Policy evaluation: {report['disposition']}", "",
             f"- Labeled cases: {report['cases']}", f"- Canonical report SHA-256: `{digest}`",
             "- Supplied recommendations only; no model call or action execution.", "",
             "| Metric | Numerator | Denominator | Estimate | 95% lower | 95% upper |",
             "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for name, metric in report["metrics"].items():
        lines.append(f"| {name} | {metric['numerator']} | {metric['denominator']} | "
                     f"{_number(metric['value'])} | {_number(metric['lower'])} | {_number(metric['upper'])} |")
    if report["gates"]:
        lines.extend(["", "| Gate | Statistic | Observed | Bounds | Minimum support | Result |",
                      "| --- | --- | ---: | --- | ---: | --- |"])
        for gate in report["gates"]:
            bounds = ", ".join(f"{side} {gate[side]}" for side in ("min", "max") if gate[side] is not None)
            result = "PASS" if gate["passed"] else f"FAIL ({gate['reason']})"
            lines.append(f"| {gate['metric']} | {gate['statistic']} | {_number(gate['observed'])} | "
                         f"{bounds} | {gate['min_denominator']} | {result} |")
    lines.extend(["", "Wilson intervals assume independent observations. Hand-authored, correlated or",
                  "unrepresentative cases do not establish deployed safety or provider quality.",
                  "Unknown denominators are unmeasured, never zero-error proof. Point-estimate",
                  "bounds are not confidence guarantees; use upper/lower bounds and enough support.", ""])
    return "\n".join(lines)


def write_evaluation(report: dict, out, sign_key: bytes | None = None) -> dict:
    """Preserve a complete, replayable report in a new or empty output directory.

    With ``sign_key`` (raw HMAC key bytes) the directory also holds ``evaluation.json.dsse.json``,
    a DSSE envelope over the exact bytes of ``evaluation.json``.
    """
    envelope = {"report": report, "sha256": digest(report, jcs=_report_schema(report) >= REPORT_SCHEMA)}
    replay_evaluation(envelope)
    with staged_output(out) as directory:
        with (directory / "evaluation.json").open("x", encoding="utf-8") as stream:
            json.dump(envelope, stream, indent=2, ensure_ascii=False, allow_nan=False)
            stream.write("\n")
        if sign_key is not None:
            from . import attestation
            signed = attestation.sign_bytes((directory / "evaluation.json").read_bytes(), "evaluation.json",
                                            envelope, sign_key, "evaluation")
            (directory / "evaluation.json.dsse.json").write_text(attestation.render_envelope(signed), encoding="utf-8")
        with (directory / "EVALUATION.md").open("x", encoding="utf-8") as stream:
            stream.write(render_evaluation(report, envelope["sha256"]))
    return envelope
