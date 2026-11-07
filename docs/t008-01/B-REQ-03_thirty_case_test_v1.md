# T008-01 B-REQ-03: 30-case synthetic acceptance test v1
No real song metadata are required and no rights to ingest commercial catalogs are assumed.
## Fixture design
Create exactly 30 independent rows with stable synthetic IDs; all names and sources are fictional; run against isolated PostgreSQL and a stub search adapter.
- N01-N10 normal: Japanese title/artist, verified both readings, partial year, unknown year, kana/romaji derivation, title/artist name separation, replay, search prefix, source lineage.
- F01-F10 orthography: mixed case Latin/Japanese, fullwidth/halfwidth, combining marks, prolonged vowel, punctuation, emoji, middle dot, alternate spaces, homograph readings, official English vs translation.
- I01-I10 identity: same title different artists, same title/artist two recordings, cover, rerecording, live, remix, compilation re-release, source ID collision, cross-source ID equality, unresolved contradictory date.
At least two fixtures must deliberately feature absent readings and two an unconfirmed year; expected NULL rather than invented value.
## Each case must contain
fixture_id, group, title, artist, proposed entity_type, source namespace + ID, claims[] {field,value,semantic/precision,verification,evidence_ref,rights_policy_version}, expected reviewed result, search queries/expected matches, expected legacy IDs and forbidden effects.
## Procedure
1. Seed 30 synthetic source rights/version fixtures in disposable DB with explicit test-only permission; never treat as evidence for real sources.
2. Snapshot old songs/artists/recordings IDs, row counts and search results; capture hashes.
3. Validate evidence rights, field-specific provenance, kana/romaji derivation and year_semantics; reject unauthorized publication and conflicting claims.
4. Queue unresolved identity conflicts; verify zero automatic merges, deletions, reassigned IDs or silent date overwrite.
5. Run exact/prefix/alias search with expected results in local adapter. Compare unaffected legacy API shape, IDs, readings.
6. Roll back entire synthetic exercise and verify snapshot equality; report detailed expected vs observed for every case.
## Metrics, independent
- case_result_coverage = test cases with documented observed decision / 30 (target 30/30).
- per_field_verified_correct / per_field_verified_assessed (target 100% for approved verified fixture facts).
- per_field_missing / per_field_applicable (report; NULL with documented reason can be correct).
- false_merges = 0; auto_deletions = 0; existing_id_reassignment = 0; permission bypass = 0.
- search_success = passed expected synthetic queries / all planned queries (target 100% for supported queries); unexpected matches reported separately.
- drift: pre/post legacy ID/API snapshots exactly equal.
## Fail vs defer
G1 FAIL on unproven value marked verified, official English generated from translation, unjustified date semantics, erroneous merge or missing case result. Missing fact with reason = PASS behavior but report separately.
G1 PASS is a functional specification test, NOT a statistically valid 10k or 2m song accuracy guarantee. Real-data test requires G2 rights clearance; G3-G5 remain separate production gates.
## Required outputs
machine-readable 30-case fixture, expected-results manifest, execution log, per-field missing/error matrix, source-policy decisions and a reviewer-signable summary. Document is a test plan; it does NOT claim fixture execution occurred.

## B-026-02/03 binding test execution contract
- T1: execute all 30 JSON manifest cases from `server/fixtures/t008_g1_30_cases.json` against independent assertions for field rules, identity, rights and staged isolation. A Stub is a helper only, never proof of production search behavior.
- T2: use the ACTUAL existing `server.api.main.app` GET `/api/v1/search` handler with disposable PostgreSQL; snapshot title and artist mode JSON, including IDs, `items`, releaseDate, releasePrecision, `readings.type=verified_or_estimated`, and estimated name verification. Stage candidate(s) and compare the unchanged JSON and legacy IDs after, without modifying the API.
- Identity fixture I02: identical song title and artist but external recording ID differs; outcome `distinct_recording` with NO automatic legacy merge.
- Identity fixture I08: identical external ID, conflicting title/artist; outcome `review`, NO overwrites.
- Orthography fixture F10: store only official English label; machine translation not official, must not appear among verified English aliases.
- `per_field_accuracy = correct_verified_assessments / verified_assessments` only when denominator >=1. If denominator == 0, show `NOT_EVALUATED` and G1 field-coverage FAIL for every required field; NEVER interpret 0/0 as 100%.
- For all 30 cases record `expected`, `observed` and PASS/FAIL with corresponding evidence. Required field categories: title, artist, release year (where known), song/artist hiragana, katakana, romaji, official English. Report unknown/null separately, including rationale; NULL is permissible when justified.
- Overall G1 PASS requires 30/30 expected-vs-observed cases, evaluated fields 100% in their nonzero applicable denominator, no auto-merges/deletes/ID changes/rights bypass, supported search cases equal their expected result, and zero unexpected legacy API response differences. A passed T1 alone is not passed G1.
- G2 manual versus automated access distinction is tracked in B-REQ-04; do NOT enable automated_access_allowed=True as a workaround for manual permission.
