# Decision record conventions

A decision record preserves the inputs and rules needed to re-check an AI-assisted
go/no-go outcome offline. The projects are independent packages, not an integrated
runtime. Verification checks internal consistency under the verifier's rules; it
does not authorize a deployment or authenticate an outside event.

## Encoding and integrity

For the three small packages, canonical JSON is
`json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`
encoded as UTF-8. Canonical-object digests are lowercase hexadecimal SHA-256.
A pretty-printed export envelope need not itself be canonical: its digest covers
the canonical embedded record. Jev provenance instead hashes exact input/output
file bytes, including JSONL newlines and Markdown formatting. Experiment-gate's
`DECISION.md` hashes the actual `decision.json` bytes, separately from the canonical
input digest.

Sources: [expgate records](../ai-workflows/experiment-gate/expgate/records.py),
[Jev evaluation](../ai-workflows/jev-decision/jevdecision/evaluation.py),
[decision-control evidence](../ai-workflows/decision-control/decisioncontrol/evidence.py).

## Records and checks

Commands below assume installed console scripts; module forms remain available
in each project's README. Paths denote files retained from a run.

| Component / record | Current schema; older readable forms | Embedded content | Offline check | Successful check proves |
| --- | --- | --- | --- | --- |
| experiment-gate `decision.json` | 2; schema 1 remains an inspectable JSON report, but cannot be verified because it has no input | Aggregate input and its canonical digest, policy, metrics, reasons, disposition, producer | `experiment-gate-verify decision.json` | Input digest matches; recomputed decision, policy, statistics and reasons agree under the running implementation |
| Jev typed answer (CLI JSON) | 2; schema 1 stays readable but cannot be verified; raw unversioned provider fixtures remain replayable | Typed answers/refusals, backend/model labels, response id/usage, producer, the question definitions, the raw provider response and `record_sha256` (RFC 8785 digest of the record without that member) | `jev-decision-verify answer.json` | Digest matches; re-parsing the embedded response with the embedded questions reproduces the recorded answers, refusals, id, usage and model. Schema 1 holds no response and exits 2 |
| Jev `evaluation.json`, `provenance.json`, `responses.jsonl`, `cases.jsonl`, `questions.json`, `requirements.json` | Evaluation/provenance 2; unversioned raw responses remain replayable, earlier reports remain inspectable | Metrics, bounds and PASS/FAIL/UNGATED; producer; provenance hashes exact input/output bytes; exact copies of the question and requirement files (runs from 0.1.0 lack them; labeled cases with states are external) | `jev-decision-verify --evaluation DIR` | Every file in `provenance.json` matches its hash, and re-scoring the retained responses reproduces `evaluation.json` and `cases.jsonl` offline. Hashes do not authenticate authorship |
| decision-control exported `record-*.json` | 3; 1 and 2 replay under their original rules | Recommendation, ticket snapshot, frozen policy/digest, proposer, producer, verdict, review, events, execution result; canonical record checksum | `decision-control replay --record record-review.json` | Checksum, frozen policy evaluation and lifecycle evidence agree, including schema 3 separation of duties; replay executes nothing |
| decision-control `evaluation.json` | 1; unchanged | Labeled cases, policy, requirements, exposure metrics, Wilson intervals and disposition inside a checksummed report; no producer field in this unchanged schema | `decision-control replay-evaluation --record evaluation.json` | Canonical checksum and recomputed policy-evaluation report agree |
| RELIA `results.json`, `MANIFEST.json` | Own unversioned results/manifest format with package/spec versions; comparison protocol schema 1 | Synthetic benchmark seeds, dataset digest, partitions, per-seed metrics, gates and guarded update; manifest hashes exact results bytes | From RELIA: `uv run --frozen python -m relia.compare reference/results.json new/results.json --protocol protocol.json` | Reference hash matches the predeclared protocol; exact fields and metric tolerances agree. This is comparison, not a release acceptance |

Implementation authorities: [expgate verifier](../ai-workflows/experiment-gate/expgate/verify.py),
[Jev answers](../ai-workflows/jev-decision/jevdecision/answers.py),
[Jev replay](../ai-workflows/jev-decision/jevdecision/evaluation.py),
[decision-control evaluation](../ai-workflows/decision-control/decisioncontrol/evaluation.py),
[RELIA run](../ai-workflows/ai-decision-reliability/relia/run.py) and
[comparison](../ai-workflows/ai-decision-reliability/relia/compare.py).
RELIA uses indented JSON and byte hashes, not the shared compact canonical encoding.
Its machine-dependent `runtime.json` is outside the reproducible results/manifest
claim. It remains unreleased under [its human-gated process](RELIA_RELEASE.md).

## Exit codes

Shared meaning: **0** success / accepted check; **1** completed but not accepted
(or action not performed); **2** invalid input, usage or unreadable file;
**3** ran without explicit question metric gates (Jev evaluation only).

| CLI | Actual outcomes |
| --- | --- |
| `experiment-gate` | 0 after writing valid reports, including HOLD/ROLLBACK/INVALID; 1 only when `--require-ship` is supplied and any result is not SHIP; 2 input/output error |
| `experiment-gate-verify` | 0 agreement; 1 mismatch; 2 malformed, unreadable, unsupported or unverifiable legacy record |
| `jev-decision` | 0 answer/dry run; 1 refusal, provider failure or response that cannot be recorded canonically; 2 input/usage error |
| `jev-decision-verify` | 0 agreement; 1 mismatch or tampered retained file; 2 malformed, unreadable, unsupported or unverifiable (schema 1) record |
| `jev-decision-eval` | 0 PASS; 1 FAIL/provider errors; 2 input/output error or live 401/403; 3 UNGATED |
| `decision-control` | 0 successful command, including descriptive UNGATED evaluation; 1 blocked lifecycle, STALE execution, skipped corrupt pending rows, failed evaluation or replay mismatch; 2 malformed/unsupported input or I/O error |
| `relia.compare` | 0 comparison passes/template written; 1 comparison differs; 2 usage, unreadable or invalid protocol |

Sources: [expgate runner](../ai-workflows/experiment-gate/expgate/run.py),
[Jev CLI](../ai-workflows/jev-decision/jevdecision/__main__.py),
[decision-control CLI](../ai-workflows/decision-control/decisioncontrol/cli.py).
Reading a valid report or replaying a FAIL outcome is distinct from accepting its gate.

## Compatibility and limits

Breaking record changes require a new integer schema version. Preserve currently
supported readers and replay rules; reject unknown schemas rather than silently
reinterpret them. Historical records cannot gain missing inputs or identity
provenance. The exceptions above describe today's actual compatibility boundary.

Digests detect change, not forgery or authorship: someone who edits an input can
recompute its hash. Producer, model, proposer and reviewer identities are supplied
metadata or caller-asserted labels. No record authenticates provider origin.
Hand-written/synthetic fixtures establish software behavior, not live-model quality,
calibration, adoption or production safety. RELIA gates are proposed engineering
thresholds, not industry/government standards or evidence of commercial performance,
fairness, legal compliance or consumer benefit.

Next: [P-011 and P-012](../.plan/phase-1-records-spec.md) cover JSON Schemas with
conformance vectors and optional authenticated records, respectively.

Regulatory provisions: a draft [mapping of these records to EU AI Act logging and retention duties, ISO/IEC 42001 A.6.2.8 and NIST AI RMF MANAGE 4.1](REGULATORY_MAPPING.md) makes no compliance claim and is not legal advice.
