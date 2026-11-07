"""One-time, CI-only rehearsal: populated 014 -> 015 preserving preview/history IDs."""
import json,os,sys,uuid
from datetime import datetime,timedelta,timezone
from pathlib import Path
import psycopg
from server.t008_policy import SourcePolicy
from server.t008_stage_import import Candidate,stage_candidates
DSN=os.getenv("KEN_T008_UPGRADE_DATABASE_URL","")
BASE=Path("/tmp/denmok_t008_b022_upgrade_fixture.json")
def require_test(conn):
    if conn.execute("SELECT current_database()").fetchone()[0]!="t008_test":
        raise RuntimeError("B022 migration rehearsal requires isolated t008_test DB")
def before():
    now=datetime.now(timezone.utc)
    src="b014_upgrade_"+uuid.uuid4().hex
    pol=SourcePolicy(src,"local_dump","test-only","fixture approved",
      frozenset({"title","artist"}),True,True,True,True,
      now-timedelta(hours=1),now+timedelta(hours=1))
    key="upgrade-"+uuid.uuid4().hex
    with psycopg.connect(DSN) as con:
        require_test(con)
        con.execute("""INSERT INTO t008_source_policies(source_code,acquisition_method,
           content_license,access_terms,allowed_fields,automated_access_allowed,
           storage_allowed,publication_allowed,reviewed_at,expires_at,policy_version)
           VALUES(%s,'local_dump','test-only','fixture approved',%s,true,true,true,%s,%s,1)""",
           (src,["title","artist"],pol.reviewed_at,pol.expires_at))
        con.commit()
        batch=uuid.uuid4()
        stage_candidates(con,batch,[Candidate("Historical 014 preview","Singer",key)],pol)
        con.commit()
        cid=con.execute("SELECT id FROM t008_candidates WHERE batch_id=%s",(batch,)).fetchone()[0]
        con.execute("SELECT t008_review_mark(%s,'historical fixture verified',true)",(cid,))
        con.execute("SELECT t008_approve_candidate(%s,'014 rehearsal approval')",(cid,))
        approval=con.execute("SELECT approved_by,approved_at,proof_digest FROM t008_approval_revisions WHERE candidate_id=%s",(cid,)).fetchone()
        # Historical pre-015 row: publication key columns are NULL after 014.
        con.execute("""INSERT INTO t008_publication_preview(candidate_id,title,artist,
           approved_by,approved_at,proof_digest,state)
           VALUES(%s,'Historical 014 preview','Singer',%s,%s,%s,'published')""",
           (cid,*approval))
        con.execute("""INSERT INTO t008_active_publications(source_code,entity_type,external_id,candidate_id)
           VALUES(%s,'recording',%s,%s)""",(src,key,cid))
        con.execute("""INSERT INTO t008_publication_history(source_code,entity_type,external_id,
           candidate_id,action,actor) VALUES(%s,'recording',%s,%s,'initial','ci-migration')""",
           (src,key,cid))
        con.commit()
        row=con.execute("SELECT source_code,entity_type,external_id FROM t008_publication_preview WHERE candidate_id=%s",(cid,)).fetchone()
        assert row==(None,None,None),row
        baseline={
          "candidate_id":str(cid),"external_id":key,"source_code":src,
          "preview_count":con.execute("SELECT count(*) FROM t008_publication_preview").fetchone()[0],
          "history_count":con.execute("SELECT count(*) FROM t008_publication_history").fetchone()[0],
          "candidates_count":con.execute("SELECT count(*) FROM t008_candidates").fetchone()[0]
        }
        BASE.write_text(json.dumps(baseline))
        print("B022_UPGRADE_014 baseline",baseline)
def after():
    baseline=json.loads(BASE.read_text())
    cid=uuid.UUID(baseline["candidate_id"])
    with psycopg.connect(DSN) as con:
        require_test(con)
        row=con.execute("""SELECT source_code,entity_type,external_id
        FROM t008_publication_preview WHERE candidate_id=%s""",(cid,)).fetchone()
        assert row==(baseline["source_code"],"recording",baseline["external_id"]),row
        for table,label in [("t008_publication_preview","preview_count"),
                            ("t008_publication_history","history_count"),
                            ("t008_candidates","candidates_count")]:
            current=con.execute("SELECT count(*) FROM "+table).fetchone()[0]
            assert current==baseline[label],(table,current,baseline[label])
        current=con.execute("SELECT candidate_id FROM t008_active_publications WHERE source_code=%s AND external_id=%s",
            (baseline["source_code"],baseline["external_id"])).fetchone()[0]
        assert current==cid
        visible=con.execute("SELECT candidate_id FROM t008_visible_publications WHERE candidate_id=%s",(cid,)).fetchone()
        assert visible==(cid,),visible
        print("B022_UPGRADE_015 PASS: existing candidate, preview, history and active reference preserved")
if __name__=="__main__":
    if os.getenv("KEN_T008_ALLOW_DISPOSABLE")!="YES" or not DSN:raise RuntimeError("disposable only")
    if sys.argv[1]=="before":before()
    elif sys.argv[1]=="after":after()
    else:raise ValueError("before or after")
