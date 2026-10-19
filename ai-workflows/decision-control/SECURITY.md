# Security policy

This independently maintained decision-control component is an initial 0.1.0 local
SDK/CLI, not a hosted service. Report vulnerabilities privately to repository
maintainer Bicheng Wang at **bichengwang17@gmail.com**. Include the affected version, reproduction,
impact and proposed mitigation; do not attach sensitive production tickets or
credentials. No response-time or supported-release SLA is promised. Do not publish
exploit details before giving the maintainer an opportunity to respond.

## Trusted-local-process boundary

Proposer and reviewer names are caller-asserted trusted-host labels, not
authenticated principals. Schemas 3 and 4 prohibit a REVIEW proposer from approving,
rejecting or cancelling under the same label. A caller claiming a different
identity can bypass this comparison: hosts must authenticate people, bind labels
to principals and control policy/reviewer configuration. Historical v1/v2 records
retain their original rules without proposer separation. The frozen policy digest
detects content changes; it does not prove policy authority. Anyone with
write access to the database can change tickets, policies, decisions and events.
Export checksums detect accidental corruption, not malicious modification or
forgery. Protect databases and evidence with OS permissions and backups. Keep
sensitive ticket identifiers and review notes out of public evidence bundles.

Inputs and database paths must come from a trusted operator. This component is
not hardened for hostile tenants, unlimited JSON inputs or untrusted SQLite files.
It contains no credential storage, model provider connection or external executor.
Frozen policies are not retroactively revoked by editing a policy file. Explicit
cancellation requires a reviewer authorized by the decision's frozen policy and
a nonempty reason. It only withdraws PENDING_REVIEW or READY decisions; it never
undoes an executed action. Cancellation and execution serialize within the same
local SQLite writer transaction. Corrupt pending rows are skipped with diagnostics;
the CLI exits 1 while retaining valid queue entries. Newer unknown SQLite store
versions are refused. Staged file/directory publication prevents partial output
from ordinary write failures; it is not a guarantee of durability after power loss.

Atomic execution and idempotency apply to the local SQLite queue only; never
treat them as guarantees for external side effects. RELIA is a separate component
and is not covered or modified by this project's implementation or license.
