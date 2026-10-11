# decision-control

An independent Python 3.11+ standard-library SDK and JSON CLI for policy-constrained
**local ticket reassignment**. It evaluates a supplied recommendation, stores frozen
evidence in SQLite, persists human review, and atomically changes the local ticket
queue. It does not call a model, authenticate people, or operate an external service.
This original MIT-licensed project is separate from RELIA: no RELIA imports, copied
implementation, integration, benchmark changes, or provider-quality claims.

## Install and run

From this directory:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install .
decision-control demo --out /tmp/decision-control-demo
python -m decisioncontrol replay --record /tmp/decision-control-demo/record-review.json
```

Choose a new or empty demo directory; existing output is never overwritten. The demo
creates `tickets.sqlite3`, policy/proposal JSON, four exported records, and
`summary.json`. It exercises ALLOW, REVIEW, DENY and ABSTAIN; closes/reopens the store
before approval; executes the approved reassignment twice safely; and replays all
serialized records. ALLOW and approved REVIEW tickets have revision 1 and new
departments; DENY and ABSTAIN tickets remain in intake at revision 0. Probabilities
are **hand-authored illustrative inputs**, not measured confidence or model calls.

## Persisted operator workflow

The bundled example requests engineering, which requires review. Run from this
directory after installation (use a fresh database for the initial ticket):

```bash
decision-control --db queue.sqlite3 ticket-create --ticket-id T-100 --department intake
decision-control --db queue.sqlite3 submit --proposal examples/proposal.json --policy examples/policy.json
decision-control --db queue.sqlite3 pending
```

Copy the returned decision `id` into `DECISION_ID`, then run:

```bash
decision-control --db queue.sqlite3 show "$DECISION_ID"
decision-control --db queue.sqlite3 approve "$DECISION_ID" --reviewer local-reviewer --note 'Checked routing'
decision-control --db queue.sqlite3 execute "$DECISION_ID"
decision-control --db queue.sqlite3 execute "$DECISION_ID"
decision-control --db queue.sqlite3 ticket-show T-100
decision-control --db queue.sqlite3 export "$DECISION_ID" --out approved-record.json
decision-control replay --record approved-record.json
```

Alternatively `reject ID --reviewer local-reviewer --note TEXT` permanently rejects
a pending review. `export ID` without `--out` prints the envelope; file export
refuses overwrite. All successful command results are JSON. `--db` is a global
option placed **before** storage commands. `demo` and `replay` need no database
option. Invalid input/IO errors exit 2, prohibited lifecycle actions or unauthorized
review exit 1, and success exits 0. Errors go to stderr; argparse help is ordinary
human-readable help. See `decision-control --help` and command `--help`.

## SDK

```python
from decisioncontrol.models import Recommendation, RoutingPolicy
from decisioncontrol.store import TicketStore
from decisioncontrol.evidence import export_record, replay

policy = RoutingPolicy('sdk-1', ('support',), (), ('local-reviewer',), 0.8)
proposal = Recommendation('reassign_ticket', 'SDK-1', 'support', 0.95,
                          'hand-authored-example', 'routing-question-1')
with TicketStore('sdk-queue.sqlite3') as store:
    store.create_ticket('SDK-1', 'intake')
    submitted = store.submit(proposal, policy)
    executed = store.execute(submitted['id'])
    assert store.execute(submitted['id']) == executed
    envelope = export_record(executed)
print(replay(envelope))
```

Model output is input, not authority. Only `reassign_ticket` is supported. Invalid
actions, mismatched tickets, prohibited destinations and no-op assignments are
DENY. Refusal, missing probability or probability below the threshold is ABSTAIN
when hard constraints otherwise permit the action. Review destinations yield
REVIEW; other permitted recommendations yield ALLOW. JSON inputs are strictly
validated; no missing probability is invented.

## Record schema v1

An export contains `record` and `sha256`. The record includes:

- `schema_version`, decision `id`, and UTC `created_at`;
- the supplied `recommendation` with model/question identifiers, probability and refusal;
- the trusted `ticket` snapshot (identifier, department and revision);
- the frozen `policy`, evaluated verdict and machine-readable reason codes;
- lifecycle `status`, authorized `review`, execution `result`, and transition `events`.

The full record is checksummed, including review and execution history. Replay
rejects inconsistent verdicts, illegal transitions, unauthorized recorded reviewers
and results that disagree with the frozen action. Schema versions other than 1
require an explicit migration rather than silent reinterpretation.

Supply the probability of the proposed choice, not an unrelated provider confidence
score. The host owns provider adaptation, model/question identity and threshold
validation on labeled application data. This library does not calibrate probabilities
or turn model recommendations into trusted permissions.

## Evidence and trust boundary

* Reviewer identifiers are labels supplied by a **trusted local host/operator**,
  not authenticated identities. There is no login, server, RBAC service or network
  boundary. A malicious process with file access can modify the database/evidence.
* Policies and ticket snapshots are frozen at submission. Updating a policy file
  does not retroactively revoke existing decisions or approvals. Apply revocation
  in the trusted host's lifecycle rather than assuming current-policy checks.
* Execution checks the frozen ticket department/revision against current state.
  A competing reassignment makes the decision STALE without changing the ticket.
  SQLite commits queue mutation, revision increment, result and event together.
  Repeating execution of the same executed decision returns its stored result.
  This is **local atomicity**, not exactly-once execution of external actions.
* Exported envelopes contain SHA-256 over canonical JSON. Replay checks corruption,
  recomputes the frozen policy evaluation and validates lifecycle evidence. It
  neither calls a model nor executes an action. Checksums are not signatures:
  attackers can recompute them. Records are not provider attestations, identity
  proof, calibrated model evidence or proof of outside-world execution.
* Protect database files, exports and notes using operating-system permissions;
  they can contain sensitive ticket metadata. Avoid untrusted database/JSON files
  and unbounded inputs. See [SECURITY.md](SECURITY.md).

## Development

```bash
python -m unittest discover -s tests
```

The package has no runtime dependencies or sibling-project imports. Setuptools is
an installation/build dependency. Repository CI uses the registered
`decision-control-ci.yml`; [CONTRIBUTING.md](CONTRIBUTING.md) describes scope.
[CHANGELOG.md](CHANGELOG.md) records changes. New project code is licensed under
[MIT](LICENSE); this does not relicense RELIA or any other component.

## Verification status

Local development verification on 2026-10-11 exercised the behavioral suite on
Python 3.11.17 and 3.13.7, fresh standalone installations, console/module demo and
replay outside the source directory, and separate-process approval/execution.
Regression coverage includes competing SQLite writers, stale approvals, duplicate
execution and rollback when decision persistence fails. This is local development
evidence, not a published package release, outside adoption or provider validation.
