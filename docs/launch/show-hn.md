# Show HN draft

Draft for the owner to rewrite in their own words and post. Nothing here has been
posted. Do the [checklist](README.md#before-posting-owner-checklist) first, and
replace the demo block with output from the release you are posting.

Rules checked 2026-10-19 at [Show HN guidelines](https://news.ycombinator.com/showhn.html)
and the [site guidelines](https://news.ycombinator.com/newsguidelines.html):

- Show HN is for something people can run: a git clone and one `pip install`
  qualifies. Blog posts and landing pages do not.
- Project you worked on personally and will be around to discuss.
- Do not put generated text in a post; write it yourself. Do not ask anyone to
  upvote or comment. Do not delete and repost.
- Submit the original source: the repository URL, not an article about it.

## Title (77 characters)

```text
Show HN: Recompute an A/B ship/rollback decision offline, with signed records
```

## URL

```text
https://github.com/BichengWang/ai-decision-system/tree/main/ai-workflows/experiment-gate
```

## First comment

Post it right after submitting.

````text
Why I built this: a ship or rollback call on a model in an A/B test often
survives as a dashboard state or a log line. Months later you can't recompute it:
the inputs have moved, the thresholds were edited, the approval was a mutable tag.

expgate takes the aggregates your experiment platform exports (units per arm,
successes or mean and sd per metric) and writes decision.json: SHIP / HOLD /
ROLLBACK / INVALID (sample-ratio mismatch), the frozen policy, the full input and
a digest of it. experiment-gate-verify recomputes the decision from that input
with no network. It is Python 3.11+, standard library only. Records can be
signed: an in-toto Statement in a DSSE envelope, HMAC key by default, Sigstore
through cosign if you opt in (that writes to a public log).

0.1.0 is on PyPI, but this signed-record demo needs unreleased 0.2.0.
Install and verify from a clone until then:

    pip install ./ai-decision-system/ai-workflows/experiment-gate
    experiment-gate-verify review-run/*/decision.json --require-signature --key signing.key

What I ran, unedited:

    $ git clone --quiet https://github.com/BichengWang/ai-decision-system.git && git -C ai-decision-system rev-parse --short HEAD
    44e3519
    $ python3 -m venv .venv && . .venv/bin/activate
    $ pip install --quiet ./ai-decision-system/ai-workflows/experiment-gate
    $ experiment-gate keygen signing.key
    {
      "key_file": "signing.key",
      "key_id": "hmac-sha256:1981ba6cb5d68a4b"
    }
    $ experiment-gate --all-scenarios --out review-run --sign-key signing.key
    cuped: HOLD 37973c767a4265a4a87b92b2b3eff73d0ba1fad912f1a74211c4f37219b04789
    early-regression: ROLLBACK 3ff09f7c0e673475600a8791b50a6de1d35a3b0cae137f21ae9c9c73ff84cbf6
    flat: HOLD 9b40598f1374d57ec3352aec328b29337fef0069f8f0ff49b2560e6b6ea4ddd4
    guardrail-breach: ROLLBACK 619380333c81df2aa03371cf35426f6fb92d3a3f36e7a878cddb614c66f455e4
    regression: ROLLBACK fd57cfd34dd2e3e8eceff79cf8b6171143a9da9426a302cc12b3427a6aa92b1b
    srm: INVALID adb4b16cd36a0565004fd6bfcb3a7486b59b211013effa9d9d20adbc24ae8f0d
    win: SHIP 563c56b0fead3034182bfed5a77e5666cb263e2814a59e4ac39d650482bee4c8
    $ experiment-gate-verify review-run/*/decision.json --require-signature --key signing.key; echo "exit code: $?"
    review-run/cuped/decision.json: verified
    review-run/early-regression/decision.json: verified
    review-run/flat/decision.json: verified
    review-run/guardrail-breach/decision.json: verified
    review-run/regression/decision.json: verified
    review-run/srm/decision.json: verified
    review-run/win/decision.json: verified
    exit code: 0
    $ sed -i.bak 's/"decision": "HOLD"/"decision": "SHIP"/' review-run/flat/decision.json
    $ experiment-gate-verify review-run/flat/decision.json --require-signature --key signing.key; echo "exit code: $?"
    review-run/flat/decision.json: signature: signature covers different record bytes
    exit code: 1

What a passing check does not prove: that the decision was right, that the
numbers you exported are true, or who signed (an HMAC key is shared, so anyone
who can verify can also sign; use Sigstore if you need an identity). It is not
compliance evidence. The scenarios above are synthetic, and I have no outside
users to point to.

The records also exist for typed model answers (jevdecision) and human-approved
actions (decisioncontrol), in the same repo. I would most like to hear where a
decision of yours would not fit this record.
````

## Notes for the owner

- The install line for PyPI, `pip install "expgate>=0.2.0"`, replaces the clone
  line only after publication (pending as of 2026-10-19) and after you re-run the demo.
- The two other packages are mentioned in one sentence because the repository
  contains them; delete it if you want the post to be about one tool.
- The last question is the one ask. Keep it a question about fit, not about stars.
