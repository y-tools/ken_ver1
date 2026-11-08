#!/usr/bin/env python3
"""Purge all non-TK artist/song master data while preserving all TK rows+IDs.

Rehearsal MUST succeed before production. Requires verified pre-delete backup.
The authorized operator runs as the PostgreSQL owner; no secrets in code.
"""
from __future__ import annotations
import os,sys,json,hashlib
import psycopg
from psycopg.rows import dict_row

KEEP=643167
ARTIST="TK from 凛として時雨"
MODE=os.environ.get("KEN_TK_PURGE_MODE")
DB=os.environ.get("KEN_TK_DB")
if (MODE,DB) not in {
 ("REHEARSAL","ken_tk_purge_rehearsal_20261109"),
 ("PRODUCTION","ken_songs")}:
 raise SystemExit("Refusing purge; expected explicit REHEARSAL or PRODUCTION DB environment")
BACKUP="/var/backups/ken-songs/ken_full_before_tk_only_20261109_tk_only.dump"
import pathlib
if not pathlib.Path(BACKUP).is_file() or pathlib.Path(BACKUP).stat().st_size<100_000_000:
 raise SystemExit("Required verified backup missing")
TABLES=["artists","songs","recordings","artist_names","song_names","release_evidence","source_song_links"]
KEEP_Q={
 "artists":"SELECT * FROM artists WHERE id=643167 ORDER BY id",
 "songs":"SELECT * FROM songs WHERE primary_artist_id=643167 ORDER BY id",
 "recordings":"SELECT r.* FROM recordings r JOIN songs s ON r.song_id=s.id WHERE s.primary_artist_id=643167 ORDER BY r.id",
 "artist_names":"SELECT * FROM artist_names WHERE artist_id=643167 ORDER BY id",
 "song_names":"SELECT n.* FROM song_names n JOIN songs s ON s.id=n.song_id WHERE s.primary_artist_id=643167 ORDER BY n.id",
 "release_evidence":"SELECT e.* FROM release_evidence e JOIN songs s ON s.id=e.song_id WHERE s.primary_artist_id=643167 ORDER BY e.id",
 "source_song_links":"SELECT l.* FROM source_song_links l JOIN songs s ON s.id=l.song_id WHERE s.primary_artist_id=643167 ORDER BY l.source_id,l.external_id",
}
def canonical(v):
 return json.dumps(v,default=str,ensure_ascii=False,sort_keys=True,separators=(",",":"))
def tk_snapshot(conn):
 res={}
 for table,query in KEEP_Q.items():
  rows=conn.execute(query).fetchall()
  res[table]=rows
 return res
def digest(v):
 return hashlib.sha256(canonical(v).encode("utf-8")).hexdigest()
with psycopg.connect(f"dbname={DB}",row_factory=dict_row,autocommit=True) as conn:
 with conn.transaction():
  conn.execute("SET LOCAL lock_timeout='10s'")
  conn.execute("SET LOCAL statement_timeout='0'")
  conn.execute("SELECT pg_advisory_xact_lock(643167,20261109)")
  artist=conn.execute("SELECT id,name,last_researched_on FROM artists WHERE id=%s FOR UPDATE",(KEEP,)).fetchone()
  if artist is None or artist["name"]!=ARTIST or str(artist["last_researched_on"])!="2026-11-08":
   raise RuntimeError("Preserved artist identity / research date mismatch")
  before={t:conn.execute(f"SELECT count(*) n FROM {t}").fetchone()["n"] for t in TABLES}
  if before["songs"]<1_000_000 or before["artists"]<10_000 or before["recordings"]<1_000_000:
   raise RuntimeError("Unexpected source counts; refusing destructive operation")
  old=tk_snapshot(conn)
  expect={"artists":1,"songs":98,"recordings":309,"artist_names":4}
  for k,v in expect.items():
   if len(old[k])!=v:raise RuntimeError(f"Unexpected TK {k}: {len(old[k])}")
  original_hash=digest(old)
  # Inspect all inbound FKs; a future schema addition must be reviewed explicitly.
  fk=conn.execute("""SELECT conrelid::regclass::text as src,confrelid::regclass::text as target
    FROM pg_constraint WHERE contype='f' AND confrelid IN
    ('artists'::regclass,'songs'::regclass,'recordings'::regclass,
     'artist_names'::regclass,'song_names'::regclass,
     'release_evidence'::regclass,'source_song_links'::regclass)
    ORDER BY 1,2""").fetchall()
  unexpected=[row for row in fk if row["src"].replace("public.","") not in TABLES]
  if unexpected:raise RuntimeError("Unrecognized table references: "+canonical(unexpected))
  print("PRECHECK_PASS",canonical({"mode":MODE,"db":DB,"tk_digest":original_hash,
    "master_counts":before,"preserved_counts":{k:len(v) for k,v in old.items()},
    "inbound_fks":fk}),flush=True)

  # Temporary tables exist only in this session. Copy all columns to preserve IDs,
  # provenance, release dates and verified/derived name references.
  for table,query in KEEP_Q.items():
   conn.execute(f"CREATE TEMP TABLE tk_save_{table} ON COMMIT DROP AS {query}")
  # The comprehensive table list avoids uncontrolled TRUNCATE CASCADE.
  conn.execute("TRUNCATE TABLE "+",".join(TABLES))
  conn.execute("INSERT INTO artists SELECT * FROM tk_save_artists")
  conn.execute("INSERT INTO songs SELECT * FROM tk_save_songs")
  conn.execute("INSERT INTO artist_names SELECT * FROM tk_save_artist_names ORDER BY derived_from_id NULLS FIRST")
  conn.execute("INSERT INTO song_names SELECT * FROM tk_save_song_names ORDER BY derived_from_id NULLS FIRST")
  conn.execute("INSERT INTO recordings SELECT * FROM tk_save_recordings")
  conn.execute("INSERT INTO release_evidence SELECT * FROM tk_save_release_evidence")
  conn.execute("INSERT INTO source_song_links SELECT * FROM tk_save_source_song_links")
  # Old bulk-import histories contain no active song rows; metadata may be
  # retained to document source origins. Remove non-TK editor audit entries.
  conn.execute("""DELETE FROM ken_admin_audit WHERE
     (entity_type='artist' AND entity_id<>643167)
     OR (entity_type='song' AND NOT EXISTS
          (SELECT 1 FROM songs WHERE songs.id=ken_admin_audit.entity_id))""")
  # B'z staging is song data and must be removed; preserve TK review only.
  conn.execute("DROP SCHEMA IF EXISTS ken_bz_review CASCADE")

  after=tk_snapshot(conn)
  if digest(after)!=original_hash:
   raise RuntimeError("Preserved TK rows/provenance mismatch; automatic rollback")
  check={t:conn.execute(f"SELECT COUNT(*) n FROM {t}").fetchone()["n"] for t in TABLES}
  expected={t:len(old[t]) for t in TABLES}
  if check!=expected:raise RuntimeError("Unexpected post-purge counts; rollback: "+canonical(check))
  if conn.execute("SELECT COUNT(*) n FROM songs WHERE primary_artist_id<>643167").fetchone()["n"]!=0:
   raise RuntimeError("Non-TK songs remain")
  if conn.execute("SELECT COUNT(*) n FROM artists WHERE id<>643167").fetchone()["n"]!=0:
   raise RuntimeError("Non-TK artists remain")
  print("PURGE_VERIFIED",canonical({"mode":MODE,"database":DB,"preserved_digest":original_hash,
    "before":before,"after":check,"deleted":{t:before[t]-check[t] for t in TABLES}}),flush=True)
print("PURGE_COMMIT_PASS",MODE,DB,flush=True)
