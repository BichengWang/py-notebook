# Awesome-list pull requests

Drafts for the owner to open. No pull request has been opened. Open each from a
fork under the owner's account, one list at a time, and log it in the
[outreach log](README.md#outreach-log).

Rules and formats below were read from each repository on 2026-10-19. Re-read
them on the day: lists change, and so can the queue in front of you.

**Not a target:** [EthicalML/awesome-production-machine-learning](https://github.com/EthicalML/awesome-production-machine-learning).
Its [CONTRIBUTING.md](https://github.com/EthicalML/awesome-production-machine-learning/blob/master/CONTRIBUTING.md)
says "Tools should have a minimum of 500 stars on GitHub", and also that tools
"must have been actively maintained within the last 12 months". This repository
does not meet the first condition (152 stars on 2026-10-18, per the
[plan](../../.plan/README.md#where-we-start)), and stars are not a target here (see
[decisions](../../.plan/decisions.md)). Do not open a PR there.

Each entry describes what the tool does and states one limit, and claims nothing
about use. Before opening any PR, confirm the repository still has the install
paths the entry implies (a clone works today; PyPI is pending as of 2026-10-19).

| List | Stars (2026-10-19) | Last push | Section | Rules source |
| --- | --- | --- | --- | --- |
| [kelvins/awesome-mlops](https://github.com/kelvins/awesome-mlops) | 5,286 | 2026-08-17 | Model Lifecycle | [CONTRIBUTING.md](https://github.com/kelvins/awesome-mlops/blob/main/CONTRIBUTING.md), [PR template](https://github.com/kelvins/awesome-mlops/blob/main/.github/PULL_REQUEST_TEMPLATE.md), [check_order.py](https://github.com/kelvins/awesome-mlops/blob/main/check_order.py) |
| [AthenaCore/AwesomeResponsibleAI](https://github.com/AthenaCore/AwesomeResponsibleAI) | 155 | 2026-09-28 | Tools > Audit | No CONTRIBUTING file; format and PR titles copied from the README and merged PRs |
| [agentrust-io/awesome-ai-governance](https://github.com/agentrust-io/awesome-ai-governance) | 60 | 2026-10-19 | Agent Action Records | [CONTRIBUTING.md](https://github.com/agentrust-io/awesome-ai-governance/blob/main/CONTRIBUTING.md) |

## 1. kelvins/awesome-mlops

**Rules** ([CONTRIBUTING.md](https://github.com/kelvins/awesome-mlops/blob/main/CONTRIBUTING.md)):

- One link per pull request. The PR title is `Add project-name`.
- Entry format: `* [project-name](http://example.com/) - A short description ends with a period.` Keep descriptions concise.
- A new section needs a description and a table-of-contents line; none is needed here.
- Search earlier pull requests and issues first (done 2026-10-19: no entry or PR for
  this repository), check spelling, remove trailing whitespace.
- CI (`validate.yml`) runs `check_order.py`, which requires entries in a section to
  be sorted case-insensitively, and a markdown link check.
- The README calls the list "A curated list of awesome MLOps tools"; the PR
  template asks two questions, answered below.

**Section:** `## Model Lifecycle` ("Tools for managing model lifecycle (tracking
experiments, parameters and metrics)"). The record is the evidence for a
promotion step in that lifecycle. `## Model Testing & Validation` is the other
plausible home; use it if you judge the fit better, and re-check the order
(`AI Decision System` sorts first there).

**Position:** between `Aeromancy` and `Aim`. I ran the list's own
`check_order.py` on a copy of its README with the line inserted there: it passes. As a
control, the same line placed after `Aim` raises "The content is not alphabetically sorted!".

**Entry:**

```markdown
* [AI Decision System](https://github.com/BichengWang/ai-decision-system) - Replayable, offline-verifiable decision records for experiment promotion, typed model answers and human-approved actions, with optional signed envelopes.
```

**PR title:** `Add AI Decision System`

**PR body** (the template's two headings):

```markdown
## What is this tool for?

Writes and re-checks decision records for go/no-go steps. `experiment-gate` turns
exported A/B aggregates into a SHIP / HOLD / ROLLBACK / INVALID record that carries
its input and frozen rules, and `experiment-gate-verify` recomputes it offline.
`jevdecision` (typed model answers) and `decisioncontrol` (human-approved actions)
do the same for their decision points. Records can be signed (in-toto Statement in
a DSSE envelope). Python 3.11+, standard library only, MIT. Not on PyPI yet:
install from the repository.

## What's the difference between this tool and similar ones?

The trackers and registries in this section record runs, parameters, metrics and
model versions. This keeps one decision's inputs and rules so a third party can
recompute it later. It does not track experiments, serve models or run
experiments, and it does not replace them. A passing check does not show that the
decision was right.
```

**Expectation:** the repository shows 87 open pull requests and the last merges on
2026-08-17, so a long wait is likely. Log "silent" only after the review date you
set in the outreach log.

## 2. AthenaCore/AwesomeResponsibleAI

**Rules:** none published. There is no CONTRIBUTING file, no pull request template and no
contribution section in the README. Follow what the README and recent merged PRs show:

- Sections are `##` headings; `## Tools` has subsections such as `### Audit`.
- Audit entries are bullets: ``- [Name](url) `Language` - description``.
  The list is not alphabetical; recent merges appended at the end.
- PR titles for merged entries read `Add <name> to Tools > Audit`
  ([#81](https://github.com/AthenaCore/AwesomeResponsibleAI/pull/81) is an example).
- 36 pull requests were open on 2026-10-19, several for the same section.

**Section:** `### Audit` under `## Tools` ("This section features tools and
libraries that help to design, implement and manage AI in a responsible way").

**Position:** append at the end of `### Audit`, after `OrcaReplay`.

**Entry:**

```markdown
- [AI Decision System](https://github.com/BichengWang/ai-decision-system) `Python` - Standard-library tools that write and re-check replayable decision records for experiment promotion, typed model answers and human-approved actions, with optional signed envelopes. A passing check does not show a decision was right or authorize anything.
```

**PR title:** `Add AI Decision System to Tools > Audit`

**PR body:**

```markdown
Adds AI Decision System to Tools > Audit: MIT-licensed, standard-library Python tools
that write decision records (input, frozen rules, result) that a third party can
recompute offline, optionally signed. Not on PyPI yet; the entry links to the
repository, where the install and verify commands are.
```

## 3. agentrust-io/awesome-ai-governance

**Rules** ([CONTRIBUTING.md](https://github.com/agentrust-io/awesome-ai-governance/blob/main/CONTRIBUTING.md)):

- Fork, add the tool in the appropriate category, submit a pull request.
- Format: `- [Name](url) - One-line description of governance-relevant functionality.` Short and neutral.
- Must be actively maintained; open source preferred; links must work.
- Does not belong: general AI/ML tools with no governance, safety or trust angle;
  unmaintained or archived tools; duplicates.
- Automation: a contributor reputation check runs when a PR opens, and external
  contributors need a named-maintainer review before merge
  ([workflows](https://github.com/agentrust-io/awesome-ai-governance/tree/main/.github/workflows)).
  Recent PRs ([#154](https://github.com/agentrust-io/awesome-ai-governance/pull/154) to [#159](https://github.com/agentrust-io/awesome-ai-governance/pull/159)) merged between about 9 hours and 2 days after opening.

**Fit:** the list is about governing AI systems that act on their own. Only
`decision-control` is close to that scope (a proposed action, a frozen policy and a
human review in one replayable record); `experiment-gate` is not. decision-control
does not call a model, and the entry says so. If you judge the fit too thin, skip
this list.

**Section:** `## Agent Action Records` ("Formats and services that record what an
agent actually did as signed receipts and public logs, which anyone can check
later, offline if needed").

**Position:** the section is alphabetical; `decision-control` goes after `Cedulon` and
before `Mandare`.

**Entry:**

```markdown
- [decision-control](https://github.com/BichengWang/ai-decision-system/tree/main/ai-workflows/decision-control) - Standard-library Python SDK and CLI that freezes a routing policy, a proposed action and a human review into a replayable record, with optional signed envelopes. Local ticket queue only: it does not call a model, authenticate people or act on external systems; identities are caller-asserted.
```

**PR title:** `Add decision-control to Agent Action Records`

**PR body:**

```markdown
Adds decision-control to Agent Action Records. It records a proposed action, the
frozen policy and the human approval as a record that can be replayed offline, and
the record can be signed (in-toto Statement in a DSSE envelope, HMAC key). MIT,
Python 3.11+, standard library only. It is a local SDK/CLI, not an identity service
or an executor, and it is not on PyPI yet; the entry links to the source.
```

## Before opening each PR

- [ ] Rules re-read; entry text still matches the format and the section still exists.
- [ ] Search the list's PRs and issues for this repository again.
- [ ] Kelvins only: re-run `check_order.py` from the list's repository on the edited README.
- [ ] Repository facts in the entry are still true (MIT; standard library only;
      install paths; the signed-record commands work on the released version).
- [ ] The repository README states PyPI availability accurately on the day.
- [ ] Log the PR link and date, then log the response and its date.
