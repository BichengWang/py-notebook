# LangGraph approvals as decision-control records

A LangGraph `interrupt()` approval is checkpointed graph state: it says a human resumed
the graph, not who, under which frozen rules, or what was decided in a form anyone can
re-check. This example maps it onto decision-control so the same approval leaves a record
that `decision-control replay` verifies offline. It is an example, not part of the
`decisioncontrol` package, which never imports LangGraph.

| File | Contents |
| --- | --- |
| [`decision_approvals.py`](decision_approvals.py) | `build_graph(store, policy, checkpointer)`: the two nodes, `resume_value()` and `langgraph_context()` |
| [`run_example.py`](run_example.py) | One run of the graph end to end: `set_ticket_priority` to `urgent`, proposed by `alice` |
| [`requirements-dev.txt`](requirements-dev.txt) | LangGraph 1.2.16 and its dependencies, pinned (dev only) |
| [`../../tests/test_langgraph_example.py`](../../tests/test_langgraph_example.py) | The tests; they skip when LangGraph is not installed |

## Mapping

| LangGraph | decision-control |
| --- | --- |
| `propose` node: the state's `proposal` and `proposed_by` | `TicketStore.submit(recommendation, policy, proposed_by)` freezes the proposal, policy and verdict; the state keeps `decision_id` |
| `review` node calls `interrupt({...})` | the payload is the pending decision: id, verdict, reason codes, recommendation, ticket, proposer, authorized reviewers, `thread_id`, `checkpoint_id` |
| `Command(resume={"decision": "approve" or "reject", "reviewer": ..., "note": ...})` | `TicketStore.approve` or `reject` by that reviewer, after the store checks the frozen reviewer list and refuses the proposer |
| end of `review` | `export_record` puts the checksummed envelope in the state as `record`; write it to a file for `decision-control replay` |
| thread id and checkpoint id | the review `note` is JSON, `{"langgraph": {"thread_id", "checkpoint_id"}, "note": ...}`; `langgraph_context(record)` reads it |

```python
graph = build_graph(store, policy, InMemorySaver())      # use a durable checkpointer in production
config = {"configurable": {"thread_id": "ticket-T-100"}}
paused = graph.invoke({"proposal": {...}, "proposed_by": "alice"}, config)
request = paused["__interrupt__"][0].value               # show this to the reviewer
done = graph.invoke(Command(resume=resume_value("approve", "bob", "checked")), config)
envelope = done["record"]                                # {"record": ..., "sha256": ...}
```

`store.execute(done["decision_id"])` applies the approved action; export again to record it.
Only a REVIEW verdict interrupts: ALLOW, DENY and ABSTAIN decisions finish the graph without a
pause, with the record exported.

## Run it

From `ai-workflows/decision-control/`, with Python 3.11 or newer:

```bash
python -m venv .venv-example && . .venv-example/bin/activate
pip install -r examples/langgraph/requirements-dev.txt
export PYTHONPATH=$PWD
python examples/langgraph/run_example.py --out /tmp/langgraph-record.json   # bob approves: exit 0
python -m decisioncontrol replay --record /tmp/langgraph-record.json        # exit 0
python examples/langgraph/run_example.py --reviewer alice                   # the proposer: exit 1
python -m unittest discover -s tests -p test_langgraph_example.py -v
```

## Design notes and limits

- **Why two nodes.** LangGraph re-runs a node from its first line on resume, so a node
  that submits and then interrupts would submit twice. `propose` runs once and its result
  is checkpointed. `review` only reads before `interrupt()`, and approve and reject are
  idempotent for identical arguments, so a re-run does nothing new. If a crash lands between
  `submit` and the checkpoint write, the retry submits again and leaves an orphan pending
  decision; the SDK has no client-supplied decision id to prevent that.
- **Self-approval.** `TicketStore.approve` refuses the proposer of a REVIEW decision and any
  reviewer outside the frozen policy (`StateError`, the CLI's exit 1). `review` turns that
  into the state's `refusal` instead of raising, because LangGraph keeps the resume value
  of a node that raised and would give it to the next reviewer's attempt (observed with
  langgraph 1.2.16). The decision stays PENDING_REVIEW; to ask again, invoke a new thread
  with `{"decision_id": ...}`. `run_example.py` exits 1 for a refusal and 2 for a malformed
  resume value. As defense in depth, a record edited to make the proposer its reviewer, even
  with a recomputed checksum, fails `decision-control replay` with exit 1 (tested).
- **Thread and checkpoint ids.** The record has no free metadata member and this example
  does not change the schema, so the ids go in the review note, which is free text covered by
  the record checksum and replayed like any other member. `checkpoint_id` is the checkpoint at
  which `review` paused (`graph.get_state(config).config["configurable"]["checkpoint_id"]`),
  the same value on pause and on resume. Replay does not verify either id against LangGraph;
  they are caller-asserted labels like the reviewer name.
- **Identity.** `proposed_by` and `reviewer` are labels the host supplies. Authenticate the
  people before building the resume value, as in the
  [trust boundary](../../README.md#evidence-and-trust-boundary). A checksum is not a signature;
  sign the exported file for attribution ([Signed records](../../README.md#signed-records)).
- **Scope.** One interrupt per decision, no `Command(goto=...)` routing, no LangGraph server or
  LangSmith. The checkpointer in `run_example.py` is in memory; the decision store is SQLite and
  survives a restart, and a durable checkpointer lets the paused thread do the same.
