#!/usr/bin/env python3
"""Safe, resumable B'z MusicBrainz metadata fetch (NO database writes).

Only metadata research. Do not equate MusicBrainz discography with a complete
official B'z catalog, and independently verify licenses/terms for production.
"""
from __future__ import annotations

import argparse
import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

MB_HOST = "https://musicbrainz.org"
BZ_ARTIST_ID = "20172e89-b8a5-4675-bd79-792d50d846a9"
USER_AGENT = "KenDenmokuResearch/0.1 (https://github.com/y-tools/ken_ver1)"
RETRYABLE = {429, 500, 502, 503, 504}


def get_json(url: str, *, max_attempts: int = 5, sleep=time.sleep, open_url=None):
    """Respect MusicBrainz rate limits. Fail closed after bounded retries."""
    if not url.startswith(MB_HOST + "/ws/2/"):
        raise ValueError("Only MusicBrainz WS/2 HTTPS is supported")
    open_url = open_url or urllib.request.urlopen
    for attempt in range(max_attempts):
        request = urllib.request.Request(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )
        try:
            with open_url(request, timeout=25) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code not in RETRYABLE or attempt == max_attempts - 1:
                raise
            retry_header = exc.headers.get("Retry-After", "").strip()
            try:
                retry_seconds = float(retry_header)
            except ValueError:
                retry_seconds = 0
            # Deterministic base with slight jitter, capped to avoid infinite waits.
            delay = min(60.0, max(2 ** (attempt + 1) + random.random(), retry_seconds))
            sleep(delay)
        except (urllib.error.URLError, TimeoutError):
            if attempt == max_attempts - 1:
                raise
            sleep(min(60.0, 2 ** (attempt + 1) + random.random()))
    raise RuntimeError("unreachable")


def fetch_recordings(artist_id: str, *, limit: int = 100, max_pages: int = 1, sleep=time.sleep, fetch=get_json):
    """Return raw recording metadata; distinct recordings are NOT deduped by title."""
    if limit < 1 or limit > 100 or max_pages < 1 or max_pages > 100:
        raise ValueError("limit must be 1..100 and max-pages 1..100")
    result = []
    for page in range(max_pages):
        # MusicBrainz browse endpoint (artist filter), retain artist IDs for verification.
        query = urllib.parse.urlencode({"artist": artist_id, "fmt": "json",
                                        "limit": limit, "offset": page * limit})
        payload = fetch(MB_HOST + "/ws/2/recording?" + query)
        rows = payload.get("recordings")
        if not isinstance(rows, list):
            raise ValueError("Unexpected MusicBrainz response")
        for row in rows:
            if not isinstance(row, dict) or not row.get("id") or not row.get("title"):
                raise ValueError("Missing recording identity or title")
            result.append({
                "recording_mbid": row["id"],
                "title": row["title"],
                "artist_credit": row.get("artist-credit"),
                "first_release_date": row.get("first-release-date") or None,
                "length_ms": row.get("length"),
                "isrcs": row.get("isrcs", []),
                "source": "MusicBrainz",
                "url": "https://musicbrainz.org/recording/" + row["id"],
                "verification": "unreviewed",
            })
        if len(rows) < limit:
            break
        if page + 1 < max_pages:
            sleep(1.2)  # never burst above the 1/sec service guideline
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--artist-id", default=BZ_ARTIST_ID)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--max-pages", type=int, default=1)
    parser.add_argument("--output", type=Path, default=Path("bz_musicbrainz_stage.json"))
    args = parser.parse_args()
    if not args.artist_id or any(ch not in "abcdefABCDEF0123456789-" for ch in args.artist_id):
        parser.error("artist-id must be UUID-like")
    rows = fetch_recordings(args.artist_id, limit=args.limit, max_pages=args.max_pages)
    payload = {"artist_id": args.artist_id, "source": "MusicBrainz",
               "status": "unreviewed-stage-only", "count": len(rows), "recordings": rows}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Atomic local export, no DB writes. Store no credentials.
    temp = args.output.with_suffix(args.output.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(args.output)
    print(f"Fetched {len(rows)} unreviewed recordings to {args.output}")


if __name__ == "__main__":
    main()
