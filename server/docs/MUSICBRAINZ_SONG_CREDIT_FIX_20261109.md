# Ken 24h research worker — recording credit ingestion fix (2026-11-09 JST)

## User-visible symptom
Artists increased but songs stayed at 98 while the worker ran continuously.

## Live root-cause evidence
- Before patch: 127 artists / 98 songs / 309 recordings; MusicBrainz recording discovery had 630 processed records (629 unique queue candidates), with **0 promotions**.
- Every queue candidate was marked `artist_credit_mismatch`.
- The MusicBrainz WS2 `/ws/2/recording?artist=<mbid>&fmt=json&limit=1` browse response omitted `artist-credit`. The identical request with `inc=artist-credits` returned the correct MusicBrainz artist ID `6114677c-fa8f-4d87-960a-3f1169aaef89` for TK.
- The implementation required exact artist-credit ID but never requested the artist-credit fields. This incorrectly classified all recordings as credit mismatches.
- The song pagination cursor advanced only on normally processed records, so skipped or already-registered recordings could stall discovery.

## Code fixes
1. Add `inc=artist-credits` to MusicBrainz recording browse.
2. Advance song cursor by the actual number of returned rows even when rows are invalid or duplicate.
3. Mark `video=true` recordings for review (rather than treating them as standalone audio songs).
4. Recalculate old queue `review_reason` when rescanned with full artist-credit data, retaining already-registered rows unchanged.
5. Reject obvious spoken material (such as `「オプション」ってなに？`) and arrangement/short-form version indicators (such as `ピアノver.`) from automatic standalone-song promotion; leave them in review.
6. Unit/CI tests validate `inc=artist-credits`, bad-versus-good title classification, duplicate recording pagination, and a successful song insertion in disposable PostgreSQL. New logic keeps no automatic overwrites/deletions, no guessed release dates/readings.

## Real DB and recovery
- The full database was backed up to `/tmp/ken_before_song_credit_fix_20261109.dump` and actually restored into independent database `ken_song_fix_restore_20261109`. Before patch/test, restored and live table counts both were **149 artists / 98 songs / 309 recordings**.
- A first patched song batch (25 recordings) inserted four songs for 戸高一生. Manual review identified two that should not have been standalone song records: `「オプション」ってなに？` (spoken information segment) and `『けけゴスペル』ピアノver.` (separate arrangement). In a single guarded transaction, only those **two known newly inserted** song IDs and recordings were removed from live catalog and reverted to review status; a `retracted` event was appended for each. Existing records were not touched. This is a correction of a newly observed test defect, not a mass delete.
- After the corrected worker implementation, another 25-recording batch for 光田康典 added **17 provisional tracks**, with existing catalog data preserved.
- Verified result immediately after this batch: **149 artists / 117 songs / 328 recordings** (98 original songs + 2 retained new + 17 further new). Confirmed source credit; official titles, alternate arrangements, approximate duplicates and readings still require separate review.
- All prior MusicBrainz records marked `artist_credit_mismatch` must be rescanned with `inc=artist-credits`. Review rows do not block the continuous loop. Do not convert old false mismatches to confirmed without re-fetching.

## Operational procedure
- The continuous systemd service was stopped before replacing the worker file. Its pre-patch executable is at `/opt/ken-song-api/server/research_worker.py.before_credit_fix_20261109`.
- The bounded on-demand worker batches were run as the unprivileged `kenresearch` role to confirm actual PostgreSQL promotion behavior.
- Restart the continuous service with `sudo systemctl start ken-research-continuous.service`, then verify its `active` state, follow the `ken_research_runs` counts and check actual `artists/songs/recordings` totals.
- Continue to distinguish provisional automated master rows from source-confirmed/human-confirmed metadata.
