# B'z catalog staging report — 2026-11-08

## Verified actions
- Accessed the existing user-authorized VPS through the Windows machine's already-configured SSH identity. Mac did not have the private key.
- MusicBrainz artist MBID: `20172e89-b8a5-4675-bd79-792d50d846a9`.
- Fetched **781 recording records**, 781 unique recording MBIDs, 472 exact titles (464 distinct titles after Ken-style normalized title keys). MusicBrainz is NOT an official completeness guarantee; recording rows include alternate performances and spoken segments.
- Ken PostgreSQL database `ken_songs` before changes: 1,999,983 songs / 125,068 artists / 1,700,000 recordings. Existing B'z artist `artists.id=376` had 65 song rows and 0 linked recording IDs. 63 normalized title keys matched downloaded source records.
- Full pg_dump made on the VPS at `/tmp/ken_songs_bz_preimport_20261108.dump` (131 MB at collection time), `pg_restore -l` passed, and a real restore into isolated `ken_bz_restore_check_20261108` reproduced **1,999,983 / 125,068 / 1,700,000** before test DB was dropped. This is a recoverability smoke test, not a full disaster recovery or timing SLA.
- Imported 781 MusicBrainz recording candidate rows into **non-public** Postgres schema `ken_bz_review`, whose privileges are revoked from PUBLIC, via `server/bz_stage_review.py`. Data source SHA256 `1fcda3b4474e61c4a7682db87626a4372ec54a2f5618ca63672b246e551e37f4`. Production master tables `songs`, `artists`, `recordings` remained unchanged and counts were compared transactionally.
- Candidate classes: 240 recording rows matched existing titles (63 distinct keys); 532 recording rows mapped to 395 normalized **new title candidates**; 9 recording rows (6 normalized titles) were obviously MC, intros, or non-song material. These are *classification candidates*, not 395 newly verified unique musical works.
- API `http://127.0.0.1:8787/api/v1/health` returned `{"ok":true,"service":"ken-song-api"}`.
- Successful staged batch: `STAGING_TRANSACTION_COMMIT_SUCCESS`; **new public song rows added = 0** and **published entries = 0**.

## Remaining work (must not overclaim)
1. Verify official B'z discography coverage against album and single release lists, including 2025 FYOP and later releases. MusicBrainz may omit songs or include misattributed records.
2. Check each recording title and contribution: live versions/MC/samples, different performances, CD editions, and normalized spelling variants. Do not merge recordings by title alone.
3. Validate and document lawful acquisition, long-term retention and public redistribution for the actual field categories and the MusicBrainz service; distinguish license of core data vs relationship or supplementary fields.
4. Set per-field provenance, source-confirmed readings, correct release-date semantics. Keep unspecified kana/romaji/English names NULL; never generate guessed official English.
5. In isolated DB, rehearse any promotion script with non-owner role permissions and verify no legacy ID changes, unique indexes, source linkage, revocation and API results.
6. Only after the above gates, promote reviewed and licensed candidates into public `songs`, `recordings`, `song_names`, `release_evidence` through an auditable append-only transaction.

## Reproduction note
`server/bz_compare_existing.py` is a read-only comparison script referencing temporary on-VPS source data and `ken_songs`.
`server/bz_stage_review.py` is an explicit, review-only staging script. It refuses execution unless `KEN_BZ_APPLY_REVIEW_STAGE=YES`, it checks B'z `artists.id=376`, and it does not update public master tables. It may need adjustment for a differently initialized environment.
`server/bz_restore_check.sh` is tailored to the snapshot/database name and must NOT be applied as a general production backup workflow.
Do not commit fetched MusicBrainz data to the public GitHub repository without completing field/license/attribution review.
