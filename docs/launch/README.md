# Launch kit (Plan ID P-024)

Drafts for the launch described in the [Phase 2 plan](../../.plan/phase-2-bridges.md).
The owner posts; nothing here has been posted, submitted or sent. Status
2026-10-19: kit drafted; owner posts on **2027-01-12**, after P-023 (0.2.0) and
P-025 (GrowthBook importer).

| File | Venue | Why this venue |
| --- | --- | --- |
| [`show-hn.md`](show-hn.md) | Hacker News (Show HN) | Something readers can install and run from a clone |
| [`reddit.md`](reddit.md) | r/MachineLearning (`[P]`) and r/mlops | Both have a project route; rules checked 2026-10-19 |
| [`linkedin.md`](linkedin.md) | LinkedIn, the owner's own profile | Reaches practitioners who run release gates |
| [`awesome-list-prs.md`](awesome-list-prs.md) | kelvins/awesome-mlops, AthenaCore/AwesomeResponsibleAI, agentrust-io/awesome-ai-governance | Rules read from each repository; entries checked against each list's format |

[EthicalML/awesome-production-machine-learning](https://github.com/EthicalML/awesome-production-machine-learning)
is **not a target**: its [CONTRIBUTING.md](https://github.com/EthicalML/awesome-production-machine-learning/blob/master/CONTRIBUTING.md)
requires at least 500 GitHub stars per tool.

## What every post says

1. **Problem first.** An AI-assisted go/no-go decision is often kept as a
   dashboard state or a log line. Months later nobody can recompute it from what was
   kept: the inputs moved, the thresholds were edited, the approval was a mutable tag.
2. **One install line, one verify line, one demo.** The demo is the signed-record
   run below, copied verbatim.
3. **What the records do not prove.** Every post states this, in the same words as
   the [project identity](../../.plan/README.md#identity) and the
   [experiment-gate README](../../ai-workflows/experiment-gate/README.md#signed-records):
   - A passing check shows the record is internally consistent under the verifier's
     rules. It does not show the decision was right, and it does not authorize a
     deployment.
   - It does not show the experiment summary behind it is true; the inputs are
     whatever the producer supplied.
   - An HMAC signature shows the signer held the shared secret. It is not an
     identity: every verifier holds the same key and so could also sign.
   - It is not compliance evidence or a legal opinion.
   - The bundled scenarios are synthetic. They are software checks, not adoption evidence.
4. **No adoption claims.** There are no users, pilots or reviews to cite. Do not
   add any, and do not quote stars (see [decisions](../../.plan/decisions.md)).

## Install and verify lines

| | Line | State on 2026-10-19 |
| --- | --- | --- |
| Install, from a clone | `pip install ./ai-decision-system/ai-workflows/experiment-gate` | Works today (run below) |
| Install, from PyPI | `pip install "expgate>=0.2.0"` | **After PyPI publish (pending).** Not on PyPI: P-016 is not done. Signing (`keygen`, `--sign-key`, `--require-signature`) is on `main` but not in the 0.1.0 release, so PyPI needs 0.2.0 (P-023) |
| Verify | `experiment-gate-verify review-run/*/decision.json --require-signature --key signing.key` | Works today (run below) |

## The demo, as run

Run on 2026-10-19, macOS arm64, Python 3.15.0, from a fresh clone of `main` at
commit `44e3519` (`expgate` 0.1.0 as reported by `expgate.__version__`; the
signing code is on `main` but unreleased). Each command was run in order, in an empty temporary directory, and the
output is pasted unedited. The key id is random per `keygen` and differs on every
run. Exit codes are printed by the `echo` on the same line as the command.

```text
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
```

The posts use exactly the lines above, through the first `exit code: 1`. The rest of
the same run shows what the signature adds beyond the digest:

```text
$ experiment-gate-verify review-run/flat/decision.json; echo "exit code: $?"
review-run/flat/decision.json: mismatch: decision
exit code: 1
$ mv review-run/flat/decision.json.bak review-run/flat/decision.json
$ python3 -c "import json; d = json.load(open('review-run/flat/decision.json')); m = d['input']['arms']['treatment']['metrics']; m['conversion']['successes'] = 400; m['refund_rate']['successes'] = 20; json.dump(d['input'], open('edited.json', 'w'))"
$ experiment-gate --input edited.json --out forged
flat: SHIP ef8544d6fbb16d65b94fe0aef48a536ef69843f5f0c0554e036038601d4e14aa
$ cp forged/decision.json review-run/flat/decision.json
$ experiment-gate-verify review-run/flat/decision.json; echo "exit code: $?"
review-run/flat/decision.json: verified
exit code: 0
$ experiment-gate-verify review-run/flat/decision.json --require-signature --key signing.key; echo "exit code: $?"
review-run/flat/decision.json: signature: signature covers different record bytes
exit code: 1
```

Reading it: the first edit (a value changed in place) fails the replay without a
signature too (`mismatch: decision`). The second edit changes the input and
re-derives the whole record with the real tool; the digest check and replay then
pass (`verified`, exit 0), and only the signature check, which binds the exact
bytes of the file to the key, exits 1. This is the case a bare digest cannot catch.
The same flags exist on `decision-control` and `jev-decision`
(see their READMEs); the demo uses only `experiment-gate`.

## Before posting (owner checklist)

Re-do every item on the day. The outputs above are a record of 2026-10-19, not of the release.

- [ ] **Release state.** P-016 done (`pip index versions expgate` lists a version),
      P-023 done (0.2.0 or later on PyPI, tagged), P-025 shipped. If any is still
      pending, post nothing and move the date in the plan.
- [ ] **Re-run the demo** against what you are posting. After 0.2.0 the printed
      decision hashes change (the record carries `expgate_version`) and the key id
      always changes. Replace the code block in every file under `docs/launch/`
      with the new output, pasted unedited. Install from PyPI in a clean virtual
      environment: `pip install "expgate>=0.2.0"`, then the same commands without the
      clone line. Swap the install line and remove the "(pending)" marker only then.
- [ ] **Claims.** Search the kit for adoption, user, pilot, review, compliance and
      PyPI wording. Add a fact only if it exists that day and you can link to it.
      If the GrowthBook importer (P-025) is mentioned, run its command first.
- [ ] **Repository.** Open Dependabot alerts: if critical or high alerts remain,
      the README must still say they are confined to the legacy workbench
      (P-019). Links in the README resolve. `main` CI is green.
- [ ] **Own words.** Rewrite each draft in your own words before posting. The
      [HN guidelines](https://news.ycombinator.com/newsguidelines.html) ask for
      text you wrote yourself, and r/mlops rule 3 excludes low-effort and
      machine-written posts. Keep the commands and outputs verbatim.
- [ ] **Rules.** Re-read each venue's rules (links in each file). They change.
- [ ] **Be present.** Plan to answer comments for the first few hours. Do not ask
      anyone to upvote or comment ([Show HN guidelines](https://news.ycombinator.com/showhn.html)).
- [ ] **Log it** in the table below the same day.

Suggested order, not a rule from any venue: awesome-list PRs and the Show HN on
the same day (both link to the repository), the subreddits after the first
comments on HN are read, LinkedIn last. Post each only once.

## Outreach log

One row per outreach, filled by the owner on the day and again when a response
arrives. Response is one of **accepted**, **declined** or **silent**. Suggested
meaning of silent: no response from maintainers or readers 14 days after the date;
record the date you checked. Also note any issue or PR from someone other than the
owner; the [phase 2 exit criteria](../../.plan/phase-2-bridges.md#exit-criteria)
count those, and a dated "none arrived" counts too.

| Date | Venue | Link | Response (accepted / declined / silent) | Response date | Non-owner issue or PR (link, or none) | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| [YYYY-MM-DD] | Hacker News (Show HN) | [url] | [ ] | [ ] | [ ] | [ ] |
| [YYYY-MM-DD] | r/MachineLearning `[P]` | [url] | [ ] | [ ] | [ ] | [ ] |
| [YYYY-MM-DD] | r/mlops | [url] | [ ] | [ ] | [ ] | [ ] |
| [YYYY-MM-DD] | LinkedIn | [url] | [ ] | [ ] | [ ] | [ ] |
| [YYYY-MM-DD] | PR to kelvins/awesome-mlops | [url] | [ ] | [ ] | [ ] | [ ] |
| [YYYY-MM-DD] | PR to AthenaCore/AwesomeResponsibleAI | [url] | [ ] | [ ] | [ ] | [ ] |
| [YYYY-MM-DD] | PR to agentrust-io/awesome-ai-governance | [url] | [ ] | [ ] | [ ] | [ ] |
