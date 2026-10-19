# Decisions

Newest first. **Adopted** decisions are in force. **Proposed** decisions were
drafted from evidence on 2026-10-18 and take effect when the owner marks them
adopted (or replaces them); until then the phase rows that depend on them stay
blocked. Each entry says what would reopen it.

## Proposed (owner decides)

| Date | Decision | Why | Reopen if |
| --- | --- | --- | --- |
| 2026-10-18 | **Publish 0.1.0 to PyPI before any new feature** (P-016) | The READMEs already promise `pip install`; a pending trusted publisher is invalidated if someone registers the name first ([PyPI docs](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/)) | – |
| 2026-10-18 | **Move the legacy `src/` workbench to its own repository** (`BichengWang/research-workbench`, history kept), with root `pyproject.toml`, `requirements.txt`, `uv.lock`, `setup.cfg`, `tests/`, the `src-baseline` workflow and the `research-workbench` component (P-019) | All 100 open Dependabot alerts (2 critical, 48 high) come from its lockfiles; it is 301 tracked files with 52 direct dependencies next to three standard-library packages; CI does not exercise the airllm 4.0.0 and transformers 5.19.0 bumps already merged. Alternative: keep it and triage alerts by upgrading or removing vulnerable dependencies | The workbench must stay here for evidence continuity |
| 2026-10-18 | **Adopt RFC 8785 (JCS) canonical JSON for the next schema version of every record type**; current schemas keep their Python `json.dumps` form and readers | Python writes `5.0` and `1e-07`, JCS writes `5` and `1e-7`; every bundled expgate example has integral floats, so digests cannot be recomputed outside Python today. JCS is implementable with the standard library. Alternative: specify Python's float repr as the canonical number form and ship it in the vectors | A JCS port proves larger than the verifier it serves |
| 2026-10-18 | **Signed records use an in-toto Statement v1 in a DSSE envelope**, one predicate type per record; runtime stays standard library with keyed HMAC-SHA256; Sigstore signing and verification go through external `cosign`/`sigstore` tooling, documented (P-012) | Reuse the supply-chain envelope verifiers already understand; in-toto's SVR predicate omits reproduction data, which is exactly what our records add; a public transparency log is wrong as a default for private decisions | in-toto vets a decision predicate that embeds inputs, or a user needs asymmetric signing in-package |
| 2026-10-18 | **Measure success by external verification events** (unaffiliated reproductions, pilot records, issues and PRs from non-owners), not stars | 57 of 152 stargazers have 0 followers and at most 2 repositories; about 33 accounts were under 60 days old when they starred; the 12 forks have no activity after 2026-10-13 | – |
| 2026-10-18 | **Replace the 15–20 merged PRs per day target in [CONTINUAL_DELIVERY.md](../docs/CONTINUAL_DELIVERY.md) with phase exit criteria** | The loop has been idle since 2026-10-12; P-006–P-010 landed in one human PR (#224); the remaining items (schemas, signing, adapters) do not split into useful daily PRs | The queue holds more than 20 independent agent rows |
| 2026-10-18 | **Move the root README's "Portfolio and publication records" section into a `docs/publication/README.md` index**, linked from one README line | The README is about decision records, then closes with an EB-2 NIW assessment section; engineering readers evaluating the packages get immigration framing that is not part of the product. The documents themselves stay unchanged and dated | The owner needs README-level visibility for those records |

## Adopted

| Date | Decision | Why | Reopen if |
| --- | --- | --- | --- |
| 2026-10-18 | **The plan lives in `.plan/`, committed; `docs/PROJECT_PLAN.md` is removed.** Plan IDs `P-0NN` stay stable and continue from P-016 | One source for direction and queue, as in the owner's RL-pricing repository; the delivery task and `DECISION_RECORDS.md` key on Plan IDs | The delivery task cannot read `.plan/` |
| 2026-10-13 | 0.1.0 of all three packages tagged and released on GitHub; PyPI waits for owner-side trusted publishing ([RELEASING.md](../docs/RELEASING.md)) | Tag-scoped, reviewed publishing with OIDC rather than stored tokens | – |
| 2026-10-12 | Packages are independent, not one integrated runtime; runtimes use the standard library only; dev-only dependencies are allowed in tests and CI | Each record must be checkable without trusting a shared runtime | A user needs a cross-package workflow, built as a separate example |
| 2026-10-12 | Breaking record changes require a new integer schema version; supported readers and replay rules are kept; unknown schemas are rejected ([conventions](../docs/DECISION_RECORDS.md#compatibility-and-limits)) | Old records must stay verifiable | – |
| 2026-10-12 | RELIA publication needs rights clearance, unaffiliated reproduction and maintainer acceptance ([RELIA_RELEASE.md](../docs/RELIA_RELEASE.md)); external evidence (independent review, real-data pilots, adoption) is recorded only when it happens, and fixtures or self-produced reports are never relabeled as such | Engineering work cannot substitute for those records; credibility of the records is the product | – |
| 2026-09-26 | RELIA's roadmap is authoritative for RELIA milestones (#133) | RELIA has its own research and release process | – |
