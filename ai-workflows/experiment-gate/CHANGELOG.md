# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
