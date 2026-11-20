#!/usr/bin/env python3
"""Read-only live API checks after TK artist/song catalog insertion."""
import json,urllib.parse,urllib.request
import psycopg

ARTIST="TK from 凛として時雨"
CASES=[
 ("アシデマトイ","title"),
 ("Ender Ember","title"),
 ("unravel","title"),
 ("てぃーけーふろむりんとしてしぐれ","artist"),
 ("TK from Ling tosite sigure","artist"),
 ("TK from Rin toshite shigure","artist"),
]
with psycopg.connect("dbname=ken_songs") as conn:
 artist=conn.execute("SELECT id FROM artists WHERE name=%s",(ARTIST,)).fetchone()
 assert artist,ARTIST
 aid=artist[0]
 songs=conn.execute("SELECT count(*) FROM songs WHERE primary_artist_id=%s",(aid,)).fetchone()[0]
 recordings=conn.execute("SELECT count(*) FROM recordings r JOIN songs s ON r.song_id=s.id WHERE s.primary_artist_id=%s",(aid,)).fetchone()[0]
 names=conn.execute("SELECT kind,value,verification FROM artist_names WHERE artist_id=%s ORDER BY kind",(aid,)).fetchall()
 check=conn.execute("SELECT title,release_year,release_month,release_day FROM songs WHERE primary_artist_id=%s AND title IN ('アシデマトイ','Ender Ember') ORDER BY title",(aid,)).fetchall()
 status=conn.execute("SELECT count(*) FROM ken_tk_review.candidates").fetchone()[0]
 print("DB_VALIDATION",json.dumps({"artist_id":aid,"songs":songs,"recordings":recordings,"aliases":names,"release_dates":check,"review_recordings":status},ensure_ascii=False))
 assert songs==98 and recordings==309 and status==332
 assert {"hiragana","katakana","romaji","english"}<=set(x[0] for x in names)
 assert len(check)==2
 for title,year,month,day in check:
  assert (year,month,day)==((2026,11,4) if title=="アシデマトイ" else (2026,4,23))
for q,mode in CASES:
 url="http://127.0.0.1:8787/api/v1/search?"+urllib.parse.urlencode({"q":q,"mode":mode,"limit":50})
 with urllib.request.urlopen(url,timeout=16) as resp:
  j=json.load(resp)
 matches=[x for x in j.get("items",[]) if x.get("artist")==ARTIST]
 print("SEARCH",repr(q),mode,"count",len(matches))
 assert matches,(q,mode)
 if mode=="artist":
  reads=matches[0].get("readings",{}).get("artist",{})
  assert reads.get("english")=="TK from Ling tosite sigure",(q,reads)
  assert reads.get("hiragana")=="てぃーけーふろむりんとしてしぐれ",(q,reads)
print("TK_LIVE_VALIDATION_PASS")
