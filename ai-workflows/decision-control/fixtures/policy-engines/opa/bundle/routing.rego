package ticket.routing

# Ticket-routing policy used to record the OPA fixtures. It is deliberately small:
# only listed routers may act, and the destinations and priorities that need a human
# are marked REVIEW. Anything else is denied.

default decision := {"verdict": "DENY", "reasons": ["no_rule_matched"]}

routers := {"alice", "bob"}

open_destinations := {"support"}

review_destinations := {"engineering"}

open_priorities := {"low", "normal", "high"}

review_priorities := {"urgent"}

decision := {"verdict": "ALLOW", "reasons": ["router_reassigns_to_open_destination"]} if {
	input.action == "reassign_ticket"
	input.proposed_by in routers
	input.recommendation.destination in open_destinations
}

decision := {"verdict": "REVIEW", "reasons": ["destination_needs_review"]} if {
	input.action == "reassign_ticket"
	input.proposed_by in routers
	input.recommendation.destination in review_destinations
}

decision := {"verdict": "ALLOW", "reasons": ["router_sets_open_priority"]} if {
	input.action == "set_ticket_priority"
	input.proposed_by in routers
	input.recommendation.priority in open_priorities
}

decision := {"verdict": "REVIEW", "reasons": ["priority_needs_review"]} if {
	input.action == "set_ticket_priority"
	input.proposed_by in routers
	input.recommendation.priority in review_priorities
}
