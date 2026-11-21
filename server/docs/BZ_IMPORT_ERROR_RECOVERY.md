# B'z metadata acquisition / two connection errors (2026-11-08)

## Error 1: MusicBrainz WS/2 HTTP 503
Cause: transient upstream unavailability/rate limiting, not evidence that B'z is absent.
- Use `python server/musicbrainz_bz_fetch.py --limit 100 --max-pages 1 --output bz_musicbrainz_stage.json` from a machine with internet access.
- The tool sends a distinct User-Agent; retries only 429/500/502/503/504 and network timeouts, with bounded exponential backoff and a max of 5 attempts; waits >=1.2s between pagination requests.
- Keep max-pages bounded. A successful page isn't proof all works, releases, live performances or songs are present.
- The script writes ONLY local unreviewed JSON. It does not write to PostgreSQL, GitHub Pages, or the live VPS.
- Before accepting any entry, verify B'z artist identity, duplicate recording IDs, licensed source fields, and first-release date semantics; don't auto-generate official English or Japanese readings.
- On permanent errors, preserve the exception and stop; never bypass throttling with parallel clients or fake User-Agent.

## Error 2: SSH authentication from Mac
The Mac account showed only `known_hosts` and no private identity key in ~/.ssh; `ssh -o BatchMode=yes ubuntu@153.127.64.17` failed (Permission denied).
The user's authorized Windows Desktop Commander endpoint has existing user SSH keys and successfully ran `ssh -o BatchMode=yes ubuntu@153.127.64.17 hostname` returning `ik1-430-47013`.
**Do not copy private keys into GitHub, logs, chat, or project files**. Use the already-authenticated Windows host for approved VPS inspections and eventual deployments. Do not turn on password SSH just to bypass the error.
Windows read-only health command:
```powershell
ssh -o BatchMode=yes ubuntu@153.127.64.17 "hostname; pg_isready; systemctl is-active ken-song-api.service ken-song-admin.service; df -h /"
```
Observed on 2026-11-08 via Windows: PostgreSQL accepting connections, both `ken-song-api` and `ken-song-admin` services active, root filesystem 394G total/343G free. This does **not** prove the source catalog is complete, API endpoints healthy for every query, or backups restorable.

## Verified minimum live fetch
A Mac request to MusicBrainz returned HTTP 200 with `recording-count=781` for the B'z artist-filter query. The new script successfully exported one unreviewed record to a temporary local JSON file. It did NOT import tracks to the VPS. A later full disk/backup, rights and identity verification is required before any production insert.

## Follow-on safety gates
1. Save an isolated backup; independently verify restoration and audit existing artist / song rows.
2. Compare source scope and artist credits; MusicBrainz's 781 recording result-count is not an official complete discography and may contain non-song or alternate recordings.
3. Deduplicate by recording MBID and independently by work/release relationships; never unify simply on title+artist.
4. Add metadata only after source rights and field evidence verification; unknown readings or dates remain unknown.
5. Keep current public legacy search behavior and IDs unchanged until tested migration approval.
