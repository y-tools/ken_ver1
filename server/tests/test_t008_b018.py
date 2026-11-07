"""T008 B-018: active-publication pointer and evidence-backed collision tests.
Only the disposable PostgreSQL CI database is used.
"""
import os, uuid, unittest, time
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import psycopg
from psycopg import errors
from server.t008_stage_import import Candidate, stage_candidates
from server.t008_policy import SourcePolicy

DSN=os.environ.get("KEN_T008_TEST_DATABASE_URL","")
@unittest.skipUnless(DSN and os.environ.get("KEN_T008_ALLOW_DISPOSABLE")=="YES",
                     "disposable PostgreSQL required")
class B018ActivePublicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source="b014_b018_"+uuid.uuid4().hex
        now=datetime.now(timezone.utc)
        cls.policy=SourcePolicy(cls.source,"local_dump","test-only","fixture approved",
             frozenset({"title","artist"}),True,True,True,True,
             now-timedelta(minutes=1),now+timedelta(hours=1))
        with psycopg.connect(DSN) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT current_database()")
                assert cur.fetchone()[0] in ("ken_test","t008_test")
                cur.execute("""INSERT INTO t008_source_policies(source_code,
                   acquisition_method,content_license,access_terms,allowed_fields,
                   automated_access_allowed,storage_allowed,publication_allowed,
                   reviewed_at,expires_at,policy_version)
                   VALUES(%s,'local_dump','test-only','fixture approved',
                   %s,true,true,true,%s,%s,1)""",
                   (cls.source,["title","artist"],cls.policy.reviewed_at,cls.policy.expires_at))
            conn.commit()

    def stage(self, external, title):
        batch=uuid.uuid4()
        with psycopg.connect(DSN) as conn:
            counts=stage_candidates(conn,batch,[Candidate(title,"Singer",external)],self.policy)
            conn.commit()
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM t008_candidates WHERE batch_id=%s",(batch,))
                row=cur.fetchone()
            conn.commit()
        return counts,row[0] if row else None

    def initial_publish(self,key,title="Song A"):
        _,cid=self.stage(key,title)
        with psycopg.connect(DSN) as conn:
            conn.execute("SELECT t008_review_mark(%s,'fictional fixture checked',true)",(cid,))
            conn.execute("SELECT t008_approve_candidate(%s,'initial approval')",(cid,))
            self.assertEqual(conn.execute("SELECT t008_publish_preview(%s)",(cid,)).fetchone()[0],"published")
            conn.commit()
        return cid

    def review_candidate(self,cid):
        with psycopg.connect(DSN) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM t008_evidence WHERE candidate_id=%s ORDER BY id",(cid,))
                items=[row[0] for row in cur.fetchall()]
                cur.execute("SELECT id FROM t008_review_queue WHERE candidate_id=%s AND status='open' ORDER BY id",(cid,))
                issues=[row[0] for row in cur.fetchall()]
                for item in items:
                    cur.execute("SELECT t008_review_evidence(%s,'confirmed synthetic field evidence')",(item,))
                for issue in issues:
                    cur.execute("SELECT t008_resolve_issue(%s,'recording identity requires independent mapping')",(issue,))
                cur.execute("SELECT t008_finalize_review(%s,'all synthetic evidence inspected')",(cid,))
            conn.commit()
        return items

    def decide(self,cid,compared,decision,items):
        with psycopg.connect(DSN) as conn:
            conn.execute("SELECT t008_identity_decide(%s,%s,%s,%s,%s,%s)",
                (cid,compared,items[0],items[1],decision,
                 "Two original synthetic records independently checked and compared"))
            conn.commit()

    def test_two_pending_candidates_do_not_change_active_pointer(self):
        key=uuid.uuid4().hex
        a=self.initial_publish(key)
        _,b=self.stage(key,"Song B")
        _,c=self.stage(key,"Song C")
        with psycopg.connect(DSN) as conn:
            cur=conn.cursor()
            cur.execute("SELECT candidate_id FROM t008_active_publications WHERE external_id=%s",(key,))
            self.assertEqual(cur.fetchone()[0],a)
            cur.execute("SELECT candidate_id FROM t008_external_claims WHERE external_id=%s AND source_code=%s",(key,self.source))
            self.assertEqual(cur.fetchone()[0],b)
            cur.execute("SELECT COUNT(*) FROM t008_candidates WHERE external_id=%s AND external_source=%s",(key,self.source))
            self.assertEqual(cur.fetchone()[0],3)
            cur.execute("SELECT count(*) FROM t008_publication_preview p WHERE p.external_id=%s AND p.state='published'",(key,))
            self.assertEqual(cur.fetchone()[0],1)
            cur.execute("SELECT status FROM t008_review_queue WHERE candidate_id=%s",(c,))
            self.assertEqual(cur.fetchone()[0],"open")

    def test_atomic_promotion_supersedes_and_failure_rolls_back(self):
        key=uuid.uuid4().hex
        a=self.initial_publish(key)
        _,b=self.stage(key,"New Synthetic Title")
        items=self.review_candidate(b)
        self.decide(b,a,"same_recording",items)
        with psycopg.connect(DSN) as conn:
            conn.execute("SELECT t008_approve_candidate(%s,'approve reviewed identity')",(b,))
            conn.commit()
        with psycopg.connect(DSN) as conn:
            with self.assertRaises(errors.RaiseException):
                with conn.transaction():
                    conn.execute("SELECT t008_publish_preview(%s,true)",(b,))
            conn.rollback()
            cur=conn.cursor()
            cur.execute("SELECT candidate_id FROM t008_active_publications WHERE external_id=%s",(key,))
            self.assertEqual(cur.fetchone()[0],a)
            cur.execute("SELECT count(*) FROM t008_publication_preview WHERE candidate_id=%s",(b,))
            self.assertEqual(cur.fetchone()[0],0)
        with psycopg.connect(DSN) as conn:
            self.assertEqual(conn.execute("SELECT t008_publish_preview(%s)",(b,)).fetchone()[0],"published")
            conn.commit()
            cur=conn.cursor()
            cur.execute("SELECT candidate_id FROM t008_active_publications WHERE external_id=%s",(key,))
            self.assertEqual(cur.fetchone()[0],b)
            cur.execute("SELECT state FROM t008_publication_preview WHERE candidate_id=%s",(a,))
            self.assertEqual(cur.fetchone()[0],"superseded")
            cur.execute("SELECT count(*) FROM t008_publication_preview WHERE external_id=%s AND state='published'",(key,))
            self.assertEqual(cur.fetchone()[0],1)
            cur.execute("SELECT count(*) FROM t008_publication_history WHERE external_id=%s AND action='supersede'",(key,))
            self.assertEqual(cur.fetchone()[0],1)

    def test_distinct_recording_identity_decision_blocks_publish(self):
        key=uuid.uuid4().hex
        a=self.initial_publish(key)
        _,b=self.stage(key,"Unrelated Other Song")
        items=self.review_candidate(b)
        self.decide(b,a,"distinct_recording",items)
        with psycopg.connect(DSN) as conn:
            conn.execute("SELECT t008_approve_candidate(%s,'reviewed fixture')",(b,))
            conn.commit()
        with psycopg.connect(DSN) as conn:
            with self.assertRaises(errors.RaiseException):
                with conn.transaction():
                    conn.execute("SELECT t008_publish_preview(%s)",(b,))
            conn.rollback()
            cur=conn.cursor()
            cur.execute("SELECT candidate_id FROM t008_active_publications WHERE external_id=%s",(key,))
            self.assertEqual(cur.fetchone()[0],a)
            cur.execute("SELECT COUNT(*) FROM t008_publication_preview WHERE external_id=%s AND state='published'",(key,))
            self.assertEqual(cur.fetchone()[0],1)
            cur.execute("SELECT decision,reviewer_id FROM t008_identity_decisions WHERE candidate_id=%s",(b,))
            self.assertEqual(cur.fetchone(),("distinct_recording","CI-REVIEWER-POSTGRES"))

    def test_pending_candidate_without_identity_decision_cannot_publish(self):
        key=uuid.uuid4().hex
        a=self.initial_publish(key)
        _,b=self.stage(key,"Changed Again")
        self.review_candidate(b)
        with psycopg.connect(DSN) as conn:
            conn.execute("SELECT t008_approve_candidate(%s,'reviewed fields, identity unresolved')",(b,))
            conn.commit()
        with psycopg.connect(DSN) as conn:
            with self.assertRaises(errors.RaiseException):
                with conn.transaction():
                    conn.execute("SELECT t008_publish_preview(%s)",(b,))
            conn.rollback()
            self.assertEqual(conn.execute("SELECT candidate_id FROM t008_active_publications WHERE external_id=%s",(key,)).fetchone()[0],a)

    def test_concurrent_promotion_and_reingestion_preserves_one_active(self):
        key=uuid.uuid4().hex
        a=self.initial_publish(key)
        _,b=self.stage(key,"Updated Recording")
        items=self.review_candidate(b)
        self.decide(b,a,"same_recording",items)
        with psycopg.connect(DSN) as conn:
            conn.execute("SELECT t008_approve_candidate(%s,'reviewed mapping')",(b,))
            conn.commit()
        gate=Event()
        def publish():
            with psycopg.connect(DSN) as conn:
                conn.execute("SET lock_timeout='5s'");conn.commit()
                gate.wait(6)
                value=conn.execute("SELECT t008_publish_preview(%s)",(b,)).fetchone()[0]
                conn.commit()
                return value
        def ingest():
            gate.wait(6)
            return self.stage(key,"Third Pending Version")
        with ThreadPoolExecutor(max_workers=2) as executor:
            future=executor.submit(publish)
            pending=executor.submit(ingest)
            gate.set()
            self.assertEqual(future.result(timeout=9),"published")
            counts,c=pending.result(timeout=9)
            self.assertEqual(counts["collision"],1)
            self.assertNotEqual(c,b)
        with psycopg.connect(DSN) as conn:
            cur=conn.cursor()
            cur.execute("SELECT candidate_id FROM t008_active_publications WHERE external_id=%s",(key,))
            self.assertEqual(cur.fetchone()[0],b)
            cur.execute("SELECT COUNT(*) FROM t008_publication_preview WHERE external_id=%s AND state='published'",(key,))
            self.assertEqual(cur.fetchone()[0],1)


    def test_two_competing_promotion_candidates_only_one_wins(self):
        key=uuid.uuid4().hex
        a=self.initial_publish(key)
        _,b=self.stage(key,"Updated Title B")
        _,c=self.stage(key,"Updated Title C")
        for candidate in (b,c):
            proofs=self.review_candidate(candidate)
            self.decide(candidate,a,"same_recording",proofs)
            with psycopg.connect(DSN) as conn:
                conn.execute("SELECT t008_approve_candidate(%s,'conflicting concurrent approval')",(candidate,))
                conn.commit()
        gate=Event()
        def promote(candidate):
            with psycopg.connect(DSN) as conn:
                conn.execute("SET lock_timeout='5s'")
                conn.commit()
                gate.wait(5)
                try:
                    result=conn.execute("SELECT t008_publish_preview(%s)",(candidate,)).fetchone()[0]
                    conn.commit()
                    return result
                except errors.RaiseException:
                    conn.rollback()
                    return "rejected"
        with ThreadPoolExecutor(max_workers=2) as executor:
            f1=executor.submit(promote,b)
            f2=executor.submit(promote,c)
            gate.set()
            outcomes=[f1.result(timeout=9),f2.result(timeout=9)]
        self.assertEqual(outcomes.count("published"),1)
        self.assertEqual(outcomes.count("rejected"),1)
        with psycopg.connect(DSN) as conn:
            cur=conn.cursor()
            cur.execute("SELECT candidate_id FROM t008_active_publications WHERE external_id=%s AND source_code=%s",(key,self.source))
            winner=cur.fetchone()[0]
            self.assertIn(winner,(b,c))
            cur.execute("SELECT count(*) FROM t008_publication_preview WHERE external_id=%s AND state='published'",(key,))
            self.assertEqual(cur.fetchone()[0],1)
            cur.execute("SELECT state FROM t008_publication_preview WHERE candidate_id=%s",(a,))
            self.assertEqual(cur.fetchone()[0],"superseded")

    def test_revoke_races_with_reacquisition(self):
        key=uuid.uuid4().hex
        a=self.initial_publish(key)
        gate=Event()
        def revoke():
            with psycopg.connect(DSN) as conn:
                gate.wait(5)
                value=conn.execute("SELECT t008_revoke_preview(%s)",(a,)).fetchone()[0]
                conn.commit()
                return value
        def ingest():
            gate.wait(5)
            return self.stage(key,"Song A")
        with ThreadPoolExecutor(max_workers=2) as executor:
            r=executor.submit(revoke)
            i=executor.submit(ingest)
            gate.set()
            self.assertEqual(r.result(timeout=9),"revoked")
            counts,new=i.result(timeout=9)
            self.assertTrue(counts["inserted"]+counts["duplicate"]>=1)
        with psycopg.connect(DSN) as conn:
            cur=conn.cursor()
            cur.execute("SELECT count(*) FROM t008_active_publications WHERE external_id=%s",(key,))
            self.assertEqual(cur.fetchone()[0],0)
            cur.execute("SELECT state FROM t008_publication_preview WHERE candidate_id=%s",(a,))
            self.assertEqual(cur.fetchone()[0],"revoked")
            cur.execute("SELECT count(*) FROM t008_publication_preview WHERE external_id=%s AND state='published'",(key,))
            self.assertEqual(cur.fetchone()[0],0)

    def test_new_policy_denial_races_with_pending_promotion(self):
        source="b014_b018_"+uuid.uuid4().hex
        policy=self.policy.__class__(source,self.policy.method,self.policy.content_license,
            self.policy.access_terms,self.policy.allowed_fields,
            self.policy.automated_access_allowed,self.policy.storage_allowed,
            self.policy.publication_allowed,self.policy.reviewed,
            self.policy.reviewed_at,self.policy.expires_at)
        key=uuid.uuid4().hex
        with psycopg.connect(DSN) as conn:
            conn.execute("""INSERT INTO t008_source_policies
                 (source_code,acquisition_method,content_license,access_terms,allowed_fields,
                  automated_access_allowed,storage_allowed,publication_allowed,reviewed_at,
                  expires_at,policy_version)
                 VALUES(%s,'local_dump','test-only','fixture approved',%s,true,true,true,%s,%s,1)""",
                 (source,["title","artist"],policy.reviewed_at,policy.expires_at))
            conn.commit()
        def add(title):
            batch=uuid.uuid4()
            with psycopg.connect(DSN) as conn:
                stage_candidates(conn,batch,[Candidate(title,"Singer",key)],policy)
                conn.commit()
                row=conn.execute("SELECT id FROM t008_candidates WHERE batch_id=%s",(batch,)).fetchone()
                return row[0]
        a=add("Original")
        with psycopg.connect(DSN) as conn:
            conn.execute("SELECT t008_review_mark(%s,'fixture review completed',true)",(a,))
            conn.execute("SELECT t008_approve_candidate(%s,'fixture A')",(a,))
            conn.execute("SELECT t008_publish_preview(%s)",(a,))
            conn.commit()
        b=add("New version")
        with psycopg.connect(DSN) as conn:
            cur=conn.cursor()
            cur.execute("SELECT id FROM t008_evidence WHERE candidate_id=%s ORDER BY id",(b,))
            ids=[r[0] for r in cur.fetchall()]
            for eid in ids:
                cur.execute("SELECT t008_review_evidence(%s,'validated independently')",(eid,))
            cur.execute("SELECT id FROM t008_review_queue WHERE candidate_id=%s",(b,))
            issue=cur.fetchone()[0]
            cur.execute("SELECT t008_resolve_issue(%s,'same external ID reviewed')",(issue,))
            cur.execute("SELECT t008_finalize_review(%s,'finished proof review')",(b,))
            cur.execute("SELECT t008_identity_decide(%s,%s,%s,%s,'same_recording',%s)",
                (b,a,ids[0],ids[1],"Compared independently as equivalent synthetic recording"))
            cur.execute("SELECT t008_approve_candidate(%s,'approved pending version')",(b,))
            conn.commit()
        entered=Event()
        release=Event()
        def change_policy():
            with psycopg.connect(DSN) as conn:
                with conn.transaction():
                    conn.execute("""INSERT INTO t008_source_policies
                        (source_code,acquisition_method,content_license,access_terms,
                         allowed_fields,automated_access_allowed,storage_allowed,
                         publication_allowed,reviewed_at,expires_at,policy_version)
                        VALUES(%s,'local_dump','test-only','fixture approved',
                         %s,true,true,false,%s,%s,2)""",
                         (source,["title","artist"],policy.reviewed_at,policy.expires_at))
                    entered.set()
                    if not release.wait(7):
                        raise TimeoutError("policy synchronization")
        def attempt_publish():
            with psycopg.connect(DSN) as conn:
                conn.execute("SET lock_timeout='5s'")
                conn.commit()
                try:
                    conn.execute("SELECT t008_publish_preview(%s)",(b,))
                    conn.commit()
                    return "published"
                except errors.RaiseException:
                    conn.rollback()
                    return "rejected"
        with ThreadPoolExecutor(max_workers=2) as pool:
            first=pool.submit(change_policy)
            self.assertTrue(entered.wait(7))
            second=pool.submit(attempt_publish)
            time.sleep(.1)
            release.set()
            first.result(timeout=9)
            self.assertEqual(second.result(timeout=9),"rejected")
        with psycopg.connect(DSN) as conn:
            cur=conn.cursor()
            cur.execute("SELECT candidate_id FROM t008_active_publications WHERE source_code=%s AND external_id=%s",(source,key))
            self.assertEqual(cur.fetchone()[0],a)
            cur.execute("SELECT COUNT(*) FROM t008_publication_preview WHERE source_code=%s AND external_id=%s AND state='published'",(source,key))
            self.assertEqual(cur.fetchone()[0],1)

    def test_direct_sql_duplicate_published_row_blocked(self):
        key=uuid.uuid4().hex
        a=self.initial_publish(key)
        _,b=self.stage(key,"Independent Title")
        with psycopg.connect(DSN) as conn:
            with self.assertRaises(errors.UniqueViolation):
                with conn.transaction():
                    cur=conn.cursor()
                    cur.execute("""INSERT INTO t008_publication_preview
                     (candidate_id,title,artist,approved_by,approved_at,proof_digest,
                     source_code,entity_type,external_id)
                     VALUES(%s,'Bypass','Singer','fixture',now(),'fake',%s,'recording',%s)""",
                     (b,self.source,key))
            conn.rollback()
            cur=conn.cursor()
            cur.execute("SELECT candidate_id FROM t008_active_publications WHERE external_id=%s AND source_code=%s",(key,self.source))
            self.assertEqual(cur.fetchone()[0],a)

if __name__=="__main__":
    unittest.main()
