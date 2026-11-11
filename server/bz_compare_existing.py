#!/usr/bin/env python3
"""Read-only: compare MusicBrainz B'z recordings to Ken's existing songs."""
import collections
import json
import re
import unicodedata
import psycopg

PATH="/tmp/ken_bz_stage_compact.json"
def normalize(v):
    v=unicodedata.normalize("NFKC",v).casefold()
    v="".join(chr(ord(ch)-96) if "\u30a1" <=ch<= "\u30f6" else ch for ch in v)
    return re.sub(r"[\s\u3000・ー‐-]","",v)
def unwanted(t):
    t=t.strip()
    return bool(re.search(r"^\s*[\[(]?(?:MC|talk|interview|intro|outro|medley|encore|member introduction|drum solo|guitar solo)\s*[\])]?\s*$",t,re.I)) or t.startswith("[") and t.endswith("]")
data=json.load(open(PATH,encoding="utf-8"))
assert data["count"]==781 and len(data["recordings"])==781
with psycopg.connect("dbname=ken_songs") as con:
    artist=con.execute("SELECT id,name FROM artists WHERE name_key=%s",("b'z",)).fetchone()
    assert artist and artist[1]=="B'z",artist
    existing=con.execute("SELECT id,title,title_key,release_year FROM songs WHERE primary_artist_id=%s",(artist[0],)).fetchall()
    old_rec=con.execute("SELECT count(*) FROM recordings r JOIN songs s ON s.id=r.song_id WHERE s.primary_artist_id=%s",(artist[0],)).fetchone()[0]
    old_mbid=set(x[0] for x in con.execute("SELECT r.musicbrainz_recording_id::text FROM recordings r JOIN songs s ON s.id=r.song_id WHERE s.primary_artist_id=%s AND r.musicbrainz_recording_id IS NOT NULL",(artist[0],)).fetchall())
bykey=collections.defaultdict(list)
for x in data["recordings"]:
    bykey[normalize(x["title"])].append(x)
existingkeys={r[2] for r in existing}
unique=set(bykey)
excluded={k for k,v in bykey.items() if unwanted(v[0]["title"])}
missing=unique-existingkeys-excluded
to_review=sorted({x["title"] for k in excluded for x in bykey[k]})
newmbid=sum(x["recording_mbid"] not in old_mbid for x in data["recordings"])
print("REPORT",json.dumps({
 "source_recordings":len(data["recordings"]),"distinct_normalized_titles":len(unique),
 "existing_Bz_songs":len(existing),"existing_Bz_recordings":old_rec,
 "already_existing_titles":len(existingkeys & unique),"existing_mbid_count":len(old_mbid),
 "recording_mbids_not_in_existing":newmbid,
 "obvious_non_songs":len(excluded),"non_song_titles":to_review[:35],
 "new_title_candidates":len(missing),
 "sample_new_titles":[bykey[k][0]["title"] for k in sorted(missing)[:40]],
 "examples_existing":[r[1] for r in existing[:20]]
},ensure_ascii=False))
