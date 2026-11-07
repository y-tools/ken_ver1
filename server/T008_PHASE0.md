# T008 Phase 0 — isolated safety prototype

No VPS or production database changed. Legacy importer and search API remain untouched.

## Files
- `sql/004_t008_staging.sql`: additive staging-only schema, no legacy migrations or promotion path
- `t008_policy.py`: fail-closed acquisition and publication policy, conservative identity classifier
- `tests/test_t008_policy.py`: fourteen offline safety unit tests

## Run offline policy tests
```sh
python -m unittest server.tests.test_t008_policy -v
```

## Run SQL only on a disposable PostgreSQL 16 database
```sh
psql -v ON_ERROR_STOP=1 -d disposable_ken_test -f server/sql/004_t008_staging.sql
```
The DDL has NOT yet been executed or verified in PostgreSQL.

## Safety boundaries and existing behavior
- `server/import_catalog.py` still writes directly into legacy tables and silently ignores name-key conflicts. **Do not run it with a production DSN**.
- `server/api/main.py` still searches legacy rows without a publication filter. The new `t008_candidates` table is not included in those queries.
- Legacy `songs` still has `UNIQUE(title_key, primary_artist_id)`. This branch deliberately does not remove it before legacy-row provenance and rollback planning.
- No `t008_candidates` row is automatically promoted to legacy `songs`.
- Source policies must be explicitly reviewed; unknown permission denies automated collection and publication.
- Even equal recording IDs only produce `link_recording`, never deletion or merge of Denmok song IDs.

## Next gates before a production change
1. Read-only VPS inventory (DB engine, constraints, row counts, API responses, storage and service load).
2. Disposable Postgres integration and 500 synthetic row test: staging, collisions, query isolation, retry, batch rollback.
3. Field-specific evidence, source hash and transform-chain validation during actual ingestion.
4. Promotion service with an explicit approval identity, durable audit trail, idempotency key and rollback.
5. Baseline p50/p95/p99 and existing API compatibility; backups plus restore test.
6. Existing static GitHub Pages catalogue exposure must be assessed independently of VPS search.

**Status:** implementation prototype only; no claim of 500-row DB test or production safety approval.
