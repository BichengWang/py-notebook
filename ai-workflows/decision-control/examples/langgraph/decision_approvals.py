"""Map a LangGraph ``interrupt()`` approval onto decision-control submit, approve and export.

Example code, not part of the ``decisioncontrol`` package: it imports LangGraph, which the
package never does. Two graph nodes:

* ``propose`` freezes the proposal in the store (``TicketStore.submit``). It is a node of its
  own because LangGraph re-runs a node from its first line when it resumes after an
  ``interrupt()``; a submit placed in the node that interrupts would run twice.
* ``review`` surfaces a pending decision with ``interrupt()``. The value of
  ``Command(resume=...)`` becomes the return value of ``interrupt()``, and the node records it
  with ``TicketStore.approve`` or ``reject`` and exports the checksummed record. Everything
  before ``interrupt()`` only reads, and approve and reject return the stored result when
  repeated identically, so a re-run is harmless.

The reviewer is whoever the resume value names. decision-control checks that label against
the frozen policy and refuses the proposer, as ``TicketStore.approve`` always does. ``review``
does not raise on a refusal: LangGraph keeps the resume value of a node that raised and hands
it to the next attempt, so a refused value would block the thread for every later reviewer.
The graph instead finishes with ``refusal`` set and the decision still PENDING_REVIEW in the
store. To ask again, start a new thread whose input is ``{"decision_id": ...}``: ``propose``
skips and ``review`` interrupts again.
"""

from __future__ import annotations

import json
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import interrupt

from decisioncontrol import (DecisionError, Recommendation, RoutingPolicy, StateError, Status, TicketStore,
                             export_record)

REQUEST_KIND = "decision-control/approval-request"
DECISIONS = ("approve", "reject")


class ApprovalState(TypedDict, total=False):
    proposal: dict[str, Any]     # input: a Recommendation as JSON
    proposed_by: str             # input: who the graph acts for; frozen in the record
    decision_id: str             # set by propose
    verdict: str                 # set by propose: ALLOW, REVIEW, DENY or ABSTAIN
    status: str                  # set by review: lifecycle status of the decision
    record: dict[str, Any]       # set by review: exported envelope, `decision-control replay` input
    refusal: dict[str, str]      # set by review instead of record: {"kind": "refused"|"invalid", "message"}


def resume_value(decision: str, reviewer: str, note: str = "") -> dict[str, str]:
    """The value for ``Command(resume=...)``: ``approve`` or ``reject`` by a named reviewer."""
    return {"decision": decision, "reviewer": reviewer, "note": note}


def langgraph_note(thread_id: str, checkpoint_id: str, note: str = "") -> str:
    """Review note that carries the LangGraph pointers. Records have no metadata member, but
    the review note is free text and is covered by the record checksum."""
    return json.dumps({"langgraph": {"thread_id": thread_id, "checkpoint_id": checkpoint_id}, "note": note},
                      sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def langgraph_context(record: dict) -> dict[str, Any]:
    """The ``{"thread_id", "checkpoint_id", "note"}`` that ``review`` wrote into a record."""
    review = record["review"]
    if review is None:
        raise DecisionError("the record has no review")
    try:
        body = json.loads(review["note"])
        return {**body["langgraph"], "note": body["note"]}
    except (ValueError, KeyError, TypeError) as error:
        raise DecisionError("the review note carries no LangGraph context") from error


def _parse_resume(value: Any) -> tuple[str, str, str]:
    if not isinstance(value, dict) or set(value) - {"decision", "reviewer", "note"}:
        raise DecisionError('resume with {"decision": "approve"|"reject", "reviewer": ..., "note": ...}')
    if value.get("decision") not in DECISIONS:
        raise DecisionError(f"decision must be one of {DECISIONS}")
    if not isinstance(value.get("reviewer"), str):
        raise DecisionError("reviewer must be a string")
    note = value.get("note", "")
    if not isinstance(note, str):
        raise DecisionError("note must be a string")
    return value["decision"], value["reviewer"], note


def build_graph(store: TicketStore, policy: RoutingPolicy, checkpointer: Any):
    """Compile ``START -> propose -> review -> END``.

    The checkpointer is required by ``interrupt()``; use a durable one in production, and the
    same SQLite ``store`` file on resume, because the state holds only the decision id.
    """

    def propose(state: ApprovalState) -> ApprovalState:
        if "decision_id" in state:  # a retried run, or a new thread asking again, must not freeze a second decision
            return {}
        record = store.submit(Recommendation.from_dict(state["proposal"]), policy,
                              proposed_by=state["proposed_by"])
        return {"decision_id": record["id"], "verdict": record["evaluation"]["verdict"]}

    def review(state: ApprovalState, runtime: Runtime) -> ApprovalState:
        record = store.get(state["decision_id"])
        if record["status"] == Status.PENDING_REVIEW.value:
            info = runtime.execution_info  # checkpoint_id is the paused checkpoint, stable across resume
            response = interrupt({
                "kind": REQUEST_KIND,
                "decision_id": record["id"],
                "verdict": record["evaluation"]["verdict"],
                "reasons": record["evaluation"]["reasons"],
                "recommendation": record["recommendation"],
                "ticket": record["ticket"],
                "proposed_by": record["proposed_by"],
                "reviewers": record["policy"]["reviewers"],
                "thread_id": info.thread_id,
                "checkpoint_id": info.checkpoint_id,
            })
            try:
                decision, reviewer, note = _parse_resume(response)
                note = langgraph_note(info.thread_id, info.checkpoint_id, note)
                record = (store.approve if decision == "approve" else store.reject)(record["id"], reviewer, note)
            except StateError as error:  # the proposer, an unlisted reviewer, or a decision no longer pending
                return {"status": record["status"], "refusal": {"kind": "refused", "message": str(error)}}
            except DecisionError as error:  # a malformed resume value
                return {"status": record["status"], "refusal": {"kind": "invalid", "message": str(error)}}
        return {"status": record["status"], "record": export_record(record)}

    graph = StateGraph(ApprovalState)
    graph.add_node("propose", propose)
    graph.add_node("review", review)
    graph.add_edge(START, "propose")
    graph.add_edge("propose", "review")
    graph.add_edge("review", END)
    return graph.compile(checkpointer=checkpointer)
