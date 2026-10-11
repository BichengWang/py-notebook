# Changelog

## 0.1.0 — Unreleased

- Independent standard-library Python SDK, installable CLI and module entry point.
- Strict recommendation/policy inputs and ALLOW, REVIEW, DENY, ABSTAIN evaluation.
- SQLite ticket queue with frozen decision snapshots, durable approval/rejection,
  revision conflict detection and atomic idempotent local reassignment.
- Exported SHA-256 evidence envelopes and non-executing lifecycle/policy replay.
- Credential-free demo with hand-authored inference inputs and actual local queue
  changes, reopened review, duplicate execution and replayed records.
- Explicit trusted-local-process limitations; no authentication, provider API,
  external executor, signed attestation or RELIA integration.
- Workspace registration and Python 3.11/3.13 CI with an installed-package demo
  and evidence replay smoke run.
- Local verification of restart-safe approval, concurrent/idempotent execution,
  transaction rollback, stale decisions and evidence corruption rejection.
- Independently labeled policy evaluation with exposure-specific safety/routing,
  review, abstention and observed approval metrics and 95% Wilson intervals.
- Explicit metric/statistic/sample-support gates; missing exposure cannot pass,
  and ungated reports do not imply approval.
- Frozen evaluation envelopes, semantic replay, JSON/Markdown reports and CLI
  gate exit codes that preserve failing evidence.
- Adverse hand-authored evaluation cases and requirements; installed evaluation
  and rejection/replay scenarios in CI, without model-quality claims.
