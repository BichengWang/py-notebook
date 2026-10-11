"""Deterministic authorization; model probabilities never grant permissions."""

from .models import Evaluation, Recommendation, RoutingPolicy, Ticket, Verdict


INITIAL_STATUS = {
    Verdict.ALLOW: "READY",
    Verdict.REVIEW: "PENDING_REVIEW",
    Verdict.DENY: "DENIED",
    Verdict.ABSTAIN: "ABSTAINED",
}


def evaluate(recommendation: Recommendation, ticket: Ticket, policy: RoutingPolicy) -> Evaluation:
    """Evaluate a proposal against trusted ticket state and a trusted policy snapshot."""
    if recommendation.ticket_id != ticket.id:
        return Evaluation(Verdict.DENY, ("ticket_mismatch",))
    if recommendation.action != "reassign_ticket":
        return Evaluation(Verdict.DENY, ("action_not_permitted",))
    if recommendation.destination not in policy.allowed_destinations:
        return Evaluation(Verdict.DENY, ("destination_not_permitted",))
    if recommendation.destination == ticket.department:
        return Evaluation(Verdict.DENY, ("already_assigned",))
    if recommendation.refused:
        return Evaluation(Verdict.ABSTAIN, ("model_refused",))
    if recommendation.probability is None:
        return Evaluation(Verdict.ABSTAIN, ("probability_unknown",))
    if recommendation.probability < policy.min_probability:
        return Evaluation(Verdict.ABSTAIN, ("below_probability_threshold",))
    if recommendation.destination in policy.review_destinations:
        return Evaluation(Verdict.REVIEW, ("destination_requires_review",))
    return Evaluation(Verdict.ALLOW, ("policy_permits_reassignment",))
