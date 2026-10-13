# Repository delivery plan

This is the cross-repository work queue. RELIA's own [roadmap](../ai-workflows/ai-decision-reliability/docs/ROADMAP.md) remains authoritative for its research and release milestones. The scheduled delivery task turns the ready entries below into GitHub issues carrying the stable `Plan ID`, `continual-ready` label, concrete outcome, and acceptance check. It searches existing issues and PRs for that ID before creating anything, so interrupted runs do not duplicate work. An issue is closed only after its PR is verified on `main` and its acceptance check passes.

## Direction

The projects share one idea: **an AI-assisted go/no-go decision should leave a record that someone else can re-verify offline.** Each component emits such a record for a different decision point — a typed model answer (`jev-decision`), a policy-gated agent action with human approval (`decision-control`), an online-experiment promotion (`experiment-gate`), and a model release or update (RELIA). The conventions they share are written down in [DECISION_RECORDS.md](DECISION_RECORDS.md). Work is prioritized by whether it makes those records more trustworthy, easier to adopt, or better evidenced — not by surface area.

## Release 0.1 (first public packages)

| Priority | Plan ID | Outcome | Acceptance check |
| --- | --- | --- | --- |
| 1 | P-006 | Remove personal and infrastructure identifiers and third-party material from the published tree; add real security, contribution, conduct and citation files. | `git grep` finds no GCP project, instance IP, or private key path; GitHub community profile files exist; `make workspace-check` passes. |
| 2 | P-007 | `expgate`, `jevdecision` and `decisioncontrol` install from a built wheel with console scripts, SPDX license metadata, single-source versions and Keep a Changelog entries. | Each project's CI builds, runs `twine check --strict`, installs the wheel in a fresh venv and runs its console scripts against bundled examples. |
| 3 | P-008 | Close the correctness and trust defects found in the release review (experiment-gate silent keys and zero-variance guardrails; Jev refusals, fabricated score probabilities and transport errors; decision-control self-approval, queue corruption and STALE exit codes). | Each defect has a failing-before/passing-after test in its project suite. |
| 4 | P-009 | Every component's decision record is re-verifiable from the record alone (`experiment-gate-verify`, `decision-control replay`, Jev provenance, RELIA compare). | Tampering with an embedded input or outcome makes the verifier exit 1 in tests and CI. |
| 5 | P-010 | Tag-driven releases: `<component>/vX.Y.Z` builds, checks, creates a GitHub Release, and publishes to PyPI by trusted publishing once enabled. | `scripts/release.py check --tag` rejects version, changelog or license drift; the release workflow's build job passes on a dry run. |

## Next (after 0.1)

| Priority | Plan ID | Outcome | Acceptance check |
| --- | --- | --- | --- |
| 6 | P-011 | Publish JSON Schemas and conformance vectors for each record type so third parties can validate records without the Python packages. | Each project's CI validates its produced records against the committed schema; vectors include a tampered case per type. |
| 7 | P-012 | Authenticated records: optional HMAC or Sigstore/in-toto attestation over the canonical record digest. | Verification fails for a re-hashed forged record when a key or attestation is required; key handling documented. |
| 8 | P-013 | Cross-check experiment-gate statistics against reference implementations (dev-only dependencies; runtime stays standard library). | Golden-vector tests agree with the reference to a stated tolerance on proportion, mean, ratio, CUPED and sequential cases. |
| 9 | P-014 | Jev contract fixtures recorded from the live providers (refusal, 429 with Retry-After, usage). | Fixture replay passes; a key-gated live smoke test is opt-in and never runs in default CI. |
| 10 | P-015 | decision-control policy adapters: evaluate an OPA/Cedar decision and freeze it into the same evidence record. | A second action type ships only through the adapter/registry; existing replay fixtures still pass. |

## Human-gated (not automatable)

- **PyPI trusted publishing:** create a pending publisher per project (workflow `release.yml`, environment `pypi`) and set the repository variable `PYPI_PUBLISH=true`. See [RELEASING.md](RELEASING.md).
- **RELIA publication:** rights clearance, unaffiliated reproduction and maintainer acceptance under [RELIA_RELEASE.md](RELIA_RELEASE.md). Engineering work cannot substitute for these records.
- **External evidence:** independent review, real-data pilots and adoption are recorded only when they actually happen; fixtures and self-produced reports are never relabeled as such.

## Completed

| Plan ID | Outcome | Evidence |
| --- | --- | --- |
| P-001 | Exact-head reviewed merge gate and recurring controller | #133 |
| P-002 | Repository links and commands repaired after the move to `ai-workflows/` | #172, #207 |
| P-003 | Bounded, CI-checked baseline for the legacy `src/` workbench | #173, #193 |
| P-004 | experiment-gate boundary and malformed-input coverage | #135, #144, #206 |
| P-005 | RELIA ranking path routed through the input guard | #176 |

After each merge, reprioritize using review findings, CI failures, regressions, and the project's own roadmap. Add a new item only when it has an observable outcome and acceptance check. Do not subdivide work solely to reach the daily PR target.
