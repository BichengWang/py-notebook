"""Registry of action types a decision may request.

Adding an action type means adding one entry to ``ACTIONS``; nothing else in the policy,
the replay or the store names a specific action. Every action shares one evaluation
pipeline (ticket match, allowlist, no-op, refusal, probability floor, review list), so a
new entry cannot skip a safety check. An action sets one ticket member to a value
from a policy allowlist; a different kind of effect needs new pipeline code, not an entry.

The registry is a constant, not a runtime ``register()``, because replay recomputes
verdicts from it: a plug-in that changed the verdict of an existing record would break
verification. Record schemas 1-4 predate the registry and permit only ``reassign_ticket``;
their readers use ``LEGACY_ACTIONS``.
"""

from dataclasses import dataclass, replace
from types import MappingProxyType

# Record schema 5 is the first version that admits registered actions beyond
# ``reassign_ticket``; schemas 1-4 keep their original shape and action set.
LEGACY_ACTIONS_SCHEMA = 4
CURRENT_SCHEMA = 5

# Members shared by Recommendation, Ticket and RoutingPolicy that an action may name.
TARGET_FIELDS = ("destination", "priority")
TICKET_FIELDS = ("department", "priority")


@dataclass(frozen=True)
class ActionType:
    name: str
    target_field: str         # Recommendation member carrying the requested value
    ticket_field: str         # Ticket member the executor sets
    allowed_field: str        # RoutingPolicy tuple of values the action may request
    review_field: str         # RoutingPolicy tuple of values that need a human reviewer
    reason_not_permitted: str
    reason_unchanged: str
    reason_allow: str
    reason_review: str

    def __post_init__(self):
        if self.target_field not in TARGET_FIELDS or self.ticket_field not in TICKET_FIELDS:
            raise ValueError(f"unsupported action members for {self.name}")

    def requested(self, recommendation):
        return getattr(recommendation, self.target_field)

    def current(self, ticket):
        return getattr(ticket, self.ticket_field)

    def allowed(self, policy):
        return getattr(policy, self.allowed_field)

    def review(self, policy):
        return getattr(policy, self.review_field)

    def apply(self, ticket, recommendation):
        """The ticket after executing ``recommendation``; the executor and replay share this."""
        return replace(ticket, **{self.ticket_field: self.requested(recommendation)},
                       revision=ticket.revision + 1)


REASSIGN_TICKET = ActionType(
    "reassign_ticket", "destination", "department", "allowed_destinations", "review_destinations",
    "destination_not_permitted", "already_assigned", "policy_permits_reassignment",
    "destination_requires_review")

SET_TICKET_PRIORITY = ActionType(
    "set_ticket_priority", "priority", "priority", "allowed_priorities", "review_priorities",
    "priority_not_permitted", "priority_unchanged", "policy_permits_priority_change",
    "priority_requires_review")

ACTIONS = MappingProxyType({action.name: action for action in (REASSIGN_TICKET, SET_TICKET_PRIORITY)})
LEGACY_ACTIONS = MappingProxyType({REASSIGN_TICKET.name: REASSIGN_TICKET})


def actions_for(schema):
    """Action types a record of ``schema`` may request."""
    return ACTIONS if schema > LEGACY_ACTIONS_SCHEMA else LEGACY_ACTIONS
