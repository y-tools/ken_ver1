#!/usr/bin/env python3
"""Non-public B'z staging only. Does not modify existing songs, artists or recordings."""
import collections
import hashlib
import json
import os
import re
import unicodedata

import psycopg

SOURCE = "/tmp/ken_bz_stage_compact.json"
DB = "ken_songs"
ARTIST_NAME = "B'z"
ARTIST_ID_EXPECTED = 376


def normalize(v):
    v = unicodedata.normalize("NFKC", v).casefold()
    v = "".join(chr(ord(ch) - 96) if "\u30a1" <= ch <= "\u30f6" else ch for ch in v)
    return re.sub(r"[\s\u3000・ー‐-]", "", v)


def obvious_non_song(v):
    v=v.strip()
    if v.startswith("[") and v.endswith("]"):
        return True
    return bool(re.match(r"^\s*[\[(]?(?:MC|talk|interview|intro|outro|encore|guitar solo|drum solo)\s*[\])]?\s*$", v, re.I))


raw = open(SOURCE, "rb").read()
source_hash = hashlib.sha256(raw).hexdigest()
payload = json.loads(raw.decode("utf-8"))
items = payload["recordings"]
assert payload["artist_id"] == "20172e89-b8a5-4675-bd79-792d50d846a9"
assert len(items) == payload["count"] == 781
assert len({r["recording_mbid"] for r in items}) == 781
if os.getenv("KEN_BZ_APPLY_REVIEW_STAGE") != "YES":
    raise SystemExit("Set KEN_BZ_APPLY_REVIEW_STAGE=YES for isolated review-only staging")
with psycopg.connect("dbname=" + DB) as conn:
    with conn.transaction():
        artist = conn.execute("SELECT id,name FROM artists WHERE id = %s", (ARTIST_ID_EXPECTED,)).fetchone()
        assert artist == (ARTIST_ID_EXPECTED, ARTIST_NAME), "B'z identity mismatch"
        before = [conn.execute("SELECT count(*) FROM " + table).fetchone()[0] for table in ("songs", "artists", "recordings")]
        song_rows = conn.execute("SELECT id,title_key FROM songs WHERE primary_artist_id=%s", (ARTIST_ID_EXPECTED,)).fetchall()
        bykey = {row[1]: row[0] for row in song_rows}
        conn.execute("CREATE SCHEMA IF NOT EXISTS ken_bz_review")
        conn.execute("REVOKE ALL ON SCHEMA ken_bz_review FROM PUBLIC")
        conn.execute("""CREATE TABLE IF NOT EXISTS ken_bz_review.ingest_batches(
             source_hash TEXT PRIMARY KEY, artist_mbid UUID NOT NULL,
             fetched_recordings INTEGER NOT NULL, status TEXT NOT NULL,
             staged_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS ken_bz_review.candidates(
            recording_mbid UUID PRIMARY KEY,
            source_hash TEXT NOT NULL REFERENCES ken_bz_review.ingest_batches(source_hash),
            artist_id BIGINT NOT NULL,
            title TEXT NOT NULL,
            title_key TEXT NOT NULL,
            observed_release_date TEXT,
            source_url TEXT NOT NULL,
            existing_song_id BIGINT,
            candidate_class TEXT NOT NULL CHECK(candidate_class IN
                ('already_existing_title','new_title_review','non_song_review')),
            review_status TEXT NOT NULL DEFAULT 'pending' CHECK
                (review_status IN ('pending','accepted','rejected')),
            captured_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )""")
        conn.execute("REVOKE ALL ON ALL TABLES IN SCHEMA ken_bz_review FROM PUBLIC")
        conn.execute("""INSERT INTO ken_bz_review.ingest_batches(
            source_hash, artist_mbid, fetched_recordings,status)
            VALUES(%s,%s,%s,'review_only')
            ON CONFLICT(source_hash) DO NOTHING""",
            (source_hash,payload["artist_id"],len(items)))
        counters=collections.Counter()
        for item in items:
            key=normalize(item["title"])
            sid=bykey.get(key)
            cls="non_song_review" if obvious_non_song(item["title"]) else (
                "already_existing_title" if sid is not None else "new_title_review")
            counters[cls]+=1
            conn.execute("""INSERT INTO ken_bz_review.candidates
              (recording_mbid,source_hash,artist_id,title,title_key,
               observed_release_date,source_url,existing_song_id,candidate_class)
              VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)
              ON CONFLICT(recording_mbid) DO NOTHING""",
              (item["recording_mbid"],source_hash,ARTIST_ID_EXPECTED,
               item["title"],key,item["first_release_date"],item["url"],sid,cls))
        after = [conn.execute("SELECT count(*) FROM " + table).fetchone()[0] for table in ("songs", "artists", "recordings")]
        assert before == after, (before,after)
        total=conn.execute("SELECT count(*) FROM ken_bz_review.candidates WHERE source_hash=%s", (source_hash,)).fetchone()[0]
        assert total == 781, ("candidate count mismatch", total)
        statuses=conn.execute("""SELECT candidate_class,count(*),count(DISTINCT title_key)
                            FROM ken_bz_review.candidates
                            WHERE source_hash=%s GROUP BY candidate_class""",(source_hash,)).fetchall()
        print("STAGING_VALIDATION",json.dumps({"source_sha256":source_hash,
            "staged_recordings":total,"candidate_classes":statuses,
            "preexisting_master_counts":before,"master_counts_after":after,
            "publication": "NONE", "new_song_rows_added": 0,
            "allowed_roles": "postgres only"},ensure_ascii=False))
print("STAGING_TRANSACTION_COMMIT_SUCCESS")
