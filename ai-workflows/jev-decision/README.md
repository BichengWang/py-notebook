# Jev decision model (`jevdecision`)

The core decision model for this workspace. A decision model answers bounded
questions about a state with **typed answers and reported probabilities** instead of
generated text: a yes/no probability, one label from a fixed set, or a position
on an ordered scale. These can inform gating agent tool calls, routing tickets,
and triage; missing choice uncertainty never becomes permission to route.

[Jev](https://docs.typesafe.ai/api) (TypeSafe's System One model) is the default
backend. The [OpenAI Decisions API](https://developers.openai.com/api/docs/guides/decisions)
is a drop-in alternative: questions are defined once and answers come back in the
same types from either provider. The package uses only the Python standard
library, so it has no dependencies and no lockfile.

## Question types

| Type | Jev request | OpenAI request | Answer |
|---|---|---|---|
| `Noul` (alias `Predicate`) | `noul` | `predicate` | `NoulAnswer.probability`: probability of yes |
| `Choice` | `choice`, `criteria` = label → description | `choice`, `choices` = `[{value, description}]` | `ChoiceAnswer.choice`, `.probabilities` per label, `.confidence` |
| `Score` | `score`, `criteria` = ordered levels | `score`, `levels` = `[{label}]` | `ScoreAnswer.score` (probability-weighted level index), `.level`, `.probabilities` per level |

Questions are validated before anything is sent: names are unique identifiers,
instructions are non-empty, a choice has 1 to 255 options, and a score has 2 to
10 distinct levels. Responses are checked against the questions they answer.
Every question must be answered with its own type, a choice must be one of the
options, and probabilities and scores must lie in range. Anything else raises
`ResponseError`, so the application never acts on a malformed answer.

## Usage

```python
from jevdecision import Choice, DecisionModel, Noul, Score

model = DecisionModel.from_env()   # DECISION_BACKEND=jev (default) or openai

decision = model.decide(
    "Help! My payouts have been failing for 3 days.",
    [
        Noul("refund", "Is the customer asking for a refund?"),
        Choice("department", "Which team should handle this?", {
            "billing": "Payments, invoicing, refunds",
            "technical": "Bugs, outages, integrations",
            "sales": "Pricing, upgrades, new accounts",
        }),
        Score("frustration", "How frustrated is the customer?", ["Calm", "Frustrated", "Very angry"]),
    ],
)
decision["department"].choice        # "technical"
decision["frustration"].level        # "Frustrated"

# Single-question helpers
model.gate(state, refund_question, threshold=0.8)                  # bool
model.route(state, department_question, min_confidence=0.7,
            fallback="human_review")                               # label or fallback
```

`route` uses the provider's `confidence` when it returns one, otherwise the
reported probability of the chosen label. If neither is supplied, it returns
`fallback` (default `None`), even with `min_confidence=0.0`. A reported confidence
still takes precedence over a reported choice probability; neither is a calibrated
safety guarantee or a replacement for application policy.

### Choice uncertainty contract

`ask` and `decide` retain a valid choice even when its uncertainty is unknown:

- `.probabilities` contains only labels whose probabilities were actually supplied,
  in question-option order. Missing, null, or empty probability collections yield `{}`.
- `.probability` is `None` when the chosen label has no reported probability.
  A supplied `confidence` does not manufacture a choice probability.
- `.ranked()` ranks only reported probabilities. `to_dict()` preserves missing
  entries instead of fabricating a complete distribution.
- A reported `0.0` remains zero, distinct from an absent value.

**Safety correction:** earlier code fabricated probability `1.0` for a choice
without probabilities and filled omitted labels with `0.0`. Callers must use
`.probability` or `.probabilities.get(label)` and handle `None`; do not rely on
every label being present. To inspect an unscored recommendation, use `ask` or
`decide`, not a confidence-gated route with an invented probability.

## Configuration

| Variable | Backend | Meaning |
|---|---|---|
| `DECISION_BACKEND` | both | `jev` (default) or `openai` |
| `TYPESAFE_API_KEY` | `jev` | Bearer token for `https://api.typesafe.ai/v1/systemone` |
| `JEV_MODEL` | `jev` | Model route (default `jev-latest`) |
| `OPENAI_API_KEY` | `openai` | Bearer token for `https://api.openai.com/v1/decisions` |
| `OPENAI_DECISIONS_MODEL` | `openai` | Model (default `gpt-6-luna`) |

Every backend also takes `api_key`, `model`, `base_url`, `path`, `timeout`,
`max_retries`, `backoff`, `max_retry_wait`, and `transport` arguments.
`max_retries` must be a non-negative integer; zero disables retries. `backoff`
must be a finite non-negative number of seconds; zero permits immediate retries
unless `Retry-After` requests a wait. Invalid settings raise `DecisionError`
before any request is sent. Use `base_url` and `path` for a gateway
that serves Jev elsewhere, for example `path="/v1/decisions"` with
`model="typesafe/jev"`. Rate-limit (429), server (5xx), and connection errors are
retried with exponential backoff (2 retries by default). When the provider sends a
`Retry-After` header (seconds or an HTTP date), the client waits at least that long
before retrying. A provider that asks for more than `max_retry_wait` seconds (60 by
default) fails the request at once with `APIError`, whose `retry_after` attribute
carries the requested wait, instead of blocking the caller. Other HTTP errors are
raised as `APIError` immediately. `transport` is any callable
`(url, headers, body_bytes, timeout) -> dict`, which tests use to replace the
network.

The structured state can be text, a JSON object, or a list of non-empty strings. Jev
receives it unchanged. The OpenAI backend sends text, so it serializes an object
as JSON with sorted keys and joins a list with blank lines.

## Command line

From this directory, with Python 3.11 or later:

```bash
python3 -m unittest discover -s tests
python3 -m jevdecision --questions examples/support-ticket.json \
    --state "Help! My payouts have been failing for 3 days." --dry-run
python3 -m jevdecision --questions examples/support-ticket.json \
    --state-file ticket.json --backend openai
```

The questions file uses Jev's native question map
([`examples/support-ticket.json`](examples/support-ticket.json)). `predicate` is
accepted as an alias of `noul`. A `.json` state file is sent as structured
state, and any other file is sent as text. `--dry-run` prints the provider request
without sending it, so it needs no API key; the state is validated first either
way. The decision is printed as JSON. Exit codes: 0 for success, 1 for a provider
or response error, 2 for invalid input (questions, state, or a `--timeout` that is
not a positive number of seconds).

From the repository root, `make jev-test` runs the tests and
`make jev-dry-run` prints the example request for both backends.

## Evaluating a decision model

Measure the model on labeled cases before software acts on its answers.
`jevdecision.evaluation` scores every question against the expected answers and
can gate the result on thresholds you set.

A case file is JSON Lines with a state and the expected answer to some or all
questions: `true` or `false` for a `noul`, a label for a `choice`, and a level
(or its index) for a `score`:

```json
{"id": "t02", "state": "I was charged twice for March. Please refund the duplicate charge.",
 "labels": {"refund": true, "department": "billing", "frustration": "Frustrated"}}
```

| Type | Metrics |
|---|---|
| `noul` | `accuracy` (at probability 0.5), `brier`, `log_loss`, `ece`, `base_rate`, `mean_probability` |
| `choice` | `accuracy`, `brier` (summed over labels), `log_loss`, `ece` (probability of the chosen label against correctness), a confusion matrix |
| `score` | `accuracy` (nearest level), `within_one`, `mae` (in level steps) |

Every question also reports `n`, the number of cases that label it, and
`accuracy_lower` and `accuracy_upper`, the 95% Wilson score interval for
`accuracy`. With 12 cases, 11 correct answers give an accuracy of 0.917 but an
interval of [0.646, 0.985], so a gate on `accuracy_lower` asks for enough cases as
well as a high hit rate. `ece` is the
expected calibration error over ten equal-width probability bins. Log loss clips
probabilities to [1e-6, 1 - 1e-6].

Missing choice probabilities do not exclude otherwise valid answers from `n`,
accuracy, its interval, or the confusion matrix. Probability metrics require the
inputs they measure on **every scored case**, not a selectively observed subset:

- Brier score requires a reported probability for every option.
- Log loss requires the expected label's reported probability.
- ECE requires the chosen label's reported probability; provider `confidence`
  is not substituted for that probability.

If any scored case lacks a metric's required inputs, that metric is `null` in
JSON and `unmeasured` in the report. A requirement on it fails. Per-case records
retain the prediction and a null chosen probability, and raw responses remain
available for replay. Re-evaluating older responses with missing probabilities
may therefore fail gates that previously scored fabricated values. Complete
probability responses retain their previous scores.

A requirement file supplies explicit question metric bounds, each a `min` or
`max`. The overall JSON field is `status` (not a boolean `pass`):

- `PASS`: at least one valid question metric bound was supplied, and all checks pass.
- `FAIL`: an explicit metric bound or the error-rate check fails.
- `UNGATED`: all checks pass but there are no question metric bounds. Omitting
  `--require`, `{}`, `{"max_error_rate": 0}`, and `{"questions": {}}` are all
  ungated, not model-quality validation.

`max_error_rate` (default 0) bounds the share of cases whose request or response
failed; it alone is not a question gate. A failed case counts as an error, never
as a wrong answer. A bound on an unmeasured metric fails. A valid question bound
means a finite numeric `min`/`max` on a supported metric; it does not mean the
threshold is scientifically adequate. For example, an `n`-only gate checks sample
count, not accuracy. Select meaningful thresholds for the decision being made.
Malformed specs (including JSON `null`, `false`, arrays, empty per-question metric
objects and empty bounds) are invalid input, not ungated runs. In the Python
`evaluate()` API, `None` means no requirement spec. Individual requirement rows
retain boolean `pass` values; the overall report does not.

```json
{"max_error_rate": 0.0,
 "questions": {"refund": {"n": {"min": 10}, "accuracy_lower": {"min": 0.8}, "brier": {"max": 0.1}}}}
```

```bash
# Replay supplied responses: no API key; origin remains unverified
python3 -m jevdecision.evaluation --questions examples/support-ticket.json \
    --cases examples/support-ticket-cases.jsonl \
    --responses examples/support-ticket-responses.jsonl \
    --require examples/support-ticket-requirements.json --out eval-run

# Ask the provider live (needs its API key); no question bounds means UNGATED
python3 -m jevdecision.evaluation --questions examples/support-ticket.json \
    --cases examples/support-ticket-cases.jsonl --backend openai --out live-run
```

`--out` must be new or empty. Each run writes `evaluation.json` (sorted keys),
a readable `EVALUATION.md`, `responses.jsonl` with the supplied replay responses
or responses obtained through the live backend, and `cases.jsonl` with one row
per case: each labeled question's expected and predicted answer (with probability
or score) and whether it was correct, or the case's error. `EVALUATION.md` lists
the first 20 incorrect answers. Exported responses can be passed as `--responses`
to re-score without calling a provider. Identical replay question, case, response
and requirement content produces byte-identical `evaluation.json`; live-to-replay
metrics remain the same, but the report's `source` changes.

CLI runs also write a separate deterministic `provenance.json`:

- `inputs` records SHA-256 of the exact question, case, requirement and response
  file bytes read for the run, with `null` for absent optional inputs.
- `response_mode` is `live` or `replay`. Replay origin is explicitly **unverified**:
  files may be hand-written, and their `model` fields do not authenticate provider output.
- `outputs` records SHA-256 of `evaluation.json`, `EVALUATION.md`, `responses.jsonl`
  and `cases.jsonl`. The manifest does not hash itself, include timestamps, paths,
  headers or credentials, or enter the metric records. Whitespace-only input
  changes can therefore change provenance without changing `evaluation.json`.

Hashes identify bytes, not authenticity, reviewer independence or model quality.
Raw responses and labeled cases may contain sensitive material; inspect them
before sharing. `--backend` names the response format to replay (`jev` by default).
The CLI and Markdown display the same overall status. Exit codes: **0** for PASS,
**1** for FAIL or a provider that cannot be used, **2** for invalid input (which
produces no evaluation artifacts), and **3** for UNGATED.

The example responses are hand-written in Jev's response format to show the
workflow. They are not output from Jev or any other model, and the example
report says nothing about any model's quality.

From the repository root, `make jev-eval` runs the example into a temporary directory.

## Limitations

- Both provider APIs are new. The Jev request and response shapes follow
  TypeSafe's published examples. The OpenAI Decisions API is in public beta, so
  the parser accepts both its object and its list answer layouts. Recheck the
  field mapping against the provider references before you depend on it in
  production.
- Image inputs and per-request options beyond the model are not modeled yet.
- Unit tests use recorded response shapes and never call a provider.
- Only accuracy carries a confidence interval. Brier, log loss, calibration
  error and MAE are point estimates, which are noisy with a few dozen cases, so set
  `n` minimums that match the thresholds you rely on.
- A live evaluation sends one request per case, sequentially.

## Safety verification

The unknown-choice-uncertainty correction was verified with the behavioral suite
on Python 3.11 and 3.13 and fresh standalone installs on both versions. Installed
SDK calls exercised both provider formats through a local HTTP fixture: unknown
uncertainty fell back at thresholds 0 and 0.99, while reported confidence,
probability, and explicit zero retained their routing semantics.

Installed decision/evaluation CLI runs preserved unknown probabilities, retained
all labeled cases, failed unmeasured metric gates, and reproduced the failed report
byte-identically from its exported responses. This is local software verification,
not a live-provider call, calibration result, or deployment-safety claim.
