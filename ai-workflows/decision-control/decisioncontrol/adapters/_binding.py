"""One definition of what a frozen external decision must be bound to.

An OPA input and a Cedar request are only evidence for a record if they were produced for
exactly this proposal. The bound document holds the complete recommendation (model,
question version, probability, refusal), the complete ticket snapshot (department,
revision, priority), the proposer and the action. OPA receives the document as its input;
Cedar receives its RFC 8785 SHA-256 as ``context.proposal_sha256``, because Cedar request
context is a flat set of attributes meant for policy conditions, not a document store.
Submit and replay enforce equality through the same function.
"""

import hashlib

from .. import jcs
from ..models import DecisionError, RecordMismatch


def proposal(recommendation, ticket, proposed_by):
    """The complete document an external decision is bound to."""
    return {"action": recommendation.action, "proposed_by": proposed_by,
            "ticket": ticket.to_dict(), "recommendation": recommendation.to_dict()}


def canonical(value, engine):
    try:
        return jcs.canonicalize(value)
    except ValueError as error:
        raise DecisionError(f"{engine} decision must be RFC 8785 canonicalizable JSON: {error}") from error


def proposal_sha256(recommendation, ticket, proposed_by):
    return hashlib.sha256(canonical(proposal(recommendation, ticket, proposed_by), "proposal")).hexdigest()


def require_equal(frozen_part, expected_part, engine, what):
    """Reject a frozen ``input`` or ``request`` that is not the one derived from the record."""
    if canonical(frozen_part, engine) != canonical(expected_part, engine):
        raise RecordMismatch(f"frozen {engine} {what} does not describe this decision's complete proposal, "
                             "ticket snapshot and proposer")
