# Security policy

Report suspected vulnerabilities privately through [GitHub private vulnerability
reporting](https://github.com/BichengWang/ai-decision-system/security/advisories/new).
Do not open public issues or disclose exploit details before coordinated review.
Include the component, version, reproduction steps, impact, and any proposed
mitigation. Do not include credentials or sensitive production data.

The maintainer aims to acknowledge reports within seven days. This is a goal,
not a service-level agreement; response and remediation times depend on the
report and maintainer availability. For private maintainer contact, including
conduct reports, use the same reporting route.

## Supported versions

Security fixes target the latest 0.1.x release of each independently released
package: `expgate`, `jevdecision`, and `decisioncontrol`. Until a package's first
release, there is no supported published version. Earlier releases are not
supported; upgrade to the latest patch release of the affected component.

RELIA is unreleased and follows its own human-gated release process. The `src/`
research workbench is unsupported. Reports about either are still welcome.

## Signed decision records

Each package can sign the records it exports and can require that signature when
verifying (`--require-signature`; format and flags in
[DECISION_RECORDS](docs/DECISION_RECORDS.md#signed-records)). A digest inside a
record can be recomputed by anyone who edits it; a signature over the exact file
bytes cannot be reproduced without the key or the signer's identity.

**Key generation.** Use the package's own command, never a hand-made key:
`experiment-gate keygen KEY`, `jev-decision --generate-key KEY`, or
`decision-control keygen KEY`. Each writes 32 random bytes (`secrets.token_bytes`)
as hex to a new file with mode 0600, refuses to overwrite an existing file, and
prints the key id (`hmac-sha256:` plus the first 16 hex digits of the key's
SHA-256). Verifiers reject a key file shorter than 32 bytes or not hex.

**Storage.** Never commit a key, put it in an image, or paste it into an issue.
Keep it in a secret manager, or in a CI secret written to a mode-0600 file for the
duration of one job. Anyone who can read the key can sign any record, so keep it
out of backups you do not trust.

**Rotation.** Generate a new key; it has a new key id. Sign new records with it and
keep the old key to verify old envelopes. A DSSE envelope may carry several
signatures, and a verifier accepts the envelope when one of them matches the key
it was given. The packages do not expire keys or revoke envelopes: retiring a key
means removing it from the verifiers that should stop trusting it.

**What HMAC proves.** Possession of the shared secret when the envelope was made,
over exactly these file bytes. It does not identify a person or system, and every
holder of the key, including every verifier, can also sign. Use it between parties
that trust each other with one secret; use Sigstore when the signer must be
attributable. Neither form shows that the facts inside the record are true.

**Sigstore.** The packages never sign with Sigstore. Sign with an external
`cosign attest-blob` (keyless in GitHub Actions needs `id-token: write`) and verify
with `--sigstore-bundle`, `--certificate-identity` and `--certificate-oidc-issuer`,
which the package passes unchanged to `cosign verify-blob-attestation`. For GitHub
Actions signing the identity is the workflow and the ref it ran on, for example
`https://github.com/OWNER/REPO/.github/workflows/WORKFLOW.yml@refs/heads/main`; a
record signed on another branch or by a pull request has a different identity.
The statement inside a cosign bundle is in-toto Statement v0.1, as cosign writes it
for a custom predicate type; only the packages' own HMAC envelopes use Statement v1.
Keyless signing writes the signer identity and the record digest to the public
Rekor transparency log permanently, so do not attest private decisions there.
The packages do not read or record the signing time, so a valid signature does not
say when a record was made and cannot prove a record was not backdated. An external
Sigstore bundle may carry Rekor inclusion-time evidence, which these packages do not
check and which in any case does not prove when the record's contents were created.

**Reporting.** A flaw in signing or verification (for example a record that
verifies under `--require-signature` after its bytes changed, or a signature that
vouches for another record type) is a vulnerability: report it privately, as
described above, and do not post forged envelopes or keys in public.

See the component-specific policies and trust boundaries for
[decision-control](ai-workflows/decision-control/SECURITY.md) and
[RELIA](ai-workflows/ai-decision-reliability/SECURITY.md).
