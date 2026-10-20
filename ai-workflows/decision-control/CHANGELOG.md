# Changelog

All notable changes to this project are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Signed records (P-012): `keygen`, `--sign-key` on `demo`, `evaluate` and `export`, and
  `--require-signature` (`--key [--signature]` or `--sigstore-bundle` with
  `--certificate-identity` and `--certificate-oidc-issuer`) on `replay` and
  `replay-evaluation`. HMAC-SHA256 DSSE envelopes (`<file>.dsse.json`) carry an in-toto
  Statement v1 whose subject is the SHA-256 of the exact file bytes; the predicate type
  names the record kind and schema version. Sigstore signing is external `cosign`;
  verification delegates to `cosign verify-blob-attestation`. `predicate` writes the
  predicate for `cosign attest-blob`. Unsigned, wrong key, edited-and-re-hashed or wrong
  predicate type exit 1; bad key file or missing `cosign` exit 2. Behavior without the
  flag is unchanged. CI signs a demo record keylessly and verifies it with the package;
  the wheel smoke check round-trips an HMAC signature.
- Action registry (`decisioncontrol.actions.ACTIONS`): `reassign_ticket` moved into it and
  `set_ticket_priority` added through it only. Tickets gain an optional `priority`
  (`ticket-create --priority`), policies optional `allowed_priorities` and
  `review_priorities`, recommendations a `priority` member for the new action. All
  actions share one evaluation pipeline and executor; replay and the store name no action.
- Exported record schema 5 (RFC 8785, like schema 4) with the registry members and two
  required members, `external_policy` and `external_policy_sha256` (null without an
  external decision). JSON Schema `record.v5.json`.
- Policy adapters (`decisioncontrol.adapters.opa`, `.cedar`) that freeze an OPA decision
  log entry (`decision_id`, `path`, bundle revisions, input, result, plus the Rego modules and
  data) or a Cedar authorization (policies as text or JSON, entities, request, decision,
  diagnostics) into the record. CLI: `freeze-opa`, `freeze-cedar`, `policy-input`,
  `submit --external-policy`. The frozen input or request must equal the one derived from
  the record's recommendation, ticket and proposer; the external verdict is combined with
  the built-in policy by taking the more restrictive one.
- `replay` re-evaluates a frozen policy with `opa eval` or `cedar authorize` when the tool is
  on PATH (OPA with `http.send`, `net.lookup_ip_addr` and `opa.runtime` removed), exiting 1 on
  disagreement. Without the tool the verification is digest-only, exits 0 and prints
  `policy NOT re-evaluated` on stderr; `replay --require-reevaluation` exits 2 instead.
  The replay result gains `external_policy` for such records.
- Recorded OPA 1.21.2 and Cedar CLI 4.14.0 decisions (`fixtures/policy-engines/`, with
  `record.py` and `tool-versions.txt`) and 42 schema 5 conformance vectors (valid, tampered, invalid), eight of the valid ones
  built from them.
- CI installs checksum-verified OPA and Cedar CLI release binaries, runs the suite with
  and without them and replays the fixtures re-evaluated and digest-only.
- Exported record schema 4 and `evaluation.json` schema 2: checksums (and the record
  `policy_sha256`) are SHA-256 of RFC 8785 (JCS) canonical bytes, via the bundled
  standard-library `decisioncontrol.jcs` (vectors in `tests/jcs_vectors.json`).
  Replay of schema 4/2 rejects duplicate object keys, non-finite numbers, integers
  beyond 2^53-1 and unpaired surrogates (exit 2).
- JSON Schema 2020-12 files for record v1-v4 and evaluation v1-v2, shipped as package
  data under `decisioncontrol/schema/`.
- Conformance vectors with `manifest.json` and a deterministic generator under
  `conformance/`: valid, tampered (including recomputed-checksum self-approval and
  frozen-policy edits) and invalid vectors for every supported schema version.
- CI validates `decision-control demo` and `evaluate` output against the shipped
  schemas with pinned dev-only `jsonschema`, runs the vectors, and the wheel smoke
  check verifies packaged schemas and replays the vectors with the installed script.
- `evaluate_cases(..., schema_version=2)` selects the report schema.

### Changed
- New decisions are stored as schema 5 and new evaluations as schema 2
  (separation-of-duties rules unchanged since schema 3).
- SQLite store schema 2 adds a nullable `tickets.priority` column; a store schema 1
  database is upgraded in place on open, after which 0.1.0 refuses it.
- The conformance vector `invalid/record-v4-unsupported-schema-version.json` now sets
  `schema_version` to 6, since 5 is a supported version.
- Schema 4 and earlier records are unchanged: they still replay under their original rules, keep
  `reassign_ticket` as the only action and reject the schema 5 members. `evaluate` and its
  reports still score `reassign_ticket` only.
- Stored schema 3 and 4 decisions keep their schema through review, cancellation and
  export; records and reports of earlier schemas stay readable and verifiable under
  their original canonicalization.
- A record or report with an unsupported or non-integer `schema_version` now exits 2
  before its checksum is examined (previously a bad checksum could exit 1 first).

## [0.1.0] - 2026-10-13

### Added
- Independent standard-library SDK, console CLI and module entry point for local
  ticket reassignment; strict policy/recommendation inputs and ALLOW/REVIEW/DENY/ABSTAIN.
- SQLite frozen decisions, durable review, revision conflicts, atomic idempotent
  local execution, and authorized pre-execution cancellation preserving approvals.
- Checksummed decision export and non-executing semantic replay; credential-free
  demo with hand-authored inputs, reopened approval and real local queue changes.
- Independently labeled policy evaluation, exposure-specific metrics, Wilson
  intervals, explicit sample/metric gates, frozen JSON/Markdown evidence and replay.
  Missing exposure cannot pass; ungated reports are not approvals.
- Adverse synthetic evaluation fixtures, concurrency/rollback regressions and
  Python 3.11/3.13 CI with installed-wheel lifecycle and evaluation smoke checks.
- Release metadata, dynamic package version, MIT SPDX license and project links.
- SQLite store schema 1 stamp and refusal of newer unknown database versions.

### Changed
- New decision records use schema 3 with required proposer identity, producer
  metadata and canonical policy digest. V1/v2 replay retains historical rules;
  cancelling a stored v1 decision promotes it to v2, preserving prior approval.
- Replay mismatches exit 1; malformed input and unsupported schemas exit 2.
- Demo, evaluation and file export publish complete staged outputs atomically.

### Fixed
- Corrupt pending rows no longer block valid queue entries; SDK diagnostics and
  CLI warnings expose skipped rows (exit 1).
- Identical rejection retries return the immutable recorded rejection.
- CLI execution of a stale decision exits 1 because no action was performed.

### Security
- Schema 3 REVIEW proposers cannot approve, reject or cancel their own decisions.
  Identities remain caller-asserted labels, not authentication; hashes detect
  change, not forgery. Local atomicity does not cover external actions.
- No provider calls, external executor, signed attestation or RELIA integration.
