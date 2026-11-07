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
