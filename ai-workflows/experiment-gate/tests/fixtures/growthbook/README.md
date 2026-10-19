# GrowthBook results fixtures (synthetic data)

Raw experiment-results exports captured from a **throwaway, self-hosted GrowthBook 5.1.0** on
**2026-10-19**, used by `tests/test_growthbook.py` to test `experiment-gate --from growthbook`.

**The data is synthetic.** The instance's warehouse was a Postgres container seeded by
[`capture/seed.sql`](capture/seed.sql) with generated exposure and conversion events for generated user ids
(each draw is an `md5` hash of the experiment, user and a salt, so the data is deterministic). Nobody used
a product, no model was involved, and the effect sizes were chosen by the author of the seed to produce the
three cases below. These files are **software-behavior evidence only**: they show the field names, types
and semantics of a real GrowthBook export and that the importer handles them. They are not evidence about any
real experiment, user population, model or effect.

## Files

| File | What it is |
|---|---|
| `ranker-v2.results.json`, `ranker-v3.results.json`, `ranker-v4.results.json` | Unmodified bodies of `GET /api/v1/experiments/{id}/results` (`getExperimentResults`), one per experiment, saved byte for byte. Do not reformat them: the record keeps the SHA-256 of these exact bytes |
| `fact-metrics.json` | Body of `GET /api/v1/fact-metrics` on the same instance: each metric's `metricType` and `inverse`, which the results export lacks |
| `instance.json` | Body of `GET /` on the API port (`build.sha`, `build.date`, `lastVersion`) |
| `mapping.json` | The mapping file for the importer: type, direction and guardrail margin per `metricId` (the ids are this capture's) |
| `capture/` | Dev-only capture stack and script (below). Not used by tests and not shipped |

SHA-256 of the committed files:

```text
df94337d65269053caffb498384d11d3fea069b09ed1c12469bf2cff54eec122  ranker-v2.results.json
8a2f39b790a0c6834b2dd2e5e3eeec8fc958fa8c3998bcdd9f13c57ae348bba8  ranker-v3.results.json
b0904abcd701b63dcf46534e0d378e7eb29817ddc48dd57453ccc7c8b6fec636  ranker-v4.results.json
```

## The three experiments

Each has 20,000 units per variation (`Control`, `Candidate`, a 50/50 split), one goal metric
(`Purchase rate`, proportion), three guardrails (`Refund rate`, proportion, inverse; `Page load ms`,
mean, inverse; `Average order value`, ratio, increase) and one secondary metric (`Revenue per user`, mean,
not imported). `mapping.json` sets guardrail margins of 0.005 (refund rate), 4 ms (page load) and 1.5
(average order value); those margins are the author's choice for the test, not GrowthBook output.

| Experiment | GrowthBook engine | GrowthBook's own numbers | GrowthBook reading | expgate decision |
|---|---|---|---|---|
| `ranker-v2` | Bayesian | Purchase rate 0.1035 to 0.1189, chance to beat control 0.999998; no guardrail worse | SHIP | SHIP (agree) |
| `ranker-v3` | Frequentist | Purchase rate 0.0993 to 0.1122, two-sided p 8.5e-5; page load +1.75 ms, two-sided p 0.146 | SHIP | HOLD: page load's one-sided upper degradation bound (4.31 ms) is not below its 4 ms margin, so non-inferiority is not shown |
| `ranker-v4` | Frequentist | Purchase rate 0.0971 to 0.1023, two-sided p 0.0909 (interval includes 0) | HOLD | SHIP: expgate's one-sided test at alpha 0.05 gives p 0.0413 and every guardrail is non-inferior |

"GrowthBook reading" is the importer's reading of those numbers (see the README), not a verdict
GrowthBook computed. All three experiments have `regressionAdjustmentEnabled` and `sequentialTestingEnabled`
false (the importer rejects exports where either is true).

## Provenance

| | |
|---|---|
| GrowthBook | `growthbook/growthbook:5.1.0`, `growthbook/growthbook@sha256:c8a124f55dca3b2e2ecc3f316c28e5cbe960f1e2988541e3ce30a5b3ed7ab003` (linux/arm64); the instance reports build `7cbc85d1d113595757f6808b5c440657e4325b47`, 2026-09-22 (`instance.json`) |
| MongoDB | `mongo:7.0.14`, `mongo@sha256:0032d2ca20db5fa34926f196c8a43b74e34ed239a7f2453ff1505b6f12ba8ea6` |
| Warehouse | `postgres:16.4`, `postgres@sha256:e62fbf9d3e2b49816a32c400ed2dba83e3b361e6833e624024309c35d334b412` |
| Host | macOS on arm64, colima 0.10.3 (Docker engine 29.5.2), `docker-compose` 5.6.0 |
| Docs read first | [Self-hosting](https://docs.growthbook.io/self-host), [API introduction](https://docs.growthbook.io/api/introduction), the published [`openapi.yaml`](https://docs.growthbook.io/openapi.yaml), and the 5.1.0 instance's own `GET /api/v1/openapi.yaml`, whose `ExperimentResults` schema is identical to the published one |

## Capture steps

Prerequisites: a running Docker engine and `docker-compose`; Python 3 (standard library only). Ports 3000 and
3100 must be free.

```sh
cd ai-workflows/experiment-gate/tests/fixtures/growthbook/capture
python3 capture.py --out ..          # writes ../ranker-v*.results.json, ../fact-metrics.json, ../instance.json
```

`capture.py` does, in order (read it for the exact calls):

1. `docker-compose up -d mongo warehouse`; loads `seed.sql` into the Postgres container with `psql`.
2. Starts GrowthBook with [`config.yml`](capture/config.yml), which defines the Postgres data source and one
   assignment query (`user_id`, `timestamp`, `experiment_id`, `variation_id`). The REST API (5.1.0) can list data
   sources but not create them, so `config.yml` is the documented route
   ([Config.yml](https://docs.growthbook.io/self-host/config)).
3. Signs up and creates an admin secret key with the calls the web UI makes (`POST /auth/register`,
   `/auth/login`, `/organization`, `/keys` on the API port). These are the only calls that are not part of
   GrowthBook's documented REST API.
4. Through the documented REST API: `POST /api/v1/fact-tables` (orders, refunds, page loads),
   `POST /api/v1/fact-metrics` (the five metrics), `POST /api/v1/experiments` (three running experiments over
   the data source, with `statsEngine` set per experiment), `POST /api/v1/experiments/{id}/snapshot` and polling
   `GET /api/v1/snapshots/{id}` until `success`, then `GET /api/v1/experiments/{id}/results`.
5. Saves each response body unchanged and runs `docker-compose down -v --remove-orphans`, which removes the
   containers, network and volumes. colima is left running.

Things that went differently from the docs, so the next capture does not repeat them: the assignment query in
`config.yml` needs `dimensions: []` (without it every snapshot failed with
`Cannot read properties of undefined (reading 'map')`); `POST /api/v1/experiments` takes `assignmentQueryId`
in 5.1.0, not the `assignmentQuery` object that the current published docs show; and a bind mount of `seed.sql`
from `/tmp` into the colima VM silently became a directory, so the compose file injects `config.yml` as a
compose `config` and the script pipes the seed through `psql`.

The seed and the analysis are deterministic: two independent captures (one by hand, one with the script) gave
the same users, numerators, denominators, means, standard deviations, p-values and chances to beat control for
every metric of every experiment. GrowthBook ids (experiments, metrics, snapshots) and timestamps are
random per instance, so re-running the script produces files with different bytes and digests; `mapping.json`
would need the new metric ids. The committed files are one capture, kept as they came out.

## Export shape confirmed by the capture

For a result with no dimension (`result.results` has one row), each metric has one entry per variation with
`users` and `analyses[]` (one per statistics engine):

| Metric type | `numerator` | `denominator` | `mean` | `stddev` |
|---|---|---|---|---|
| proportion | users with a conversion | 0 | `numerator / users` | `sqrt(p (1 - p))` |
| mean | sum over users | 0 | `numerator / users` | sample standard deviation of the per-user values |
| ratio | sum of the numerator column | sum of the denominator (here, order count) | `numerator / denominator` | per-user delta-method standard deviation of the ratio (an arm's standard error of `mean` is `stddev / sqrt(users)`) |

`chanceToBeatControl` is oriented toward "better" for inverse metrics (`Page load ms` rose 0.18% and its chance
to beat control is 0.21), so it needs no direction. The baseline variation's `percentChange`, `pValue`, `ciLow`,
`ciHigh` and `chanceToBeatControl` are 0.

## Limits

One GrowthBook version, one data-source type (Postgres), fact metrics only (legacy SQL metrics, quantile and
funnel metrics, dimensions, CUPED, post-stratification and sequential testing are not captured and the importer
rejects the last three and any dimension). The captured numbers are for an invented warehouse and say nothing
about GrowthBook's behavior on real data.
