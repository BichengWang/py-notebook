"""Credential-free demonstration: hand-authored inputs, real SQLite mutations."""
import json
from pathlib import Path

from ._outputs import staged_output
from .evidence import export_record, replay
from .models import Recommendation, RoutingPolicy
from .store import TicketStore


def _save(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")


def run_demo(out):
    with staged_output(out) as staging:
        return _build_demo(staging, Path(out))


def _build_demo(directory, published):
    policy = RoutingPolicy("demo-policy-1", ("support", "engineering"),
                           ("engineering",), ("local-reviewer",), 0.8)
    cases = (("allow", "support", 0.95), ("review", "engineering", 0.95),
             ("deny", "finance", 0.99), ("abstain", "support", None))
    db = directory / "tickets.sqlite3"
    ids = {}
    _save(directory / "policy.json", policy.to_dict())
    with TicketStore(db) as store:
        for name, destination, probability in cases:
            store.create_ticket(f"demo-{name}", "intake")
            proposal = Recommendation("reassign_ticket", f"demo-{name}", destination,
                                      probability, "hand-authored-demo", "routing-question-1")
            _save(directory / f"proposal-{name}.json", proposal.to_dict())
            ids[name] = store.submit(proposal, policy, proposed_by="local-proposer")["id"]
        store.execute(ids["allow"])
    # Review is durable: close and reopen before approval by a trusted operator.
    with TicketStore(db) as store:
        pending_before_approval = [record["id"] for record in store.pending()]
        store.approve(ids["review"], "local-reviewer", "Reviewed destination and frozen policy")
        first = store.execute(ids["review"])
        repeated = store.execute(ids["review"])
        replay_results = {}
        records = {}
        tickets = {}
        for name, _, _ in cases:
            record = store.get(ids[name])
            envelope = export_record(record)
            record_path = directory / f"record-{name}.json"
            _save(record_path, envelope)
            # Replay the serialized evidence, not just the in-memory envelope.
            with record_path.open(encoding="utf-8") as stream:
                replay_results[name] = replay(json.load(stream))
            records[name] = {"id": record["id"], "verdict": record["evaluation"]["verdict"],
                             "status": record["status"], "file": str(published / record_path.name)}
            tickets[name] = store.get_ticket(f"demo-{name}").to_dict()
    summary = {
        "database": str(published / db.name),
        "inputs": "Hand-authored probabilities and recommendations; no model or provider was called.",
        "execution_boundary": "Actual local SQLite queue reassignment only; no external action.",
        "reopened_before_approval": True,
        "pending_before_approval": pending_before_approval,
        "repeat_execution_same_record": first == repeated,
        "decisions": records,
        "tickets": tickets,
        "replay": replay_results,
    }
    _save(directory / "summary.json", summary)
    return summary
