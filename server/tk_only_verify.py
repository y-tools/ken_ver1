import json,urllib.parse,urllib.request,psycopg
api="http://127.0.0.1:8787/api/v1/search"
tests=[
 ("title","unravel",True),
 ("title","Ender Ember",True),
 ("artist","TK from 凛として時雨",True),
 ("artist","TK from Ling tosite sigure",True),
 ("artist","B'z",False),
 ("title","江南スタイル",False),
 ("title","Lemon",False),
]
for mode,q,expected in tests:
 u=api+"?"+urllib.parse.urlencode({"mode":mode,"q":q,"limit":50})
 with urllib.request.urlopen(u,timeout=15) as res:
  d=json.load(res)
 items=d.get("items",[])
 only_tk=all(x.get("artist")=="TK from 凛として時雨" for x in items)
 assert only_tk,(mode,q,items[:2])
 if expected: assert len(items)>0,(mode,q)
 else:assert len(items)==0,(mode,q)
 print("API_QUERY_PASS",mode,repr(q),"result_count",len(items),flush=True)
with psycopg.connect("dbname=ken_songs") as conn:
 n=conn.execute("SELECT COUNT(*) FROM artists").fetchone()[0]
 ns=conn.execute("SELECT COUNT(*) FROM songs").fetchone()[0]
 nr=conn.execute("SELECT COUNT(*) FROM recordings").fetchone()[0]
 cnt=conn.execute("SELECT COUNT(*) FROM song_names").fetchone()[0]
 keep=conn.execute("SELECT name,last_researched_on FROM artists WHERE id=643167").fetchone()
 assert(n,ns,nr,cnt)==(1,98,309,0)
 assert keep[0]=="TK from 凛として時雨" and str(keep[1])=="2026-11-08"
 print("DB_POST_PURGE_VERIFY_PASS",n,ns,nr,cnt)
print("TK_ONLY_API_DB_PASS")
