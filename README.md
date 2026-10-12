# Scalable AI Decision Systems

Research and experiment workspace for **AI-assisted decision making**: multi-agent reasoning, reinforcement learning, causal inference, and quantitative finance.

## Projects

Run the commands below from the repository root. The [workspace guide](ai-workflows/README.md) lists the independent projects and their own run directories.

| Project | Scope | Status and environment |
| --- | --- | --- |
| [RELIA](ai-workflows/ai-decision-reliability/README.md) | Reproducible evaluation and release controls for synthetic commerce offers and ranking | Unreleased candidate; independent Python environment and lockfile |
| [Experiment gate](ai-workflows/experiment-gate/README.md) | Ship / hold / rollback decisions for online A/B tests of decision models | Standard library only; no lockfile |
| [Jev decision model](ai-workflows/jev-decision/README.md) | Core decision model: typed decisions from Jev, or from the OpenAI Decisions API | Standard library only; no lockfile |
| [decision-control](ai-workflows/decision-control/README.md) | Policy-constrained agent actions with durable approval and replayable evidence | Standard library only; no lockfile |
| Existing `src/` research | Agents, RL, ML, finance, and study material | Research and experiments using the root environment |

[`workspace.json`](workspace.json) registers these components with their paths,
CI checks, and test commands. `make workspace-list` shows them, `make affected`
shows what your branch touches, and `make affected-test` runs those components'
tests. See the [workspace guide](ai-workflows/README.md#workspace-manifest) for
the boundary rules that `make workspace-check` enforces.

RELIA's [specification](ai-workflows/ai-decision-reliability/docs/SPEC.md),
[reproduction protocol](ai-workflows/ai-decision-reliability/docs/REPRODUCE.md),
and [limitations](ai-workflows/ai-decision-reliability/docs/LIMITATIONS.md)
define its bounded scope. Other projects are not validated RELIA integrations.
Its development and release dates are recorded independently of this repository's history.

```shell
make relia-sync
make relia-test
make relia-reproduce RELIA_OUT=/absolute/new/run-directory
```

These commands use only the project's own environment. See the
[release workflow](docs/RELIA_RELEASE.md) for project-only snapshots and their
source identity. No accepted RELIA public release is claimed yet.

The root MIT license applies to the existing research material it covers. RELIA
has a separate [licensing status](ai-workflows/ai-decision-reliability/LICENSE)
and currently grants no license; its intended Apache-2.0 release remains subject
to rights clearance.

Setup, environments, the directory layout and the decision-loop quick start for the
`src/` research material are in the [setup guide](scripts/README.md).

## Technical report and news readiness

The [author-produced portfolio report](docs/PUBLICATION_REPORT.md) documents the
four independent projects, fresh local verification, adverse outcomes, and
evidence gaps relevant to an EB-2 NIW assessment. It is not independent
recognition, a legal eligibility finding, or an accepted RELIA release.

- [News and reviewer briefing](docs/NEWS_READY.md) — attributed announcement and editorial pitch
- [Public publication record](docs/PUBLICATION_RECORD.md) — report/source identity and review status
- [Official USCIS/NIST source notes](docs/NIW_SOURCE_NOTES.md) — evidence requirements and claim limits
- [Publication protocol](docs/PUBLICATION_GUIDE.md) — reproduction, artifact integrity and rights boundaries
- [Compact local evidence summary](docs/publication/evidence-2026-10-11.json) — source and selected artifact hashes

Run the existing project workflows and retain a new external evidence directory:

```bash
uv run --no-project --python 3.11 python scripts/publication_evidence.py --out /tmp/ai-decision-evidence-new
uv run --no-project --python 3.11 python scripts/publication_evidence.py --verify /tmp/ai-decision-evidence-new
```

No provider calls are made. Fixture passes are not live-model quality, adoption,
production impact, or national-importance evidence. RELIA publication and reuse
remain subject to its separate rights/reproduction/acceptance process.
