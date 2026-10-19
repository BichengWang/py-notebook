# Pilot protocol (template)

This is a template. Copy it, fill every `[bracketed]` field, and have both parties
sign it **before any result is produced or looked at**. Nothing in this repository
shows that a pilot has been run, agreed or offered to a named team; a completed
copy is the only evidence that one exists (Plan ID P-027; the run and its
published record are P-032 in the [plan](../.plan/phase-3-external-evidence.md)).

A pilot runs one reference package on one of the team's own decisions and records
what happened, whatever it shows. The packages are standard-library tools that
write and re-check [decision records](DECISION_RECORDS.md). A successful check
shows the record is internally consistent under the verifier's rules. It does not
authorize a deployment, authenticate who produced an input, or show that the
decision was right.

## How to use this template

1. Fill sections 1 to 11. Leave nothing blank: write `none` or `not applicable` and why.
2. Freeze: the maintainer commits the filled copy to a git repository both parties
   can read, tags it `pilot/<team-slug>/v1`, and both sign section 12 with the
   tag's commit ID.
3. Only after both signatures are dated may the team send data to, or run, the
   package. Results produced earlier are not covered by this protocol and may not
   be described as a pilot.
4. After the run, fill section 13 and follow sections 8 and 9 for publication.

A first result is never deleted or replaced (section 10).

## 1. Parties and contacts

| Role | Name | Organization | Contact | Date of agreement to participate |
| --- | --- | --- | --- | --- |
| Pilot team lead (owns the decision) | [ ] | [ ] | [ ] | [ ] |
| Pilot team data owner (releases inputs) | [ ] | [ ] | [ ] | [ ] |
| Project maintainer | Bicheng Wang | ai-decision-system | [contact] | [ ] |
| Analyst (runs the package; may be either party) | [ ] | [ ] | [ ] | [ ] |
| Anyone else with access to inputs or results | [ ] | [ ] | [ ] | [ ] |

Relationships and interests, each party: [employment, funding, referral path,
compensation, equity or any other interest in the outcome, or `none`]. Record
here whether the team has contributed to or modified the package; if it has, the
result is not an independent evaluation of that part.

## 2. Decision point and package

One decision point, one package. A pilot that needs two packages is two pilots.

| Field | Entry |
| --- | --- |
| Decision being recorded (one sentence: who decides what, between which outcomes) | [ ] |
| Who or what proposes the outcome, and who may overrule it | [ ] |
| Period covered and the unit counted (experiments, tickets, questions) | [ ] |
| Is the decision made by the team regardless of this pilot? | [yes / no; if no, say what changes] |
| Package | [`expgate` / `jevdecision` / `decisioncontrol`] |
| Package version, exact | [ ] |
| Source commit and tag | [tag such as `experiment-gate/v0.2.0` and the 40-character commit ID] |
| Installed from | [PyPI with artifact SHA-256 / source checkout at the commit above] |
| Python version and operating system | [ ] |
| Verification command the team will run | [see below] |

Choose the package by the decision, not by preference:

| Package | Fits a decision of | Needs from the team | Check |
| --- | --- | --- | --- |
| [`expgate`](../ai-workflows/experiment-gate/README.md) | Ship, hold or roll back a model or change that is already in an online A/B test | The aggregate summary the experimentation platform exports (units per arm, successes or mean and standard deviation per metric), the design's expected split, and the primary and guardrail metrics | `experiment-gate-verify decision.json` |
| [`jevdecision`](../ai-workflows/jev-decision/README.md) | Whether typed model answers meet requirements on labeled cases | Questions, labeled cases, saved model responses, and requirements fixed in advance | `jev-decision-eval ... --out new-replay`, then compare metrics and digests |
| [`decisioncontrol`](../ai-workflows/decision-control/README.md) | Whether a recommended action is allowed, needs review, or is denied, and who approved it | A recommendation, the item it acts on, a policy, and named proposer and reviewer | `decision-control replay --record record-review.json` |

Exact flags are in each package README and in [Decision record conventions](DECISION_RECORDS.md#records-and-checks).
The package does not call the team's systems. The team exports a file; the
package reads it.

## 3. Inputs and data handling

Be specific about what leaves the team. The default is the minimum a verifier needs.

| Item | Leaves the team? | Form | Who sees it | Retention and deletion |
| --- | --- | --- | --- | --- |
| Raw event or user-level data | no | [ ] | team only | stays in the team's systems |
| Aggregate or derived input the package reads (the file itself) | [yes / no] | [file name, schema, example of one field] | [ ] | [date or event after which copies are deleted] |
| Policy / requirements / questions file | [yes / no] | [ ] | [ ] | [ ] |
| Decision records the package writes | [yes / no] | `decision.json`, `evaluation.json`, `record-*.json` or equivalents | [ ] | [ ] |
| Logs and error output | [yes / no] | [ ] | [ ] | [ ] |
| Anything else (screenshots, notes, calls) | [ ] | [ ] | [ ] | [ ] |

Records embed their inputs by design: an `expgate` record contains the aggregate
input, and a `decisioncontrol` record contains the recommendation and the ticket
snapshot. A record that is published contains whatever its input contained.
Before the freeze, the data owner confirms for each item that it contains no
personal data, credentials, customer identifiers or confidential figures beyond
what section 8 allows, or states the redaction applied and who verified it.

- Redaction method, if any: [ ]. Redaction changes the input, so the digest
  then covers the redacted input; say that in the published record.
- Where analysis runs: [team machine / maintainer machine / either]. The
  commands in section 4 read exported files. `jevdecision` calls a model
  provider only in its live mode; a pilot uses saved responses unless section 4
  says otherwise and names the provider and its data terms.
- Sharing channel: [ ]. Retention by the maintainer: [period, then deletion,
  confirmed in writing]. Records the team agreed to publish are not deleted
  (section 8).

## 4. Policy and thresholds, frozen before results

Everything that can change the outcome is written here or in a file listed
here, **before** the team's first exported input is read by anyone outside the
team. Attach the files to the tagged commit.

| Frozen item | Value or file | SHA-256 of file |
| --- | --- | --- |
| Policy / thresholds file | [ ] | [ ] |
| Metric definitions and the primary metric | [ ] | [ ] |
| Significance level, margins, minimum sample, power (`expgate`) | [e.g. `alpha`, `srm_alpha`, guardrail `margin`] | [ ] |
| Requirements and gate values (`jevdecision`) | [ ] | [ ] |
| Policy, allowed action types and reviewer rule (`decisioncontrol`) | [ ] | [ ] |
| Population, period and exclusion rules | [ ] | [ ] |
| Analysis commands, in order, with every flag | [ ] | [ ] |
| Verification commands, in order | [ ] | [ ] |
| Signing option and predicate type (section 6) | [`none` / `hmac` / `sigstore`; predicate type URL] | not applicable |
| Package source commit (section 2) | [40-character ID] | not applicable |
| Date and time this section was frozen | [ ] | not applicable |

Rules for thresholds:

- Thresholds come from the team's own decision rule, written before the data
  exist. If the team has no rule, the protocol uses the package default and says so.
- Nobody may tune a threshold after seeing a result. A change is an amendment
  (section 10).
- A stopping rule for experiments is stated here. If results are looked at while
  the test runs, the protocol names the sequential method or says that early
  looks are not used for the decision.

## 5. Outcomes: success, failure, null

Define these before results. Two kinds of outcome are separate: what the
package decided about the team's decision, and whether the pilot itself worked.

**Decision outcome** (what the record says): the package's own result, for
example `SHIP`, `HOLD`, `ROLLBACK`, `INVALID`; `PASS`, `FAIL`, `UNGATED`;
`ALLOW`, `REVIEW`, `DENY`, `ABSTAIN`. A `HOLD` or `FAIL` is a valid result, not
a failed pilot.

**Pilot outcome** (whether the record was useful to the team). Fill each entry
with a measurable statement:

| Outcome | Definition for this pilot |
| --- | --- |
| **Success** | [e.g. the team can re-run the verification command from the frozen files and gets exit 0; the team's reviewer states in writing whether the record would have been sufficient for audit or review of this decision; the package's decision agrees or disagrees with the team's own decision, and the reasons in the record explain any difference] |
| **Failure** | [e.g. the record cannot be produced from the team's export without changing the package or the input after the freeze; verification fails on the team's machine for a reason in the package; the record omits something the team needed to justify the decision] |
| **Null** | [e.g. the record is produced and verifies but the team states it gave no help beyond its existing process; or the decision was not made in the period] |
| **Not run** | [e.g. data not released, decision point did not occur by the date below; a dated reason is recorded and published only if section 8 allows] |

Record the comparison the team cares about: the team's own decision on the same
case [if one exists], the package's decision, and whether they agree. Agreement
is not evidence of correctness; disagreement is not evidence of an error in
either. Say how disagreements are examined (who, by when) before the run.

Deadline for the decision to occur and the run to finish: [date].
A run that has not finished by [date] is recorded as `not run`.

## 6. Signed records (optional)

Records detect change. They do not detect forgery or authorship: someone who edits
an input can recompute its digest. A signature adds who vouched for the record.
Signing is available only if the package version fixed in section 2 ships it
(plan item P-012; not shipped at the time of drafting), so check that version's
README and `SECURITY.md` before choosing; if the pinned version does not ship
signing, choose `none`.

Format, when shipped: an in-toto Statement v1 in a DSSE envelope, one predicate
type per record type and schema version
(`https://github.com/BichengWang/ai-decision-system/predicate/<package>/<record>/v<N>`).
The statement's subject is the SHA-256 of the record file's exact bytes. Write
the predicate type and the signing option into section 4 of the frozen protocol.

| Option | What it gives | Trade-off |
| --- | --- | --- |
| `none` | Digest check only | Anyone with the file can edit and re-hash |
| `hmac` (default when signing is shipped) | In-package keyed HMAC-SHA256 over the DSSE envelope, standard library only; a shared secret key proves the record came from a key holder | Both sides need the same secret; no third party can verify it without that secret; key custody is on the team |
| `sigstore` | Signature through external `cosign` (`cosign attest-blob`, checked with `cosign verify-blob-attestation`), verifiable by identity | Sigstore entries are public and permanent: the signed digest, identity and time become visible, including for rejected or null results. Use only if section 8 allows publication of those facts |

Chosen option: [ ]. Key custody (who generates, stores, rotates): [ ].
Where verification keys or trusted identities are recorded: [ ].
A key or identity is part of the frozen protocol; changing it is an amendment.

## 7. Disclosures

Modeled on the reproduction report form in
[RELIA's reproduction guide](../ai-workflows/ai-decision-reliability/docs/REPRODUCE.md#reproduction-report-form).
The analyst and the team lead each complete one column before the freeze;
environment details are completed again after the run.

| Field | Team | Maintainer |
| --- | --- | --- |
| Name, title, organization | [ ] | [ ] |
| Relationship, referral path, compensation, financial or other interest | [ ] | [ ] |
| Did this party author or modify any part of the package? If yes, say which; do not describe the run as independent | [ ] | [ ] |
| Machine and account: has it held this package before? basis | [ ] | [ ] |
| Environment (hardware, OS, architecture, Python, package version and artifact SHA-256, lock or dependency list) | [ ] | [ ] |
| Exact commands run, in order; package-manager cache used? | [ ] | [ ] |
| Assistance received from the other party (every clarification, fix or call, with date) | [ ] | [ ] |
| Retries, restarts, warnings, failures, deviations from this protocol, and how each was resolved | [ ] | [ ] |
| Deviations, defects or unclear definitions found in the package or this protocol | [ ] | [ ] |

A disclosure may be amended after the freeze, but the earlier entry is kept and
the amendment is dated.

## 8. What may be published

The default is that **every outcome is published**: positive, negative or null,
including `INVALID`, `ROLLBACK`, `FAIL` and `not run`. The maintainer does not
choose which results appear. The team may decline to have its identity or its
data published; it may not later request that only favorable results appear.

Fill each row before the freeze:

| Item | Published? | Form | Conditions |
| --- | --- | --- | --- |
| Team name and organization | [named / described generically / no] | [ ] | [ ] |
| This protocol and its tag | [yes / redacted copy] | [ ] | [ ] |
| Decision records the package wrote | [yes / digest and summary only / no] | [ ] | [ ] |
| Inputs inside those records | [yes / redacted / no] | [ ] | [ ] |
| Outcome (section 5), including unfavorable or null | yes | [ ] | [ ] |
| Disagreements between the package and the team's own decision | [yes / summary] | [ ] | [ ] |
| Team's written comments or quotes | [only with quote-level approval] | [ ] | [ ] |
| Publication venue and place | [repository `docs/` / release asset / paper / other] | [ ] | [ ] |

**Permission step.** Before anything is published, the maintainer sends the team
the exact text and files. The team has [10] working days to respond. The team may
(a) approve, (b) approve with further redactions, or (c) withdraw permission
for identity or data. Withdrawal of identity does not remove the outcome: the result
is published without the team's name. Silence is not approval of anything that
goes beyond the table above. The approval is written, dated and committed with
the published record.

If permission for identity is withdrawn, the maintainer publishes the outcome
without naming the team, unless the team shows that the outcome cannot be
described without identifying it; in that case the parties record what was
agreed and the reason. Nothing is claimed beyond what the records and the team's
written statements show: not adoption, not production use, not compliance, not
performance outside the pilot's data.

## 9. Evidence rules

- Records produced from synthetic, example or hand-written inputs are not a pilot
  result, and are never relabeled as one.
- A pilot result describes one decision point over one period. It does not
  establish model quality, calibration, fairness, legal compliance, commercial
  benefit or production safety.
- No result is backdated. Each record, signature, approval and amendment carries
  the date it was made.

## 10. Amendments

- The protocol is frozen when section 12 is signed. After that, **any change**
  (policy, thresholds, population, package version, commands, outcome
  definitions, publication terms, signing option) is an amendment.
- An amendment is a new protocol version (`pilot/<team-slug>/v2`, and so on),
  signed by both parties and dated, stating what changed and why, and whether it
  was made before or after any result existed.
- The **first result is preserved**. A result produced under v1 is published as
  a v1 result even if v2 exists. A rerun under v2 is an additional result, labeled
  with its version and the reason; it does not replace v1.
- If a change is made after results exist, the amendment says which result had
  been seen. It does not hide an earlier version.
- A defect found in the package after the freeze is recorded with the version
  and commit; the pilot continues on the pinned version unless both parties
  agree to amend.

## 11. Termination

Either party may stop at any time before inputs are shared. After they are
shared, stopping is recorded as `not run` or as the partial outcome defined in
section 5, and section 8 applies. Data handling and deletion in section 3 survive
termination.

## 12. Sign-off

By signing, each party confirms that: sections 1 to 10 are filled; the policy and
thresholds in section 4 were fixed before any result existed; no result had been
produced or seen when this was signed; and the signer is authorized to agree for
their organization.

Frozen text: git tag `pilot/[team-slug]/v1`, commit [40-character ID], protocol
SHA-256 [ ].

| Party | Name and title | Signature | Date (YYYY-MM-DD) |
| --- | --- | --- | --- |
| Team lead | [ ] | [ ] | [ ] |
| Team data owner | [ ] | [ ] | [ ] |
| Maintainer | [ ] | [ ] | [ ] |

Signatures made after the first result existed are not sign-off for this
protocol. The signing date must precede the first data transfer in section 3.

## 13. Completed after the run

Fill this part after the run. Do not edit sections 1 to 12.

| Field | Entry |
| --- | --- |
| Date data were first shared; date of first run | [ ] |
| Package version and commit actually used (equal to section 2?) | [ ] |
| Records produced (file names, SHA-256) | [ ] |
| Verification result and exit code on the team's machine | [ ] |
| Decision outcome (section 5) | [ ] |
| Pilot outcome: success, failure, null or not run, and the reason | [ ] |
| Comparison with the team's own decision | [ ] |
| Amendments made, with dates and whether results had been seen | [ ] |
| Permission step: date sent, date answered, answer | [ ] |
| Where published | [ ] |
| Limits and unverified claims | [ ] |
