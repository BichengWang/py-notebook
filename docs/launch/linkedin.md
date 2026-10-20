# LinkedIn draft

Draft for the owner to rewrite in their own words and post from their own profile.
Nothing here has been posted. Do the
[checklist](README.md#before-posting-owner-checklist) first. LinkedIn is a personal
post on your own profile, not a group or advertisement, and no LinkedIn rules were
read for this kit; check the current
[Professional Community Policies](https://www.linkedin.com/legal/professional-community-policies)
before posting.

LinkedIn does not render code blocks. The post carries one command and the real
result lines; the full run is in the repository and in [README.md](README.md#the-demo-as-run).
Replace the output lines with those from the release you post.

## Post

````text
If someone asks why a model was shipped six months ago, can you recompute the decision from what you kept?

Most teams keep a dashboard state or a log line. The inputs have moved on, the thresholds may have been edited, and the approval is a tag someone can change.

I built small, open-source tools that write a decision record you can re-check offline: the input, the frozen rules and the result, optionally signed. The first one takes A/B test aggregates and writes SHIP, HOLD, ROLLBACK or INVALID (sample-ratio mismatch). Python standard library only, MIT.

I signed a set of synthetic scenarios, edited one record, and checked again:

pip install ./ai-decision-system/ai-workflows/experiment-gate
experiment-gate-verify review-run/flat/decision.json --require-signature --key signing.key; echo "exit code: $?"
review-run/flat/decision.json: signature: signature covers different record bytes
exit code: 1

What a passing check does not prove: that the decision was right, that the numbers you exported are true, or who signed (an HMAC key is shared). It is not compliance evidence, and the scenarios are synthetic.

0.1.0 is on PyPI, but this signed-record demo needs unreleased 0.2.0, so install from a clone for now. The full commands and output are in the repo: https://github.com/BichengWang/ai-decision-system/tree/main/ai-workflows/experiment-gate

If you run release gates for models, I'd like to know which of your decisions this record could not hold.
````

## Notes for the owner

- The install line, the verify line and the two result lines are copied from the run
  in [README.md](README.md#the-demo-as-run). `pip install` prints nothing with
  `--quiet`, which the transcript uses; the post drops that flag for readability.
- Switch the signed-record demo's source install to
  `pip install "expgate>=0.2.0"` only after 0.2.0 is published on PyPI.
- Do not add a count of stars, forks or views, or a claim about users.
