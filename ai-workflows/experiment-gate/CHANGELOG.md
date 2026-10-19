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

### Fixed
- The sample-ratio p-value is accurate in the tail: it was `2 * (1 - cdf(z))`, which lost
  digits below about 1e-7 and returned `0.0` once `z` exceeded about 8.3. Below 1e-6 it now
  uses `erfc`.
- `z_for` is accurate for `alpha` below 1e-6: it rounded `1 - alpha` (relative error 4.4e-7 in
  the critical value at `alpha = 1e-12`). Below 1e-6 it now uses `-inv_cdf(alpha)`.

Both changes leave results unchanged at and above a tail probability of 1e-6, so records made
by 0.1.0 replay to identical values there; records with a sample-ratio p-value or `alpha` below
1e-6 can replay with different digits.

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
