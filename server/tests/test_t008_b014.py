"""T008 B-014 disposable PostgreSQL regressions (no production access)."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime,timezone,timedelta
from threading import Event
from statistics import median
import os,uuid,time,unittest
import psycopg
from psycopg import errors
from server.t008_policy import SourcePolicy
from server.t008_stage_import import Candidate,stage_candidates

DSN=os.environ.get("KEN_T008_TEST_DATABASE_URL","")
@unittest.skipUnless(DSN and os.getenv("KEN_T008_ALLOW_DISPOSABLE")=="YES","disposable test DB only")
class T008B014Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source="b014_"+uuid.uuid4().hex
        now=datetime.now(timezone.utc)
        cls.policy=SourcePolicy(cls.source,"local_dump","test-only","fixture approved",
            frozenset({"title","artist"}),True,True,True,True,
            now-timedelta(hours=1),now+timedelta(hours=1))
        with psycopg.connect(DSN) as con:
            with con.cursor() as c:
                c.execute("SELECT current_database()")
                assert c.fetchone()[0] in ("ken_test","t008_test")
                c.execute("""INSERT INTO t008_source_policies
                 (source_code,acquisition_method,content_license,access_terms,allowed_fields,
                  automated_access_allowed,storage_allowed,publication_allowed,reviewed_at,expires_at,policy_version)
                 VALUES (%s,'local_dump','test-only','fixture approved',%s,true,true,true,%s,%s,1)
                 RETURNING id""",
                (cls.source,["title","artist"],cls.policy.reviewed_at,cls.policy.expires_at))
                cls.pid=c.fetchone()[0]
            con.commit()

    def stage(self,key=None, title="Reissue", pol=None):
        key=key or uuid.uuid4().hex
        batch=uuid.uuid4()
        with psycopg.connect(DSN) as con:
            r=stage_candidates(con,batch,[Candidate(title,"Singer",key)],pol or self.policy)
            con.commit()
            with con.cursor() as c:
                c.execute("SELECT id FROM t008_candidates WHERE batch_id=%s",(batch,))
                result=c.fetchone()
            con.commit()
        return key,r,result[0] if result else None

    def test_unknown_terms_refused_at_database_function(self):
        for label in ("n/a","none","not reviewed","未審査"):
            source="deny_"+uuid.uuid4().hex
            with psycopg.connect(DSN) as con:
                with con.cursor() as c:
                    c.execute("""INSERT INTO t008_source_policies
                      (source_code,acquisition_method,content_license,access_terms,allowed_fields,
                      automated_access_allowed,storage_allowed,publication_allowed,reviewed_at,
                      expires_at,policy_version) VALUES (%s,'local_dump','test-only',%s,
                      %s,true,true,true,%s,%s,1) RETURNING id""",
                      (source,label,["title","artist"],self.policy.reviewed_at,self.policy.expires_at))
                    pid=c.fetchone()[0]
                    c.execute("SELECT t008_policy_storage_ok(%s,%s,'local_dump')",(pid,source))
                    self.assertFalse(c.fetchone()[0],label)
                    c.execute("""SELECT count(*) FROM t008_policy_authorizations WHERE policy_id=%s""",(pid,))
                    self.assertEqual(c.fetchone()[0],0)
                con.commit()

    def test_no_authorization_even_with_positive_flags(self):
        with psycopg.connect(DSN) as con:
            with con.cursor() as c:
                c.execute("""INSERT INTO t008_source_policies
                  (source_code,acquisition_method,content_license,access_terms,allowed_fields,
                   automated_access_allowed,storage_allowed,publication_allowed,reviewed_at,
                   expires_at,policy_version)
                   VALUES ('not_preapproved','local_dump','test-only','fixture approved',
                   %s,true,true,true,%s,%s,1) RETURNING id""",
                  (["title","artist"],self.policy.reviewed_at,self.policy.expires_at))
                pid=c.fetchone()[0]
                c.execute("SELECT t008_policy_storage_ok(%s,'not_preapproved','local_dump')",(pid,))
                self.assertFalse(c.fetchone()[0])
            con.commit()

    def test_revocation_reapplication_creates_new_candidate(self):
        key,r,old=self.stage()
        self.assertEqual(r["inserted"],1)
        with psycopg.connect(DSN) as con:
            with con.cursor() as c:
                c.execute("SELECT t008_review_mark(%s,'fixture reviewed',true)",(old,))
                c.execute("SELECT t008_approve_candidate(%s,'fixture approved')",(old,))
                c.execute("SELECT t008_publish_preview(%s)",(old,))
                self.assertEqual(c.fetchone()[0],"published")
                c.execute("SELECT t008_revoke_preview(%s)",(old,))
                self.assertEqual(c.fetchone()[0],"revoked")
            con.commit()
        key,r,new=self.stage(key)
        self.assertEqual(r["inserted"],1)
        self.assertNotEqual(old,new)
        with psycopg.connect(DSN) as con:
            with con.cursor() as c:
                c.execute("""SELECT previous_candidate_id FROM t008_reapplications
                  WHERE candidate_id=%s""",(new,))
                self.assertEqual(c.fetchone()[0],old)
                c.execute("SELECT verification FROM t008_candidates WHERE id=%s",(new,))
                self.assertEqual(c.fetchone()[0],"review")
                c.execute("SELECT state FROM t008_publication_preview WHERE candidate_id=%s",(old,))
                self.assertEqual(c.fetchone()[0],"revoked")
                c.execute("""SELECT reason FROM t008_review_queue WHERE candidate_id=%s
                  AND status='open'""",(new,))
                self.assertEqual(c.fetchone()[0],"reapplication_after_revocation")
                c.execute("SELECT count(*) FROM t008_evidence WHERE candidate_id=%s",(new,))
                self.assertEqual(c.fetchone()[0],2)
                with self.assertRaises(errors.RaiseException):
                    with con.transaction():
                        c.execute("SELECT t008_review_mark(%s,'bulk override',true)",(new,))
                con.rollback()

    def test_item_review_requires_specific_evidence_and_reason(self):
        key,r,first=self.stage()
        key,r,second=self.stage(key,title="Changed Title")
        self.assertEqual(r["collision"],1)
        with psycopg.connect(DSN) as con:
            with con.cursor() as c:
                c.execute("""SELECT id FROM t008_review_queue WHERE candidate_id=%s AND status='open'""",
                          (second,))
                issue=c.fetchone()[0]
                with self.assertRaises(errors.RaiseException):
                    with con.transaction():
                        c.execute("SELECT t008_resolve_issue(%s,'too soon')",(issue,))
                con.rollback()
                with self.assertRaises(errors.RaiseException):
                    with con.transaction():
                        c.execute("SELECT t008_review_mark(%s,'bulk',true)",(second,))
                con.rollback()
                c.execute("SELECT id FROM t008_evidence WHERE candidate_id=%s ORDER BY id",(second,))
                proofs=[x[0] for x in c.fetchall()]
                for pid in proofs:
                    c.execute("SELECT t008_review_evidence(%s,%s)",(pid,"verified fixture against source"))
                c.execute("SELECT t008_resolve_issue(%s,'distinct recording, independently checked')",(issue,))
                c.execute("SELECT t008_finalize_review(%s,'resolved collision evidence')",(second,))
                c.execute("""SELECT count(*) FROM t008_review_decisions
                   WHERE candidate_id=%s AND reviewer_id='CI-REVIEWER-POSTGRES'""",(second,))
                self.assertEqual(c.fetchone()[0],3)
                c.execute("SELECT verification FROM t008_candidates WHERE id=%s",(second,))
                self.assertEqual(c.fetchone()[0],"verified")
            con.commit()

    def test_policy_insert_before_intake_rejects_stale_version(self):
        source="b014_"+uuid.uuid4().hex
        policy=replace(self.policy,source_code=source)
        with psycopg.connect(DSN) as con:
            with con.cursor() as c:
                c.execute("""INSERT INTO t008_source_policies
                   (source_code,acquisition_method,content_license,access_terms,allowed_fields,
                   automated_access_allowed,storage_allowed,publication_allowed,reviewed_at,
                   expires_at,policy_version) VALUES(%s,'local_dump','test-only',
                   'fixture approved',%s,true,true,true,%s,%s,1)""",
                   (source,["title","artist"],policy.reviewed_at,policy.expires_at))
            con.commit()
        started=Event()
        release=Event()
        def update_terms():
            with psycopg.connect(DSN) as con:
                with con.transaction():
                    with con.cursor() as c:
                        c.execute("""INSERT INTO t008_source_policies
                          (source_code,acquisition_method,content_license,access_terms,allowed_fields,
                          automated_access_allowed,storage_allowed,publication_allowed,reviewed_at,
                          expires_at,policy_version) VALUES(%s,'local_dump','test-only',
                          'fixture approved',%s,true,false,false,%s,%s,2)""",
                          (source,["title","artist"],policy.reviewed_at,policy.expires_at))
                        started.set()
                        if not release.wait(7): raise TimeoutError("policy race synchronization")
        def ingest():
            with psycopg.connect(DSN) as con:
                con.execute("SET lock_timeout='5s'")
                con.commit()
                with self.assertRaises((errors.RaiseException,PermissionError)):
                    stage_candidates(con,uuid.uuid4(),
                      [Candidate("Should be refused","Singer",uuid.uuid4().hex)],policy)
                con.rollback()
        with ThreadPoolExecutor(max_workers=2) as pool:
            a=pool.submit(update_terms)
            self.assertTrue(started.wait(7))
            b=pool.submit(ingest)
            time.sleep(.1)
            release.set()
            a.result(timeout=8);b.result(timeout=8)
        with psycopg.connect(DSN) as con:
            with con.cursor() as c:
                c.execute("""SELECT count(*) FROM t008_candidates WHERE external_source=%s""",(source,))
                self.assertEqual(c.fetchone()[0],0)

if __name__=="__main__":
    unittest.main()
