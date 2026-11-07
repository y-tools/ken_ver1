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
