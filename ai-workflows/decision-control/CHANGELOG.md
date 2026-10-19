# Changelog

All notable changes to this project are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
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
- New decisions are stored as schema 4 (separation-of-duties rules unchanged from
  schema 3); new evaluations are schema 2. Records and reports of earlier schemas stay
  readable and verifiable under their original canonicalization; stored schema 3
  decisions keep schema 3 through review, cancellation and export.
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
