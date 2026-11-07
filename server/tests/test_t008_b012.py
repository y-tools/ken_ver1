"""T008 B-012 adversarial executable tests: disposable PostgreSQL only."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
from threading import Event
import hashlib,json,os,statistics,time,unittest,uuid
import psycopg
from psycopg import errors
from server.t008_policy import SourcePolicy
from server.t008_stage_import import Candidate,stage_candidates,fingerprint

DSN=os.getenv("KEN_T008_TEST_DATABASE_URL","")
LOGIN=os.getenv("KEN_T008_STAGE_LOGIN_DSN","")
@unittest.skipUnless(DSN and os.getenv("KEN_T008_ALLOW_DISPOSABLE")=="YES",
                     "requires disposable PostgreSQL")
class T008IntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source="b012_"+uuid.uuid4().hex
        now=datetime.now(timezone.utc)
        cls.policy=SourcePolicy(cls.source,"local_dump","test-only","fixture",
            frozenset({"title","artist"}),True,True,True,True,
            now-timedelta(minutes=1),now+timedelta(hours=1))
        with psycopg.connect(DSN) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT current_database()")
                if cur.fetchone()[0] not in ("ken_test","t008_test"):
                    raise RuntimeError("not disposable")
                cur.execute("""INSERT INTO t008_source_policies
                 (source_code,acquisition_method,content_license,access_terms,allowed_fields,
                  automated_access_allowed,storage_allowed,publication_allowed,reviewed_at,expires_at,policy_version)
                 VALUES(%s,%s,%s,%s,%s,true,true,true,%s,%s,1) RETURNING id""",
                 (cls.source,"local_dump","test-only","fixture",["title","artist"],
                  cls.policy.reviewed_at,cls.policy.expires_at))
                cls.policy_id=cur.fetchone()[0]
            conn.commit()

    def _stage(self,title,key,policy=None,batch=None):
        batch=batch or uuid.uuid4()
        with psycopg.connect(DSN) as conn:
            res=stage_candidates(conn,batch,[Candidate(title,"Singer",key)],policy or self.policy)
            conn.commit()
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM t008_candidates WHERE batch_id=%s",(batch,))
                row=cur.fetchone()
            conn.commit()
        return res,row[0] if row else None,batch

    def _approved(self):
        result,cid,batch=self._stage("Approved "+uuid.uuid4().hex,uuid.uuid4().hex)
        with psycopg.connect(DSN) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT t008_review_mark(%s,'independently checked',true)",(cid,))
                cur.execute("SELECT t008_approve_candidate(%s,'fixture reviewer')",(cid,))
            conn.commit()
        return cid,batch

    def test_db_rejects_forged_digests(self):
        key="forgery-"+uuid.uuid4().hex
        with psycopg.connect(DSN) as conn:
            with self.assertRaises(errors.RaiseException):
                with conn.transaction():
                    with conn.cursor() as cur:
                        cur.execute("SELECT t008_stage_one(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (uuid.uuid4(),"Forgery","Singer",self.source,"recording",key,
                         self.policy_id,"f"*64,"e"*64))
            conn.rollback()
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM t008_candidates WHERE external_id=%s",(key,))
                self.assertEqual(cur.fetchone()[0],0)
            conn.commit()

    def test_utf8_canonical_digest(self):
        item=Candidate("青い海 / Ω","歌手『沖縄』","recording-🎵")
        cd=fingerprint(item)
        ed=hashlib.sha256(json.dumps([self.source,"local_dump",self.policy_id,cd],
             separators=(",",":")).encode("utf-8")).hexdigest()
        with psycopg.connect(DSN) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT t008_content_sha256(%s,%s,%s,%s)",
                            (item.title,item.artist,item.source_id,item.entity_type))
                self.assertEqual(cur.fetchone()[0],cd)
                cur.execute("SELECT t008_event_sha256(%s,%s,%s,%s)",
                            (self.source,"local_dump",self.policy_id,cd))
                self.assertEqual(cur.fetchone()[0],ed)
            conn.commit()

    def test_direct_verification_without_reason_fails(self):
        _,cid,_=self._stage("Audit "+uuid.uuid4().hex,uuid.uuid4().hex)
        with psycopg.connect(DSN) as conn:
            with self.assertRaises(errors.RaiseException):
                with conn.transaction():
                    with conn.cursor() as cur:
                        cur.execute("UPDATE t008_candidates SET verification='verified' WHERE id=%s",(cid,))
            conn.rollback()
            with conn.cursor() as cur:
                cur.execute("SELECT t008_review_mark(%s,'manual evidence check',true)",(cid,))
            conn.commit()
            with conn.cursor() as cur:
                cur.execute("""SELECT count(*) FROM t008_audit WHERE action='verification_changed'
                   AND details->>'candidate_id'=%s AND details->>'reason'='manual evidence check'""",
                   (str(cid),))
                self.assertGreaterEqual(cur.fetchone()[0],3)
            conn.commit()

    def test_updated_license_uses_current_evidence_with_reapproval(self):
        # Distinct source avoids altering any other test policy.
        source="policyupgrade_"+uuid.uuid4().hex
        now=datetime.now(timezone.utc)
        old=SourcePolicy(source,"local_dump","test-only","fixture",
            frozenset({"title","artist"}),True,True,True,True,
            now-timedelta(minutes=1),now+timedelta(hours=1),1)
        with psycopg.connect(DSN) as conn:
            with conn.cursor() as cur:
                cur.execute("""INSERT INTO t008_source_policies
                    (source_code,acquisition_method,content_license,access_terms,allowed_fields,
                     automated_access_allowed,storage_allowed,publication_allowed,reviewed_at,expires_at,policy_version)
                    VALUES(%s,'local_dump','test-only','fixture',%s,true,true,true,%s,%s,1)""",
                    (source,["title","artist"],old.reviewed_at,old.expires_at))
            conn.commit()
        _,cid,_=self._stage("Upgrade",uuid.uuid4().hex,old)
        with psycopg.connect(DSN) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT t008_review_mark(%s,'verify v1',true)",(cid,))
                cur.execute("SELECT t008_approve_candidate(%s,'approve v1')",(cid,))
                cur.execute("""INSERT INTO t008_source_policies
                    (source_code,acquisition_method,content_license,access_terms,allowed_fields,
                     automated_access_allowed,storage_allowed,publication_allowed,reviewed_at,expires_at,policy_version)
                    VALUES(%s,'local_dump','test-only','fixture',%s,true,true,true,%s,%s,2)""",
                    (source,["title","artist"],old.reviewed_at,old.expires_at))
            conn.commit()
            with self.assertRaises(errors.RaiseException):
                with conn.transaction():
                    with conn.cursor() as cur:
                        cur.execute("SELECT t008_publish_preview(%s)",(cid,))
            conn.rollback()
        # Same logical record is re-acquired with v2; both proof generations persist.
        with psycopg.connect(DSN) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT external_id FROM t008_candidates WHERE id=%s",(cid,))
                ext=cur.fetchone()[0]
        r,_,_=self._stage("Upgrade",ext,old.__class__(
            old.source_code,old.method,old.content_license,old.access_terms,
            old.allowed_fields,old.automated_access_allowed,old.storage_allowed,
            old.publication_allowed,old.reviewed,old.reviewed_at,old.expires_at,2))
        self.assertEqual(r["duplicate"],1)
        with psycopg.connect(DSN) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT t008_review_mark(%s,'verify current v2',true)",(cid,))
                cur.execute("SELECT t008_approve_candidate(%s,'reapprove on v2')",(cid,))
                cur.execute("SELECT t008_publish_preview(%s)",(cid,))
                self.assertEqual(cur.fetchone()[0],"published")
                cur.execute("SELECT count(*) FROM t008_approval_revisions WHERE candidate_id=%s",(cid,))
                self.assertEqual(cur.fetchone()[0],2)
                cur.execute("SELECT count(DISTINCT source_policy_id) FROM t008_evidence WHERE candidate_id=%s",(cid,))
                self.assertEqual(cur.fetchone()[0],2)
            conn.commit()

    def test_review_reopen_serializes_with_publish(self):
        cid,_=self._approved()
        started=Event(); release=Event()
        def reopening():
            with psycopg.connect(DSN) as conn:
                with conn.transaction():
                    with conn.cursor() as cur:
                        cur.execute("SELECT t008_review_mark(%s,'reopen on new finding',false)",(cid,))
                        started.set()
                        if not release.wait(8):
                            raise TimeoutError("review test handoff")
        def publishing():
            with psycopg.connect(DSN) as conn:
                with self.assertRaises(errors.RaiseException):
                    with conn.transaction():
                        with conn.cursor() as cur:
                            cur.execute("SET LOCAL lock_timeout='5s'")
                            cur.execute("SELECT t008_publish_preview(%s)",(cid,))
        with ThreadPoolExecutor(max_workers=2) as pool:
            a=pool.submit(reopening)
            self.assertTrue(started.wait(8))
            b=pool.submit(publishing)
            time.sleep(.1)
            release.set()
            a.result(timeout=8);b.result(timeout=8)
        with psycopg.connect(DSN) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT count(*) FROM t008_publication_preview WHERE candidate_id=%s",(cid,))
                self.assertEqual(cur.fetchone()[0],0)

    def test_lock_timeout_then_safe_retry(self):
        key="lock-"+uuid.uuid4().hex
        batch=uuid.uuid4()
        with psycopg.connect(DSN) as blocker:
            with blocker.transaction():
                with blocker.cursor() as cur:
                    cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                                ("t008:claim:"+self.source+":recording:"+key,))
                with psycopg.connect(DSN) as impatient:
                    with impatient.cursor() as cur:
                        cur.execute("SET lock_timeout='150ms'")
                    impatient.commit()
                    with self.assertRaises(errors.LockNotAvailable):
                        stage_candidates(impatient,batch,[Candidate("Timeout","Singer",key)],self.policy)
                    impatient.rollback()
        result,_,_=self._stage("Timeout",key,self.policy,batch)
        self.assertEqual(result["inserted"],1)
        with psycopg.connect(DSN) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT count(*) FROM t008_candidates WHERE batch_id=%s",(batch,))
                self.assertEqual(cur.fetchone()[0],1)

    def test_20_and_50_connection_contention_metrics(self):
        for count in (20,50):
            key=f"load-{count}-"+uuid.uuid4().hex
            def task(i):
                start=time.perf_counter()
                with psycopg.connect(DSN) as conn:
                    conn.execute("SET lock_timeout='10s'")
                    conn.commit()
                    rows=[Candidate(f"Load {i}","Singer",key)]
                    result=stage_candidates(conn,uuid.uuid4(),rows,self.policy)
                    conn.commit()
                return result,(time.perf_counter()-start)*1000
            with ThreadPoolExecutor(max_workers=count) as pool:
                results=list(pool.map(task,range(count)))
            latencies=sorted(ms for _,ms in results)
            with psycopg.connect(DSN) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT count(*) FROM t008_candidates WHERE external_id=%s",(key,))
                    self.assertEqual(cur.fetchone()[0],count)
                    cur.execute("SELECT count(*) FROM t008_evidence e JOIN t008_candidates c ON e.candidate_id=c.id WHERE c.external_id=%s",(key,))
                    self.assertEqual(cur.fetchone()[0],count*2)
                    cur.execute("SELECT count(*) FROM t008_review_queue q JOIN t008_candidates c ON c.id=q.candidate_id WHERE c.external_id=%s",(key,))
                    self.assertEqual(cur.fetchone()[0],count-1)
            self.assertEqual(sum(x["collision"] for x,_ in results),count-1)
            def pct(p):
                return round(latencies[min(len(latencies)-1,int((len(latencies)-1)*p))],2)
            print(f"B012 load={count} completed={count} rejected=0 deadlocks=0 duplicate_candidates=0 "+
                  f"latency_ms_p50={pct(.50)} p95={pct(.95)} p99={pct(.99)} max={round(max(latencies),2)}")


    def test_concurrent_evidence_edit_then_approval(self):
        _,cid,_=self._stage("Edit before approval "+uuid.uuid4().hex,uuid.uuid4().hex)
        with psycopg.connect(DSN) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT t008_review_mark(%s,'initial verification',true)",(cid,))
            conn.commit()
        started=Event(); release=Event()
        def modifying():
            with psycopg.connect(DSN) as conn:
                with conn.transaction():
                    with conn.cursor() as cur:
                        cur.execute("""UPDATE t008_evidence SET source_url='https://fictional.test/source'
                        WHERE candidate_id=%s AND field_name='title'""",(cid,))
                        started.set()
                        if not release.wait(8):
                            raise TimeoutError("evidence lock test")
        def approving():
            with psycopg.connect(DSN) as conn:
                with conn.cursor() as cur:
                    cur.execute("SET lock_timeout='5s'")
                    cur.execute("SELECT t008_approve_candidate(%s,'after evidence change')",(cid,))
                conn.commit()
        with ThreadPoolExecutor(max_workers=2) as executor:
            a=executor.submit(modifying)
            self.assertTrue(started.wait(8))
            b=executor.submit(approving)
            time.sleep(.1)
            release.set()
            a.result(timeout=8); b.result(timeout=8)
        with psycopg.connect(DSN) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT t008_publish_preview(%s)",(cid,))
                self.assertEqual(cur.fetchone()[0],"published")
                cur.execute("""SELECT count(*) FROM t008_audit WHERE action='approved'
                    AND details->>'candidate_id'=%s""",(str(cid),))
                self.assertEqual(cur.fetchone()[0],1)
            conn.commit()

    def test_concurrent_policy_revocation_before_publish(self):
        source="policy_race_"+uuid.uuid4().hex
        now=datetime.now(timezone.utc)
        pol=SourcePolicy(source,"local_dump","test-only","fixture",
             frozenset({"title","artist"}),True,True,True,True,
             now-timedelta(minutes=1),now+timedelta(hours=1))
        with psycopg.connect(DSN) as conn:
            with conn.cursor() as cur:
                cur.execute("""INSERT INTO t008_source_policies
                (source_code,acquisition_method,content_license,access_terms,allowed_fields,
                automated_access_allowed,storage_allowed,publication_allowed,reviewed_at,
                expires_at,policy_version)
                VALUES(%s,'local_dump','test-only','fixture',%s,true,true,true,%s,%s,1)""",
                (source,["title","artist"],pol.reviewed_at,pol.expires_at))
            conn.commit()
        _,cid,_=self._stage("Race policy",uuid.uuid4().hex,pol)
        with psycopg.connect(DSN) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT t008_review_mark(%s,'verified before race',true)",(cid,))
                cur.execute("SELECT t008_approve_candidate(%s,'approved before race')",(cid,))
            conn.commit()
        started=Event();release=Event()
        def revoke_policy():
            with psycopg.connect(DSN) as conn:
                with conn.transaction():
                    with conn.cursor() as cur:
                        cur.execute("""INSERT INTO t008_source_policies
                            (source_code,acquisition_method,content_license,access_terms,
                             allowed_fields,automated_access_allowed,storage_allowed,
                             publication_allowed,reviewed_at,expires_at,policy_version)
                            VALUES(%s,'local_dump','test-only','fixture',%s,true,true,false,%s,%s,2)""",
                            (source,["title","artist"],pol.reviewed_at,pol.expires_at))
                        started.set()
                        if not release.wait(8):
                            raise TimeoutError("policy test handoff")
        def publish():
            with psycopg.connect(DSN) as conn:
                with self.assertRaises(errors.RaiseException):
                    with conn.transaction():
                        with conn.cursor() as cur:
                            cur.execute("SET LOCAL lock_timeout='5s'")
                            cur.execute("SELECT t008_publish_preview(%s)",(cid,))
        with ThreadPoolExecutor(max_workers=2) as executor:
            a=executor.submit(revoke_policy)
            self.assertTrue(started.wait(8))
            b=executor.submit(publish)
            time.sleep(.1)
            release.set()
            a.result(timeout=8); b.result(timeout=8)
        with psycopg.connect(DSN) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT count(*) FROM t008_publication_preview WHERE candidate_id=%s",(cid,))
                self.assertEqual(cur.fetchone()[0],0)

    def test_connection_termination_rolls_back_and_retries(self):
        source=self.source
        key="disconnect-"+uuid.uuid4().hex
        batch=uuid.uuid4()
        content=fingerprint(Candidate("Disconnected","Singer",key))
        event=hashlib.sha256(json.dumps([source,"local_dump",self.policy_id,content],
             separators=(",",":")).encode("utf-8")).hexdigest()
        inserted=Event();release=Event();info={}
        def dying_writer():
            try:
                with psycopg.connect(DSN) as conn:
                    with conn.cursor() as cur:
                        cur.execute("SELECT pg_backend_pid()")
                        info["pid"]=cur.fetchone()[0]
                        cur.execute("SELECT t008_stage_one(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                            (batch,"Disconnected","Singer",source,"recording",key,
                             self.policy_id,content,event))
                        self.assertEqual(cur.fetchone()[0],"new")
                        inserted.set()
                        release.wait(8)
                    conn.commit()
            except psycopg.OperationalError:
                info["terminated"]=True
        with ThreadPoolExecutor(max_workers=1) as executor:
            job=executor.submit(dying_writer)
            self.assertTrue(inserted.wait(8))
            with psycopg.connect(DSN) as killer:
                with killer.cursor() as cur:
                    cur.execute("SELECT pg_terminate_backend(%s)",(info["pid"],))
                    self.assertTrue(cur.fetchone()[0])
            release.set()
            job.result(timeout=8)
        self.assertTrue(info.get("terminated"))
        # A PostgreSQL backend termination must have rolled back the uncommitted
        # candidate, evidence, intake event and external-claim atomically.
        with psycopg.connect(DSN) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT count(*) FROM t008_candidates WHERE batch_id=%s",(batch,))
                self.assertEqual(cur.fetchone()[0],0)
        result,_,_=self._stage("Disconnected",key,self.policy,batch)
        self.assertEqual(result["inserted"],1)
        with psycopg.connect(DSN) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT count(*) FROM t008_candidates WHERE batch_id=%s",(batch,))
                self.assertEqual(cur.fetchone()[0],1)

if __name__=="__main__":
    unittest.main()
