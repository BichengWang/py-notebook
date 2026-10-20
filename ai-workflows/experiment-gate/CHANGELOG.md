# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Signed records (P-012): `experiment-gate keygen KEY` and `--sign-key KEY` on the producer (one
  `decision.json.dsse.json` per record, also for `--all-scenarios`), and `--require-signature`
  (`--key [--signature]`, or `--sigstore-bundle` with `--certificate-identity` and
  `--certificate-oidc-issuer`) on `experiment-gate-verify`. HMAC-SHA256 DSSE envelopes carry an
  in-toto Statement v1 whose subject is the SHA-256 of the exact `decision.json` bytes; the predicate
  type names the schema version. Sigstore signing is external `cosign`; verification delegates to
  `cosign verify-blob-attestation` on a private copy of the bytes already read. `experiment-gate
  predicate` writes the predicate for `cosign attest-blob`. The file is read once: signature, parse
  and replay see the same bytes. Unsigned, wrong key, edited-and-re-hashed or wrong predicate type
  exit 1; a bad key file, missing `cosign` or flag misuse exits 2 (a bad `--sign-key` before any
  output is written). Behavior without the flags is unchanged. CI signs a record keylessly and
  verifies it with the package, and the wheel smoke check round-trips an HMAC signature.
- `experiment-gate --from growthbook results.json --mapping mapping.json` (P-025): converts the body of
  GrowthBook's `GET /api/v1/experiments/{id}/results` (per-variation users, counts, means and standard
  deviations) into an expgate input, evaluates it under expgate's rules and writes a normal schema-3
  record. Offline and standard library only (`expgate/importers/growthbook.py`). A mapping file supplies
  what the export lacks: metric type, direction and guardrail margin, and a `snapshot` block asserting
  the snapshot's allocation share and that it was not regression-adjusted, because the results endpoint
  pairs the latest snapshot with the experiment's current settings; the assertions are recorded in
  `source.asserted` and the import is refused when the export's current weights or adjustment flags
  contradict them. A malformed or unsupported export or
  mapping (other dimensions than none, more than two variations or a repeated variation id, regression
  adjustment or sequential testing, a phase that is not a valid index, a probability outside [0, 1], a metric
  whose shape contradicts its type, duplicate keys, `NaN`) exits 2 with the field named. Post-stratification
  is accepted. GrowthBook's p-values, intervals and chance to win are never used
  for the decision. The README has the field mapping and what is and is not imported.
- Optional `source` object in a schema-3 `input` (`format`, `export_sha256`, experiment and snapshot ids,
  `stats_engine`, `asserted`, `reading`), added to `decision.v3.json`. `export_sha256` is the SHA-256 of the export
  file's exact bytes, so `input_sha256` covers it and `experiment-gate-verify` detects an edit. `reading`
  holds the importer's reading of GrowthBook's own statistics (ship, hold or rollback) and, when it
  differs from expgate's decision, the `policy difference:` lines that `reasons` then repeats; replay
  reproduces them. Decisions never depend on `source`. Schema 2 rejects it. Schema 3 is unreleased, so
  this is part of schema 3, not a new schema version.
- Fixtures captured from a throwaway self-hosted GrowthBook 5.1.0 with a synthetic warehouse
  (`tests/fixtures/growthbook/`: three exports, a mapping file and the dev-only capture script and
  compose stack), and `tests/test_growthbook.py`. One export shows GrowthBook's reading and expgate's
  decision agreeing, one a SHIP reading that expgate holds because a guardrail is not shown
  non-inferior, one a HOLD reading that expgate ships by its one-sided test. They are
  software-behavior evidence only: the data is synthetic.
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
