#!/usr/bin/env python3
"""TK from Ling tosite sigure: vetted CC0 metadata import with all-source review."""
import collections
import hashlib
import json
import re
import unicodedata
import uuid
from datetime import date
from pathlib import Path
import psycopg

PATH=Path("/tmp/ken_tk_stage_compact.json")
NAME="TK from 凛として時雨"
ARTIST_MBID="6114677c-fa8f-4d87-960a-3f1169aaef89"
GUARD=Path("/tmp/ken_songs_tk_preimport_20261108.dump")
PROV="ken_tk_metadata_20261108"
SOURCE="https://musicbrainz.org/artist/"+ARTIST_MBID+"/recordings"
BANNED=[
 r"^_fragment\s*#\d+",
 r"^interview\s*\d+",
 r"^documentary\b",
 r"\(documentary",
 r"\(bonus video\)",
 r"\(music video\)",
 r"\bmusic video$",
 r"non.credit opening movie",
 r"ノンクレジットオープニングムービー",
 r"^tvアニメ.*movie",
 r"^opening(?:\s*\(|$)",
 r"^introduction$",
 r"^se$",
]
VERSION=[
 r"\s*\((?:instrumental|ill instrumental|tv edit|tv size|sainou mix|album version|film edition|acoustic version|.*live.*|.*remix.*|.*reconstructed.*|.*leveling ver\.|english ver\.|devils from chainsaw edition|.*recorded from vinyl.*)\)$",
 r"\s*-\s*from the first take$",
]
def norm(v):
 v=unicodedata.normalize("NFKC",str(v)).casefold()
 v="".join(chr(ord(ch)-96) if "ァ"<=ch<="ヶ" else ch for ch in v)
 return re.sub(r"[\s\u3000・ー‐-]","",v)
def is_bad(t):
 return any(re.search(p,t,re.I) for p in BANNED)
def canonical(t):
 x=t.strip()
 if is_bad(x):return None
 if x.lower().startswith("ephemeral mist -rhythmless mix-"):return "ephemeral mist"
 if re.search(r"^unravel\s*-?\s*\(.*bootleg.*\)$",x,re.I):return "unravel"
 for _ in range(3):
  before=x
  for p in VERSION:x=re.sub(p,"",x,flags=re.I).strip()
  if before==x:break
 return x or None
def detect_type(t,base):
 if t==base:return "unknown"
 if re.search("remix|sainou mix|rhythmless",t,re.I):return "remix"
 if re.search("live|the first take",t,re.I):return "live"
 if re.search("acoustic|reconstructed|version|edition|leveling|tv edit|instrumental",t,re.I):return "alternate"
 return "alternate"

raw=PATH.read_bytes()
data=json.loads(raw.decode("utf-8"))
items=data["recordings"]
assert data["artist_id"]==ARTIST_MBID and len(items)==data["count"]==332
assert len({x["recording_mbid"] for x in items})==332
assert GUARD.exists() and GUARD.stat().st_size>1_000_000,"Backup unavailable"
digest=hashlib.sha256(raw).hexdigest()
groups=collections.defaultdict(list)
for x in items:
 uuid.UUID(x["recording_mbid"])
 base=canonical(x["title"])
 if base:groups[norm(base)].append((base,x))
base_names={}
for key,rows in groups.items():
 # Prefer an exact canonical recording title to a derived version title.
 names=[base for base,row in rows if row["title"].strip()==base]
 base_names[key]=names[0] if names else rows[0][0]
official={
 "アシデマトイ":date(2026,11,4),
 "Ender Ember":date(2026,4,23)
}
with psycopg.connect("dbname=ken_songs") as conn:
 with conn.transaction():
  conn.execute("SELECT pg_advisory_xact_lock(890087,20261108)")
  before={table:conn.execute("SELECT count(*) FROM "+table).fetchone()[0]
          for table in ["artists","songs","recordings","artist_names"]}
  # Stop rather than join unrelated bands or prior alias owners.
  owners=conn.execute("""SELECT id,name FROM artists
      WHERE name_key = %s""",(norm(NAME),)).fetchall()
  assert len(owners)<=1,owners
  if owners: artist_id=owners[0][0]
  else:
   artist_id=conn.execute("INSERT INTO artists(name,name_key,identity_status) VALUES(%s,%s,'source_confirmed') RETURNING id",
                          (NAME,norm(NAME))).fetchone()[0]
  source_id=conn.execute("SELECT id FROM source_catalogs WHERE code='musicbrainz' AND license_id='CC0'").fetchone()
  assert source_id,"MusicBrainz CC0 source missing"
  source_id=source_id[0]
  conn.execute("""INSERT INTO source_catalogs
    (code,display_name,source_url,license_id,attribution)
    VALUES('tk_official_discography','TK from Ling tosite sigure official discography',
           'https://tkofficial.jp/s/n150/artist/2/discography','factual_reference',
           'TK official (date evidence only)')
    ON CONFLICT(code) DO NOTHING""")
  official_source_id=conn.execute("SELECT id FROM source_catalogs WHERE code='tk_official_discography'").fetchone()[0]
  names=[
   ("hiragana","てぃーけーふろむりんとしてしぐれ","source_confirmed",
    "https://utaten.com/artist/8498/",None),
   ("english","TK from Ling tosite sigure","source_confirmed",
    "https://tkofficial.jp/s/n150/artist/2/profile",None),
  ]
  for kind,val,verification,url,parent in names:
   conn.execute("""INSERT INTO artist_names
       (artist_id,kind,value,search_key,verification,source_url,reviewed_by,checked_at)
       VALUES(%s,%s,%s,%s,%s,%s,%s,now())
       ON CONFLICT(artist_id,kind,search_key) DO NOTHING""",
       (artist_id,kind,val,norm(val),verification,url,PROV))
  hira=conn.execute("""SELECT id FROM artist_names
       WHERE artist_id=%s AND kind='hiragana' AND search_key=%s
       AND verification IN ('source_confirmed','human_confirmed')
       ORDER BY id LIMIT 1""",(artist_id,norm("てぃーけーふろむりんとしてしぐれ"))).fetchone()
  assert hira
  for kind,val in [("katakana","ティーケーフロムリントシテシグレ"),
                   ("romaji","TK from Rin toshite shigure")]:
   conn.execute("""INSERT INTO artist_names
       (artist_id,kind,value,search_key,verification,derived_from_id,reviewed_by,checked_at)
       VALUES(%s,%s,%s,%s,'derived_from_confirmed',%s,%s,now())
       ON CONFLICT(artist_id,kind,search_key) DO NOTHING""",
       (artist_id,kind,val,norm(val),hira[0],PROV))
  conn.execute("CREATE SCHEMA IF NOT EXISTS ken_tk_review")
  conn.execute("REVOKE ALL ON SCHEMA ken_tk_review FROM PUBLIC")
  conn.execute("""CREATE TABLE IF NOT EXISTS ken_tk_review.candidates(
    recording_mbid UUID PRIMARY KEY, source_hash TEXT NOT NULL, raw_title TEXT NOT NULL,
    proposed_title TEXT, class TEXT NOT NULL, release_date_observed TEXT,
    source_url TEXT NOT NULL, captured_at TIMESTAMPTZ NOT NULL DEFAULT now()
  )""")
  conn.execute("REVOKE ALL ON ALL TABLES IN SCHEMA ken_tk_review FROM PUBLIC")
  title_to_song={}
  new_songs=0
  existing_songs=0
  for key,title in sorted(base_names.items()):
   row=conn.execute("SELECT id FROM songs WHERE title_key=%s AND primary_artist_id=%s",(key,artist_id)).fetchone()
   if row: sid=row[0];existing_songs+=1
   else:
    dt=official.get(title)
    sid=conn.execute("""INSERT INTO songs
      (title,title_key,primary_artist_id,identity_status,release_year,
       release_month,release_day,release_precision,release_source_id)
      VALUES(%s,%s,%s,'provisional',%s,%s,%s,%s,%s) RETURNING id""",
      (title,key,artist_id,dt.year if dt else None,dt.month if dt else None,
       dt.day if dt else None,"day" if dt else "unknown",official_source_id if dt else None)).fetchone()[0]
    new_songs+=1
    if dt:
     conn.execute("""INSERT INTO release_evidence
      (song_id,source_id,release_year,release_month,release_day,precision,reference_url)
      VALUES(%s,%s,%s,%s,%s,'day',%s)""",
      (sid,official_source_id,dt.year,dt.month,dt.day,
       "https://tkofficial.jp/s/n150/artist/2/discography"))
   title_to_song[key]=sid
  staged_nonmusic=0
  conflicts=0
  inserted_recordings=0
  for x in items:
   title=x["title"]
   base=canonical(title)
   kind="nonmusic_review" if not base else "song_candidate"
   conn.execute("""INSERT INTO ken_tk_review.candidates
     (recording_mbid,source_hash,raw_title,proposed_title,class,release_date_observed,source_url)
     VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(recording_mbid) DO NOTHING""",
     (x["recording_mbid"],digest,title,base,kind,x["first_release_date"],x["url"]))
   if not base:
    staged_nonmusic+=1
    continue
   sid=title_to_song[norm(base)]
   mbid=x["recording_mbid"]
   existing=conn.execute("SELECT id,song_id FROM recordings WHERE musicbrainz_recording_id=%s",(mbid,)).fetchone()
   if existing:
    if existing[1]!=sid: conflicts+=1
    continue
   conn.execute("""INSERT INTO recordings
      (song_id,musicbrainz_recording_id,recording_type,version_label)
      VALUES(%s,%s,%s,%s)""",
      (sid,mbid,detect_type(title,base),title if title!=base else None))
   inserted_recordings+=1
  assert conn.execute("SELECT count(*) FROM ken_tk_review.candidates WHERE source_hash=%s",(digest,)).fetchone()[0]==332
  counts={t:conn.execute("SELECT count(*) FROM "+t).fetchone()[0]
          for t in ["artists","songs","recordings","artist_names"]}
  assert counts["songs"]==before["songs"]+new_songs
  assert counts["recordings"]==before["recordings"]+inserted_recordings
  names_check=conn.execute("SELECT kind,value,verification FROM artist_names WHERE artist_id=%s ORDER BY kind",(artist_id,)).fetchall()
  print("IMPORT_VERIFIED",json.dumps({
   "artist_id":artist_id,"source_sha256":digest,"candidate_recordings":332,
   "canonical_song_titles":len(groups),"new_songs":new_songs,"previous_existing_songs":existing_songs,
   "new_recordings":inserted_recordings,"nonmusic_review_recordings":staged_nonmusic,
   "recording_mbid_conflicts":conflicts,"counts_before":before,"counts_after":counts,
   "artist_aliases":names_check
  },ensure_ascii=False,default=str))
print("TK_PUBLIC_IMPORT_COMMITTED")
