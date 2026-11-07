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
