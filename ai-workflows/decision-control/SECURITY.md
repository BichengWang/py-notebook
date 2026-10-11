# Security policy

This independently maintained decision-control component is an initial 0.1.0 local
SDK/CLI, not a hosted service. Report vulnerabilities privately to repository
maintainer Bicheng Wang at **bichengwang17@gmail.com** (the contact published in the
repository's `scripts/README.md`). Include the affected version, reproduction,
impact and proposed mitigation; do not attach sensitive production tickets or
credentials. No response-time or supported-release SLA is promised. Do not publish
exploit details before giving the maintainer an opportunity to respond.

## Trusted-local-process boundary

Reviewer names are trusted-host labels, not authenticated principals. Anyone with
write access to the database can change tickets, policies, decisions and events.
Export checksums detect accidental corruption, not malicious modification or
forgery. Protect databases and evidence with OS permissions and backups. Keep
sensitive ticket identifiers and review notes out of public evidence bundles.

Inputs and database paths must come from a trusted operator. This component is
not hardened for hostile tenants, unlimited JSON inputs or untrusted SQLite files.
It contains no credential storage, model provider connection or external executor.
Frozen policies are not retroactively revoked by editing a policy file. Atomic
execution and idempotency apply to the local SQLite queue only; never treat them
as guarantees for external side effects. RELIA is a separate component and is not
covered or modified by this project's implementation or license.
