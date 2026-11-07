"""B-010 adversarial integration cases on disposable PostgreSQL only."""
import os
import uuid
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import psycopg
from psycopg import errors
from server.t008_policy import SourcePolicy
from server.t008_stage_import import Candidate, stage_candidates

DSN=os.getenv("KEN_T008_TEST_DATABASE_URL","")
LOGIN=os.getenv("KEN_T008_STAGE_LOGIN_DSN","")

@unittest.skipUnless(DSN and os.getenv("KEN_T008_ALLOW_DISPOSABLE")=="YES",
                     "disposable database required")
class T008ConcurrencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db=psycopg.connect(DSN)
        now=datetime.now(timezone.utc)
        cls.source="b010_"+uuid.uuid4().hex
        cls.policy=SourcePolicy(cls.source,"local_dump","test-only","test-only",
             frozenset({"title","artist"}),True,True,True,True,
             now-timedelta(minutes=1),now+timedelta(hours=1))
        with cls.db.cursor() as cur:
            cur.execute("SELECT current_database()")
            assert cur.fetchone()[0]=="ken_test"
            cur.execute("""INSERT INTO t008_source_policies
                 (source_code,acquisition_method,content_license,access_terms,allowed_fields,
                  automated_access_allowed,storage_allowed,publication_allowed,reviewed_at,expires_at,policy_version)
                 VALUES(%s,%s,%s,%s,%s,true,true,true,%s,%s,1)""",
                 (cls.source,"local_dump","test-only","test-only",["title","artist"],
                  cls.policy.reviewed_at,cls.policy.expires_at))
        cls.db.commit()

    @classmethod
    def tearDownClass(cls):
        cls.db.close()

    def stage(self,title,external,policy=None,batch=None):
        batch=batch or uuid.uuid4()
        with psycopg.connect(DSN) as conn:
            result=stage_candidates(conn,batch,[Candidate(title,"Singer",external)],policy or self.policy)
            conn.commit()
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM t008_candidates WHERE batch_id=%s",(batch,))
                c=cur.fetchone()
            conn.commit()
        return result,c[0] if c else None

    def test_two_connection_same_external_id_collision(self):
        key="parallel-"+uuid.uuid4().hex
        def worker(title):
            return self.stage(title,key)
        with ThreadPoolExecutor(max_workers=2) as pool:
            a=pool.submit(worker,"Parallel A")
            b=pool.submit(worker,"Parallel B")
            first,second=a.result(timeout=15),b.result(timeout=15)
        self.assertEqual(first[0]["inserted"]+second[0]["inserted"],2)
        self.assertEqual(first[0]["collision"]+second[0]["collision"],1)
        with self.db.cursor() as cur:
            cur.execute("SELECT count(*) FROM t008_candidates WHERE external_id=%s",(key,))
            self.assertEqual(cur.fetchone()[0],2)
            cur.execute("""SELECT count(*) FROM t008_review_queue r JOIN t008_candidates c
                           ON c.id=r.candidate_id WHERE c.external_id=%s AND r.status='open'""",(key,))
            self.assertEqual(cur.fetchone()[0],1)
            cur.execute("SELECT count(*) FROM t008_evidence WHERE candidate_id IN (%s,%s)",
                        (first[1],second[1]))
            self.assertEqual(cur.fetchone()[0],4)
        self.db.commit()

    def test_distinct_policy_version_retains_proof(self):
        source="versioned_"+uuid.uuid4().hex
        policy=replace(self.policy,source_code=source)
        with self.db.cursor() as cur:
            cur.execute("""INSERT INTO t008_source_policies
              (source_code,acquisition_method,content_license,access_terms,allowed_fields,
               automated_access_allowed,storage_allowed,publication_allowed,reviewed_at,expires_at,policy_version)
               VALUES(%s,'local_dump','test-only','test-only',%s,true,true,true,%s,%s,1)""",
               (source,["title","artist"],policy.reviewed_at,policy.expires_at))
        self.db.commit()
        key="policy-"+uuid.uuid4().hex
        _,cid=self.stage("Proof",key,policy)
        with self.db.cursor() as cur:
            cur.execute("""INSERT INTO t008_source_policies
              (source_code,acquisition_method,content_license,access_terms,allowed_fields,
               automated_access_allowed,storage_allowed,publication_allowed,reviewed_at,expires_at,policy_version)
               VALUES(%s,'local_dump','test-only','test-only',%s,true,true,true,%s,%s,2)
               RETURNING id""",(source,["title","artist"],policy.reviewed_at,policy.expires_at))
            newer=cur.fetchone()[0]
        self.db.commit()
        # Stale caller must reject even if license text has not changed.
        with self.assertRaises(PermissionError):
            self.stage("Proof",key,policy)
        # A new evidence event can be retained for an existing logical recording.
        result,latest=self.stage("Proof",key,replace(policy,policy_version=2))
        self.assertEqual(result["duplicate"],1)
        self.assertIsNone(latest)
        with self.db.cursor() as cur:
            cur.execute("SELECT COUNT(DISTINCT source_policy_id) FROM t008_evidence WHERE candidate_id=%s",(cid,))
            self.assertEqual(cur.fetchone()[0],2)
            cur.execute("SELECT COUNT(*) FROM t008_intake_events WHERE candidate_id=%s",(cid,))
            self.assertEqual(cur.fetchone()[0],2)
        self.db.commit()

    def _make_verified(self):
        source="pub_"+uuid.uuid4().hex
        now=datetime.now(timezone.utc)
        pol=SourcePolicy(source,"local_dump","test-only","fixture",
            frozenset({"title","artist"}),True,True,True,True,
            now-timedelta(minutes=1),now+timedelta(hours=1))
        with self.db.cursor() as cur:
            cur.execute("""INSERT INTO t008_source_policies
             (source_code,acquisition_method,content_license,access_terms,allowed_fields,
              automated_access_allowed,storage_allowed,publication_allowed,reviewed_at,expires_at,policy_version)
             VALUES(%s,'local_dump','test-only','fixture',%s,true,true,true,%s,%s,1)""",
             (source,["title","artist"],pol.reviewed_at,pol.expires_at))
        self.db.commit()
        _,cid=self.stage("Publish",uuid.uuid4().hex,pol)
        with self.db.cursor() as cur:
            cur.execute("UPDATE t008_candidates SET verification='verified' WHERE id=%s",(cid,))
            cur.execute("UPDATE t008_evidence SET verification='verified' WHERE candidate_id=%s",(cid,))
            cur.execute("SELECT t008_approve_candidate(%s,'test')",(cid,))
        self.db.commit()
        return pol,cid

    def test_after_approval_evidence_mutation_is_detected(self):
        pol,cid=self._make_verified()
        with self.db.cursor() as cur:
            cur.execute("UPDATE t008_evidence SET source_url='https://changed.example' WHERE candidate_id=%s",(cid,))
        self.db.commit()
        with self.assertRaises(errors.RaiseException):
            with self.db.transaction():
                with self.db.cursor() as cur:
                    cur.execute("SELECT t008_publish_preview(%s)",(cid,))
        self.db.rollback()

    def test_after_approval_candidate_change_is_detected(self):
        pol,cid=self._make_verified()
        with self.db.cursor() as cur:
            cur.execute("UPDATE t008_candidates SET artist='Other' WHERE id=%s",(cid,))
        self.db.commit()
        with self.assertRaises(errors.RaiseException):
            with self.db.transaction():
                with self.db.cursor() as cur:
                    cur.execute("SELECT t008_publish_preview(%s)",(cid,))
        self.db.rollback()

    def test_policy_version_change_blocks_old_approval(self):
        pol,cid=self._make_verified()
        with self.db.cursor() as cur:
            cur.execute("""INSERT INTO t008_source_policies
             (source_code,acquisition_method,content_license,access_terms,allowed_fields,
              automated_access_allowed,storage_allowed,publication_allowed,reviewed_at,expires_at,policy_version)
             VALUES(%s,'local_dump','test-only','fixture',%s,true,true,false,%s,%s,2)""",
             (pol.source_code,["title","artist"],pol.reviewed_at,pol.expires_at))
        self.db.commit()
        with self.assertRaises(errors.RaiseException):
            with self.db.transaction():
                with self.db.cursor() as cur:
                    cur.execute("SELECT t008_publish_preview(%s)",(cid,))
        self.db.rollback()

    def test_permanent_revoke(self):
        pol,cid=self._make_verified()
        with self.db.cursor() as cur:
            cur.execute("SELECT t008_publish_preview(%s)",(cid,))
            self.assertEqual(cur.fetchone()[0],"published")
            cur.execute("SELECT t008_revoke_preview(%s)",(cid,))
            self.assertEqual(cur.fetchone()[0],"revoked")
        self.db.commit()
        with self.assertRaises(errors.RaiseException):
            with self.db.transaction():
                with self.db.cursor() as cur:
                    cur.execute("SELECT t008_publish_preview(%s)",(cid,))
        self.db.rollback()
        with self.assertRaises(errors.RaiseException):
            with self.db.transaction():
                with self.db.cursor() as cur:
                    cur.execute("SELECT t008_approve_candidate(%s,'reapprove')",(cid,))
        self.db.rollback()

    @unittest.skipUnless(LOGIN,"nonowner CI login required")
    def test_real_login_cannot_bypass_permissions(self):
        with psycopg.connect(LOGIN) as c:
            with c.cursor() as cur:
                cur.execute("SELECT session_user,current_user")
                self.assertEqual(cur.fetchone()[0],"t008_stage_login")
                cur.execute("SELECT has_table_privilege(current_user,'songs','INSERT')")
                self.assertFalse(cur.fetchone()[0])
                cur.execute("SELECT has_table_privilege(current_user,'t008_candidates','INSERT')")
                self.assertFalse(cur.fetchone()[0])
                with self.assertRaises(errors.InsufficientPrivilege):
                    with c.transaction():
                        cur.execute("INSERT INTO songs(title,title_key,primary_artist_id) VALUES('fail','fail',1)")
                c.rollback()
                with self.assertRaises(errors.InsufficientPrivilege):
                    with c.transaction():
                        cur.execute("SET ROLE t008_reviewer")
                c.rollback()
                with self.assertRaises(errors.InsufficientPrivilege):
                    with c.transaction():
                        cur.execute("SELECT t008_approve_candidate(%s,'forged')",(uuid.uuid4(),))
                c.rollback()

if __name__=="__main__":
    unittest.main()
