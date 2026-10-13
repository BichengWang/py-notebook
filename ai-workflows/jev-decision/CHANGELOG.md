# Changelog

All notable changes are documented here, following [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/).
This project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - Unreleased

### Added
- Installable standard-library-only package, annotated public API, MIT license, source/sdist examples, and `jev-decision` / `jev-decision-eval` commands.
- Typed per-question refusals, refusal counts/rates, and score Brier, log-loss and ECE metrics.
- Versioned decision/evaluation/provenance records with producer metadata and canonical JSON.

### Changed
- Live evaluation durably appends responses and case results in a sibling staging directory; completed output is published atomically. Authentication failures stop with exit 2.
- Decision CLI returns exit 1 for a result containing refusals while retaining sibling answers.

### Fixed
- Correctly rounded floating-point accumulation gives identical bundled replay metrics on Python 3.11 and 3.13.
- Examples ship once in the source/sdist, rather than being duplicated in the installed package.
- Missing score probabilities stay unknown; only complete distributions can derive a score. Missing metric inputs fail requirements.
- Probability values must be finite and within [0,1]; complete distributions must sum to 1 within rounding tolerance.
- HTTP protocol failures become retryable `APIError`; HTTP 408 is retryable.

### Security
- Remote provider URLs require HTTPS; HTTP is limited to loopback hosts. URL credentials are rejected and authenticated POST redirects are never followed.
