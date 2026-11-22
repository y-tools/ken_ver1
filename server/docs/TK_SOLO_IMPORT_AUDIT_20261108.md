# TK from 凛として時雨 — Ken production import audit (2026-11-08)

## Scope and evidence
- Artist: TK from 凛として時雨 (solo); artist ID in Ken: **643167**. Distinct from 凛として時雨 (band).
- MusicBrainz artist MBID: `6114677c-fa8f-4d87-960a-3f1169aaef89`.
- Source: MusicBrainz WS/2 recordings; **332** source rows with **332 distinct MBIDs**; **172 exact title strings**. Each recording was retrieved with rate-limited client and kept with source URL.
- Source compact JSON SHA256: `a724280dd1547f7a97d8bf97812e3c0d900e2bf4a6242013fdec0623e217c981` (private VPS staging). Not committed to public repository.

## Live write result
- Master **artists**: 125,068 -> 125,069 (+1).
- Master **songs**: 1,999,983 -> 2,000,081 (+98).
- Master **recordings**: 1,700,000 -> 1,700,309 (+309).
- Master **artist_names**: 323,196 -> 323,200 (+4).
- Isolated private `ken_tk_review.candidates`: 332 source rows, of which 23 were categorized nonmusic/visual/interview/intro candidates and not added to master recordings.
- 98 normalized canonical title keys were promoted to `songs` with conservative version-title reduction. These are provisional song records; not a comprehensive discography certification. Strong caution: some version classification may need manual review and title-merging decisions, especially videos, instrumental/TV edits, unusual titles, collaborations.
- New artist readings:
  - hiragana: `てぃーけーふろむりんとしてしぐれ` (source_confirmed)
  - katakana: `ティーケーフロムリントシテシグレ` (derived_from_confirmed)
  - romaji: `TK from Rin toshite shigure` (derived_from_confirmed)
  - official English: `TK from Ling tosite sigure` (source_confirmed)
- Officially checked 2026 release-date evidence for two songs only: `Ender Ember` 2026-04-23 and `アシデマトイ` 2026-11-04. Other songs' `songs.release_*` remain unknown instead of copying MusicBrainz recording-date semantics into work-date fields. Raw observed recording dates remain in the private review schema.

## Backup and validation
- Full `pg_dump -Fc` made before changes: `/tmp/ken_songs_tk_preimport_20261108.dump` (about 131MB).
- Isolated `pg_restore` into `ken_tk_restore_check_20261108` reconstructed the three major table counts **1,999,983 | 125,068 | 1,700,000** with `RESTORE_VERIFIED PASS`. Test DB was deleted by script after successful count checks.
- Permanent copy: `/var/backups/ken-songs/ken_songs_tk_preimport_20261108.dump` (postgres-owned mode 600). SHA256 identical to the original: `7e19b22a7350e6bd2227c67a01816bca330e586de5e58f90bc060a5c43fc6588`.
- Read-only `server/tk_solo_verify.py` validated catalog counts, 4 artist aliases, 2 release dates, 332 review rows and live FastAPI searches. Observed:
  - Title searches `アシデマトイ`, `Ender Ember`, `unravel`: PASS.
  - Artist searches `てぃーけーふろむりんとしてしぐれ`, `TK from Ling tosite sigure`, `TK from Rin toshite shigure`: PASS.
- The original API and database schema were not modified. Only inserts into catalog master and isolated review records.
- Existing sample `ken_tk_restore_check.sh` emitted an irrelevant carriage-return/BOM shell error *after* RESTORE_VERIFIED PASS; the checksum and real restore result were successful.

## Known limitations and follow-up review
- Title canonicalization uses deterministic rules; it can hide genuinely distinct works behind variant suffixes and may leave certain versions as separate provisional works. Review manually, especially TV, music video, collaboration, remixes and nonmusic items.
- MusicBrainz 332 recordings are not a verified exhaustive solo discography, and production alias provenance/source use should be reviewed field by field under T008 G2/G3/G5 controls.
- No song title reading aliases were mass-generated or asserted verified. Only artist readings and English official name were entered.
- This work does **not** import 凛として時雨 band tracks as TK solo.
- Production service health and search checks passed, but mobile/browser full acceptance and performance at scale were not evaluated in this run.

## Code
- `server/tk_solo_import.py` — exact source-guided import script. It uses live VPS paths and the 2026-11-08 backup guard. Do NOT rerun against production casually; review the code, time-limited date assertions, database permissions and source records first.
- `server/tk_solo_verify.py` — read-only DB/API validation, tied to this import's expected counts.
