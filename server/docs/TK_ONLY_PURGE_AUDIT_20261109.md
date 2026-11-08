# TK-only destructive catalog reset — execution audit, 2026-11-09 (JST)

## Requested scope
The user requested that every artist and song EXCEPT **TK from 凛として時雨** be removed from BOTH production VPS PostgreSQL and GitHub Pages' static catalog. The operating app/UI should remain usable. Browser-local request/history/stream records are not centrally stored in the database and are not remotely erased.

## Before reset: production PostgreSQL
- PostgreSQL database: `ken_songs`, TK artist ID `643167`.
- Artists **125,069**, songs **2,000,081**, recordings **1,700,309**, artist aliases **323,200**, song aliases **737,358**; TK records: 1 artist, 98 songs, 309 recordings, 4 artist aliases, 0 song aliases, 2 release evidence rows.
- TK research date: `2026-11-08`.

## Full backup and real restore check
- Backup `/var/backups/ken-songs/ken_full_before_tk_only_20261109_tk_only.dump` was created before any deletion, via `pg_dump -Fc`.
- Backup SHA256: `f31c6a34842ca83483e8e27ff431fba7d1753b02c6050290ebb2e654c6cd3a46`. Archive listing passed `pg_restore -l`.
- Restored backup to a separate database, `ken_restore_check_20261109_tk_only`, using `pg_restore`. All six principal entity/audit row counts matched, and TK ID/name/research date were present. `RESTORE_VERIFIED_PASS`. Temporary test DB was deleted.
- A second restore into `ken_tk_purge_rehearsal_20261109` was followed by the *exact* guarded purge script, `server/tk_only_purge.py`. It produced `PURGE_COMMIT_PASS REHEARSAL` with a TK-preserved row digest of `e06b9f1492d7913ccc7398fa68ec635877e3b9fd3fadb538c9f08bb4764c9b65`.
- The rehearsal database can be removed after final operational verification; the real full backup remains stored. Do not delete the verified backup without separate user authorization.

## Applied to live VPS
- The same script ran as PostgreSQL owner with explicit environment mode `PRODUCTION`. It used an atomic transaction, copied all TK row data/IDs to temporary tables, truncated only the seven catalog master tables with an explicit FK inventory check, then restored the TK rows by original IDs. Verification was completed *before commit*. It also dropped the B'z review schema, retaining TK review candidates.
- `PURGE_VERIFIED` and `PURGE_COMMIT_PASS PRODUCTION ken_songs` were observed.
- **After:** 1 artist, 98 songs, 309 recordings, 4 artist aliases, 0 song aliases, 2 release evidence rows, 0 source-song links.
- **Removed:** 125,068 artists, 1,999,983 songs, 1,700,000 recordings, 323,196 artist aliases, 737,358 song aliases; no TK record changes.
- TK identity, 2026-11-08 research date, 98 song IDs, 309 recording IDs, alias verification/provenance and release evidence content remained byte-for-byte identical via SHA256 snapshot digest.
- The old B'z review schema `ken_bz_review` was removed; TK review schema was retained.
- The old source metadata and historic source-import logs remain for provenance/audit, but do not contain current non-TK song/artist master rows.

## Live post-purge API confirmation
Read-only API checks on `http://127.0.0.1:8787/api/v1/search`:
- `title=unravel`: TK results only, 2 matched records (title substring).
- `title=Ender Ember`: 1 TK result.
- `artist=TK from 凛として時雨`: 50 TK results (API cap).
- `artist=TK from Ling tosite sigure`: 50 TK results (API cap).
- `artist=B'z`, `title=江南スタイル`, `title=Lemon`: all zero results.
- `TK_ONLY_API_DB_PASS`.

## GitHub Pages static catalog cleanup
- Pre-delete versioned backup: immutable legacy data is accessible from branch `backup/ken-pre-tk-only-20261109` (snapshot of main before removal).
- Active `catalog.json` was replaced with exactly 98 rows exported from the TK artist of the live DB.
- Removed **835** tracked files (approximately **585.8 MiB**) containing former static mass catalogs, kana-reading buckets and generators/build workflows.
- Current index no longer loads deleted bulk catalog JS. Current `app.js` filters all visible catalog results (including VPS fallback and stale browser cache) to TK only, shows a true 98-song count, and keeps separate song/artist inputs and karaoke verification links.
- Repository's importer command is now limited to `--dataset tk_only` and integration CI's fixture likewise, preventing a future accidental legacy reimport.
- The browser-local request and streaming history features were intentionally not mass-deleted; prior listener requests/history from individual devices might include other artists, but are not catalog search results.

## Limitations
- Git history and the explicit backup branch retain pre-delete records for recovery. The user requested live catalog deletion rather than rewriting and expunging Git history.
- The 98 TK songs are the existing provisional normalized song records, not a promise of a complete official discography.
- Open caches on old browser tabs may display the previously loaded UI until a full reload. New-page behavior filters stale catalog JSON.
- Restoration has been tested at table/data and row-count level in isolated DB, not a full application disaster-recovery drill.
