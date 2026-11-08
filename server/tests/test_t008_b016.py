"""B-016 regression: published reingestion, lock ordering, repeated revocation and review identity."""
import os,time,uuid,unittest
from datetime import datetime,timedelta,timezone
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import psycopg
from psycopg import errors
from dataclasses import replace
from server.t008_policy import SourcePolicy
from server.t008_stage_import import Candidate,stage_candidates

DSN=os.getenv("KEN_T008_TEST_DATABASE_URL","")
REVIEW_DSN=os.getenv("KEN_T008_REVIEW_LOGIN_DSN","")
@unittest.skipUnless(DSN and os.getenv("KEN_T008_ALLOW_DISPOSABLE")=="YES","disposable test DB required")
class B016Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src="b014_b016_"+uuid.uuid4().hex
        now=datetime.now(timezone.utc)
        cls.policy=SourcePolicy(cls.src,"local_dump","test-only","fixture approved",
             frozenset({"title","artist"}),True,True,True,True,
             now-timedelta(minutes=1),now+timedelta(hours=1))
        with psycopg.connect(DSN) as c:
            with c.cursor() as cur:
                cur.execute("SELECT current_database()")
                assert cur.fetchone()[0] in ("ken_test","t008_test")
                cur.execute("""INSERT INTO t008_source_policies
                  (source_code,acquisition_method,content_license,access_terms,allowed_fields,
                   automated_access_allowed,storage_allowed,publication_allowed,reviewed_at,
                   expires_at,policy_version) VALUES (%s,'local_dump','test-only','fixture approved',
                   %s,true,true,true,%s,%s,1)""",
                   (cls.src,["title","artist"],cls.policy.reviewed_at,cls.policy.expires_at))
            c.commit()

    def stage(self,key,title="Reingest",pol=None,batch=None):
        batch=batch or uuid.uuid4()
        with psycopg.connect(DSN) as c:
            outcome=stage_candidates(c,batch,[Candidate(title,"Singer",key)],pol or self.policy)
            c.commit()
            with c.cursor() as cur:
                cur.execute("SELECT id FROM t008_candidates WHERE batch_id=%s",(batch,))
                row=cur.fetchone()
            c.commit()
        return outcome,row[0] if row else None

    def publish(self,cid):
        with psycopg.connect(DSN) as c:
            with c.cursor() as cur:
                cur.execute("SELECT t008_review_mark(%s,'checked fixture',true)",(cid,))
                cur.execute("SELECT t008_approve_candidate(%s,'fixture approval')",(cid,))
                cur.execute("SELECT t008_publish_preview(%s)",(cid,))
                self.assertEqual(cur.fetchone()[0],"published")
            c.commit()

    def test_published_same_policy_is_event_only(self):
        key=uuid.uuid4().hex
        _,cid=self.stage(key)
        self.publish(cid)
        r,new=self.stage(key)
        self.assertEqual(r["duplicate"],1)
        self.assertIsNone(new)
        with psycopg.connect(DSN) as c:
            with c.cursor() as cur:
                cur.execute("SELECT count(*) FROM t008_evidence WHERE candidate_id=%s",(cid,))
                self.assertEqual(cur.fetchone()[0],2)
                cur.execute("SELECT count(*) FROM t008_intake_events WHERE candidate_id=%s",(cid,))
                self.assertEqual(cur.fetchone()[0],2)
                cur.execute("SELECT state FROM t008_publication_preview WHERE candidate_id=%s",(cid,))
                self.assertEqual(cur.fetchone()[0],"published")

    def test_published_new_policy_uses_new_review_candidate(self):
        key=uuid.uuid4().hex
        _,first=self.stage(key)
        self.publish(first)
        source="b014_b016_"+uuid.uuid4().hex
        # Independent policy source to avoid affecting other shared fixtures.
        with psycopg.connect(DSN) as c:
            with c.cursor() as cur:
                cur.execute("""INSERT INTO t008_source_policies
                  (source_code,acquisition_method,content_license,access_terms,allowed_fields,
                   automated_access_allowed,storage_allowed,publication_allowed,reviewed_at,expires_at,policy_version)
                  VALUES(%s,'local_dump','test-only','fixture approved',%s,true,true,true,%s,%s,1)""",
                   (source,["title","artist"],self.policy.reviewed_at,self.policy.expires_at))
            c.commit()
        _,original=self.stage(uuid.uuid4().hex,pol=replace(self.policy,source_code=source))
        # Use the original external ID of this source.
        with psycopg.connect(DSN) as c:
            with c.cursor() as cur:
                cur.execute("SELECT external_id FROM t008_candidates WHERE id=%s",(original,))
                ext=cur.fetchone()[0]
        self.publish(original)
        with psycopg.connect(DSN) as c:
            with c.cursor() as cur:
                cur.execute("""INSERT INTO t008_source_policies
                  (source_code,acquisition_method,content_license,access_terms,allowed_fields,
                   automated_access_allowed,storage_allowed,publication_allowed,reviewed_at,expires_at,policy_version)
                  VALUES(%s,'local_dump','test-only','fixture approved',%s,true,true,true,%s,%s,2)""",
                   (source,["title","artist"],self.policy.reviewed_at,self.policy.expires_at))
            c.commit()
        refreshed,new=self.stage(ext,pol=replace(self.policy,source_code=source,policy_version=2))
        self.assertEqual(refreshed["collision"],1)
        self.assertNotEqual(original,new)
        with psycopg.connect(DSN) as c:
            with c.cursor() as cur:
                cur.execute("SELECT previous_candidate_id,reason FROM t008_publication_refreshes WHERE candidate_id=%s",(new,))
                self.assertEqual(cur.fetchone(),(original,"policy_version_changed"))
                cur.execute("SELECT count(*) FROM t008_evidence WHERE candidate_id=%s",(original,))
                self.assertEqual(cur.fetchone()[0],2)
                cur.execute("SELECT state FROM t008_publication_preview WHERE candidate_id=%s",(original,))
                self.assertEqual(cur.fetchone()[0],"published")
                cur.execute("SELECT status FROM t008_review_queue WHERE candidate_id=%s",(new,))
                self.assertEqual(cur.fetchone()[0],"open")

    def test_two_consecutive_reapplications_preserve_lineage(self):
        key=uuid.uuid4().hex
        _,first=self.stage(key)
        self.publish(first)
        with psycopg.connect(DSN) as c:
            c.execute("SELECT t008_revoke_preview(%s)",(first,))
            c.commit()
        _,second=self.stage(key)
        with psycopg.connect(DSN) as c:
            with c.cursor() as cur:
                cur.execute("SELECT id FROM t008_review_queue WHERE candidate_id=%s",(second,))
                issue=cur.fetchone()[0]
                cur.execute("SELECT id FROM t008_evidence WHERE candidate_id=%s ORDER BY id",(second,))
                evidence=[x[0] for x in cur.fetchall()]
                for eid in evidence:
                    cur.execute("SELECT t008_review_evidence(%s,'fixture checked')",(eid,))
                cur.execute("SELECT t008_resolve_issue(%s,'reapplication justified')",(issue,))
                cur.execute("SELECT t008_finalize_review(%s,'all evidence reviewed')",(second,))
                cur.execute("SELECT t008_approve_candidate(%s,'approved again')",(second,))
                cur.execute("SELECT t008_publish_preview(%s)",(second,))
                self.assertEqual(cur.fetchone()[0],"published")
                cur.execute("SELECT t008_revoke_preview(%s)",(second,))
            c.commit()
        _,third=self.stage(key)
        self.assertEqual(len(set([first,second,third])),3)
        with psycopg.connect(DSN) as c:
            with c.cursor() as cur:
                cur.execute("SELECT previous_candidate_id FROM t008_reapplications WHERE candidate_id=%s",(second,))
                self.assertEqual(cur.fetchone()[0],first)
                cur.execute("SELECT previous_candidate_id FROM t008_reapplications WHERE candidate_id=%s",(third,))
                self.assertEqual(cur.fetchone()[0],second)
                cur.execute("SELECT count(*) FROM t008_publication_preview WHERE candidate_id IN (%s,%s) AND state='revoked'",(first,second))
                self.assertEqual(cur.fetchone()[0],2)

    def test_intake_vs_publish_same_identity_no_deadlock(self):
        key=uuid.uuid4().hex
        _,cid=self.stage(key)
        with psycopg.connect(DSN) as c:
            c.execute("SELECT t008_review_mark(%s,'ready to publish',true)",(cid,))
            c.execute("SELECT t008_approve_candidate(%s,'approved')",(cid,))
            c.commit()
        start=Event()
        def publish():
            with psycopg.connect(DSN) as c:
                c.execute("SET lock_timeout='5s'")
                c.commit()
                start.wait(5)
                value=c.execute("SELECT t008_publish_preview(%s)",(cid,)).fetchone()[0]
                c.commit()
                return value
        def ingest():
            start.wait(5)
            return self.stage(key)
        with ThreadPoolExecutor(max_workers=2) as pool:
            p=pool.submit(publish)
            i=pool.submit(ingest)
            start.set()
            self.assertEqual(p.result(timeout=9),"published")
            counts,other=i.result(timeout=9)
            self.assertEqual(counts["duplicate"],1)
            self.assertIsNone(other)
        with psycopg.connect(DSN) as c:
            with c.cursor() as cur:
                cur.execute("SELECT count(*) FROM t008_evidence WHERE candidate_id=%s",(cid,))
                self.assertEqual(cur.fetchone()[0],2)

    def test_concurrent_issue_resolution_exactly_once(self):
        key=uuid.uuid4().hex
        self.stage(key)
        _,cid=self.stage(key,title="other title")
        with psycopg.connect(DSN) as c:
            with c.cursor() as cur:
                cur.execute("SELECT id FROM t008_review_queue WHERE candidate_id=%s",(cid,))
                issue=cur.fetchone()[0]
                cur.execute("SELECT id FROM t008_evidence WHERE candidate_id=%s ORDER BY id",(cid,))
                for (eid,) in cur.fetchall():
                    cur.execute("SELECT t008_review_evidence(%s,'specific proof validated')",(eid,))
            c.commit()
        entered=Event(); release=Event()
        def first():
            with psycopg.connect(DSN) as c:
                with c.transaction():
                    c.execute("SELECT t008_resolve_issue(%s,'review 1')",(issue,))
                    entered.set()
                    if not release.wait(7):raise TimeoutError("review")
        def second():
            with psycopg.connect(DSN) as c:
                c.execute("SET lock_timeout='5s'")
                c.commit()
                try:
                    c.execute("SELECT t008_resolve_issue(%s,'review 2')",(issue,))
                    c.commit()
                    return "resolved"
                except errors.RaiseException:
                    c.rollback();return "rejected"
        with ThreadPoolExecutor(max_workers=2) as pool:
            f=pool.submit(first);self.assertTrue(entered.wait(7))
            other=pool.submit(second);time.sleep(.1);release.set()
            f.result(timeout=8);self.assertEqual(other.result(timeout=8),"rejected")
        with psycopg.connect(DSN) as c:
            with c.cursor() as cur:
                cur.execute("SELECT count(*) FROM t008_review_decisions WHERE issue_id=%s AND decision='resolved'",(issue,))
                self.assertEqual(cur.fetchone()[0],1)

    @unittest.skipUnless(REVIEW_DSN,"CI reviewer login is absent")
    def test_real_nonowner_reviewer_identity_and_denials(self):
        key=uuid.uuid4().hex
        _,cid=self.stage(key)
        with psycopg.connect(DSN) as c:
            with c.cursor() as cur:
                cur.execute("SELECT id FROM t008_evidence WHERE candidate_id=%s ORDER BY id LIMIT 1",(cid,))
                evidence=cur.fetchone()[0]
        with psycopg.connect(REVIEW_DSN) as c:
            with c.cursor() as cur:
                cur.execute("SELECT session_user")
                self.assertEqual(cur.fetchone()[0],"t008_review_login")
                cur.execute("SELECT t008_review_evidence(%s,'verified with dedicated reviewer login')",(evidence,))
            c.commit()
        with psycopg.connect(DSN) as c:
            with c.cursor() as cur:
                cur.execute("SELECT reviewer_id FROM t008_review_decisions WHERE evidence_id=%s",(evidence,))
                self.assertEqual(cur.fetchone()[0],"CI-REVIEWER-ROLE")
                cur.execute("SELECT COUNT(*) FROM t008_audit WHERE action='evidence_reviewed' AND details->>'reviewer_id'='CI-REVIEWER-ROLE' AND details->>'evidence_id'=%s",(str(evidence),))
                self.assertEqual(cur.fetchone()[0],1)
        with psycopg.connect(REVIEW_DSN) as c:
            with self.assertRaises(errors.InsufficientPrivilege):
                with c.transaction():
                    c.execute("SELECT t008_review_mark(%s,'unauthorized bulk',true)",(cid,))
            c.rollback()
            with self.assertRaises(errors.InsufficientPrivilege):
                with c.transaction():
                    c.execute("UPDATE t008_review_decisions SET reason='forged'")
            c.rollback()
if __name__=="__main__":unittest.main()
