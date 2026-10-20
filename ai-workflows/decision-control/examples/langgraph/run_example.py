"""Run the two-node approval graph once and export the replayable record.

    python run_example.py --out record.json                    # bob approves alice's proposal
    python run_example.py --out record.json --reviewer alice   # the proposer: refused, exit 1
    python decision-control replay --record record.json        # exit 0

Exit codes follow decision-control: 0 recorded, 1 the review was refused (self-review or an
unauthorized reviewer), 2 invalid input. Probabilities and the model name are hand-authored.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tempfile

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from decision_approvals import build_graph, langgraph_context, resume_value
from decisioncontrol import Recommendation, RoutingPolicy, TicketStore

POLICY = RoutingPolicy("langgraph-example-1", ("support", "engineering"), ("engineering",), ("alice", "bob"), 0.8,
                       ("low", "normal", "high", "urgent"), ("urgent",))
PROPOSER = "alice"
THREAD_ID = "ticket-T-100-priority"


def run(reviewer: str, decision: str, out: Path | None, db: Path) -> int:
    proposal = Recommendation("set_ticket_priority", "T-100", None, 0.95, "hand-authored-example-not-a-provider",
                              "priority-question-1", priority="urgent")
    config = {"configurable": {"thread_id": THREAD_ID}}
    with TicketStore(db) as store:
        store.create_ticket("T-100", "support", priority="normal")
        graph = build_graph(store, POLICY, InMemorySaver())
        paused = graph.invoke({"proposal": proposal.to_dict(), "proposed_by": PROPOSER}, config)
        request = paused["__interrupt__"][0].value
        print(json.dumps({"awaiting_review": request}, indent=2))
        done = graph.invoke(Command(resume=resume_value(decision, reviewer, "checked the ticket")), config)
    if "refusal" in done:
        print(f"decision-control: {done['refusal']['message']}", file=sys.stderr)
        return 1 if done["refusal"]["kind"] == "refused" else 2
    print(json.dumps({"status": done["status"], "langgraph": langgraph_context(done["record"]["record"])}, indent=2))
    if out is not None:
        with out.open("x", encoding="utf-8") as handle:
            json.dump(done["record"], handle, indent=2)
        print(f"wrote {out}", file=sys.stderr)
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--reviewer", default="bob")
    parser.add_argument("--decision", choices=("approve", "reject"), default="approve")
    parser.add_argument("--out", type=Path, help="new file for the exported record")
    parser.add_argument("--db", type=Path, help="new SQLite file (default: a temporary one)")
    args = parser.parse_args(argv)
    if args.db is not None:
        return run(args.reviewer, args.decision, args.out, args.db)
    with tempfile.TemporaryDirectory() as directory:
        return run(args.reviewer, args.decision, args.out, Path(directory) / "queue.sqlite3")


if __name__ == "__main__":
    sys.exit(main())
