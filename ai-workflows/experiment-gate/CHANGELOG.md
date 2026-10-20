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
  Schema 3 uses them (below).
- Documented that `expgate.verify` is exact only on the producing platform: records written on
  macOS arm64 verify there but, on Linux, five of the seven 0.1.0 scenario records report a
  last-digit `metrics` mismatch, and sequential records also differ between Python 3.15 and
  3.11/3.13. No behavior change; the committed 0.1.0 fixtures are compared with a tolerance.
- Decision record **schema 3**: `input_sha256` is the SHA-256 of the RFC 8785 (JCS)
  canonical form of `input` (`expgate/jcs.py`, checked against 647 number, structure and
  rejection vectors), so other languages can reproduce it. `experiment-gate` writes
  schema 3; `experiment-gate-verify` verifies schemas 2 (python-json-v1, unchanged) and 3
  and rejects duplicate keys, non-finite numbers and out-of-range integers in schema 3
  with exit 2. Schema 1 still exits 2; any other schema is unsupported.
- JSON Schemas for schema 2 and 3 shipped as package data (`expgate/schema/decision.v2.json`,
  `decision.v3.json`); `evaluate(..., schema_version=2)` replays the older form.
- Conformance vectors (`conformance/`: valid, tampered and invalid records for schemas 2 and 3, a
  schema-1 record, exact canonical input bytes, `manifest.json`) with a deterministic generator
  and tests; CI validates CLI-produced records against the schemas with a pinned dev-only
  `jsonschema` and verifies the vectors with the built wheel.

- Replay comparison for schemas 2 and 3 is one function. Only computed statistics (`p_value`, and per
  metric `diff`, `se`, `improvement`, `improvement_bounds`, `z`, `mde`, CUPED `adjustment`) agree within a
  relative 1e-9 (absolute 1e-12 where the replayed value is exactly 0); non-finite values must be
  identical. Inputs, copied policy values and margins, counts (whatever their int/float spelling),
  digests, strings, booleans, dispositions and structure stay exact. Schema 2 keeps its python-json-v1
  digest, 0.1.0 tail formulas and lenient parsing. No record that verified before stops verifying.
- Schema 3 canonicalizes the whole record when verifying, so ignored members with unsafe integers,
  overflowed floats or lone surrogates exit 2, and `evaluate` raises `ValueError` for a schema-3 input
  whose statistics overflow to infinity.

### Changed
- `experiment-gate-verify` no longer reports last-digit float differences between platforms: the 0.1.0
  scenario records written on macOS now verify on Linux (five of seven failed before).
- New records have `schema_version: 3`, which uses the accurate tails (`exact_tail=True`: the `srm`
  scenario records `p_value` 6.7e-49 instead of 0.0; one mapping, `records.EXACT_TAIL`). Records
  written by 0.1.0 (schema 2) still verify with the 0.1.0 formulas. A 0.1.0 verifier rejects
  schema 3 as unsupported.

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
