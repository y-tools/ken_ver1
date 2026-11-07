"""T008 B-008 integration adversaries against disposable ken_test only."""
import os
import uuid
import unittest
from datetime import datetime, timedelta, timezone
import psycopg
from psycopg import errors
from server.t008_policy import SourcePolicy
from server.t008_stage_import import Candidate, stage_candidates

DSN=os.environ.get("KEN_T008_TEST_DATABASE_URL","")
@unittest.skipUnless(DSN and os.getenv("KEN_T008_ALLOW_DISPOSABLE")=="YES","disposable DB required")
class T008ReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conn=psycopg.connect(DSN)
        with cls.conn.cursor() as cur:
            cur.execute("SELECT current_database()")
            assert cur.fetchone()[0] in ("ken_test","t008_test")
            now=datetime.now(timezone.utc)
            cls.policy=SourcePolicy("b008_"+uuid.uuid4().hex,"local_dump","test-only","fixture-only",
                  frozenset({"title","artist"}),True,True,False,True,
                  now-timedelta(hours=1),now+timedelta(hours=1))
            cur.execute("""INSERT INTO t008_source_policies
             (source_code,acquisition_method,content_license,access_terms,allowed_fields,
              automated_access_allowed,storage_allowed,publication_allowed,reviewed_at,expires_at,policy_version)
              VALUES(%s,%s,%s,%s,%s,true,true,false,%s,%s,1)""",
             (cls.policy.source_code,cls.policy.method,cls.policy.content_license,
              cls.policy.access_terms,list(cls.policy.allowed_fields),
              cls.policy.reviewed_at,cls.policy.expires_at))
        cls.conn.commit()

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def stage(self, title, external, batch=None):
        batch=batch or uuid.uuid4()
        result=stage_candidates(self.conn,batch,[Candidate(title,"Singer",external)],self.policy)
        self.conn.commit()
        with self.conn.cursor() as cur:
            cur.execute("SELECT id FROM t008_candidates WHERE batch_id=%s",(batch,))
            row=cur.fetchone()
        self.conn.commit()
        return batch,result,row[0] if row else None

    def test_interbatch_external_collision_kept(self):
        key="collision-"+uuid.uuid4().hex
        _,r1,c1=self.stage("First",key)
        _,r2,c2=self.stage("Changed",key)
        self.assertEqual((r1["inserted"],r2["collision"]),(1,1))
        self.assertNotEqual(c1,c2)
        with self.conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM t008_review_queue WHERE candidate_id=%s AND status='open'",(c2,))
            self.assertEqual(cur.fetchone()[0],1)
            cur.execute("SELECT count(*) FROM t008_intake_events WHERE external_id=%s",(key,))
            self.assertEqual(cur.fetchone()[0],2)
        self.conn.commit()

    def test_interbatch_identical_claim_reuses_identity(self):
        key="repeat-"+uuid.uuid4().hex
        _,a,c1=self.stage("Same",key)
        _,b,c2=self.stage("Same",key)
        self.assertEqual(a["inserted"],1)
        self.assertEqual(b["duplicate"],1)
        self.assertIsNone(c2)

    def test_license_version_is_immutable(self):
        with self.assertRaises(errors.RaiseException):
            with self.conn.transaction():
                with self.conn.cursor() as cur:
                    cur.execute("UPDATE t008_source_policies SET content_license='altered' WHERE source_code=%s",(self.policy.source_code,))
        self.conn.rollback()

    def test_role_privileges(self):
        with psycopg.connect(DSN) as conn:
            with conn.cursor() as cur:
                for role in ("t008_stage_writer","t008_reviewer","t008_publisher"):
                    cur.execute("SET ROLE "+role)
                    for table,permission in (("songs","INSERT"),("artists","UPDATE"),("recordings","DELETE")):
                        cur.execute("SELECT has_table_privilege(current_user,%s,%s)",(table,permission))
                        self.assertFalse(cur.fetchone()[0],(role,table,permission))
                    if role=="t008_stage_writer":
                        cur.execute("SELECT has_table_privilege(current_user,'t008_candidates','UPDATE')")
                        self.assertFalse(cur.fetchone()[0])
                        with self.assertRaises(errors.InsufficientPrivilege):
                            with conn.transaction():
                                cur.execute("UPDATE t008_candidates SET verification='verified'")
                        conn.rollback()
                        # ROLLBACK also undoes SET ROLE issued within this transaction.
                        cur.execute("SET ROLE t008_stage_writer")
                        with self.assertRaises(errors.InsufficientPrivilege):
                            with conn.transaction():
                                cur.execute("""INSERT INTO t008_candidates
                                    (id,batch_id,title,artist,title_key,artist_key,verification)
                                    VALUES(%s,%s,'forge','forge','forge','forge','verified')""",
                                    (uuid.uuid4(),uuid.uuid4()))
                        conn.rollback()
                    cur.execute("RESET ROLE")
        self.conn.rollback()

    def test_private_staging_cannot_publish(self):
        _,_,candidate=self.stage("Private", "private-"+uuid.uuid4().hex)
        with self.conn.cursor() as cur:
            cur.execute("SELECT t008_review_mark(%s,'fixture evidence verification',true)",(candidate,))
        self.conn.commit()
        with self.assertRaises(errors.RaiseException):
            with self.conn.transaction():
                with self.conn.cursor() as cur:
                    cur.execute("SELECT t008_approve_candidate(%s,'test')",(candidate,))
        self.conn.rollback()

    def test_explicit_approval_replay_revoke_and_failure(self):
        # New immutable version grants only this test fixture publication, not any real data source.
        key="pub_"+uuid.uuid4().hex
        now=datetime.now(timezone.utc)
        allowed=SourcePolicy(key,"local_dump","test-only","fixture-only",
                 frozenset({"title","artist"}),True,True,True,True,
                 now-timedelta(minutes=1),now+timedelta(hours=1))
        with self.conn.cursor() as cur:
            cur.execute("""INSERT INTO t008_source_policies
              (source_code,acquisition_method,content_license,access_terms,allowed_fields,
               automated_access_allowed,storage_allowed,publication_allowed,reviewed_at,expires_at,policy_version)
               VALUES(%s,%s,%s,%s,%s,true,true,true,%s,%s,1)""",
               (key,"local_dump","test-only","fixture-only",list(allowed.allowed_fields),
                allowed.reviewed_at,allowed.expires_at))
        self.conn.commit()
        batch=uuid.uuid4()
        stage_candidates(self.conn,batch,[Candidate("Publish","Singer",uuid.uuid4().hex)],allowed)
        self.conn.commit()
        with self.conn.cursor() as cur:
            cur.execute("SELECT id FROM t008_candidates WHERE batch_id=%s",(batch,))
            cid=cur.fetchone()[0]
            cur.execute("SELECT t008_review_mark(%s,'fixture evidence verification',true)",(cid,))
        self.conn.commit()
        with psycopg.connect(DSN) as rev:
            with rev.cursor() as cur:
                cur.execute("SET ROLE t008_reviewer")
                cur.execute("SELECT t008_approve_candidate(%s,'reviewed')",(cid,))
            rev.commit()
        with psycopg.connect(DSN) as pub:
            with pub.cursor() as cur:
                cur.execute("SET ROLE t008_publisher")
                with self.assertRaises(errors.RaiseException):
                    with pub.transaction():
                        cur.execute("SELECT t008_publish_preview(%s,true)",(cid,))
                pub.rollback()
                cur.execute("SELECT t008_publish_preview(%s,false)",(cid,))
                self.assertEqual(cur.fetchone()[0],"published")
                cur.execute("SELECT t008_publish_preview(%s,false)",(cid,))
                self.assertEqual(cur.fetchone()[0],"already_published")
                cur.execute("SELECT t008_revoke_preview(%s)",(cid,))
                self.assertEqual(cur.fetchone()[0],"revoked")
            pub.commit()
        with self.conn.cursor() as cur:
            cur.execute("SELECT state FROM t008_publication_preview WHERE candidate_id=%s",(cid,))
            self.assertEqual(cur.fetchone()[0],"revoked")
            cur.execute("SELECT COUNT(*) FROM t008_audit WHERE details->>'candidate_id'=%s",(str(cid),))
            self.assertEqual(cur.fetchone()[0],3)
        self.conn.commit()

if __name__=="__main__":
    unittest.main()
