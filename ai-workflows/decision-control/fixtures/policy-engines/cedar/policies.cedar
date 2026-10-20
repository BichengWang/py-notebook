// Ticket-routing policy used to record the Cedar fixtures. Cedar answers Allow or Deny;
// whether a human must review is decided by the built-in policy and the record combines them.

@id("routers-reassign-to-open-destinations")
permit (
    principal in Group::"routers",
    action == Action::"reassign_ticket",
    resource
)
when { context.requested == "support" || context.requested == "engineering" };

@id("routers-set-priority")
permit (
    principal in Group::"routers",
    action == Action::"set_ticket_priority",
    resource
)
when { ["low", "normal", "high", "urgent"].contains(context.requested) };

@id("legal-tickets-stay-in-legal")
forbid (
    principal,
    action == Action::"reassign_ticket",
    resource
)
when { context has current && context.current == "legal" };
