# Medium draft

Draft for the owner to rewrite in their own words and publish from their own Medium
account. Nothing here has been published. Do the
[checklist](README.md#before-posting-owner-checklist) first, and paste the demo
transcript from the milestone's tracking issue (opened by the [trigger](README.md#trigger))
where the story marks it.

Rules checked 2026-10-22:

- Medium's [AI content policy](https://help.medium.com/hc/en-us/articles/22576852947223-Artificial-Intelligence-AI-content-policy)
  requires a story that incorporates AI assistance to say so within its first two
  paragraphs. Undisclosed AI-assisted text is limited to the author's own network,
  and AI-generated writing may not go behind the Partner Program paywall. Rewrite
  the story yourself; if AI assistance remains, add the disclosure.
- Medium [no longer issues API integration tokens](https://help.medium.com/hc/en-us/articles/213480228-API-Importing),
  so the trigger cannot publish here. Publish in the Medium editor: copy the
  rendered Story section below from GitHub, paste it, and check that the code
  blocks and links survived.

## Title

```text
Can you recompute an AI go/no-go decision six months later?
```

## Subtitle

```text
Small, offline-verifiable records for experiment promotions, model answers and approved actions
```

## Story

Someone asks why a model was shipped in March. The experiment dashboard now shows
numbers recomputed on newer data, the thresholds in the config have been edited
since, and the approval is a tag in a model registry that anyone with write access
can move. You can say what the systems show today. You cannot recompute what was
decided then.

I have been building small open-source tools for that gap. They write a decision
record: the inputs, the frozen rules and the result of one go/no-go decision, so
that someone else can recompute the decision offline and get the same answer, or
find out that they cannot.

### What a record holds

A record is a JSON file with the decision's full input, the policy it was judged
under, the result, and a digest over an RFC 8785 canonical form, so the digest can
be recomputed in any language. A verifier re-derives the decision from the record
alone, with no network, and exits non-zero when anything disagrees. Three
standard-library Python packages write and verify records at three decision
points:

- **expgate** takes the aggregates an A/B testing platform exports and writes
  SHIP, HOLD, ROLLBACK or INVALID (sample-ratio mismatch).
- **jevdecision** records a typed model answer and its offline evaluation.
- **decisioncontrol** records a policy-gated action with human approval; the
  proposer cannot approve their own action.

Records can be signed: an in-toto Statement in a DSSE envelope, with a shared HMAC
key by default, or Sigstore through `cosign` if you choose a public transparency log.

### A one-minute demo

Sign a set of synthetic scenarios, edit one record, and check again:

```text
[Paste the demo transcript from the milestone's tracking issue here, unedited.]
```

The edited record fails with `signature covers different record bytes` and exit
code 1. The more interesting case is a forgery made with the real tool: change the
input, re-derive the whole record, and the digest check and the replay both pass,
because the record is internally consistent. Only the signature, which binds the
exact bytes of the file to the key, exits 1. The
[full run](https://github.com/BichengWang/ai-decision-system/blob/main/docs/launch/README.md#the-demo-as-run)
shows it step by step.

### What a passing check does not prove

- A passing check shows the record is internally consistent under the verifier's
  rules. It does not show the decision was right, and it does not authorize a
  deployment.
- It does not show the experiment summary behind it is true; the inputs are
  whatever the producer supplied.
- An HMAC signature shows the signer held the shared secret. It is not an
  identity: every verifier holds the same key and so could also sign.
- It is not compliance evidence or a legal opinion.
- The bundled scenarios are synthetic. They are software checks, not adoption
  evidence.

### Where it fits

The tools you already use keep parts of a decision, not a record you can replay.
OPA decision logs carry the input, the result and the bundle revision, but they
are neither signed nor hash-chained, and fields can be masked
([OPA docs](https://www.openpolicyagent.org/docs/management-decision-logs)). MLflow
approvals are mutable tags and aliases
([MLflow docs](https://mlflow.org/docs/latest/ml/model-registry/)). in-toto's
verification summary predicate "does not include information for reproducing the
verification result" ([SVR](https://github.com/in-toto/attestation/blob/main/spec/predicates/svr.md)).
LangGraph approvals are checkpointed state, not evidence
([interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)).

So the records complement those tools rather than replace them: signing comes from
in-toto and Sigstore, policy from OPA or Cedar, statistics from the experiment
platform, workflow from LangGraph. 0.2.0 ships a GrowthBook results importer, OPA
and Cedar adapters, and an example that maps LangGraph interrupt approvals onto
decisioncontrol.

The EU AI Act's Article 12 requires automatic event logs for high-risk systems
without prescribing a format. That does not make these records compliance
evidence. It does make "which inputs and which rules produced this decision" a
question auditors will ask; the
[regulatory mapping](https://github.com/BichengWang/ai-decision-system/blob/main/docs/REGULATORY_MAPPING.md)
says what a record covers and what it does not.

### Try it

```text
pip install "expgate>=0.2.0"
```

The code, the schemas and the conformance vectors are at
[github.com/BichengWang/ai-decision-system](https://github.com/BichengWang/ai-decision-system).
If you run model or experiment release gates, I would like to know which of your
decisions this record could not hold.

## Notes for the owner

- Paste the transcript only from a run of the release you are announcing; the key
  id changes on every run and the record hashes change with the package version.
- Do not add a count of stars, forks, views or downloads, or a claim about users.
- Suggested tags: MLOps, Machine Learning, AI Governance, Python, Open Source.
