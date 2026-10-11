# Contributing

Work within `ai-workflows/decision-control`; this is an independently installable
Python 3.11+ standard-library package. Do not import sibling projects or copy RELIA
implementation. Keep changes to RELIA out of decision-control work.

Install with `python -m pip install -e .`, then run
`python -m unittest discover -s tests`. Exercise the console command and
`python -m decisioncontrol demo --out` with a fresh temporary directory. Tests
should verify persisted behavior, lifecycle rejection, atomic mutation and evidence
replay, not just strings or forwarding. Update README and CHANGELOG when behavior
changes. Preserve strict schema validation, frozen snapshots, local transaction
boundaries and idempotency; do not introduce provider calls or claim authenticated
review without implementing an explicit new trust boundary.

Report security issues privately as described in SECURITY.md. Contributions to
this original component are under its MIT license; other repository components
retain their own licensing and behavior.
