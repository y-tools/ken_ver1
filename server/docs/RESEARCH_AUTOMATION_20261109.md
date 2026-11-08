# Ken continuous research queue and unattended importer (2026-11-09)

## 2026-11-09 continuous mode (supersedes the daily VPS timers)

After explicit user request, the VPS no longer needs to wait for 08:35 / 09:35 before running its next batch.

- `ken-research-continuous.service` runs continuously under Linux user `kenresearch`. In one non-overlapping process, it alternates **5 Japan-related artist checks** and **25 recordings for one artist**, and then immediately starts the next pair. The sequence is bounded by external service pacing, not a daily schedule.
- Old `ken-research-artists.timer` and `ken-research-songs.timer` are disabled and stopped before enabling the continuous service. Keep their unit files for a possible rollback but never run both old timers and the continuous service at the same time.
- All HTTP requests stay rate limited at >=1.2s with the same persistent client instance for both lanes; batch boundaries wait 1.5s. On 429, 5xx, timeout, or malformed data, the worker backs off (15s up to 15min) and systemd restarts unexpectedly exited processes after 20 seconds. No bypass of source usage policies.
- **Eligible new artists go straight into the catalog with `identity_status='provisional'`**, without requiring Wikidata/official-homepage confirmation: MusicBrainz artist UUID, explicit country JP, Person/Group type, valid normalized name and a collision-free existing catalog check are mandatory. If official homepage and reciprocal Wikidata ID are independently confirmed, the record has `identity_status='source_confirmed'`. Name collisions / missing country / unsuitable types are *not* automatically registered.
- Eligible unique new songs go straight into the catalog only when the MusicBrainz artist recording credit is exactly one artist, recording length is >=30 seconds, the title is non-media/non-version, the recording MBID is unique, and no normalized title collision exists. All unconfirmed dates, kana, romanization and English titles remain NULL. Ambiguous/duplicate rows are retained in the queue as review history but **do not block the next batch**.
- Durable cursors mean the next batch continues from where the prior batch finished. `ken_research_runs` still logs each bounded batch for auditing and unexpected failures; database records are append-only and deletion of master data is forbidden to this role.
- CPU <=50%, memory <=220MB and journald monitoring. The operator can disable continuous operation immediately with `sudo systemctl stop ken-research-continuous.service`. Use `journalctl -u ken-research-continuous.service -n 100 --no-pager` for recent results.
- The two separate **ChatGPT scheduled tasks** remain daily **reports**. ChatGPT scheduled tasks are not continuous trigger-on-completion jobs; do not claim that ChatGPT itself is running non-stop. VPS is continuous, ChatGPT research is not.

### Deployment
```sh
sudo systemctl disable --now ken-research-artists.timer ken-research-songs.timer
sudo systemctl stop ken-research-artists.service ken-research-songs.service
sudo install -m 644 server/ken-research-continuous.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ken-research-continuous.service
sudo systemctl status ken-research-continuous.service --no-pager
```

### Rollback
```sh
sudo systemctl disable --now ken-research-continuous.service
sudo systemctl enable --now ken-research-artists.timer ken-research-songs.timer
```

The prior backup and worker version should be preserved before swapping executable files.



## Purpose
Separate ChatGPT's source-cited reporting from **autonomous server-side collection**. The installed `ken-research-artists.timer` and `ken-research-songs.timer` run without Desktop Commander or an interactive ChatGPT approval. Their **own** source fetches can reach PostgreSQL directly; ChatGPT reports are **not** automatically ingested into this worker.

## Live bounded schedules, Japan time
- 08:35 (up to 120s random delay): discover at most 5 Japan-country MusicBrainz artist candidates.
- 09:35 (up to 120s random delay): inspect at most 25 MusicBrainz recordings for one registered artist, then rotate the artist queue.
- `Persistent=true` and a PostgreSQL advisory lock prevent normal missed-schedule gaps and simultaneous workers. Both tasks can be inspected with `systemctl list-timers` and `journalctl -u ken-research-artists.service -u ken-research-songs.service`.
- Current source automation is deliberately limited to **MusicBrainz WS/2 + Wikidata CC0**. TuneCore, Eggs, Apple Music, MINC, major-label and live-house sites remain *manual source-cited discovery by ChatGPT* until their API/licensing/consent are individually verified. Nothing here grants permission to copy their catalogs.
- New sources must pass data license, provenance, identity and rate-limit gates before integration.

## Artist lane
1. Fetch at most 5 `country:JP` artist search results and inspect each actual MusicBrainz artist URL/relation.
2. Store candidate `artist_mbid`, name, official page URL, country, Wikidata QID, source URL, reason for review and checked timestamp in `ken_research_artists`.
3. **Only promote a newly found artist** when its MusicBrainz country is JP, MusicBrainz provides an HTTPS official-homepage relation and linked Wikidata QID, and the Wikidata entity reciprocally asserts the identical MusicBrainz ID (P434). Also require nonempty normalized name and no existing normalized-name collision.
4. Collisions, missing official homepage, aliases that could mask a different person, absent Wikidata, non-JP artists and network/API failures stay under review. The automation cannot change or delete existing artist rows or claim verified kana/English translations.
5. MusicBrainz search `country:JP` does not encompass every musician active in Japan. ChatGPT's separately scheduled research covers wider discovery and recommends candidates for later review.

## Song lane
1. Pick **one registered artist** with the oldest research check date, starting with the existing curated `TK from 凛として時雨` (MBID `6114677c-fa8f-4d87-960a-3f1169aaef89`, Ken ID `643167`).
2. Fetch up to 25 recordings, record each MusicBrainz recording UUID, source URL, observed release text and review status in `ken_research_songs`.
3. Only promote previously absent titles with exact artist ID credit, one credited artist, a length >=30 seconds, no obvious media/interview/version wording, no existing normalized title, and no previously imported recording UUID.
4. Add a provisional song + recording UUID only, with no guessed release date, title reading, romanization or English official name. Collisions and live/remix/TV edits are held for review. This is intentionally conservative; it is not guaranteed to discover all songs.
5. Never delete existing master entries, overwrite a human-corrected field or silently merge alternate performances. Continue from saved per-artist offset and reset after reaching the source's end.

## Database and permissions
- Apply migration `server/sql/030_ken_research_queue.sql` once; tables: `ken_research_runs`, `ken_research_artists`, `ken_research_songs`, `ken_research_state`, `ken_research_events`.
- Apply `server/sql/031_research_worker_grants.sql` as PostgreSQL owner. `kenresearch` role has **SELECT/INSERT (no UPDATE/DELETE)** on master `artists`, `songs`, `recordings`. It can maintain only its queue and append events. It cannot modify existing aliases or source catalogs. The `keneditor` role only reads queue data.
- Run as local non-login Linux service user `kenresearch` using peer authentication (no password or token in GitHub/ChatGPT). Restrict OS service capabilities with `NoNewPrivileges`, `ProtectSystem=strict`, and resource limits.
- The existing admin API (port 8788) exposes **GET** `/api/admin/research/overview` and `/api/admin/research/candidates?lane=artists|songs`. Both require the same short-lived admin Bearer token as existing editor endpoints. There are no public write endpoints for unverified reports.
- Admin UI shows status and last runs above artist search; no direct public approval bypass.

## Source-service safeguards
- Unique meaningful User-Agent; bounded retry on 429/5xx/temporary errors; at least 1.2 seconds between HTTP calls; no proxy rotation or CAPTCHA bypass.
- Strict source URL allowlist (HTTPS MusicBrainz WS2 and Wikidata entity JSON).
- Persistent cursors mean the same 5 artists are not rechecked every day; one artist and 25 recordings maximum per run.
- Audit `ken_research_runs` with counts, success or error, and `ken_research_events` for master additions.
- Back up before initial schema migration and test actual restoration in a disposable database. The worker is append-only for the public master. If verification fails, stop and place a candidate in review; never delete data.

## Real implementation checks
- 2026-11-09 backup `/var/backups/ken-songs/ken_research_prechange_20261109.dump`, SHA256 `866a62d1c17db5d70854f80fe9c3263b7071374a2fbd47fd65eaf13f5473d187` matches original /tmp dump.
- Restored to disposable `ken_research_restore_probe_20261109` and independently matched **1 artist, 98 songs, 309 recordings, 4 artist aliases** before first migration.
- Initial live dry-runs completed, then 1 artist and 5 TK recordings were fetched and stored in review; **0 public master records were added** in this initial sample.
- GitHub CI exercises database migration, source trust checks and editor/browser behavior. Running services and next-run timers must be verified on the VPS after deployment.

## Do not conflate schedules
The two ChatGPT automations are **research-only reports** (8:00 and 9:00 approximate). They do not run SSH/Remote Desktop/connector writes and do not feed the worker automatically. The local VPS timers are **independent, deterministic scheduled fetch+validation+safe-insert jobs** (08:35/09:35). Reports and VPS candidate queues need an explicit bridge or manual review to exchange extra discoveries.

## Useful commands
```sh
systemctl list-timers --all | grep ken-research
systemctl status ken-research-artists.timer ken-research-songs.timer
journalctl -u ken-research-artists.service -n 80 --no-pager
journalctl -u ken-research-songs.service -n 80 --no-pager
sudo -u postgres psql -d ken_songs -c "SELECT lane,status,discovered,staged,promoted,started_at FROM ken_research_runs ORDER BY id DESC LIMIT 10"
sudo -u postgres psql -d ken_songs -c "SELECT status,count(*) FROM ken_research_artists GROUP BY status"
sudo -u postgres psql -d ken_songs -c "SELECT status,count(*) FROM ken_research_songs GROUP BY status"
```
