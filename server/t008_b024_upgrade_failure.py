"""B-024 disposable migration failure/rollback, timeout/retry, mixed 014 states."""
import hashlib,json,os,sys,uuid
from pathlib import Path
from datetime import datetime,timedelta,timezone
import psycopg
from psycopg import errors
from server.t008_policy import SourcePolicy
from server.t008_stage_import import Candidate,stage_candidates

DSN=os.getenv("KEN_T008_UPGRADE_DATABASE_URL","")
SNAP=Path("/tmp/denmok_t008_b024_snapshot.json")
TABLES=("t008_candidates","t008_evidence","t008_publication_preview",
        "t008_publication_history","t008_active_publications",
        "t008_review_queue","t008_approval_revisions")
def database():
    conn=psycopg.connect(DSN,connect_timeout=4)
    name=conn.execute("SELECT current_database()").fetchone()[0]
    conn.commit()
    if name!="t008_test":
        conn.close()
        raise RuntimeError("B024 rehearsals run only in disposable t008_test")
    return conn

def snapshot(conn):
    state={}
    for table in TABLES:
        # Keep exact serialized rows (including timestamps, identifiers and audit).
        # Excludes sequence counters: aborted migrations cannot change data rows.
        rows=conn.execute("SELECT to_jsonb(t)::text FROM "+table+" t ORDER BY 1").fetchall()
        state[table]=hashlib.sha256(json.dumps([r[0] for r in rows],ensure_ascii=False).encode()).hexdigest()
        state[table+"_count"]=len(rows)
    return state

def prepare():
    now=datetime.now(timezone.utc)
    source="b014_upgrade_"+uuid.uuid4().hex
    policy=SourcePolicy(source,"local_dump","test-only","fixture approved",
        frozenset({"title","artist"}),True,True,True,True,
        now-timedelta(minutes=1),now+timedelta(hours=1))
    with database() as conn:
        conn.execute("""INSERT INTO t008_source_policies(source_code,acquisition_method,
          content_license,access_terms,allowed_fields,automated_access_allowed,
          storage_allowed,publication_allowed,reviewed_at,expires_at,policy_version)
          VALUES(%s,'local_dump','test-only','fixture approved',%s,
                 true,true,true,%s,%s,1)""",
          (source,["title","artist"],policy.reviewed_at,policy.expires_at))
        conn.commit()
        statuses=("published","revoked","superseded","published")
        candidate_ids=[]
        for i,status in enumerate(statuses):
            key="mixed-"+uuid.uuid4().hex
            batch=uuid.uuid4()
            stage_candidates(conn,batch,[Candidate("Synthetic 014 "+str(i),"Singer",key)],policy)
            conn.commit()
            cid=conn.execute("SELECT id FROM t008_candidates WHERE batch_id=%s",(batch,)).fetchone()[0]
            conn.execute("SELECT t008_review_mark(%s,'synthetic migration checked',true)",(cid,))
            conn.execute("SELECT t008_approve_candidate(%s,'synthetic review')",(cid,))
            appr=conn.execute("""SELECT approved_by,approved_at,proof_digest
                FROM t008_approval_revisions WHERE candidate_id=%s""",(cid,)).fetchone()
            # Rows 0 & 1 contain NULL keys, row 2 is fully populated,
            # and row 3 contains an incorrect but non-null source key.
            extras=(None,None,None) if i<2 else (
                (source,"recording",key) if i==2 else ("wrong-but-nonnull","recording",key))
            conn.execute("""INSERT INTO t008_publication_preview
               (candidate_id,title,artist,approved_by,approved_at,proof_digest,
                state,source_code,entity_type,external_id)
                VALUES(%s,%s,'Singer',%s,%s,%s,%s,%s,%s,%s)""",
                (cid,"Synthetic 014 "+str(i),*appr,status,*extras))
            if status=="published":
                conn.execute("""INSERT INTO t008_active_publications
                   (source_code,entity_type,external_id,candidate_id)
                   VALUES(%s,'recording',%s,%s)""",(source,key,cid))
            conn.execute("""INSERT INTO t008_publication_history
                 (source_code,entity_type,external_id,candidate_id,action,actor)
                 VALUES(%s,'recording',%s,%s,%s,'ci-b024')""",
                 (source,key,cid,"initial" if status=="published" else "revoke"))
            candidate_ids.append(str(cid))
            conn.commit()
        state=snapshot(conn)
        SNAP.write_text(json.dumps({"state":state,"ids":candidate_ids,"source":source}))
        print("B024_MIGRATION_BEFORE statuses=published,revoked,superseded,published; bad_nonnull=1")
        print("B024_MIGRATION_BEFORE counts",
            {t:state[t+"_count"] for t in TABLES})

def ensure_failed():
    before=json.loads(SNAP.read_text())
    with database() as conn:
        after=snapshot(conn)
        assert before["state"]==after,"Failed DDL changed persisted records"
        count=conn.execute("""SELECT count(*) FROM information_schema.columns
            WHERE table_name='t008_identity_decisions' AND column_name='title_digest'""").fetchone()[0]
        assert count==0,"015 migration should have rolled back all schema changes"
        nullable=conn.execute("""SELECT is_nullable FROM information_schema.columns
            WHERE table_name='t008_publication_preview' AND column_name='source_code'""").fetchone()[0]
        assert nullable=="YES",nullable
        print("B024_MIGRATION_FAIL_ROLLBACK PASS all historical rows and prior schema preserved")

def repair():
    data=json.loads(SNAP.read_text())
    with database() as conn:
        # A human-approved correction to NULL is used only in the synthetic test.
        cid=uuid.UUID(data["ids"][-1])
        conn.execute("""UPDATE t008_publication_preview SET source_code=NULL
            WHERE candidate_id=%s AND source_code='wrong-but-nonnull'""",(cid,))
        conn.commit()
        data["state"]=snapshot(conn)
        SNAP.write_text(json.dumps(data))
        print("B024_MIGRATION_REPAIRED synthetic conflicting value explicitly quarantined")

def test_timeout():
    data=json.loads(SNAP.read_text())
    sql=Path("server/sql/015_t008_b020.sql").read_text()
    with database() as blocker:
        blocker.execute("LOCK TABLE t008_publication_preview IN ACCESS SHARE MODE")
        try:
            with psycopg.connect(DSN,autocommit=True) as runner:
                assert runner.execute("SELECT current_database()").fetchone()[0]=="t008_test"
                runner.execute("SET lock_timeout='250ms'")
                try:
                    runner.execute(sql)
                    raise AssertionError("Expected DDL lock timeout")
                except errors.LockNotAvailable:
                    pass
        finally:
            blocker.rollback()
    with database() as conn:
        assert snapshot(conn)==data["state"],"Interrupted migration did not roll back"
        assert conn.execute("""SELECT count(*) FROM information_schema.columns
             WHERE table_name='t008_identity_decisions' AND column_name='title_digest'""").fetchone()[0]==0
        print("B024_MIGRATION_TIMEOUT_ROLLBACK PASS unchanged data and schema")

def after():
    data=json.loads(SNAP.read_text())
    with database() as conn:
        assert snapshot(conn)==data["state"],"Data or history changed during migration"
        ids=conn.execute("""SELECT id::text FROM t008_candidates
               WHERE id=ANY(%s) ORDER BY id""",([uuid.UUID(x) for x in data["ids"]],)).fetchall()
        assert {x[0] for x in ids}==set(data["ids"])
        rows=conn.execute("""SELECT source_code,entity_type,external_id FROM
                t008_publication_preview WHERE candidate_id=ANY(%s)""",
                ([uuid.UUID(x) for x in data["ids"]],)).fetchall()
        assert len(rows)==4 and all(all(v is not None for v in row) for row in rows)
        assert conn.execute("""SELECT count(*) FROM information_schema.columns
              WHERE table_name='t008_identity_decisions' AND column_name='title_digest'""").fetchone()[0]==1
        print("B024_MIGRATION_RETRY_PASS migrated keys, unchanged UUIDs, 4 mixed histories")

if __name__=="__main__":
    if not DSN or os.getenv("KEN_T008_ALLOW_DISPOSABLE")!="YES":
        raise RuntimeError("disposable test only")
    {"before":prepare,"failed":ensure_failed,"repair":repair,
     "timeout":test_timeout,"after":after}[sys.argv[1]]()
