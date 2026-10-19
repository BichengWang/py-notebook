# Experiment gate (`expgate`)

Replayable decision records for AI-assisted go/no-go decisions. This small,
deterministic workflow handles the step that follows offline release gates:
deciding whether a real-time decision model that is **already in an online A/B
test** should be shipped, held for more data, or rolled back.

It reads the aggregate summary an experimentation platform exports (units per
arm, successes for proportion metrics, mean and standard deviation for mean
metrics) and writes a decision record. It uses only the Python standard library,
so it has no dependencies and no lockfile.

## Decision rules

Rules are applied in order; the first match wins.

| Decision | When |
|---|---|
| `INVALID` | Sample-ratio mismatch: the observed assignment split differs from the design (chi-square, `srm_alpha`, default 0.001). No effect estimate is trusted. |
| `ROLLBACK` | The primary metric is significantly worse, or a guardrail is significantly worse **and** its point degradation exceeds its margin. |
| `SHIP` | The primary metric is significantly better **and** every guardrail is shown non-inferior (its upper degradation bound is below its margin). |
| `HOLD` | Anything else: the experiment is inconclusive. |

The primary metric uses a one-sided test at `alpha` (default 0.05). Guardrail
bounds are one-sided and Bonferroni-adjusted across guardrails. Proportions use
the unpooled Wald standard error; means use the Welch standard error; ratio
metrics use a delta-method standard error (see [Ratio metrics](#ratio-metrics)).
All are large-sample approximations. A metric can optionally be estimated with CUPED
regression adjustment, which narrows its interval (see
[Variance reduction](#variance-reduction-cuped)). A test that is checked while it
runs can replace every bound with an always-valid confidence sequence (see
[Sequential monitoring](#sequential-monitoring)).

Every metric reports `mde = (z + z_power) * se`, using its critical value,
observed standard error, and `policy.power` (default 0.8). For fixed-horizon
analysis, `mde_basis` is `fixed_horizon_normal_approximation`: approximate
single-metric detectability at the current sample size, not a guarantee that all
guardrails pass or the experiment ships. For sequential analysis it is
`current_look_normal_approximation`: a sensitivity estimate for this look,
**not a guarantee of power under repeated looks or a stopping rule**. The formula
and thresholds are unchanged. A zero standard error makes the metric inconclusive;
its numerical MDE of zero is not evidence of detectability.

## Quick start

Install with Python 3.11 or later (the first PyPI release is pending):

```bash
pip install expgate
experiment-gate --input examples/offer-ranker-v2.json --out review-run --require-ship
experiment-gate-verify review-run/decision.json
```

The examples live in this repository; supply your own exported summary after
installation. From this directory:

```bash
python3 -m unittest discover -s tests
python3 -m expgate.run --all-scenarios --out review-run
python3 -m expgate.run --input examples/offer-ranker-v2.json --out review-run/example --require-ship
```

`python -m expgate` is also supported; `python -m expgate.run` remains available.

`--out` must be new or empty. Each evaluation writes `decision.json` (sorted
keys; byte-identical across runs for the same input) and a readable
`DECISION.md`. `--input` takes several summaries at once (`--input exports/*.json`);
each record then goes to `--out/<experiment>/`, so every summary must name its
`experiment`, and the names must be distinct (ignoring case) and usable as a
directory name. Every summary is read and evaluated before anything is written,
so one invalid file leaves no partial records. The entire run is written into a
staging directory next to `--out` and atomically published with `os.replace`; a
write failure leaves the target untouched and the run can be retried. `--require-ship` exits 1 unless every decision is `SHIP`, so the
command can gate a promotion job.

| Exit | Evaluation CLI | Verification CLI |
|---|---|---|
| 0 | Records written; required SHIP condition met, if requested | All records verified |
| 1 | Completed, but `--require-ship` was not met | Hash or replay content mismatch |
| 2 | Invalid input, usage, unreadable file, or output failure | Unreadable/invalid record, usage, or unsupported/legacy schema |

Without `--require-ship`, writing a HOLD, ROLLBACK, or INVALID decision succeeds
with exit 0; inspect the record or request the gate explicitly.

From the repository root, `make expgate-test` and
`make expgate-run EXPGATE_OUT=/abs/new/dir` run the same commands.

## Input format

See [`examples/offer-ranker-v2.json`](examples/offer-ranker-v2.json). Exactly
one metric has `"role": "primary"`; every other metric is a `"guardrail"` with a
non-negative `margin` in the metric's own units. `direction` states which way is
better (`increase` or `decrease`). `policy` and `assignment` are optional;
`policy.sequential` turns on sequential monitoring.

The summary is validated before any statistic is computed: counts must be
integers within range, means, standard deviations and guardrail margins must be finite,
`alpha`, `srm_alpha`, `power` and `expected_treatment_share` must lie in (0, 1), and
`policy.sequential.planned_units` must be an integer of at least 2. `experiment`,
when present, must be a non-empty string. The allowed top-level keys are
`experiment`, `description`, `seed` (synthetic metadata), `metrics`, `arms`,
`policy`, and `assignment`. Metric specs allow only `type`, `role`, `direction`,
and `margin`; arm metrics must all be declared in the specs. Unknown keys at
the summary top level, in metric specs, in `policy`,
`policy.sequential`, `assignment`, an arm's metric statistics, and a `covariate`
are rejected rather than ignored, so a misspelled setting such as `alpah` cannot
silently fall back to its default.
Any violation exits 2 with the offending field named, so malformed input is
never mistaken for a `--require-ship` refusal (exit 1). Every metric with zero
standard error (including zero-event or all-event proportions, zero-variance
means/ratios, and perfectly adjusted CUPED outcomes) is `INCONCLUSIVE`; it can
neither establish significant improvement/harm nor non-inferiority. A zero-error
primary or guardrail therefore prevents SHIP.

## Decision records and offline verification

`decision.json` preserves the existing decision, reasons, policy, sample-ratio,
metrics, and `expgate_version` fields. New records have integer `schema_version: 2`,
`produced_by: {"name": "expgate", "version": "0.1.0"}`, the full parsed `input`, and
`input_sha256`. The input digest is lowercase SHA-256 of canonical JSON:
`json.dumps(input, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`
encoded as UTF-8. `DECISION.md` shows the SHA-256 of the actual `decision.json`
bytes (including formatting), which is a different digest.

```bash
python -m expgate.verify review-run/decision.json
experiment-gate-verify review-run/*/decision.json
```

Verification recomputes the input digest and calls `evaluate` with the running
version. It names mismatches in the decision, reasons, metrics, experiment,
policy, sample-ratio, and sequential fields using canonical JSON comparison
(including value types). It needs no network access. Missing
`schema_version` means schema 1: existing JSON remains readable, but lacks the
embedded input needed for verification and exits 2 with an explanation. Future
versions may produce different replay results; a mismatch is reported, not hidden.
Hashes detect changes, not forgery or authenticity: someone who rewrites the input
and recomputes the report can produce a consistent record.

The public API exports `evaluate`, `verify_record`, and `__version__` from
`expgate`. `verify_record(record)` returns a list of mismatched field names and
raises `ValueError` for invalid/unsupported records.

## Bundled examples

All examples are hand-written schema demonstrations, not live-model,
calibration, adoption, or production evidence:

| Input | Demonstrates |
|---|---|
| `examples/offer-ranker-v2.json` | Proportion primary and proportion/mean guardrails |
| `examples/ratio.json` | Revenue per session with user-level numerator/denominator summaries |
| `examples/cuped.json` | Mean primary adjusted by one pre-assignment covariate |
| `examples/sequential.json` | An interim look toward 200,000 planned units |

```bash
experiment-gate --input examples/*.json --out example-records
experiment-gate-verify example-records/*/decision.json
```

## Ratio metrics

Some metrics are a ratio of two per-unit totals: revenue per session, clicks per page view,
when users (not sessions) are randomized. Sessions from the same user are correlated, so
treating them as independent draws understates the standard error. Declare the metric with
`"type": "ratio"` and give each arm the per-unit mean and sample standard deviation of the
numerator and the denominator, and their correlation across units:

```json
"revenue_per_session": {"numerator": {"mean": 31.2, "sd": 40.5},
                        "denominator": {"mean": 3.1, "sd": 2.4}, "corr": 0.62}
```

The arm's value is `numerator.mean / denominator.mean`, and its variance comes from the
first-order delta method,
`(sd_y^2 - 2 R corr sd_y sd_x + R^2 sd_x^2) / (mean_x^2 n)` with `R` the ratio and `n` the
arm's units. The denominator mean must be positive. Ratio metrics take any role and direction,
work with sequential monitoring, and do not take a CUPED `covariate`.

In 1,000 simulated A/A tests that randomize 2,000 users per arm, each with a varying number
of sessions and a user-level spending propensity, the delta-method standard error averaged
0.212 against an empirical spread of 0.211, and a one-sided test at 0.05 shipped 4.6% of
them. Treating sessions as independent shipped 9.8%.

## Variance reduction (CUPED)

If you have a pre-experiment measurement of the same unit that predicts the outcome (last
month's revenue for this month's revenue, say), add a `covariate` summary to **that metric in
both arms** (the numbers below are illustrative):

```json
"revenue_per_user": {"mean": 20.57, "sd": 8.1,
                     "covariate": {"mean": 20.46, "sd": 7.9, "corr": 0.8}}
```

`covariate.mean` and `covariate.sd` describe the pre-experiment value, and `corr` is its
correlation with the outcome within the arm. Proportion metrics take the same block next to
`successes`. The estimate becomes `(ybar_t - ybar_c) - theta * (xbar_t - xbar_c)`, with one
`theta` shared by both arms: the pooled within-arm regression slope. The standard error
shrinks by about `1 - rho^2` in variance, and the adjustment also removes the part of the
difference caused by a chance imbalance in the covariate. The decision rules do not change, and
a metric's row in `decision.json` gains an `adjustment` object (`theta`, the unadjusted
difference and standard error, and the variance reduction).

Things the tool cannot check for you:

- The covariate must be measured **before assignment** and must not be affected by the
  treatment. A post-treatment covariate biases the estimate.
- The adjustment can move a single experiment's estimate either way. In the `cuped` scenario
  the treatment arm's covariate runs high by chance, the unadjusted lift is inflated, and the
  adjusted analysis holds. Across 300 simulated experiments with a real lift of 0.4 the adjusted
  analysis ships 80% of the time against 47% unadjusted. With no real lift over 1,500 runs they ship
  5.5% and 5.9% of the time, consistent with the nominal 5%.
- `theta` is treated as known. Its estimation error is negligible at the sample sizes this tool
  targets, but it is ignored.

## Sequential monitoring

The default bounds assume the summary is evaluated once, at a sample size fixed in advance.
Evaluating it every day and acting on the first `SHIP` or `ROLLBACK` inflates the error rates:
in 2,000 simulated A/A tests checked at 20 evenly spaced looks, re-applying the fixed-horizon
bounds at each look shipped 19.8% of them and rolled back 22.0%, against a nominal 5%.

To check a running test, declare the total sample size (both arms) the test is planned to reach:

```json
"policy": {"alpha": 0.05, "sequential": {"planned_units": 60000}}
```

Every bound then uses a normal-approximation confidence sequence: a one-sided normal-mixture
sequential probability ratio test on the same normal approximation, inverted into a bound. Under the
known-variance normal model, probability at least `1 - alpha` applies to each bound
at every look at once. With observed standard errors this is approximate, so the summary can be evaluated
as often as the platform refreshes it, and the experiment can stop at the first `SHIP` or
`ROLLBACK`. The decision rules, the Bonferroni split across guardrails and CUPED are unchanged;
only the multiplier on each standard error (the `z` in a metric's row) is larger. `decision.json`
gains a `sequential` object (planned and current units, and the information fraction), and
`DECISION.md` gains one line. A summary without `policy.sequential` uses fixed-horizon bounds.

`planned_units` tunes the mixing variance so the bound is narrowest at the planned size. It must be
fixed before the test starts; choosing it after seeing the data voids the guarantee. Under the known-variance normal model the bound
stays valid before and after the plan, only wider; the plug-in implementation remains approximate. A `HOLD` at or past the plan says that the
planned sample size was reached without a decision.

The price is power at the plan. In the same simulation, with a real conversion lift from 0.100 to
0.108 and 60,000 planned units, a single fixed-horizon analysis at the plan ships 95% of tests.
Sequential monitoring over 20 looks ships 74% of them, and those it ships stop on average at 56% of
the planned sample. Without a real effect it ships 1.0% and rolls back 1.2%. At the plan the
primary multiplier is 2.77 standard errors against 1.64 for the fixed-horizon test at
`alpha = 0.05`. Use sequential monitoring when stopping early (above all, rolling back a harmful
candidate early) is worth that cost.

## Synthetic scenarios

`--scenario` / `--all-scenarios` simulate an offer-ranking model with a fixed
seed (`expgate/generator.py`):

| Scenario | Expected decision |
|---|---|
| `win` | `SHIP` |
| `flat` | `HOLD` |
| `guardrail-breach` | `ROLLBACK` (latency) |
| `regression` | `ROLLBACK` (primary) |
| `srm` | `INVALID` |
| `cuped` | `HOLD` (a revenue lift that looks significant only because of a covariate imbalance) |
| `early-regression` | `ROLLBACK` (primary) at an interim look, a quarter of the way to the planned sample size |

## Cross-checks against reference libraries

Every estimator in `expgate/stats.py` is compared with an independent implementation on fixed
inputs. The references' answers are committed as JSON in
[`tests/golden/`](tests/golden/), so the default test suite
(`tests/test_golden.py`) checks them using only the standard library. The generator,
`tests/golden/generate.py`, needs the pinned libraries in `tests/golden/requirements.txt` and
Python 3.10 (`confseq` 0.0.11, its latest release, has no wheels for newer interpreters; `gbstats`
0.8.0 pins `numpy<2` and `pandas<2`). A CI job (`golden vectors` in `expgate-ci.yml`) regenerates
the files and fails on any difference.

```sh
python3.10 -m venv .venv && .venv/bin/pip install -r tests/golden/requirements.txt
.venv/bin/python tests/golden/generate.py             # rewrites tests/golden/*.json
```

Pinned references: scipy 1.14.1, statsmodels 0.15.0, gbstats 0.8.0, confseq 0.0.11, numpy 1.26.4,
pandas 1.5.3. All are used for development and CI only; none is imported by `expgate`, listed as a
dependency, or shipped in the wheel. Licenses, from each distribution's metadata and bundled
license file: gbstats MIT (Copyright 2024 GrowthBook, Inc.), confseq MIT, statsmodels BSD-3-Clause,
scipy, numpy and pandas BSD. All permit this use. That finding covers the PyPI distributions we
install, not other parts of the GrowthBook repository.

| Method (`expgate.stats`) | Reference | Compared at | Result |
|---|---|---|---|
| `proportion_effect` (unpooled Wald) | statsmodels `test_proportions_2indep` and `confint_proportions_2indep` (`method="wald"`), gbstats `ProportionStatistic` | 1e-9 relative | agrees |
| `mean_effect` (Welch) | scipy `ttest_ind_from_stats(equal_var=False)`, gbstats `SampleMeanStatistic` | 1e-9 relative | agrees |
| `ratio_effect` (delta method) | gbstats `RatioStatistic`; linearization recomputed from raw per-unit data with numpy | 1e-9 relative | agrees |
| `cuped_effect` | OLS of `y ~ treated + x` on raw per-unit data (statsmodels) with the variance of `y - theta x` per arm (numpy); gbstats `RegressionAdjustedStatistic` where the method is the same | 1e-9 relative | agrees; gbstats differs by design, see below |
| `sample_ratio_p_value` | scipy `chisquare` | 1e-9 relative | disagreed in the tail; fixed |
| `minimum_detectable_effect` | scipy `norm.isf` and `norm.ppf`; statsmodels `NormalIndPower().power` at that effect equals the requested power | 1e-9 relative | agrees |
| `z_for` | scipy `norm.isf` | 1e-9 relative | disagreed for `alpha` below about 1e-9; fixed |
| mixture critical value at a fixed mixing ratio | scipy `quad` for the half-normal mixture integral and `brentq` for its root | 1e-9 relative | agrees |
| `sequential_multiplier` | confseq `normal_mixture_bound` (one-sided), mixing variance tuned with scipy `minimize_scalar` to be narrowest at the planned size | 1e-6 relative | agrees to 2.6e-7 at worst |

Vectors cover ordinary cases and boundaries: small samples, success rates at 0, at 1 and within
1e-5 of them, very unequal variances, negative effects, covariate imbalance, covariate
correlations of 0, 0.95 and -0.7, tiny and huge scales, unequal arms, and sample-ratio
mismatches from mild to a p-value of 1e-138. They are stored to eleven significant digits (seven
for the sequential boundary), so last-bit differences between platforms cannot change the
committed bytes.

**Tolerances.** Closed-form results must agree to 1e-9 relative, with no absolute floor except
for the two CUPED fields that are exactly 0 in expgate and rounding noise (about 1e-17) in a
regression on raw data: `theta` and `variance_reduction` also pass within 1e-12. Observed
agreement was within 1e-10 everywhere (the largest, in CUPED, is cancellation in the raw-data
reference). The sequential boundary is compared at 1e-6 relative because both sides iterate:
confseq solves for the boundary numerically and the mixing variance comes from a
one-dimensional minimizer on an objective that is flat at its minimum. The two agreed to 2.6e-7
at worst across 35 combinations of `alpha` (0.001 to 0.2) and planned-to-current information
ratio (0.1 to 10); a wrong boundary would be off by far more (the fixed-horizon value at
`alpha = 0.05` is 40% lower).

**Disagreements found, and fixed.**

- The sample-ratio p-value was computed as `2 * (1 - cdf(z))`. The subtraction loses digits
  below about 1e-7 (a split of 4,700 to 5,300 reported 1.9731754e-9, 5.6e-8 relative error) and
  returns exactly 0 once `z` exceeds about 8.3, so a severe mismatch reported `p = 0.0` where
  scipy gives 2.5e-43 (40,000 against 44,000 units). The tail now uses `erfc`. The gate decision
  changes only for an `srm_alpha` below the true p-value, which the exact 0 used to force to
  `INVALID`.
- `z_for` computed `inv_cdf(1 - alpha)`, which rounds `1 - alpha` to a multiple of 1.1e-16: a
  relative error of 1e-4 in `alpha` at 1e-12, which is 4.4e-7 in the critical value (1.9e-9 at
  1e-10). Below `alpha = 1e-6` it now uses `-inv_cdf(alpha)`.

Both fixes apply only below a tail probability of 1e-6. Above it the original expressions are
kept, so a record made by 0.1.0 still replays to identical values; only records whose
sample-ratio p-value is below 1e-6 or whose `alpha` is below 1e-6 can replay with different
digits.

**Deliberate differences from the references.** These are method choices, not defects. The
vectors record the other side where it helps (the `informational` blocks are not asserted).

- *Proportions: unpooled variance.* statsmodels' `proportions_ztest` pools the variance under
  the null of no difference. expgate uses the unpooled (Wald) standard error because the same
  error builds the bounds around a non-zero estimate. For 100/1,000 against 150/1,000 the
  unpooled z is 3.3903 and the pooled z is 3.3806. The tests compare against the unpooled
  form (`method="wald"`).
- *Means: normal critical values.* A Welch t-test uses Student's t with Welch-Satterthwaite
  degrees of freedom; expgate uses the normal quantile at every sample size, as the estimators
  are documented to be large-sample. The standard errors agree; the one-sided 0.05 critical
  values do not at small `n` (1.645 against 5.08 for arms of 2 and 3 units, 1.645 against 1.650
  at 100 and 400).
- *CUPED: the slope.* expgate uses the pooled within-arm slope, the coefficient on `x` in
  `y ~ treated + x`. gbstats takes the slope of `y` on `x` over the pooled sample, ignoring arm.
  The two are equal when the arms' covariate means are equal. Otherwise the pooled sample also
  picks up the association between treatment and covariate: in the `covariate-imbalance` vector
  the slopes are 0.81128 and 0.81220 and the adjusted differences 0.29098 and 0.29024; in the
  `uncorrelated` vector, where the correlation within each arm is 0, expgate's slope is 0 and
  gbstats' is 0.0031. Vectors with equal covariate means are compared against gbstats; all are
  compared against the regression.
- *CUPED: the standard error.* expgate sums each arm's variance of `y - theta x` over its own
  units and treats `theta` as known (see the section above). The OLS standard error of the
  treatment coefficient pools residual variance across arms and includes the estimation error
  of `theta`; it is slightly larger (0.09687 against 0.09675 in the imbalance vector, 1.134
  against 1.007 with 4 and 3 units).
- *Sequential: other mixtures.* gbstats ships a two-sided sequential test (Waudby-Smith et al.
  2023, Gaussian mixture with a fixed tuning parameter) and confseq other boundaries. expgate's
  is the one-sided half-normal mixture, so only confseq's one-sided `normal_mixture_bound` is a
  reference for it. That function's own tuning rule is a closed-form approximation of the
  optimal mixing variance, and the multiplier it gives differs from expgate's optimized one by
  up to 0.8% (spot check at `alpha` 0.01 to 0.05 and information ratios 0.25 to 4). Both are
  valid; the vectors give confseq the optimized mixing variance so that only the boundary is
  compared.

What this shows and does not: the estimators implement the referenced formulas on these fixed
inputs. It does not show that a method is appropriate for a real experiment, and the vectors
are synthetic, not live or production evidence.

## Limitations

The simulation figures above describe synthetic experiments, not measured product
performance or calibration on live-model outcomes.

- Without `policy.sequential` the bounds are fixed-horizon: checking results repeatedly
  and stopping early inflates error rates.
- Sequential bounds plug in the observed standard error at each look, as the fixed-horizon
  bounds do. The guarantee is exact for normal estimates with known variance and holds only
  approximately at small samples. The sample-ratio check is not sequential: re-running it at
  every look raises its false alarm rate above `srm_alpha`.
- CUPED is supported for one covariate per proportion or mean metric. There is no CUPED for
  ratio metrics, no multi-covariate adjustment, and no heterogeneous-effect analysis.
- The delta method is a first-order approximation. It needs enough units that the
  denominator mean is estimated well away from zero.
- Synthetic scenarios show that the rules behave as specified. They say nothing
  about any real product's effects.
