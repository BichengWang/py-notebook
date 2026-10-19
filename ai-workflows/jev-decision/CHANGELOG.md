# Changelog

All notable changes are documented here, following [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/).
This project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `jev-decision-verify answer.json` re-parses the embedded raw provider response with the embedded question definitions, compares typed answers, refusals, `id`, `usage` and `model`, and recomputes the digest. Exit 0 verified, 1 mismatch, 2 malformed or unverifiable.
- `jev-decision-verify --evaluation DIR` hashes every file listed in `provenance.json` and re-scores the retained responses against `evaluation.json` and `cases.jsonl` without calling a provider; recomputed metric floats compare with a relative tolerance of 1e-9, everything else exactly.
- Answer record schema 2: embeds `questions` and the raw `response` and carries `record_sha256`, the SHA-256 of the RFC 8785 (JCS) canonical record without that member. `jevdecision/jcs.py` ships with the RFC 8785 test vectors.
- `jev-decision --schema-version {1,2}`.
- Signed records: `jev-decision --out FILE --sign-key KEYFILE` and `jev-decision-eval --sign-key KEYFILE` write an in-toto Statement v1 in an HMAC-SHA256 DSSE envelope (`FILE.dsse.json`, `provenance.json.dsse.json`) over the exact file bytes; `jev-decision --generate-key KEYFILE` creates a 0600 key and never overwrites. `jev-decision-verify` gains `--require-signature` with `--key KEYFILE [--signature ENVELOPE]` or `--sigstore-bundle BUNDLE --certificate-identity ID --certificate-oidc-issuer URL` (external `cosign`), and `--predicate-out FILE` for `cosign attest-blob`. Unsigned, wrongly keyed, re-hashed, wrong-predicate or malformed-envelope input exits 1; a bad key file or missing `cosign` exits 2. `jevdecision/signing.py` is the shared signing module.
- JSON Schemas (2020-12) for answer records 1 and 2, `evaluation.json` 2 and `provenance.json` 2, shipped as package data in `jevdecision/schema/`.
- Conformance vectors under `conformance/` (valid, tampered and invalid answer records and evaluation directories, with canonical bytes and `bytes` digests), `conformance/manifest.json` and the deterministic `conformance/generate.py`.

### Changed
- `jev-decision --out FILE` writes the answer record to a new file instead of stdout. `jev-decision` prints schema 2 answer records by default; it exits 1 when the provider response cannot be recorded as canonical JSON. Schema 1 records stay readable and exit 2 in the verifier as unverifiable.
- `jev-decision-eval` retains exact copies of the question file and any requirement file as `questions.json` and `requirements.json` and lists them in `provenance.json` `outputs`. Runs from 0.1.0 need `--questions` and `--requirements` to be verified.

## [0.1.0] - 2026-10-13

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
