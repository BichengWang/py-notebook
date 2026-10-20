# decision-control

Replayable decision records for AI-assisted go/no-go decisions, demonstrated by
**local ticket reassignment**. An independent Python 3.11+ standard-library SDK and
JSON CLI. It evaluates a supplied recommendation, stores frozen evidence in SQLite, persists human review, and atomically changes the local ticket
queue. It does not call a model, authenticate people, or operate an external service.
This original MIT-licensed project is separate from RELIA: no RELIA imports, copied
implementation, integration, benchmark changes, or provider-quality claims.

## Install and run

Install the PyPI distribution (the first PyPI release, 0.2.0, is prepared but not yet published):

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
  replay succeeds even for a recorded FAIL; ungated evaluation also exits 0. A record
  with a frozen OPA or Cedar decision that was verified **digest-only** (the tool is
  not on PATH) also exits 0, with a distinct stderr message; see
  [Replay: re-evaluation and digest-only](#replay-re-evaluation-and-digest-only).
- **1**: gate failed, replay checksum/semantic mismatch (including a frozen OPA or Cedar
  policy that, re-evaluated, disagrees with the frozen decision), prohibited lifecycle
  action, unauthorized/self review, execution returned STALE (no action performed), or
  `pending` skipped corrupt rows.
- **2**: invalid input/usage, unreadable file, unsupported record/store schema, IO error,
  or `replay --require-reevaluation` of a record whose frozen policy could not be
  re-evaluated because `opa` or `cedar` is not on PATH. Under `--require-signature`, an
  unsigned, wrongly keyed, re-hashed or wrong-predicate record exits 1 and a bad key file
  or missing `cosign` exits 2 (see Signed records).

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

Model output is input, not authority. Only registered action types are supported
(see [Action registry](#action-registry)). Unregistered actions, mismatched tickets,
unlisted values and no-op changes are DENY. Refusal, missing probability or probability
below the threshold is ABSTAIN when hard constraints otherwise permit the action.
Review values yield REVIEW; other permitted recommendations yield ALLOW. JSON inputs are
strictly validated; no missing probability is invented.

## Action registry

`decisioncontrol.actions.ACTIONS` lists the action types a decision may request. Each
entry names the recommendation member that carries the requested value, the ticket member
the executor sets, the policy allowlist and review list, and the reason codes. Every
action runs through one evaluation pipeline, so an entry cannot skip a check:

1. a recommendation for another ticket is DENY (`ticket_mismatch`); an unregistered
   action is DENY (`action_not_permitted`);
2. a value outside the policy allowlist is DENY, and a value equal to the ticket's current
   value is DENY (no-op);
3. a model refusal, an unknown probability or a probability below `min_probability` is ABSTAIN;
4. a value on the policy review list is REVIEW; anything else permitted is ALLOW.

| Action | Recommendation member | Sets ticket member | Policy members | Reason codes |
| --- | --- | --- | --- | --- |
| `reassign_ticket` | `destination` | `department` | `allowed_destinations`, `review_destinations` | `destination_not_permitted`, `already_assigned`, `policy_permits_reassignment`, `destination_requires_review` |
| `set_ticket_priority` | `priority` | `priority` | `allowed_priorities`, `review_priorities` | `priority_not_permitted`, `priority_unchanged`, `policy_permits_priority_change`, `priority_requires_review` |

A ticket may have a `priority` (`ticket-create --priority`, absent by default); executing
`set_ticket_priority` sets it and increments the ticket revision like any other action.
`allowed_priorities`/`review_priorities` are optional in a policy; a policy without them
permits no priority change. One policy document covers every action, and the reviewers
are shared.

```bash
decision-control --db queue.sqlite3 ticket-create --ticket-id T-100 --department support --priority normal
decision-control --db queue.sqlite3 submit --proposal examples/proposal-priority.json \
  --policy examples/policy-priorities.json --proposed-by local-proposer
```

Adding an action type is one new `ActionType` entry in `actions.py` plus tests; policy,
replay and the store name no specific action. The registry is a constant rather than a
runtime `register()` because replay recomputes verdicts from it. The registry fixes the
members an action may use (`destination` or `priority` on the recommendation,
`department` or `priority` on the ticket): an action that needs a new member needs a new
record schema. Record schemas 1-4 predate the registry and keep permitting only
`reassign_ticket`; a v1-v4 reader rejects the new members. The evaluation command and
reports still score `reassign_ticket` only.

## LangGraph approvals

[`examples/langgraph/`](examples/langgraph/README.md) maps a LangGraph `interrupt()` approval
onto this workflow: a `propose` node calls `submit`, a `review` node surfaces the pending
decision with `interrupt()` and records the reviewer's `Command(resume=...)` as `approve` or
`reject`, then exports a record for `replay`. The proposer cannot approve their own REVIEW
decision, and the LangGraph thread and checkpoint ids are kept in the review note. LangGraph
is a dev-only dependency of the example (pinned in its `requirements-dev.txt`); the package
does not import it.

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
for both schemas (no tolerance). That is portable because every floating-point
operation involved is correctly rounded by IEEE 754 and so gives identical bits on
every platform: integer-to-float division (`numerator / denominator`), `+ - *` and
`/` on floats, and `math.sqrt`. `denominator ** 2` is exact integer arithmetic, and
the 95% normal quantile is a fixed literal. Nothing calls a platform-libm function
(`log`, `exp`, `erf`, float `pow`) or an inverse-CDF routine, whose last digits can
differ between libm builds. A unit test reads `evaluation.py` and fails if it uses
anything from `math` other than `sqrt` (including through `import math as m` or
`from math import ...`), imports a statistics or numeric library, calls `pow`, or uses
`**` other than `denominator ** 2`. It cannot prove types, so it does not catch a
float passed as `denominator`. The committed vectors are generated on one machine and replayed by CI on
Linux, which exercises the claim; no regeneration happens in CI. Decision records contain no derived floats
(probabilities and thresholds are copied inputs), so record replay has no
floating-point recomputation.

## Frozen OPA and Cedar decisions

A record can freeze the decision of an external policy engine next to the built-in
policy, so that a third party can check what OPA or Cedar answered and, when the engine
is installed, ask it again. The adapters are offline: they read decision logs and files,
open no network connection and run no service. `opa` and `cedar` are optional
subprocesses used only to freeze a Cedar decision and to re-evaluate on replay.

**Binding.** The frozen OPA `input` or Cedar `request` must equal the one decision-control
derives from the record's own complete proposal, ticket snapshot and proposer (one shared
function for both engines); otherwise submit and replay reject the record, so a decision
taken for another proposal, or for the same proposal against another ticket revision, cannot
be attached. "Complete" means the whole recommendation (model, question version,
probability, refusal), the whole ticket (department, revision, priority), the proposer
and the action.
`decision-control --db DB policy-input --engine opa|cedar --proposal FILE --proposed-by NAME`
prints it for a proposal against the current ticket.

* OPA input: `{"action", "proposed_by", "ticket": {...}, "recommendation": {...}}`, the
  bound document itself.
* Cedar request: principal `User::"<proposer>"`, action `Action::"<action>"`, resource
  `Ticket::"<ticket id>"`, context `{"requested": <target value>, "current": <value it
  replaces, when the ticket has one>, "proposal_sha256": <RFC 8785 SHA-256 of the bound
  document>}`. Cedar context is flat attributes for policy conditions, so the rest of the
  proposal is bound by digest. Entities are supplied by the caller and are evidence by
  digest only.

**Combining.** The external verdict does not replace the built-in policy: the record's
verdict is the more restrictive of the two (DENY, then ABSTAIN, then REVIEW, then
ALLOW), with the reasons of the winning side(s). Reviewers still come from the frozen
built-in policy. Make the built-in policy permissive to let the engine decide alone.

**OPA** (`freeze-opa`, `decisioncontrol.adapters.opa`). Run OPA as a server with decision
logs (`opa run --server --bundle DIR --set decision_logs.console=true`), query the
decision with the policy input, and freeze the log entry. The frozen block keeps the
[decision log](https://www.openpolicyagent.org/docs/management-decision-logs) members
`decision_id`, `path`, `bundles` (name to `revision`), `input`, `result` and, when
present, `timestamp` and `labels` (which carry the OPA version), plus the policy
`modules` (`.rego` sources) and root `data.json` that produced the decision, since a log
entry names a bundle revision but does not contain the bundle. Entries with `erased` or
`masked` members are refused: their input or result is no longer what OPA evaluated. If
the policy directory has a `.manifest` revision it must be one of the entry's bundle
revisions.

```bash
decision-control freeze-opa --decision-log decision-log.jsonl --decision-id ID \
  --policy-dir opa/bundle --out external.json
decision-control --db queue.sqlite3 submit --proposal proposal.json --policy policy.json \
  --proposed-by alice --external-policy external.json
```

The OPA `result` maps to a verdict: a boolean is ALLOW or DENY; an object with a `verdict`
member (`ALLOW`, `DENY`, `REVIEW` or `ABSTAIN`) and an optional `reasons` list is that
verdict (reasons are prefixed `opa:`); other shapes are rejected.

**Cedar** (`freeze-cedar`, `decisioncontrol.adapters.cedar`). The frozen block keeps the
policy set (Cedar text, or the Cedar JSON policy format with `--policy-format json`),
the `entities`, the `request` (as for `cedar authorize --request-json`), the `decision`
(`Allow` or `Deny`) and `diagnostics` in the shape of a Cedar response (`reason` lists the
determining policy ids, `errors` lists `{"policyId", "error"}`). `freeze-cedar` runs
`cedar authorize --verbose` for the decision; pass `--response FILE` (a Cedar response from
an SDK) to freeze a decision made elsewhere. Allow maps to ALLOW and Deny to DENY
(`cedar:permit:<policy id>`, `cedar:forbid:<policy id>` or `cedar:no_permit_applied`); Cedar has no
review outcome, so review requirements belong in the built-in policy.

The recorded fixtures (`fixtures/policy-engines/`) are real decisions of OPA 1.21.2 and
Cedar CLI 4.14.0 on a small ticket-routing policy; `record.py` there reruns the
recording (tool versions in `tool-versions.txt`). They exercise software behavior, not
production policies.

### Replay: re-evaluation and digest-only

`replay` always checks the record checksum, `policy_sha256`, `external_policy_sha256`,
the binding above, the mapped external decision and the recomputed verdict. It then
**re-evaluates the frozen policy** when the engine is installed:

* OPA: `opa eval` over the frozen modules, data and input at the logged `path`, in a
  temporary directory with the `http.send`, `net.lookup_ip_addr` and `opa.runtime`
  built-ins removed, so a frozen policy cannot reach the network or the environment. The
  result must equal the frozen `result`. Re-evaluation needs an OPA that accepts the
  frozen Rego (v1 syntax for OPA 1.x) and a deterministic policy.
* Cedar: `cedar authorize` over the frozen policies, entities and request. The decision,
  the determining policy ids and the policies that errored must equal the frozen ones.

A policy that the engine rejects, or that gives another result, exits 1. The result gains
`external_policy` with `verification: "reevaluated"` and the tool version.

When `opa` or `cedar` is **not on PATH**, replay is **digest-only**: the digests, binding
and mapping above are verified, the policy is not run, and the result says
`"verification": "digest-only"` and stderr says
`decision-control: policy NOT re-evaluated (opa was not found on PATH); digest-only verification of the frozen opa decision`.
The exit code is still **0**, because a missing optional tool is not evidence of
tampering. Pass `--require-reevaluation` to exit **2** instead (nothing on stdout) when a
frozen policy could not be re-evaluated; it has no effect on records without a frozen
external decision, whose built-in policy replay always recomputes. Exit 2 is the
code of this CLI for "could not complete the requested check"; exit 1 stays reserved for
evidence that is wrong.

What each mode catches: an edit of the frozen input or result with a stale checksum
or stale `external_policy_sha256` fails in both modes, as does an edit that makes the input
not describe the proposal or the result not match the recorded verdict. An edit of the frozen
policy source (a Rego module or Cedar policy) with recomputed digests is invisible to
digest-only verification, and re-evaluation catches it **only when the evaluated outcome
changes**: a policy edit that still yields the frozen result passes. Metadata that does not
affect evaluation (an OPA `decision_id`, `timestamp` or `labels`, bundle names and revisions,
Cedar entities that no policy reads) can be edited with recomputed digests and still pass in
both modes. Recomputed digests are not signatures: only `replay --require-signature`
(see Signed records) ties the whole file to a key holder; see the trust boundary below.

## Record schema v5 (v1-v4 readable)

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
Schema 4 differs from schema 3 only in canonicalization: the record `sha256` and
`policy_sha256` are digests of RFC 8785 (JCS) canonical bytes, and replay rejects
duplicate object keys (exit 2). New decisions use `schema_version: 5`, which keeps
schema 4's canonicalization and adds the [action registry](#action-registry) (optional
ticket `priority`, optional policy `allowed_priorities`/`review_priorities`, and a
`priority` recommendation member for `set_ticket_priority`) and two required members:
`external_policy` (a frozen OPA or Cedar decision, or `null`) and
`external_policy_sha256` (the JCS digest of `external_policy`, `null` exactly when it is).
Schema 4 and earlier readers reject these members. JCS writes
a whole-number float such as `1.0` as `1`, so never rely on the int/float
distinction in records; integers beyond 2^53-1, NaN/Infinity and unpaired surrogates
exit 2. A CANCELLED event has `event`, `at`, `reviewer` and `note` fields.
Other event shapes remain unchanged.

Archived v1-v4 evidence and stored decisions remain valid under their original
rules: v1/v2 have no proposer separation check, and v1-v3 digest Python sorted
compact JSON (see below). They do not gain invented identity provenance on replay.
Existing stored v3 and v4 decisions keep their version (including after `approve` or
`cancel`); only new submissions are v5. Cancelling a stored v1 decision explicitly promotes that record
to v2, preserving its inputs and prior approval. Unknown schema versions are
rejected (exit 2) rather than silently reinterpreted. Policy-evaluation reports use
their own schema (1 or 2, above).

### JSON Schemas and conformance vectors

Every record and evaluation version the readers accept has a JSON Schema 2020-12
file shipped as package data: `decisioncontrol/schema/record.v{1,2,3,4,5}.json` and
`evaluation.v{1,2}.json`. They describe the exported envelope (`record`/`report` plus
`sha256`), state the canonicalization and the covered fields in `$comment`, and set
`additionalProperties: false` where the readers reject unknown keys. A schema cannot
express the replay rules (recomputed verdict, lifecycle, reviewer authorization, the
per-action recommendation member, the input/request binding, re-evaluation);
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

## Signed records

A checksum is recomputable by anyone who edits a record. A signature binds a record
file to a secret key (HMAC) or to a signer identity (Sigstore), so an edited and
re-hashed record fails verification. The signed subject is the SHA-256 of the
**exact bytes of the exported file** (re-formatting the file breaks the signature),
wrapped in an in-toto Statement v1 inside a DSSE envelope. The predicate type is
`https://github.com/BichengWang/ai-decision-system/predicate/decisioncontrol/<record|evaluation>/v<N>`
for the file's schema version `N`, with predicate `{"schema": "<the schema $id>"}`, so
an evaluation signature cannot vouch for a record or a different schema version.

```bash
decision-control keygen signing.key            # 32 random bytes as hex, mode 0600, never overwrites
decision-control demo --out out --sign-key signing.key        # out/record-*.json.dsse.json
decision-control evaluate --cases CASES --policy POLICY --out out --sign-key signing.key
decision-control --db queue.sqlite3 export ID --out record.json --sign-key signing.key   # record.json.dsse.json
decision-control replay --record record.json --require-signature --key signing.key
decision-control replay-evaluation --record out/evaluation.json --require-signature --key signing.key
```

`--sign-key` is available on `demo`, `evaluate` and `export` (which needs `--out`,
because the signature covers the file). The key is read before anything is written, so
a bad key exits 2 and leaves no output. The envelope is `<file>.dsse.json` next to the
record; `--signature ENVELOPE` selects another. Without `--require-signature`,
`replay` and `replay-evaluation` behave exactly as before and ignore envelopes.
With it, the signature is checked first (the file bytes are read once), then the normal
replay runs:

| Situation | Exit |
| --- | --- |
| Unsigned (no envelope), wrong key, record edited and re-hashed, wrong predicate type, malformed envelope or Sigstore rejection | 1 |
| Missing/short/non-hex key file, `cosign` not installed, conflicting or incomplete flags | 2 |

**Sigstore.** `decision-control predicate --record record.json --out pred.json` writes
the predicate and prints its type. Sign with an external `cosign`, for example keyless
in GitHub Actions (`permissions: id-token: write`):

```bash
cosign attest-blob --yes --predicate pred.json --type "$PREDICATE_TYPE" \
  --bundle record.json.sigstore.json record.json
decision-control replay --record record.json --require-signature \
  --sigstore-bundle record.json.sigstore.json \
  --certificate-identity "$SIGNER_IDENTITY" --certificate-oidc-issuer https://token.actions.githubusercontent.com
```

The certificate identity includes the signing ref, for example
`https://github.com/OWNER/REPO/.github/workflows/decision-control-ci.yml@refs/heads/main`
(a pull request signs as `@refs/pull/N/merge`); verifying a record signed on another ref
needs exactly that identity. The verifier hands `cosign` a private copy (mode 0600, in a
fresh temporary directory) of the same bytes it parses and replays, so swapping the file
mid-verification cannot make the two disagree.

Verification shells out to `cosign verify-blob-attestation`; the package never signs
with Sigstore and has no dependency on it. CI exercises this keylessly in a
`sigstore` job (skipped for fork and Dependabot pull requests, which get no OIDC token).

**Key handling.**
- *Generate and store:* `keygen` creates the key file with mode 0600 and refuses to
  overwrite. Keep keys outside the repository and out of backups you do not trust;
  anyone who reads the key can sign anything.
- *Rotate:* make a new key (a new `hmac-sha256:` key id, shown by `keygen` and written
  in each envelope) and sign new records with it. Keep old keys to verify old envelopes.
- *What HMAC proves:* the signer held the shared secret. It is not an identity, and
  every verifier holds the same key and so could also sign. For a public or
  attributable identity use Sigstore.
- *Sigstore trade-off:* keyless signing writes the signer identity and the record
  digest to the public Rekor transparency log, permanently. Do not use it for private
  decisions.

Signatures do not make the inputs true: they show who attested to the file, not that
the proposer, reviewer or model labels inside it are authentic. Synthetic demo
records signed in CI are software checks, not adoption evidence.

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
  record v4 and v5 and evaluation v2 use RFC 8785 (JCS) via the bundled `decisioncontrol.jcs`;
  older schemas use `json.dumps` with sorted keys, `separators=(",", ":")`,
  `ensure_ascii=False`, UTF-8. Digests are lowercase hexadecimal SHA-256. Replay neither calls a model nor executes an action. Checksums are not signatures:
  attackers can recompute them. Records are not provider attestations, identity
  proof, calibrated model evidence or proof of outside-world execution.
* Protect database files, exports and notes using operating-system permissions;
  they can contain sensitive ticket metadata. Avoid untrusted database/JSON files
  and unbounded inputs. See [SECURITY.md](SECURITY.md).

* A frozen OPA or Cedar decision is evidence of what the engine answered for the frozen
  policy and input, not of that policy's quality or provenance. Without re-evaluation the
  policy source is attested only by the digests, which an attacker can recompute; with it,
  only by the installed engine's agreement. The caller, not decision-control, authenticates
  whoever ran the engine, and Cedar entities are not checked against any source of truth.

SQLite store schema 2 is stamped in `PRAGMA user_version`. Store schema 1 databases
(0.1.0) are upgraded in place on open: a nullable `priority` column is added to `tickets`
and existing rows and records are unchanged, but 0.1.0 then refuses the upgraded
database. Legacy unversioned stores are accepted and stamped; newer unknown
store versions are refused before creating tables. Journal mode is unchanged.

## Development

```bash
python -m unittest discover -s tests
```

Schema validation tests need the dev-only `jsonschema` package and skip when it is
absent; CI installs pinned versions (see `decision-control-ci.yml`) and also checks
that the records written by `decision-control demo` validate against the shipped
schemas. The re-evaluation tests need `opa` and `cedar` on PATH and skip otherwise; the
digest-only tests run everywhere. The LangGraph example test (`tests/test_langgraph_example.py`)
needs the pinned `examples/langgraph/requirements-dev.txt` and skips without it; CI installs it
and sets `DECISION_CONTROL_REQUIRE_LANGGRAPH=1` so a missing install fails. CI runs the suite twice, first with neither tool and
then with the pinned OPA 1.21.2 and Cedar CLI 4.14.0 release binaries (checksum
verified) and `DECISION_CONTROL_REQUIRE_POLICY_TOOLS=1`, which makes a missing tool
fail instead of skip. To refresh the OPA and Cedar fixtures run
`python3 fixtures/policy-engines/record.py` with both tools installed, then
`python3 conformance/generate.py`.

The package has no runtime dependencies or sibling-project imports. Setuptools is
an installation/build dependency. Repository CI uses the registered
`decision-control-ci.yml`; [CONTRIBUTING.md](CONTRIBUTING.md) describes scope.
[CHANGELOG.md](CHANGELOG.md) records changes. New project code is licensed under
[MIT](LICENSE); this does not relicense RELIA or any other component.

## Verification status

Behavioral tests cover restart-safe review, concurrent local execution, rollback,
stale decisions, separation of duties, corrupt queue rows, idempotent rejection,
retryable output failures, v1-v5 replay, the action registry, frozen OPA and Cedar
decisions (digest-only, and re-evaluated when the tools are installed), RFC 8785 test
vectors and every conformance vector. CI builds and validates the wheel, installs it into a fresh environment, then
runs demo, decision replay, an adverse fixture evaluation, evaluation replay, a rejected
self-approval, a `set_ticket_priority` decision, digest-only replay of a frozen OPA
decision, the packaged schemas and the conformance vectors outside the source tree. These are software checks on hand-authored fixtures, not live-model,
calibration, adoption or production evidence. PyPI publication is a separate step.
