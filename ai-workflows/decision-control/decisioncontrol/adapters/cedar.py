"""Freeze a Cedar authorization: policies, entities, request, decision and diagnostics.

The frozen block keeps the policy set (Cedar text or Cedar JSON policy format), the
entity hierarchy, the request (principal, action, resource and context, as for
``cedar authorize --request-json``), the decision (``Allow`` or ``Deny``) and
the diagnostics in the shape of the Cedar ``Response``: ``reason`` lists the
determining policy ids and ``errors`` lists ``{"policyId", "error"}`` pairs.

Mapping to a verdict: Allow is ALLOW and Deny is DENY. Cedar has no review outcome; a
decision that needs a human reviewer is expressed by the built-in policy. Replay
re-evaluates with ``cedar authorize`` when ``cedar`` is on PATH.
"""

from collections.abc import Mapping
import json
from pathlib import Path
import re
import tempfile

from .. import jcs
from ..actions import ACTIONS
from ..models import DecisionError, Evaluation, RecordMismatch, Verdict, _fields, _text
from . import _binding, _tools

NAME = "cedar"
FIELDS = {"engine", "policies", "entities", "request", "decision", "diagnostics"}
DECISIONS = ("Allow", "Deny")
_ERROR_LINE = re.compile(r"error while evaluating policy `(.+?)`: (.*)\Z")


def _literal(text):
    """Cedar string literal contents for ``text``."""
    out = []
    for character in text:
        if character in '\\"':
            out.append("\\" + character)
        elif ord(character) < 0x20 or ord(character) == 0x7F:
            out.append(f"\\u{{{ord(character):x}}}")
        else:
            out.append(character)
    return "".join(out)


def authorization_request(recommendation, ticket, proposed_by):
    """The Cedar request for a proposal; replay requires the frozen request to equal it.

    Principal ``User::"<proposer>"``, action ``Action::"<action>"``, resource
    ``Ticket::"<ticket id>"`` and a context with ``requested`` (the target value), ``current``
    (the value it would replace, when the ticket has one) and ``proposal_sha256``, the digest
    of the complete bound proposal (see ``_binding``).
    """
    context = {"requested": recommendation.target,
               "proposal_sha256": _binding.proposal_sha256(recommendation, ticket, proposed_by)}
    action = ACTIONS.get(recommendation.action)
    if action is not None and action.current(ticket) is not None:
        context["current"] = action.current(ticket)
    return {"principal": f'User::"{_literal(proposed_by)}"',
            "action": f'Action::"{_literal(recommendation.action)}"',
            "resource": f'Ticket::"{_literal(ticket.id)}"', "context": context}


def _canonical(value):
    try:
        return jcs.canonicalize(value)
    except ValueError as error:
        raise DecisionError(f"Cedar decision must be RFC 8785 canonicalizable JSON: {error}") from error


def _policies(value):
    if not isinstance(value, Mapping) or value.get("format") not in ("cedar", "json"):
        raise DecisionError("policies must be an object with format cedar or json")
    if value["format"] == "cedar":
        if not isinstance(_fields(value, {"format", "text"})["text"], str):
            raise DecisionError("Cedar policy text must be text")
    elif not isinstance(_fields(value, {"format", "json"})["json"], Mapping):
        raise DecisionError("Cedar JSON policies must be an object")


def _diagnostics(value):
    raw = _fields(value, {"reason", "errors"})
    reason = raw["reason"]
    if not isinstance(reason, list) or len({_text(item, "policy id") for item in reason}) != len(reason):
        raise DecisionError("diagnostics.reason must be a list of unique policy ids")
    if not isinstance(raw["errors"], list):
        raise DecisionError("diagnostics.errors must be a list")
    for error in raw["errors"]:
        fields = _fields(error, {"policyId", "error"})
        _text(fields["policyId"], "policy id")
        if not isinstance(fields["error"], str):
            raise DecisionError("diagnostics error message must be text")


def validate(frozen):
    raw = _fields(frozen, FIELDS)
    if raw["engine"] != NAME:
        raise DecisionError("not a Cedar decision")
    _policies(raw["policies"])
    if not isinstance(raw["entities"], list) or not all(isinstance(item, Mapping) for item in raw["entities"]):
        raise DecisionError("entities must be a list of Cedar entity objects")
    request = _fields(raw["request"], {"principal", "action", "resource", "context"})
    for name in ("principal", "action", "resource"):
        _text(request[name], name)
    if not isinstance(request["context"], Mapping):
        raise DecisionError("context must be a JSON object")
    if raw["decision"] not in DECISIONS:
        raise DecisionError("decision must be Allow or Deny")
    _diagnostics(raw["diagnostics"])
    _canonical(raw)
    return raw


def bind(frozen, recommendation, ticket, proposed_by):
    """Reject a frozen decision that was taken for a different proposal, ticket or proposer."""
    _binding.require_equal(frozen["request"], authorization_request(recommendation, ticket, proposed_by),
                           "Cedar", "request")


def evaluation(frozen):
    """The verdict and reasons a frozen Cedar decision maps to."""
    reasons = sorted(frozen["diagnostics"]["reason"])
    if frozen["decision"] == "Allow":
        if not reasons:
            raise RecordMismatch("frozen Cedar decision is Allow but no permit policy determined it")
        return Evaluation(Verdict.ALLOW, tuple(f"cedar:permit:{policy}" for policy in reasons))
    if reasons:
        return Evaluation(Verdict.DENY, tuple(f"cedar:forbid:{policy}" for policy in reasons))
    return Evaluation(Verdict.DENY, ("cedar:no_permit_applied",))


def _authorize(binary, policies, entities, request, root):
    """Run ``cedar authorize --verbose`` and return ``(decision, diagnostics)`` in frozen form."""
    suffix = "cedar" if policies["format"] == "cedar" else "json"
    source = root / f"policies.{suffix}"
    if policies["format"] == "cedar":
        source.write_text(policies["text"], encoding="utf-8")
    else:
        source.write_text(json.dumps(policies["json"]), encoding="utf-8")
    (root / "entities.json").write_text(json.dumps(entities), encoding="utf-8")
    (root / "request.json").write_text(json.dumps(request), encoding="utf-8")
    completed = _tools.run([binary, "authorize", "--policies", str(source), "--policy-format", policies["format"],
                            "--entities", str(root / "entities.json"), "--request-json",
                            str(root / "request.json"), "--verbose"], cwd=root)
    lines = completed.stdout.splitlines()
    first = next((line.strip() for line in lines if line.strip()), "")
    if completed.returncode not in (0, 2) or first not in ("ALLOW", "DENY"):
        raise _tools.ToolFailure("cedar could not authorize the request: "
                                 + _tools.first_line(completed.stderr or completed.stdout))
    reason, errors, listing = [], [], False
    for line in lines:
        if line.startswith("note: this decision was due to the following policies"):
            listing = True
        elif listing and line.startswith("  ") and line.strip():
            reason.append(line.strip())
        else:
            listing = False
            match = _ERROR_LINE.match(line)
            if match:
                errors.append({"policyId": match.group(1), "error": match.group(2)})
    return first.title(), {"reason": sorted(reason), "errors": errors}


def authorize(policies, entities, request):
    """Authorize with the installed ``cedar`` CLI; ``(decision, diagnostics)`` for freezing."""
    binary = _tools.find("cedar")
    if binary is None:
        raise DecisionError("cedar is not on PATH; pass a recorded response instead")
    with tempfile.TemporaryDirectory(prefix="decisioncontrol-cedar-") as temporary:
        return _authorize(binary, policies, entities, request, Path(temporary))


def reevaluate(frozen):
    """Re-evaluate the frozen decision. ``None`` when cedar is absent, else the tool version.

    Raises RecordMismatch when the decision or its determining policies differ.
    """
    binary = _tools.find("cedar")
    if binary is None:
        return None
    with tempfile.TemporaryDirectory(prefix="decisioncontrol-cedar-") as temporary:
        root = Path(temporary)
        try:
            decision, diagnostics = _authorize(binary, frozen["policies"], frozen["entities"],
                                               frozen["request"], root)
        except _tools.ToolFailure as error:
            raise RecordMismatch(str(error)) from error
        frozen_errors = sorted(error["policyId"] for error in frozen["diagnostics"]["errors"])
        if (decision != frozen["decision"]
                or sorted(frozen["diagnostics"]["reason"]) != diagnostics["reason"]
                or frozen_errors != sorted(error["policyId"] for error in diagnostics["errors"])):
            raise RecordMismatch(f"re-evaluating the frozen Cedar policies gives {decision} "
                                 f"({diagnostics['reason']}), not the frozen {frozen['decision']}")
        version = _tools.run([binary, "--version"], cwd=root).stdout.strip()
        return version or "cedar (unknown version)"


def freeze(policies, entities, request, response=None):
    """Build the frozen block. Without ``response`` (a Cedar ``Response``: ``decision`` and
    ``diagnostics``) the decision comes from the installed ``cedar`` CLI."""
    if response is None:
        decision, diagnostics = authorize(policies, entities, request)
    else:
        raw = _fields(response, {"decision", "diagnostics"})
        decision, diagnostics = raw["decision"], raw["diagnostics"]
    frozen = {"engine": NAME, "policies": policies, "entities": entities, "request": request,
              "decision": decision, "diagnostics": diagnostics}
    return validate(frozen)
