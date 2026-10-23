# GitHub Discussions announcement draft

Template that the [trigger](README.md#trigger) fills in when a milestone in
[`milestones.json`](milestones.json) is reached. `{{releases}}` becomes links to the
PyPI pages and GitHub Releases it checked, `{{demo}}` the demo transcript of that run
and `{{demo_note}}` where and when the demo ran. The filled text goes into the
milestone's tracking issue; the announce job posts the issue's text to the
Announcements category once the owner has edited it there and approved the
`outreach` deployment. Nothing has been posted.

Discussions is this repository's own channel, so the venue rules that ask for text
you wrote yourself (Hacker News, r/mlops) do not apply. The claim rules of the
[kit](README.md#what-every-post-says) do.

## Post

````text
Version 0.2.0 of expgate, jevdecision and decisioncontrol is on PyPI:

{{releases}}

The three packages write decision records for AI-assisted go/no-go decisions: an experiment promotion, a typed model answer and a policy-gated action with human approval. A record holds the inputs, the frozen rules and the result, so someone else can recompute the decision offline. 0.2.0 adds JSON Schemas with conformance vectors, optional signed records (an in-toto Statement in a DSSE envelope), a record-only verifier for jevdecision answers, a GrowthBook results importer, OPA and Cedar adapters, and an example that maps LangGraph interrupt approvals onto decision-control. Each release's notes list the rest.

Sign a set of synthetic scenarios, edit one record, and check again:

```text
{{demo}}
```

{{demo_note}}

What a passing check does not prove:

- A passing check shows the record is internally consistent under the verifier's rules. It does not show the decision was right, and it does not authorize a deployment.
- It does not show the experiment summary behind it is true; the inputs are whatever the producer supplied.
- An HMAC signature shows the signer held the shared secret. It is not an identity: every verifier holds the same key and so could also sign.
- It is not compliance evidence or a legal opinion.
- The bundled scenarios are synthetic. They are software checks, not adoption evidence.

If you run model or experiment release gates and one of your decisions would not fit these records, reply here or open an issue.
````
