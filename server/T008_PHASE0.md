# T008 Phase 0 — B-006 review candidate (disposable environment only)

**Never deploy this PR to the production VPS.** Existing importer, API, legacy schema and static catalog are unchanged. No new data is promoted to public search.

## Components

- `sql/004_t008_staging.sql`: additive staging-only PostgreSQL schema.
- `sql/005_t008_constraints.sql`: evidence-policy FK, same-candidate ancestry FK, per-batch idempotency indexes and evidence-source trigger.
- `t008_policy.py`: deny unknown/blank/expired rights, unknown method, empty field list, missing evidence. Recording ID matching also requires title/artist agreement and identical source namespace.
- `t008_stage_import.py`: synthetic-fixture-only importer; checks rights before DB writes and allows only databases named `ken_test`/`t008_test`. Does not write to legacy tables.
- `tests/test_t008_policy.py` and `tests/test_t008_database.py`: policy regressions and 500 synthetic-row integration tests.
- `../.github/workflows/vps-db-tests.yml`: disposable PostgreSQL 16 execution.

## CI and measurements

CI applies 001, 004 and 005 SQL to GitHub Actions disposable database, uses a fictional local data source, then runs all server tests. See GitHub Actions for actual pass/fail logs; do not infer results from file creation.

`t008_stage_import.py` is deliberately a constrained development fixture, **not** a production-approved acquisition/publishing pipeline. In particular it is not authorized to fetch any external catalog or promote data. The existing import_catalog.py must not run against a production DSN under this PR.

## Rights and provenance caveats

- The policy gate is strict, with time-bound review and permitted-field evidence.
- The test importer writes source evidence with hashes but does not implement a license provenance UI or verify a real-world supplier agreement.
- DB constraints validate policy references and per-candidate evidence links, but transitive ancestry cycle proofs and production access-role grants need hardening. `005` checks immediate parent ordering in the trigger.
- Source authorization is evaluated in the Python stage importer, **not** universally for arbitrary direct SQL writes. Production protection will require database roles, restricted grants, and a controlled public promotion procedure.

## Required gates before merge/deployment

1. All CI tests green including synthetic 500-row, replay and rollback.
2. Verify role-isolation and forbidden SQL writes using a disposable DB non-owner.
3. Verify inter-batch external ID collisions, fake source terms and lineage cycles.
4. Implement explicit approval-based promotion, audited rollback and no-merge guarantees.
5. Read-only real VPS inventory; real DB snapshot and restoration test; API compatibility and p50/p95/p99.
6. Review static GitHub Pages catalog separately; no blanket claim of 2 million verified songs.

**Merge and production deployment remain on hold.**


## B-008 independent review prototype (2026-11-07)

The following is a **disposable PostgreSQL-only proof**, not a production deployment.

- `sql/006_t008_review.sql` creates immutable, version-numbered source-policy rows; input event records, external-ID claims, approval records, and revocable publication *preview* records.
- `sql/007_t008_roles_test.sql` establishes NOLOGIN test roles `t008_stage_writer`, `t008_reviewer`, `t008_publisher` with column-scoped writes. It refuses to execute outside `ken_test` and `t008_test`.
- `t008_stage_import.py` now looks up an administrator-provisioned policy version, checks access and storage only (not publication), records intake events, retains conflicting external IDs as distinct review candidates, and stores field evidence linked to immutable license policy.
- `tests/test_t008_review.py` verifies cross-batch collision preservation, exact repeat deduplication, immutable source policies, PostgreSQL role denial, private staging without public rights, explicit reviewer approval, idempotent publish, revoke, and injected publish failure.
- No preview record is exposed by `server/api/main.py`. Neither the legacy importer nor the legacy `songs` identifiers were modified.

**Important implementation boundaries:**
1. This review protocol validates only explicit title and artist evidence from synthetic test data. Real catalog field provenance and source-contract interpretation remain unverified.
2. The preview remains **private**; there is no public promotion to legacy `songs`.
3. Candidate verification transitions are currently made through test-review SQL; actual authenticated reviewer service and its durable identity management have not been deployed.
4. The test DB uses PostgreSQL superuser for schema provisioning; this must not be copied to an application service.
5. Revoke changes only the preview state and preserves append-only audit; it does not roll back existing legacy database edits because this prototype makes none.

**Before deploying:** independently review complete permissions and defaults (including table ownership, sequence grants, function EXECUTE, schema search paths, SET ROLE and concurrency); verify all rejection cases and recovery under a non-owner connection, and conduct a read-only inventory of the VPS. Draft PR remains HOLD.

## B-012 hardening (disposable database only)

Files:
- `sql/009_t008_integrity.sql`: PostgreSQL-side SHA-256 content/event digests, policy serialization, verification audits, reviewer gateway, current policy evidence selection, append-only approval revisions; no changes to legacy songs.
- `tests/test_t008_b012.py`: 20/50-connection contention, lock timeout and retry, concurrent review vs publication, forged-digest rejection, Unicode hashes, current-license evidence and reapproval tests.
- `t008_inventory_readonly.py`: opt-in safe read-only VPS inspection. No actual VPS connection has been performed.

### License and approval lifecycle

Old policies and evidence remain in immutable history. For publication, current verified title/artist evidence must exist under the newest policy version for each contributing source/method. When proofs change, a new approval revision is required. Existing published/revoked previews are non-reapprovable. The preview is private and not exposed in user-facing Denmok search.

### Verification and audit boundaries

Reviewer status changes use `t008_review_mark(candidate_id, reason, verified)`. Direct reviewer UPDATE grants are revoked. Trigger audit includes login, role, reason, before/after status and timestamp. This test design is not a real production authentication service or externally tamper-proof audit ledger.

### Read-only VPS inventory runbook (NOT yet executed)

1. Obtain authorized PostgreSQL read-only credentials. Never use a production superuser for inspection; never paste DSNs or secrets into issues, logs or CI.
2. Run `KEN_T008_AUDIT_DSN=... python server/t008_inventory_readonly.py` **only on an approved host**. Supply the DSN privately; do not paste literal credentials into shell history. The tool establishes a READ ONLY transaction with 2500 ms statement timeout and only exports aggregate DB metadata, API decorator counts and resource statistics.
3. Record anonymized schema/index totals, DB version, active connections, memory/CPU/disk headroom; separately document backup method, retention and encrypted off-host copies without opening backup contents.
4. Compare real existing API response shapes and all legacy song identifiers against a separately restored isolated clone. Establish p50/p95/p99, check backend authentication, and measure restoration time. Do not modify the production DB or stop existing services.
5. Local no-DB smoke check: `python server/t008_inventory_readonly.py --no-db`.

### Remaining release blockers

Production actor identity/credentials, DB default privileges, untrusted-source rights proof, multi-connection recovery under real VPS limits, restoration rehearsal, API compatibility and stable legacy IDs are unverified. MD5 approval digests remain test-only integrity hints; deployable audit integrity needs a stronger, separately controlled design. Draft PR #3 stays unmerged.


## B-014 review: disposable validation only (2026-11-07)

- `sql/010_t008_b014.sql` requires an explicit `t008_policy_authorizations` row referencing a particular approved source/method/policy version. Fictional test-only source approvals are seeded ONLY in the disposable CI DB; real external sources are never implicitly approved. New intake takes the same advisory lock as policy-version insertion, preventing a transaction from committing intake under a superseded policy version.
- A revoked preview stays permanently revoked; repeated identical acquisition creates a fresh candidate ID, `t008_reapplications` links the new candidate to its revoked predecessor, and a new review-queue item is required. Existing song IDs and production tables remain unchanged.
- `sql/011_t008_item_review.sql` provides individual evidence and issue review decisions, with reason and mapped reviewer ID for a *unique CI login*. The old bulk helper remains accessible only to the test database owner; the reviewer role cannot invoke it. Production needs real, distinct authenticated reviewer logins or a secure principal-binding service before this can be used.
- `tests/test_t008_b014.py`: unknown or unapproved source policy SQL rejection; revoked candidate reapplication and ancestry preservation; item-level issue decisions; concurrent policy update versus stage intake; reviewer role's bulk-call refusal.
- `tests/test_t008_b014_load.py`: repeat 20 and 50 logical requests three times with CI-only maximum of ten simultaneous DB connections. These figures are **not** VPS throughput predictions.

### VPS inspection blocker
`t008_inventory_readonly.py` has been tested with synthetic/local PostgreSQL and static API code, but **no authorized direct PostgreSQL read-only connection to the real VPS is present in this PR/CI environment**. Do not connect via production credentials, escalate permissions, download user records, or perform a destructive migration. When an operator supplies an approved read-only endpoint and the target environment is verified, run a secret-free aggregate survey and capture only anonymized results. Disk usage from this tool is the current working filesystem, not necessarily the PostgreSQL volume. Backups and API compatibility require separate verification.

### Security limitations
CI fixture policy authorization is not a real license review; sample source values are test-only. A database owner/superuser can bypass database role and trigger enforcement; full production hardening requires separate owner/service identities, tamper-resistant logs and independent audit. Draft PR #3 remains unmerged. Never install disposable-only SQL migrations on VPS.


## B-016 remediation (synthetic disposable PostgreSQL only)

- `sql/012_t008_b016.sql` replaces stage intake with a consistent acquisition ordering: external-ID advisory lock, pre-existing candidate row lock (if any), source/method policy advisory lock, then external-claim row and evidence. Approval/publish already lock candidate before policy; this avoids the previously observed lock-order inversion. Explicit transaction timeouts remain mandatory.
- If an existing candidate is already **published** and the same source/version/content is reacquired, only the acquisition event and audit entry are added. Existing published proofs are never modified, avoiding the evidence trigger rejection. Changed content or policy version opens a fresh, independently reviewable candidate with a `t008_publication_refreshes` link; it is **not automatically public**. If the current candidate was **revoked**, a fresh candidate linked by `t008_reapplications` is created, keeping each prior revoked ID and audit.
- `sql/013_t008_b016_review.sql` locks the candidate, then the issue row, **rechecks** that it is open, and conditionally transitions it to resolved. Another concurrent resolver is refused, so at most one resolution decision should be persisted.
- `tests/test_t008_b016.py` exercises published same-version replay, refreshed-policy re-registration, two consecutive permanent revocations/reapplications, concurrent double resolution, dedicated non-owner reviewer session identity, and stage-versus-publish concurrency. This is not a production authentication integration.
- All real VPS inventory, backup restore, API compatibility, and production connection-capacity investigations remain **unperformed**. There is no authorized least-privilege PostgreSQL read-only route or confirmed production DB identity available to this CI execution. Never substitute existing desktop devices' possible SSH credentials, infer connection strings or escalate access.
- Draft PR #3 stays unmerged; the new SQL files are forbidden on non-disposable DBs. Preserve the legacy song IDs and public API unchanged.


## B-018 preview-only active-publication invariants (2026-11-07)

- `sql/014_t008_active_publication.sql`: the source/type/external-ID primary key of `t008_active_publications` identifies **exactly one active preview candidate**. `t008_publication_preview` has a partial unique index for `state='published'`. The intake/review hint `t008_external_claims` is **not** the active-publication pointer. `t008_publication_history` records initial activation, supersession and revocation as append-only events.
- A newer staged candidate does not change the active pointer. After explicit evidence-backed identity adjudication, verified field evidence, issue resolution and approval, `t008_publish_preview` switches the pointer and marks the predecessor `superseded` **atomically in the same transaction**. Synthetic failure injection rolls the entire transition back. A `distinct_recording` decision can never take ownership of the same external ID. Competing publishers are serialized on the external-key advisory lock.
- `t008_identity_decisions` links a proposed candidate and a compared candidate, verified title and artist evidence IDs, authenticated CI-reviewer mapping, decision type, reason and timestamp. A review-queue status alone **does not** authorize replacing the active identity. The identity decision is currently a *manual adjudication fixture*, not independent proof of a real-world recording, and must be corroborated by trusted provider data in deployment.
- Public search API and legacy song IDs remain entirely untouched. `t008_publication_preview` is an **isolated private test preview**, and does not imply a migrated song is live on Denmok.
- Regression file `tests/test_t008_b018.py` covers public A + pending B/C, atomic A->B supersession and injected failure rollback, distinct identity reject, missing identity decision reject, concurrent intake+publish, competing B/C promotions, revocation versus reacquisition, and a direct SQL duplicate-live-preview constraint test.
- The role model for real deployment requires individually authenticated reviewer/publisher principals, separate memberships, evidence-linked adjudications, protected immutable audit, nonowner execution, secure approval identity binding (not client-supplied), and a two-person review rule for high-risk identity conflicts. No real user authentication bridge was deployed. All SQL remains disposable-only.
- The user-facing catalog, real server topology and backup-restoration results are **unverified**; no connection to production VPS was attempted without an operator-verified, least-privileged read-only DB endpoint and an approved access route. No production data, indexes, configuration, accounts or APIs were altered.
