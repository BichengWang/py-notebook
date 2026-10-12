# Scalable AI Decision Systems

A research and development workspace for **AI-assisted decision making**: typed model answers, policy-constrained actions, experiment decisions, and reproducible reliability evaluation, alongside agents, reinforcement learning, causal inference, and quantitative-finance experiments.

This is a **multi-component repository, not one deployable decision system**. Projects under `ai-workflows/` run independently; the older `src/` workbench uses the root environment. A component's software checks or example results do not establish live-model quality, production safety, or validation of the other components.

## Choose a component

| Project | Use it for | Status and environment |
| --- | --- | --- |
| [RELIA](ai-workflows/ai-decision-reliability/README.md) | Synthetic commerce offer/ranking evaluation: calibration, input and policy guards, drift, release gates, and guarded updates | Unreleased reference candidate; Python 3.13, independent environment and lockfile; no current license grant |
| [Experiment gate](ai-workflows/experiment-gate/README.md) | Turn aggregate online A/B-test summaries into SHIP / HOLD / ROLLBACK / INVALID records | Python 3.11+; standard library only, no lockfile; evaluates summaries, does not run the experiment or deploy a model |
| [Jev decision model](ai-workflows/jev-decision/README.md) | Request typed yes/no, choice, and score answers from Jev or the OpenAI Decisions API; evaluate labeled cases | Python 3.11+; standard library only, no lockfile; live requests require provider credentials; examples use hand-written responses |
| [decision-control](ai-workflows/decision-control/README.md) | Apply routing policy, persist human review, reassign local tickets in SQLite, and replay evidence | Python 3.11+; standard library runtime, no lockfile; local SDK/CLI, not an external-action or identity service |
| [Research workbench](scripts/README.md) | Explore agents, RL, ML, finance, utilities, and study material in `src/` | Root research environment; Python 3.10+ metadata, Python 3.11 for the pinned baseline; script-specific dependencies and services |

The [workspace guide](ai-workflows/README.md) explains project directories and boundary rules. Do not merge project dependencies into the root environment or assume these projects form a validated integration. RELIA's development and release dates are recorded independently of this repository's history.

## Get started

Run the commands below **from the repository root**, unless a subshell explicitly changes directory. Choose one component rather than installing every environment.

### Credential-free workflows

With Python 3.11+ available as `python3` and `make` installed, these projects run from source without a root dependency install:

```shell
# Check the independent standard-library projects.
make workspace-test COMPONENTS="experiment-gate jev-decision decision-control"

# Inspect both provider request formats without sending a request.
make jev-dry-run

# Score the bundled hand-written responses; prints EVALUATION.md.
make jev-eval

# Generate the experiment-gate scenario decision records.
make expgate-run EXPGATE_OUT=/tmp/experiment-gate-run

# Persist local ticket actions, then replay the exported review record.
(cd ai-workflows/decision-control && \
  python3 -m decisioncontrol demo --out /tmp/decision-control-demo && \
  python3 -m decisioncontrol replay --record /tmp/decision-control-demo/record-review.json)
```

Use new or empty output directories; change the example `/tmp/` paths if they already contain a run. Experiment gate writes `decision.json` and `DECISION.md` per scenario; decision-control writes a SQLite queue, records, and `summary.json`. The Jev evaluation and decision-control demo use **hand-authored fixtures**, not live-provider measurements.

For real inputs, installation, SDK usage, credentials, and evaluation requirements, use the component READMEs above. Live Jev calls need `TYPESAFE_API_KEY`; the OpenAI backend needs `OPENAI_API_KEY`. Provider-reported confidence is not a calibrated safety guarantee.

### RELIA: frozen synthetic evaluation

Install [uv](https://docs.astral.sh/uv/getting-started/installation/). RELIA declares Python 3.13 and pins 3.13.7 for candidate reproduction; its own metadata and lockfile are the dependency authorities.

```shell
make relia-sync
make relia-test
make relia-reproduce RELIA_OUT=/tmp/relia-reproduction
```

These targets use only RELIA's project environment. For reproduction, the absolute output directory **must not exist**, and its parent must exist. The helper performs frozen setup, the full suite, and two fresh benchmark runs, retaining logs and artifacts. It does not complete the separate stored-reference comparison or reviewer attestations.

Read the [specification](ai-workflows/ai-decision-reliability/docs/SPEC.md), [reproduction protocol](ai-workflows/ai-decision-reliability/docs/REPRODUCE.md), and [limitations](ai-workflows/ai-decision-reliability/docs/LIMITATIONS.md) before interpreting results. Synthetic results do not establish real-world commercial performance, fairness, legal compliance, or consumer benefit; release thresholds are proposed engineering gates, not industry or government standards.

**No accepted RELIA public release is claimed.** See the [release workflow](docs/RELIA_RELEASE.md) for project-only snapshots, source identity, and the separate rights-review, reproduction, and acceptance steps. A successful local export or test run is not release acceptance.

### Existing `src/` research

Use the [research setup guide](scripts/README.md) for environment choices, directory navigation, and decision-loop examples. The root [`pyproject.toml`](pyproject.toml) describes the research package (`py-notebook`), not the independent projects.

For the limited, service-free research baseline, use Python 3.11 because the pinned pandas 1.5.3 has no wheels for Python 3.12+:

```shell
python3.11 -m venv venv
source venv/bin/activate
python -m pip install -c requirements.txt pytest pytest-custom-exit-code flake8 pandas tabulate
make test
```

`make test` cleans generated test artifacts, lints the baseline, and runs tests in `tests/` and `src/lc/`; it is **not a repository-wide validation**. Broker integration, browser automation, and ML environment probes require their own services or environments and are excluded from that baseline. Broader notebook and agent setup is separate.

## Workspace navigation and validation

[`workspace.json`](workspace.json) registers component ownership, paths, environments, CI checks, and test commands. The workspace tool itself uses only the Python standard library.

```shell
make workspace-list
make workspace-check
make affected BASE=origin/main
make affected-test BASE=origin/main
```

- `workspace-list` shows component names, paths, and CI checks.
- `workspace-check` runs workspace-tool tests and checks registry/CI consistency, import boundaries, and local Markdown links. It does not run every component's behavioral suite.
- `affected` reports components selected by changes against the specified Git base; use an available base ref if `origin/main` is not present.
- `affected-test` runs those components' registered tests, so prepare their environments first. To select explicitly, use names from `workspace-list`, for example `make workspace-test COMPONENTS="decision-control"`.

See the [workspace manifest guide](ai-workflows/README.md#workspace-manifest) for routing details and the [root Makefile](Makefile) for convenience targets. Component READMEs remain the authority for project-specific commands and limitations.

## Licensing

The root [MIT license](LICENSE) applies to the existing research material it covers; check component-specific licensing before reuse. RELIA has a separate [licensing status](ai-workflows/ai-decision-reliability/LICENSE): it currently grants **no license**, and the root MIT license does not grant rights to it. Its intended Apache-2.0 release remains subject to rights clearance.

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
