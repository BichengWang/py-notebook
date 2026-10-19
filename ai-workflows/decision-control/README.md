# decision-control

Replayable decision records for AI-assisted go/no-go decisions, demonstrated by
**local ticket reassignment**. An independent Python 3.11+ standard-library SDK and
JSON CLI. It evaluates a supplied recommendation, stores frozen evidence in SQLite, persists human review, and atomically changes the local ticket
queue. It does not call a model, authenticate people, or operate an external service.
This original MIT-licensed project is separate from RELIA: no RELIA imports, copied
implementation, integration, benchmark changes, or provider-quality claims.

## Install and run

Install the PyPI distribution (the 0.1.0 release is prepared but not yet published):

```bash
pip install decisioncontrol
```

For a source installation, run from this directory:

```bash
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python .
. .venv/bin/activate
decision-control demo --out /tmp/decision-control-demo
python -m decisioncontrol replay --record /tmp/decision-control-demo/record-review.json
```

Choose a new or empty demo directory; existing output is never overwritten. The demo
publishes a complete directory using staging and `os.replace`, so failed writes
leave the target new or empty and retryable. It creates `tickets.sqlite3`,
policy/proposal JSON, four exported records, and
`summary.json`. It exercises ALLOW, REVIEW, DENY and ABSTAIN; closes/reopens the store
before approval; executes the approved reassignment twice safely; and replays all
serialized records. ALLOW and approved REVIEW tickets have revision 1 and new
departments; DENY and ABSTAIN tickets remain in intake at revision 0. Probabilities
are **hand-authored illustrative inputs**, not measured confidence or model calls.

## Persisted operator workflow

The bundled example requests engineering, which requires review. Run from this
directory after installation (use a fresh database for the initial ticket):

```bash
decision-control --db queue.sqlite3 ticket-create --ticket-id T-100 --department intake
decision-control --db queue.sqlite3 submit --proposal examples/proposal.json --policy examples/policy.json --proposed-by local-proposer
decision-control --db queue.sqlite3 pending
```

Copy the returned decision `id` into `DECISION_ID`, then run:

```bash
decision-control --db queue.sqlite3 show "$DECISION_ID"
decision-control --db queue.sqlite3 approve "$DECISION_ID" --reviewer local-reviewer --note 'Checked routing'
```

The decision is now READY, not yet executed. Choose execution or withdrawal.

To execute:

```bash
decision-control --db queue.sqlite3 execute "$DECISION_ID"
decision-control --db queue.sqlite3 execute "$DECISION_ID"
decision-control --db queue.sqlite3 ticket-show T-100
decision-control --db queue.sqlite3 export "$DECISION_ID" --out approved-record.json
decision-control replay --record approved-record.json
```

To withdraw **before executing**, use a reviewer from the decision's frozen policy
and a nonempty reason. This also works for pending reviews and automatically
allowed READY decisions:

```bash
decision-control --db queue.sqlite3 cancel "$DECISION_ID" --reviewer local-reviewer --note 'Approval was mistaken'
decision-control --db queue.sqlite3 export "$DECISION_ID" --out cancelled-record.json
decision-control replay --record cancelled-record.json
```

Cancellation leaves the ticket unchanged and permanently blocks execution and
further review. The record retains any original approval and adds a CANCELLED
event with the cancelling reviewer, reason and time. SDK callers use
`store.cancel(decision_id, reviewer, note)`. Repeating the same cancellation is
idempotent; a different actor or reason cannot rewrite it. A cancelled pending
review leaves the pending queue. If execution commits first, cancellation fails:
it is not an undo operation. Both operations use the same SQLite writer
transaction, so overlapping callers cannot both commit their conflicting actions.

Alternatively `reject ID --reviewer local-reviewer --note TEXT` permanently rejects
a pending review. Identical repeated approvals, rejections and cancellations return
the recorded result; conflicting retries fail. For new REVIEW decisions, the
proposer cannot approve, reject or cancel, even if listed as a policy reviewer.
`export ID` without `--out` prints the envelope; file export
refuses overwrite. All successful command results are JSON. `--db` is a global
option placed **before** storage commands. `demo` and `replay` need no database
option. Exit codes are:

- **0**: command succeeded, gate passed, or evidence replayed successfully. Valid
  replay succeeds even for a recorded FAIL; ungated evaluation also exits 0.
- **1**: gate failed, replay checksum/semantic mismatch, prohibited lifecycle action,
  unauthorized/self review, execution returned STALE (no action performed), or
  `pending` skipped corrupt rows.
- **2**: invalid input/usage, unreadable file, unsupported record/store schema, or IO error.

`pending()` returns a list-compatible result whose `.skipped` contains `{id, error}`
diagnostics. The CLI still prints valid pending records as JSON, warns on stderr
and exits 1 if it skipped any rows. It does not repair corrupt rows. Each submitted
record (including DENY/ABSTAIN) is persisted successfully; submission exit 0 means
recorded, and execution is a separate command.

Errors go to stderr; argparse help is ordinary
human-readable help. See `decision-control --help` and command `--help`.

## SDK

```python
from decisioncontrol import Recommendation, RoutingPolicy, TicketStore, export_record, replay

policy = RoutingPolicy('sdk-1', ('support',), (), ('local-reviewer',), 0.8)
proposal = Recommendation('reassign_ticket', 'SDK-1', 'support', 0.95,
                          'hand-authored-example', 'routing-question-1')
with TicketStore('sdk-queue.sqlite3') as store:
    store.create_ticket('SDK-1', 'intake')
    submitted = store.submit(proposal, policy, proposed_by="local-proposer")
    executed = store.execute(submitted['id'])
    assert store.execute(submitted['id']) == executed
    envelope = export_record(executed)
print(replay(envelope))
```

Model output is input, not authority. Only `reassign_ticket` is supported. Invalid
actions, mismatched tickets, prohibited destinations and no-op assignments are
DENY. Refusal, missing probability or probability below the threshold is ABSTAIN
when hard constraints otherwise permit the action. Review destinations yield
REVIEW; other permitted recommendations yield ALLOW. JSON inputs are strictly
validated; no missing probability is invented.

## Evaluate supplied recommendations

Evaluate a candidate routing policy on independently labeled JSON Lines before
allowing it to automate actions. This is an offline evaluator: it neither calls a
provider nor executes actions or approves pending decisions.

```bash
decision-control evaluate --cases examples/evaluation-cases.jsonl \
  --policy examples/policy.json --out /tmp/decision-control-evaluation
decision-control evaluate --cases examples/evaluation-cases.jsonl \
  --policy examples/policy.json --require examples/evaluation-requirements.json \
  --out /tmp/decision-control-gated
# The supplied adverse fixture intentionally exits 1 and records FAIL.
decision-control replay-evaluation --record /tmp/decision-control-gated/evaluation.json
```

Each output directory must be new or empty. Evaluation and demo directories, and
file exports, are built beside the target and published with `os.replace`; failed
writes leave no partial target. Existing nonempty outputs are refused.
`evaluation.json` retains the full
cases, labels, policy, requirements, per-case verdicts, metrics and gate outcomes
in a checksummed envelope. `EVALUATION.md` is the human-readable report. A failed
gate still writes evidence and exits 1; invalid input exits 2 without excluding
bad rows from the score. Omitting `--require` gives `UNGATED`, **not PASS**.
Replay returns success for valid evidence even when its recorded gate is FAIL;
the returned disposition remains FAIL.

The example cases and review outcomes are **hand-authored software fixtures**.
They include an unsafe automatic allowance, an incorrect review approval and an
unobserved review. Their small sample intentionally fails the example gates;
neither that failure nor an ungated report measures any live model.

### Case labels

Each JSON Lines row has `id`, `ticket`, `recommendation`, `labels`, and an optional
`review_outcome`. Ticket and recommendation use the existing SDK schemas.

- `labels.safe_to_execute`: human judgment of whether the proposed action would
  be safe if the required approval were obtained.
- `labels.requires_review`: human judgment of whether approval is required.
- `labels.correct_destination`: independently labeled routing destination.
- `review_outcome`: supplied `APPROVED`, `REJECTED`, or null/absent. It is an
  observation, not a request to approve anything or proof of reviewer identity.

Duplicate case identifiers, empty datasets, malformed inputs and unknown fields
are rejected. Labels must not be generated by the policy being evaluated.

### Metrics and denominators

| Metric | Numerator | Denominator |
| --- | --- | --- |
| `auto_allow_rate` | ALLOW cases | All cases |
| `unsafe_auto_allow_rate` | ALLOW despite an unsafe or required-review label | ALLOW cases |
| `auto_route_error_rate` | ALLOW with an incorrect destination | ALLOW cases |
| `review_rate` | REVIEW cases | All cases |
| `abstain_rate` | ABSTAIN cases | All cases |
| `deny_rate` | DENY cases | All cases |
| `required_review_recall` | REVIEW with a required-review label | All required-review cases |
| `review_precision` | REVIEW with a required-review label | REVIEW cases |
| `incorrect_approval_rate` | Observed APPROVED with an unsafe label or incorrect destination | Observed APPROVED on REVIEW cases |
| `review_observation_rate` | Supplied review outcome on REVIEW cases | REVIEW cases |

Every metric includes its numerator, denominator, point estimate (`value`) and
95% Wilson bounds (`lower`, `upper`). A zero denominator yields null estimates,
not zero errors, and cannot satisfy a required bound. A safe DENY/ABSTAIN does not
count as REVIEW recall. Review observations are scored only for cases this policy
routes to REVIEW; approval error is conditional on observed approvals. Require
enough observations rather than assuming missing approvals were correct.

### Gate contract and statistical limits

Requirements contain `min_cases` and a nonempty `bounds` object keyed by the
metric names above. Each bound has `min` and/or `max`, an optional `statistic`
(`value`, `lower`, `upper`), and optional positive `min_denominator`.

Use `upper` for error ceilings and `lower` for recall floors, plus enough sample
support. A point-estimate gate does not establish a confidence guarantee:
zero observed errors in ten allowed cases still has a 95% upper bound near 0.278.
Freeze policies and requirements before examining a representative holdout.
Intervals assume independent observations, are per-metric rather than simultaneous
guarantees, and do not correct for threshold tuning or repeated looks. Synthetic,
correlated or selectively observed cases do not establish deployed safety,
calibrated provider probabilities or legal compliance.

SDK entry points are `EvaluationCase`, `load_cases(path)`,
`evaluate_cases(cases, policy, requirements=None, schema_version=2)`,
`write_evaluation(report, out)` and `replay_evaluation(envelope)`. Evaluation
evidence is distinct from the executed-decision records below. Both checksums
detect corruption, not forgery.

Reports are `schema_version: 2`: the `sha256` covers the report in RFC 8785 (JCS)
canonical form, and `replay-evaluation` rejects duplicate object keys (exit 2).
Schema 1 reports, digested as Python sorted compact JSON, still replay under their
original rules (`evaluate_cases(..., schema_version=1)` reproduces one). Replay
picks the rule from the report's own `schema_version`; unknown versions exit 2.

Replay recomputes every metric and compares it with the recorded report exactly,
for both schemas. This is portable because the recomputation uses only integer
counts, IEEE 754 division, multiplication, addition and `math.sqrt` (correctly
rounded), plus a fixed literal for the 95% normal quantile. It calls no libm
transcendental function (`log`, `exp`, `erf`) and no inverse-CDF routine, so the
Wilson bounds are bit-identical across platforms. The committed vectors are
generated on one machine and replayed by CI on Linux, which is the check of that
claim; no regeneration happens in CI. Decision records contain no derived floats
(probabilities and thresholds are copied inputs), so record replay has no
floating-point recomputation.

## Record schema v4 (v1-v3 readable)

An export contains `record` and `sha256`. The record includes:

- integer `schema_version`, `produced_by` distribution name/version, decision `id`,
  and UTC `created_at`;
- caller-asserted `proposed_by` and lowercase `policy_sha256` over canonical policy JSON;
- the supplied `recommendation` with model/question identifiers, probability and refusal;
- the trusted `ticket` snapshot (identifier, department and revision);
- the frozen `policy`, evaluated verdict and machine-readable reason codes;
- lifecycle `status`, authorized `review`, execution `result`, and transition `events`.

The full record is checksummed, including review and execution history. Replay
rejects inconsistent verdicts, illegal transitions, unauthorized recorded reviewers
and results that disagree with the frozen action. Schema 3 and later additionally
validate the policy digest and forbid proposer review/cancellation of REVIEW decisions.
New decisions use `schema_version: 4`, which differs from schema 3 only in
canonicalization: the record `sha256` and `policy_sha256` are digests of RFC 8785
(JCS) canonical bytes, and replay rejects duplicate object keys (exit 2). JCS writes
a whole-number float such as `1.0` as `1`, so never rely on the int/float
distinction in records; integers beyond 2^53-1, NaN/Infinity and unpaired surrogates
exit 2. A CANCELLED event has `event`, `at`, `reviewer` and `note` fields.
Other event shapes remain unchanged.

Archived v1, v2 and v3 evidence and stored decisions remain valid under their original
rules: v1/v2 have no proposer separation check, and v1-v3 digest Python sorted
compact JSON (see below). They do not gain invented identity provenance on replay.
Existing stored v3 decisions stay v3 (including after `approve` or `cancel`); only new
submissions are v4. Cancelling a stored v1 decision explicitly promotes that record
to v2, preserving its inputs and prior approval. Unknown schema versions are
rejected (exit 2) rather than silently reinterpreted. Policy-evaluation reports use
their own schema (1 or 2, above).

### JSON Schemas and conformance vectors

Every record and evaluation version the readers accept has a JSON Schema 2020-12
file shipped as package data: `decisioncontrol/schema/record.v{1,2,3,4}.json` and
`evaluation.v{1,2}.json`. They describe the exported envelope (`record`/`report` plus
`sha256`), state the canonicalization and the covered fields in `$comment`, and set
`additionalProperties: false` where the readers reject unknown keys. A schema cannot
express the replay rules (recomputed verdict, lifecycle, reviewer authorization);
only `replay` checks those. Load them with
`importlib.resources.files("decisioncontrol") / "schema"`.

`conformance/` holds vectors and `manifest.json` (`format: 1`; each vector names its
verify command, expected exit code, schema documents and digests): `valid/` replays with
exit 0 and carries the exact canonical bytes and digests of each checksum;
`tampered/` replays with exit 1 (stale checksums, and edits with a recomputed
checksum such as proposer self-approval or an edited frozen policy that replay still
detects); `invalid/` exits 2 (duplicate keys, NaN, unsafe integers, unknown schema
or fields). `python3 conformance/generate.py` regenerates the tree deterministically;
a unit test fails if the committed files differ. The vectors are synthetic software
fixtures, not live or adoption evidence. A checksum recomputed over a self-consistent
edit that obeys every replay rule (for example, adding yourself to the frozen
reviewers) is undetectable; that needs signatures.

Supply the probability of the proposed choice, not an unrelated provider confidence
score. The host owns provider adaptation, model/question identity and threshold
validation on labeled application data. This library does not calibrate probabilities
or turn model recommendations into trusted permissions.

## Evidence and trust boundary

* Proposer and reviewer identifiers are caller-asserted labels supplied by a
  **trusted local host/operator**, not authenticated identities. There is no login, server, RBAC service or network
  boundary. Separation of duties compares labels, so a caller can bypass it by
  claiming another identity. The host must authenticate people, bind labels to
  principals and control who supplies the policy/reviewer list. A policy digest
  freezes the supplied content; it does not establish that policy as trusted.
  A malicious process with file access can modify the database/evidence.
* Policies and ticket snapshots are frozen at submission. Updating a policy file
  does not retroactively revoke existing decisions or approvals. Use `cancel` for
  explicit pre-execution withdrawal, not an assumed current-policy check.
* Execution checks the frozen ticket department/revision against current state.
  A competing reassignment makes the decision STALE without changing the ticket.
  The SDK returns STALE; the CLI exits 1. SQLite commits queue mutation, revision
  increment, result and event together.
  Repeating execution of the same executed decision returns its stored result.
  This is **local atomicity**, not exactly-once execution of external actions.
* Exported envelopes contain SHA-256 over canonical JSON. Replay checks corruption,
  recomputes the frozen policy evaluation and validates lifecycle evidence. Schemas
  record v4 and evaluation v2 use RFC 8785 (JCS) via the bundled `decisioncontrol.jcs`;
  older schemas use `json.dumps` with sorted keys, `separators=(",", ":")`,
  `ensure_ascii=False`, UTF-8. Digests are lowercase hexadecimal SHA-256. Replay neither calls a model nor executes an action. Checksums are not signatures:
  attackers can recompute them. Records are not provider attestations, identity
  proof, calibrated model evidence or proof of outside-world execution.
* Protect database files, exports and notes using operating-system permissions;
  they can contain sensitive ticket metadata. Avoid untrusted database/JSON files
  and unbounded inputs. See [SECURITY.md](SECURITY.md).

SQLite store schema 1 is stamped in `PRAGMA user_version`. Legacy unversioned
stores are accepted and stamped without changing their records; newer unknown
store versions are refused before creating tables. Journal mode is unchanged.

## Development

```bash
python -m unittest discover -s tests
```

Schema validation tests need the dev-only `jsonschema` package and skip when it is
absent; CI installs pinned versions (see `decision-control-ci.yml`) and also checks
that the records written by `decision-control demo` validate against the shipped
schemas.

The package has no runtime dependencies or sibling-project imports. Setuptools is
an installation/build dependency. Repository CI uses the registered
`decision-control-ci.yml`; [CONTRIBUTING.md](CONTRIBUTING.md) describes scope.
[CHANGELOG.md](CHANGELOG.md) records changes. New project code is licensed under
[MIT](LICENSE); this does not relicense RELIA or any other component.

## Verification status

Behavioral tests cover restart-safe review, concurrent local execution, rollback,
stale decisions, separation of duties, corrupt queue rows, idempotent rejection,
retryable output failures, v1-v4 replay, RFC 8785 test vectors and every conformance
vector. CI builds and validates the wheel, installs it into a fresh environment, then
runs demo, decision replay, an adverse fixture evaluation, evaluation replay, a rejected
self-approval, the packaged schemas and the conformance vectors outside the
source tree. These are software checks on hand-authored fixtures, not live-model,
calibration, adoption or production evidence. PyPI publication is a separate step.
