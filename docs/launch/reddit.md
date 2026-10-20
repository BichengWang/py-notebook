# Reddit drafts

Drafts for the owner to rewrite in their own words and post. Nothing here has been
posted. Do the [checklist](README.md#before-posting-owner-checklist) first, and
replace each demo block with output from the release you are posting.

Two subreddits, each post written for its readers. Post one, wait for the replies,
then the other; do not paste the same text twice.

## Rules checked 2026-10-19

Read from each subreddit's sidebar rule list while logged out. Rule text is quoted
from there; the sidebars do not list post flairs to logged-out readers, so check
the flair picker when you submit.

### r/MachineLearning

| # | Rule (title and what it says) | How the post below complies |
| --- | --- | --- |
| 1 | **No Spam.** Posts deemed spam are removed and repeat offenders banned. | One post, once. |
| 2 | **No Self-Promotion.** No promotion of paid products where the intent is clearly to promote a product. Posts linking paid products are acceptable if they offer sufficient value and the intent is to share a resource or collect feedback. Decided entirely at the moderators' discretion. | Free MIT-licensed code, no paid product, no sign-up. The post carries the method and a runnable demo, discloses that it is the author's project and ends on a request for feedback. |
| 3 | **No Marketing Campaigns (SEO).** Strategic marketing campaigns and SEO posts are prohibited, with permanent bans. | No campaign: one post, no links to anything but the repository. |
| 4 | **No Disrespectful Behavior.** Be cordial and professional. | Answer critique on the merits. |
| 5 | **No arXiv Links without Body Text.** | Not a paper; the post has a full body anyway. |
| 6 | **No Low-Effort, Beginner Questions.** | Not a question about basics. |

Also seen on the page: a pinned `[D] Self-Promotion Thread`, and the `[P]` tag with
a "Project" flair on current posts. If moderators remove the post, use the pinned
thread instead of reposting. The sidebar showed no rule about weekdays or weekends.
Rule text can change, so re-read it
([r/MachineLearning](https://www.reddit.com/r/MachineLearning/)).

### r/mlops

| # | Rule | How the post below complies |
| --- | --- | --- |
| 1 | **Don't Be an Asshole.** | n/a |
| 2 | **Vendors and self-promotion should be flaired and show effort.** Posting here is allowed, but do show effort and use the flair provided. | Use the flair the subreddit provides for self-promotion. The post shows its work: commands, output, limits. |
| 3 | **No low-effort or AI content.** Using AI is fair, but the discourse should stay organic. | Write the post yourself from the draft; keep the commands and outputs verbatim. |

Rules at [r/mlops](https://www.reddit.com/r/mlops/).

### Not used: r/Python

Rule 1 is "No showcase posts": showcases go in the monthly showcase post or a
daily thread, and rule 11 asks showcases for "What My Project Does", "Target
Audience" and "Comparison" sections. Use that thread only if you want a Python
audience; the text below maps onto those three headings.

## r/MachineLearning

Flair: Project.

**Title**

```text
[P] expgate: recompute A/B ship/rollback decisions offline, with signed records
```

**Body**

````text
I'm the author. Free, MIT, standard-library Python 3.11+, no service.

The problem: when a model that is already in an online A/B test is shipped, held
or rolled back, the decision often survives as a dashboard state. Months later
you can't recompute it from what was kept.

expgate reads the aggregates an experiment platform exports (units per arm;
successes for proportions; mean and sd for means; user-level numerator and
denominator summaries for ratios) and writes decision.json: the decision, the
reasons, the frozen policy, the full input and a digest of it.
experiment-gate-verify recomputes the decision from that input, offline.

The rules, applied in order: sample-ratio mismatch (chi-square) gives INVALID and
no effect estimate is trusted; primary significantly worse, or a guardrail
significantly worse beyond its margin, gives ROLLBACK; primary significantly
better and every guardrail non-inferior (Bonferroni-adjusted one-sided bounds)
gives SHIP; anything else is HOLD. Proportions use the unpooled Wald standard
error, means Welch, ratios the delta method. CUPED and an always-valid sequential
mode are optional. All of these are large-sample approximations. The estimators
are cross-checked against scipy, statsmodels, gbstats and confseq with committed
golden vectors (those libraries are dev-only).

Records can be signed (in-toto Statement in a DSSE envelope; HMAC by default,
Sigstore through cosign as an opt-in). From a clone, since it is not on PyPI yet:

    pip install ./ai-decision-system/ai-workflows/experiment-gate
    experiment-gate-verify review-run/*/decision.json --require-signature --key signing.key

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

What a passing check does not prove: that the decision was right, that the exported
numbers are true, or who signed (an HMAC key is shared, so anyone who can verify
can also sign). It is not compliance evidence, and the scenarios are synthetic.

Repo: https://github.com/BichengWang/ai-decision-system/tree/main/ai-workflows/experiment-gate

Feedback I'd value: which parts of your own go/no-go process this record can't hold.
````

## r/mlops

Flair: the one the subreddit provides for vendors and self-promotion.

**Title**

```text
Replayable, signed records for model go/no-go decisions (standard library, offline verify)
```

**Body**

````text
Author here. Free, MIT, no service, Python 3.11+ standard library only.

If someone asks in six months why a model was promoted, what do you have? A
dashboard that has moved on, a config that may have been edited, an approval that
is a mutable tag. I wanted the decision itself to be re-checkable, so I wrote
a record format and small reference verifiers rather than another platform.

What exists today, from a clone (not on PyPI yet): experiment-gate turns exported
A/B aggregates into a SHIP / HOLD / ROLLBACK / INVALID record that carries its own
input and frozen rules, and experiment-gate-verify recomputes it offline. The
same repository has records for typed model answers (jevdecision) and for
human-approved actions (decisioncontrol). Records can be HMAC-signed
(in-toto Statement in a DSSE envelope) or signed with Sigstore through cosign.

    pip install ./ai-decision-system/ai-workflows/experiment-gate
    experiment-gate-verify review-run/*/decision.json --require-signature --key signing.key

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

It is not a registry, a monitor or an approval workflow, and it does not run
experiments or deploy anything. A passing check does not show the decision was
right, that the exported numbers are true, or who signed (an HMAC key is shared).
It is not compliance evidence. The scenarios are synthetic and I have no outside
users yet.

Repo: https://github.com/BichengWang/ai-decision-system

Question: where in your release process would a record like this have to plug in
for you to use it?
````

If that last sentence "no outside users yet" is no longer true on the day, edit it
to what is true and linkable, or drop it.
