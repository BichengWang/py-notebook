# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Golden vectors under `tests/golden/` that compare every estimator in `expgate.stats` with
  scipy, statsmodels, gbstats and confseq (dev-only, pinned in `tests/golden/requirements.txt`).
  The default tests read the committed JSON and need no third-party library; a CI job
  regenerates the vectors and fails on any difference. The README documents references,
  versions, tolerances and the deliberate differences (pooled versus unpooled proportion
  variance, normal versus t critical values, the CUPED slope and standard error).
- `exact_tail=True` on `stats.sample_ratio_p_value` and `stats.z_for` (`erfc` and
  `-inv_cdf(alpha)`). The cross-checks showed the defaults lose digits in the tails: the
  sample-ratio p-value below about 1e-7 and as exactly 0.0 past `z` of about 8.3, `z_for` for
  `alpha` below about 1e-9. The defaults are unchanged: schema-2 records, including every 0.1.0
  scenario record (now committed as test fixtures), replay with the formulas that produced them.
  The accurate tails are intended for the next decision schema.
- Documented that `expgate.verify` is exact only on the producing platform: records written on
  macOS arm64 verify there but, on Linux, five of the seven 0.1.0 scenario records report a
  last-digit `metrics` mismatch, and sequential records also differ between Python 3.15 and
  3.11/3.13. No behavior change; the committed 0.1.0 fixtures are compared with a tolerance.

## [0.1.0] - 2026-10-13

### Added
- Installable standard-library-only package, MIT license, `experiment-gate` and
  `experiment-gate-verify` commands, `python -m expgate`, and a small public API.
- Schema-2 records with producer version, embedded input and canonical input SHA-256;
  offline verification reports hash and replay mismatches. Schema 1 remains readable
  but cannot be verified without embedded input.
- Ratio, CUPED and sequential examples, wheel smoke checks and replay coverage.

### Changed
- Whole runs publish atomically from an adjacent staging directory, allowing retry
  after a write failure without partial output.
- MDE now states its normal-approximation basis; sequential MDE describes the current
  look and does not promise power under a stopping rule.

### Fixed
- Reject unknown summary/spec keys and undeclared arm metrics instead of ignoring them.
- Treat zero-standard-error primary and guardrail metrics as inconclusive, preventing
  unsupported significance and non-inferiority claims.
