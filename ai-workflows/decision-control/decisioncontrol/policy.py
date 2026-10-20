"""Deterministic authorization; model probabilities never grant permissions."""

from .actions import CURRENT_SCHEMA, actions_for
from .models import Evaluation, Recommendation, RoutingPolicy, Ticket, Verdict


INITIAL_STATUS = {
    Verdict.ALLOW: "READY",
    Verdict.REVIEW: "PENDING_REVIEW",
    Verdict.DENY: "DENIED",
    Verdict.ABSTAIN: "ABSTAINED",
}

# Most restrictive first: a REVIEW or ALLOW from one policy never overrides a DENY from another.
_STRICTNESS = (Verdict.DENY, Verdict.ABSTAIN, Verdict.REVIEW, Verdict.ALLOW)


def evaluate(recommendation: Recommendation, ticket: Ticket, policy: RoutingPolicy,
             *, schema: int = CURRENT_SCHEMA) -> Evaluation:
    """Evaluate a proposal against trusted ticket state and a trusted policy snapshot.

    ``schema`` selects the action registry: record schemas 1-4 permit only
    ``reassign_ticket``; later schemas permit every entry of ``actions.ACTIONS``.
    """
    if recommendation.ticket_id != ticket.id:
        return Evaluation(Verdict.DENY, ("ticket_mismatch",))
    action = actions_for(schema).get(recommendation.action)
    if action is None:
        return Evaluation(Verdict.DENY, ("action_not_permitted",))
    requested = action.requested(recommendation)
    if requested not in action.allowed(policy):
        return Evaluation(Verdict.DENY, (action.reason_not_permitted,))
    if requested == action.current(ticket):
        return Evaluation(Verdict.DENY, (action.reason_unchanged,))
    if recommendation.refused:
        return Evaluation(Verdict.ABSTAIN, ("model_refused",))
    if recommendation.probability is None:
        return Evaluation(Verdict.ABSTAIN, ("probability_unknown",))
    if recommendation.probability < policy.min_probability:
        return Evaluation(Verdict.ABSTAIN, ("below_probability_threshold",))
    if requested in action.review(policy):
        return Evaluation(Verdict.REVIEW, (action.reason_review,))
    return Evaluation(Verdict.ALLOW, (action.reason_allow,))


def combine(builtin: Evaluation, external: Evaluation) -> Evaluation:
    """The most restrictive verdict of the built-in policy and a frozen external decision.

    DENY outranks ABSTAIN, REVIEW and ALLOW in that order. Reasons come from every
    evaluation that has the winning verdict, built-in first, without duplicates.
    """
    verdict = next(v for v in _STRICTNESS if v in (builtin.verdict, external.verdict))
    reasons = []
    for evaluation in (builtin, external):
        if evaluation.verdict == verdict:
            reasons.extend(reason for reason in evaluation.reasons if reason not in reasons)
    return Evaluation(verdict, tuple(reasons))
