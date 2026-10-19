# Regulatory mapping: decision records and logging provisions

> **No compliance claim. Not legal advice.** This document does not state, imply or
> support a claim that any record, package or deployment complies with, conforms to,
> or is certified under the EU AI Act, ISO/IEC 42001, the NIST AI RMF or any other
> law or standard. It maps field names that exist today to the *kind* of information
> each provision names, and lists what the records do not cover. Whether an AI system
> is high-risk, who is its provider or deployer, and what a given provision requires
> of a given organisation are legal questions this document does not answer. Ask a
> qualified lawyer or auditor.

Status: drafted for plan item P-028; owner review pending. Retrieval date for every
source below is **2026-10-19**. The records are described as they are today; JSON
Schemas and further schema versions are being added under
[P-011](../.plan/phase-1-records-spec.md), and optional authenticated records under
P-012. Re-check the mapping when those land.

## What "serves" means here

A field "serves" a provision when it carries information of the kind the provision
names. It does not mean the provision is satisfied. Three limits apply to every row.

- The packages are not AI systems and are not wired into one. Article 12 concerns the
  logging capability of a high-risk AI system itself, recording events over the
  system's lifetime. The records here are produced by separate tooling around a
  go/no-go decision, from a run of that tooling, not by the AI system.
- Records are files (JSON, JSONL, Markdown) and, for decision-control, rows in a
  SQLite file that can be exported. Retention is the duty of whoever keeps the files.
  No package sets, enforces or evidences a retention period.
- Digests and checksums detect change after the fact. They do not authenticate who
  wrote a record, and anyone who edits a record can recompute them. See
  [Encoding and integrity](DECISION_RECORDS.md#encoding-and-integrity) and
  [Compatibility and limits](DECISION_RECORDS.md#compatibility-and-limits).

## Primary texts and dates

| Source | URL | Retrieved | What was read |
| --- | --- | --- | --- |
| Regulation (EU) 2024/1689 (AI Act), consolidated text of 2026-07-27 | <https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:02024R1689-20260727> | 2026-10-19 | Articles 12, 19, 26, 72, 113. EUR-Lex marks this text "purely as a documentation tool" with no legal effect; the authentic text is the Official Journal. |
| Regulation (EU) 2024/1689, Official Journal text of 2024-07-12 | <https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=OJ:L_202401689> (ELI <http://data.europa.eu/eli/reg/2024/1689/oj>) | 2026-10-19 | Original unamended text; not compared line by line with the consolidated text, from which the articles were quoted |
| Regulation (EU) 2026/1744 (Digital Omnibus on AI), of 8 July 2026, OJ L 1744, 24.7.2026 | <https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:32026R1744> (ELI <http://data.europa.eu/eli/reg/2026/1744/oj>) | 2026-10-19 | Recital 40 and the amendment to Article 113 (Article 1, point 40) |
| NIST AI 100-1, Artificial Intelligence Risk Management Framework (AI RMF 1.0), January 2023 | <https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.100-1.pdf> (DOI <https://doi.org/10.6028/NIST.AI.100-1>) | 2026-10-19 | Table 4, MANAGE 4.1, printed page 33. AI RMF Playbook not reviewed |
| ISO/IEC 42001:2023, Annex A control A.6.2.8 | <https://www.iso.org/standard/42001> (public preview: ISO Online Browsing Platform) | 2026-10-19 | **Full text not reviewed; it is paywalled.** The public preview's table of contents stops at clause 8.4 and does not list Annex A. The number and title "A.6.2.8 AI system recording of event logs" were confirmed only from a third party's published statement of applicability ([Darktrace v1.11, 2025-12-03](https://cdn.prod.website-files.com/626ff4d25aca2edf4325ff97/6931b27220b329fdba170de2_Darktrace%20ISO%2042001%20Statement%20of%20Applicability.pdf)). This document relies on the title only and does not paraphrase the control's requirements or Annex B guidance |

### Application dates (confirmed against EUR-Lex)

Regulation (EU) 2026/1744 replaces Article 113, third paragraph, point (c) of
Regulation (EU) 2024/1689. In the consolidated text it reads:

> Chapter III, Sections 1, 2, and 3, with the exception of Article 6(5), shall apply from:
> (i) 2 December 2027 as regards AI systems classified as high-risk pursuant to Article 6(2) and Annex III; and
> (ii) 2 August 2028 as regards AI systems classified as high-risk pursuant to Article 6(1) and Annex I;

Recital 40 of Regulation (EU) 2026/1744 gives the same two dates. Article 12 sits in
Chapter III Section 2; Articles 19 and 26 sit in Section 3. The roadmap's statement
that Annex III obligations moved to 2 December 2027 is therefore **confirmed** on
EUR-Lex; no correction to the plan was needed on the date. (The plan cited secondary
sources; this document and `.plan/README.md` now cite EUR-Lex.)

Other dates read in the same texts:

- Regulation (EU) 2026/1744 was published in the Official Journal on 24 July 2026 and
  enters into force on the third day after publication. The consolidated text is
  dated 2026-07-27, and Article 113, third paragraph, point (d), as amended, sets
  27 July 2026 for Articles 102 to 110.
- The general date of application of Regulation (EU) 2024/1689 remains 2 August 2026
  in the base text of Article 113, which the amendment does not replace.
- Articles 12, 19 and 26 carry no amendment marker in the consolidated text:
  Regulation (EU) 2026/1744 did not change their wording. It did amend Article 72(3)
  (guidance and template on the post-market monitoring plan, due by 2 September 2027,
  instead of an implementing act).

Whether any given AI-assisted decision involves a system "classified as high-risk
pursuant to Article 6(2) and Annex III" is a classification this document does not make.

### Provision text used

Quoted from the consolidated text above. EUR-Lex remains authoritative for the
exact wording.

**Article 12(1)**: "High-risk AI systems shall technically allow for the automatic
recording of events (logs) over the lifetime of the system."

**Article 12(2)**: "In order to ensure a level of traceability of the functioning of
a high-risk AI system that is appropriate to the intended purpose of the system,
logging capabilities shall enable the recording of events relevant for:
(a) identifying situations that may result in the high-risk AI system presenting a
risk within the meaning of Article 79(1) or in a substantial modification;
(b) facilitating the post-market monitoring referred to in Article 72; and
(c) monitoring the operation of high-risk AI systems referred to in Article 26(5)."

**Article 12(3)** sets minimum logging content only for high-risk AI systems referred
to in Annex III, point 1(a) (period of each use, reference database, matched input
data, identification of the persons verifying results). None of the records here is
designed for such systems, and paragraph 3 is not mapped below.

**Article 19(1)**: "Providers of high-risk AI systems shall keep the logs referred to
in Article 12(1), automatically generated by their high-risk AI systems, to the
extent such logs are under their control. Without prejudice to applicable Union or
national law, the logs shall be kept for a period appropriate to the intended purpose
of the high-risk AI system, of at least six months, unless provided otherwise in the
applicable Union or national law, in particular in Union law on the protection of
personal data." Article 19(2) concerns providers that are financial institutions.

**Article 26(6)**: "Deployers of high-risk AI systems shall keep the logs
automatically generated by that high-risk AI system to the extent such logs are
under their control, for a period appropriate to the intended purpose of the
high-risk AI system, of at least six months, unless provided otherwise in applicable
Union or national law, in particular in Union law on the protection of personal
data." Article 26(5) (cross-referenced by 12(2)(c)) requires deployers to monitor
operation on the basis of the instructions for use, to inform providers in
accordance with Article 72, and in defined cases to inform the provider or
distributor and the market surveillance authority, to suspend use, and to report
serious incidents.

**NIST AI 100-1, MANAGE 4.1**: "Post-deployment AI system monitoring plans are
implemented, including mechanisms for capturing and evaluating input from users and
other relevant AI actors, appeal and override, decommissioning, incident response,
recovery, and change management."

**ISO/IEC 42001:2023, A.6.2.8**: title "AI system recording of event logs" only; see
the source table.

## Mapping by record type

Record names and schema numbers follow
[Records and checks](DECISION_RECORDS.md#records-and-checks). Field names are the ones
the shipped packages write today. "-" means no field serves the provision.

| Record | Art. 12(2)(a): risk situations, substantial modification | Art. 12(2)(b): post-market monitoring (Art. 72) | Art. 12(2)(c): deployer monitoring (Art. 26(5)) | Retention (Art. 19 provider, Art. 26(6) deployer) | ISO/IEC 42001 A.6.2.8 | NIST MANAGE 4.1 | Does not cover |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **expgate `decision.json`** (schema 2) and `DECISION.md` | `decision` (SHIP/HOLD/ROLLBACK/INVALID), `reasons`, `metrics[].status` and `improvement_bounds` for guardrails, `sample_ratio.pass` flag a change that failed its predeclared guardrails before release | `experiment`, `policy`, `metrics`, `produced_by`, `expgate_version` give a comparable per-change data point a monitoring process could ingest | - | `input` embedded with `input_sha256`, `schema_version` and `DECISION.md`'s SHA-256 of the `decision.json` bytes let a holder detect later edits and pick the verifier rules | Not assessed (control text not reviewed). Fact: one aggregate record per evaluation, with no event times | `decision`, `policy` and `input_sha256` document one change-management gate: what was evaluated and under which thresholds | No timestamp or event time in the record. Aggregate summary only, no per-use events. Does not say whether a change is a substantial modification. Input provenance is the caller's. `produced_by` is a label, not an authenticated identity. No retention period, deletion, access control or legal hold |
| **Jev typed answer** (CLI JSON, schema 1) | `answers[*]` of type `refusal`, and choice/score/`noul` `probabilities`, expose uncertainty or refusal per question | `model`, `backend`, `id`, `usage`, `produced_by` identify the response that fed a decision | - | None beyond being a JSON file: no digest, no checksum, no verifier | Not assessed (control text not reviewed). Fact: one model response, with no timestamp | - | No timestamp, no input/question text, no digest, no standalone verifier. `model`, `backend` and `id` are supplied metadata; nothing authenticates provider origin. Not a log of every use. No retention handling |
| **Jev `evaluation.json`** (schema 2) with **`provenance.json`** (schema 2), `responses.jsonl`, `cases.jsonl` | `status` (PASS/FAIL/UNGATED), `error_rate`, `errors`, per-question `refusal_rate`, `refusals`, accuracy bounds, `requirements[].pass` show measured quality against stated requirements on labeled cases | `jevdecision_version`, `produced_by`, `model`, `backend`, `source` (replay/live) and `cases` let the same labeled cases be re-scored later and compared | - | `provenance.json` records SHA-256 of exact input and output bytes (`inputs.*.sha256`, `outputs`), so retained files can be re-checked; `response_origin` states whether responses were hand-supplied; original questions, cases and requirements stay external and must be retained separately | Not assessed (control text not reviewed). Fact: offline scoring record, with no timestamps | A repeatable evaluation artifact usable as an input to change management and periodic re-evaluation; nothing here implements monitoring | Offline scoring of saved responses, not runtime events. No timestamps. No record-only provenance verifier; re-scoring needs the retained inputs. `provenance.json` hashes detect change and do not authenticate authorship. Labeled cases and raw responses may contain personal data; minimisation and erasure are the keeper's concern. Synthetic fixtures show software behavior, not live-model quality |
| **decision-control exported record** `record-*.json` (schema 3; schemas 1 and 2 replay under their original rules) | `evaluation.verdict` and `evaluation.reasons` (ALLOW/REVIEW/ABSTAIN/DENY), `recommendation.refused`, `recommendation.probability`, `status` (e.g. CANCELLED, STALE) | `created_at`, `events[].at`, `policy.version`, `policy_sha256`, `recommendation.model`, `recommendation.question_version` give a dated, policy-pinned data point per decision | `review.decision`, `review.reviewer`, `review.note`, `review.at`; `events` including `CANCELLED` (a reversed approval stays on record); `result` shows what was executed | Checksum over the whole record (`sha256`) plus embedded policy, ticket snapshot, review and events make an exported file self-contained and change-evident; the working store is a mutable SQLite file and only exports carry the checksum | Not assessed (control text not reviewed). Fact: the only record here with timestamped events (`events[].at`, `review.at`), one record per decision, written by the workflow and not by an AI system | `review` (human approval or denial before execution), `CANCELLED` (reversal of an earlier approval), `policy.reviewers` and `policy_sha256` evidence an approval, override and change-control step for one decision | Timestamps come from the local clock (UTC) with no trusted time source. `proposed_by`, `review.reviewer` and `produced_by` are caller-asserted labels: identity is not authenticated and nothing is signed. Does not capture user or affected-person input, appeals, incident response, serious-incident reporting, decommissioning or recovery. Does not detect a deleted or withheld record. No hash chain across records. Replay executes nothing. No retention period, deletion or legal hold |
| **decision-control `evaluation.json`** (schema 1, `report` + `sha256`) | `metrics` (e.g. `unsafe_auto_allow_rate`, `incorrect_approval_rate`, `required_review_recall`), `gates`, `disposition` on labeled cases | `kind`, `source`, `cases`, `confidence_level`, `policy`, `requirements` allow the same cases to be re-evaluated against a changed policy | - | Canonical `sha256` over `report`; replay recomputes the report from the embedded content | Not assessed (control text not reviewed). Fact: offline report, with no timestamps | A policy-evaluation report usable as change-management evidence before a policy or model change | No `produced_by` and no timestamps in this schema. Offline evaluation of supplied cases, not runtime events. Labeled cases are the caller's. Checksum is not a signature. No retention handling |

### Reading the table

- **12(2)(a)** and **12(2)(c)** concern events from operating a high-risk system. Only
  the decision-control exported record carries per-decision, time-stamped lifecycle
  events (`events`, `review`), and those describe the approval workflow around a
  recommendation, not events inside an AI system. The evaluation records describe
  measured quality on labeled cases and say nothing about events during use.
- **12(2)(b)** concerns data that supports a provider's post-market monitoring system
  under Article 72. The records contribute re-scorable, hashed data points. They are
  not a monitoring plan (Article 72(3)) and not an incident report (Article 73).
- **Retention** is a duty of the provider (Article 19) or deployer (Article 26(6)) for
  logs "under their control", and the period depends on the intended purpose and other
  law, including data protection law. The packages produce files and offer integrity
  checks over them; storing, retaining, protecting and deleting them is outside the
  packages.
- **ISO/IEC 42001 A.6.2.8**: the control text was not reviewed (see the source
  table), so no statement is made about what it requires or whether any record could
  serve it. The column lists only facts about each record, in particular whether it
  carries event times. Only the decision-control exported record does.
- **MANAGE 4.1** lists mechanisms (input from users and other actors, appeal and
  override, decommissioning, incident response, recovery, change management). The
  records can evidence the override and change-management items for the decisions they
  cover. They do not implement any monitoring plan.

## What none of the records cover

These apply across the table and are stated once here.

- **Identity authentication without signing.** Producer, model, proposer and reviewer
  are labels. No record is signed, so a record can be rewritten with a recomputed
  digest. Optional authenticated records are planned under P-012; until they ship,
  nothing here binds a record to a person or system.
- **System-level logging.** The records are not the automatic event logs of an AI
  system (Article 12(1)), do not record each use, and carry none of the Article 12(3)
  items.
- **Retention enforcement.** No retention period field, deletion policy, backup,
  access control, encryption, legal hold or personal-data erasure workflow exists.
- **Completeness and ordering.** Nothing shows that every decision produced a record,
  that no record was removed, or that records are in order across runs. There is no
  hash chain or transparency log.
- **Trusted time.** Only decision-control records timestamps, from the local system
  clock. expgate and Jev records have none.
- **Provider origin.** No record authenticates that a model response came from a
  named provider. Jev's `response_origin` states this limit.
- **Operator duties.** Instructions for use, human-oversight assignment, informing
  providers or authorities, suspension of use and serious-incident reporting
  (Articles 26 and 73) are organisational processes that the records do not perform
  or evidence.
- **Evidence of real-world use.** Hand-written and synthetic fixtures establish
  software behavior, not live-model quality, calibration, adoption or production use.
- **RELIA.** The reliability benchmark (`results.json`, `MANIFEST.json`) is outside
  this mapping. It is a synthetic comparison, not a decision record.

## Maintenance

Update this document when a schema version, record field or application date
changes. In particular: the JCS and JSON Schema work in P-011, signed records in
P-012, and any amendment to Regulation (EU) 2024/1689 after the 2026-07-27
consolidated version. Re-check the NIST AI RMF text when NIST publishes its revision
(on 2026-10-19, <https://airc.nist.gov/airmf-resources/airmf/> states that AI RMF 1.0
"is being updated"; this document uses AI RMF 1.0 as published in January 2023).
Re-read the ISO/IEC 42001 control from a
licensed copy before describing it in more detail.
