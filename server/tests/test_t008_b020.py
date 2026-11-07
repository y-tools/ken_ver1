"""B-020: independent license, identity evidence, DDL and non-owner publisher regressions.
All tests use synthetic PostgreSQL 16; never production.
"""
import os,uuid,unittest
from datetime import datetime,timedelta,timezone
from server.t008_stage_import import Candidate,stage_candidates
from server.t008_policy import SourcePolicy
import psycopg
from psycopg import errors

DSN=os.getenv("KEN_T008_TEST_DATABASE_URL","")
PUBLISH_DSN=os.getenv("KEN_T008_PUBLISH_LOGIN_DSN","")
@unittest.skipUnless(DSN and os.getenv("KEN_T008_ALLOW_DISPOSABLE")=="YES","test database only")
class B020SafetyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source="b014_b020_"+uuid.uuid4().hex
        now=datetime.now(timezone.utc)
        cls.policy=SourcePolicy(cls.source,"local_dump","test-only","fixture approved",
            frozenset({"title","artist"}),True,True,True,True,
            now-timedelta(minutes=1),now+timedelta(hours=1))
        with psycopg.connect(DSN) as conn:
            with conn.cursor() as cur:
                cur.execute("""INSERT INTO t008_source_policies(source_code,acquisition_method,
                  content_license,access_terms,allowed_fields,automated_access_allowed,
                  storage_allowed,publication_allowed,reviewed_at,expires_at,policy_version)
                  VALUES(%s,'local_dump','test-only','fixture approved',%s,true,true,true,%s,%s,1)""",
                  (cls.source,["title","artist"],cls.policy.reviewed_at,cls.policy.expires_at))
            conn.commit()
    def stage(self,key,title="Song",policy=None):
        batch=uuid.uuid4()
        with psycopg.connect(DSN) as conn:
            result=stage_candidates(conn,batch,[Candidate(title,"Artist",key)],policy or self.policy)
            conn.commit()
            row=conn.execute("SELECT id FROM t008_candidates WHERE batch_id=%s",(batch,)).fetchone()
        return result,row[0] if row else None
    def publish_first(self,key):
        _,cid=self.stage(key)
        with psycopg.connect(DSN) as conn:
            conn.execute("SELECT t008_review_mark(%s,'fixture checked',true)",(cid,))
            conn.execute("SELECT t008_approve_candidate(%s,'approved')",(cid,))
            conn.execute("SELECT t008_publish_preview(%s)",(cid,))
            conn.commit()
        return cid
    def prepare_conflict(self,key,old):
        _,new=self.stage(key,"Updated song")
        with psycopg.connect(DSN) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM t008_evidence WHERE candidate_id=%s ORDER BY id",(new,))
                proofs=[x[0] for x in cur.fetchall()]
                for e in proofs:
                    cur.execute("SELECT t008_review_evidence(%s,'reviewed independently')",(e,))
                cur.execute("SELECT id FROM t008_review_queue WHERE candidate_id=%s",(new,))
                issue=cur.fetchone()[0]
                cur.execute("SELECT t008_resolve_issue(%s,'independent entity mapping')",(issue,))
                cur.execute("SELECT t008_finalize_review(%s,'completed evidence review')",(new,))
                cur.execute("SELECT t008_identity_decide(%s,%s,%s,%s,'same_recording',%s)",
                    (new,old,proofs[0],proofs[1],"Synthetic independent recording evidence comparison"))
                cur.execute("SELECT t008_approve_candidate(%s,'approval')",(new,))
            conn.commit()
        return new,proofs
    def test_existing_active_disappears_from_visibility_after_new_denied_policy(self):
        # This mutation must never invalidate another test's shared source.
        source="b014_b020_"+uuid.uuid4().hex
        now=datetime.now(timezone.utc)
        separate=SourcePolicy(source,"local_dump","test-only","fixture approved",
            frozenset({"title","artist"}),True,True,True,True,
            now-timedelta(minutes=1),now+timedelta(hours=1))
        key=uuid.uuid4().hex
        with psycopg.connect(DSN) as conn:
            conn.execute("""INSERT INTO t008_source_policies(source_code,acquisition_method,
               content_license,access_terms,allowed_fields,automated_access_allowed,
               storage_allowed,publication_allowed,reviewed_at,expires_at,policy_version)
               VALUES(%s,'local_dump','test-only','fixture approved',%s,true,true,true,%s,%s,1)""",
               (source,["title","artist"],separate.reviewed_at,separate.expires_at))
            conn.commit()
        batch=uuid.uuid4()
        with psycopg.connect(DSN) as conn:
            stage_candidates(conn,batch,[Candidate("Source Revoke","Artist",key)],separate)
            conn.commit()
            a=conn.execute("SELECT id FROM t008_candidates WHERE batch_id=%s",(batch,)).fetchone()[0]
            conn.execute("SELECT t008_review_mark(%s,'fixture checked',true)",(a,))
            conn.execute("SELECT t008_approve_candidate(%s,'approved')",(a,))
            conn.execute("SELECT t008_publish_preview(%s)",(a,))
            conn.commit()
            self.assertEqual(conn.execute("SELECT count(*) FROM t008_visible_publications WHERE candidate_id=%s",(a,)).fetchone()[0],1)
            conn.execute("""INSERT INTO t008_source_policies(source_code,acquisition_method,
               content_license,access_terms,allowed_fields,automated_access_allowed,storage_allowed,
               publication_allowed,reviewed_at,expires_at,policy_version)
               VALUES (%s,'local_dump','test-only','fixture approved',%s,true,true,false,%s,%s,2)""",
               (source,["title","artist"],separate.reviewed_at,separate.expires_at))
            conn.commit()
            self.assertEqual(conn.execute("SELECT count(*) FROM t008_visible_publications WHERE candidate_id=%s",(a,)).fetchone()[0],0)
            self.assertEqual(conn.execute("SELECT count(*) FROM t008_active_publications WHERE candidate_id=%s",(a,)).fetchone()[0],1)
            self.assertEqual(conn.execute("SELECT t008_reconcile_visibility(%s)",(a,)).fetchone()[0],"revoked")
            conn.commit()
            self.assertEqual(conn.execute("SELECT count(*) FROM t008_active_publications WHERE candidate_id=%s",(a,)).fetchone()[0],0)
            self.assertEqual(conn.execute("SELECT state FROM t008_publication_preview WHERE candidate_id=%s",(a,)).fetchone()[0],"revoked")
            self.assertEqual(conn.execute("SELECT count(*) FROM t008_publication_history WHERE candidate_id=%s AND action='revoke'",(a,)).fetchone()[0],1)

    def test_identity_proof_mutation_after_decision_blocks_publication(self):
        key=uuid.uuid4().hex
        old=self.publish_first(key)
        new,proofs=self.prepare_conflict(key,old)
        with psycopg.connect(DSN) as conn:
            conn.execute("UPDATE t008_evidence SET source_url='https://fixture.invalid/changed' WHERE id=%s",(proofs[0],))
            conn.commit()
            with self.assertRaises(errors.RaiseException):
                with conn.transaction():
                    conn.execute("SELECT t008_publish_preview(%s)",(new,))
            conn.rollback()
            self.assertEqual(conn.execute("SELECT candidate_id FROM t008_active_publications WHERE external_id=%s AND source_code=%s",(key,self.source)).fetchone()[0],old)

    def test_direct_publication_null_key_and_mismatched_active_rejected(self):
        key=uuid.uuid4().hex
        a=self.publish_first(key)
        _,b=self.stage(uuid.uuid4().hex,"Another key")
        with psycopg.connect(DSN) as conn:
            with self.assertRaises(errors.NotNullViolation):
                with conn.transaction():
                    conn.execute("""INSERT INTO t008_publication_preview(candidate_id,title,artist,
                      approved_by,approved_at,proof_digest,state,source_code,entity_type,external_id)
                      VALUES (%s,'foo','bar','fixture',now(),'bogus','published',NULL,'recording',%s)""",
                      (b,key))
            conn.rollback()
            with self.assertRaises(errors.ForeignKeyViolation):
                with conn.transaction():
                    conn.execute("""INSERT INTO t008_active_publications(source_code,entity_type,external_id,candidate_id)
                      VALUES (%s,'recording',%s,%s)""",(self.source,uuid.uuid4().hex,b))
            conn.rollback()
            self.assertEqual(conn.execute("SELECT candidate_id FROM t008_active_publications WHERE external_id=%s AND source_code=%s",(key,self.source)).fetchone()[0],a)

    def test_cross_candidate_identity_evidence_rejected_by_compound_fk(self):
        key=uuid.uuid4().hex
        first=self.publish_first(key)
        _,second=self.stage(key,"Another version")
        with psycopg.connect(DSN) as conn:
            own=conn.execute("SELECT id FROM t008_evidence WHERE candidate_id=%s ORDER BY id",(second,)).fetchall()
            foreign=conn.execute("SELECT id FROM t008_evidence WHERE candidate_id=%s ORDER BY id",(first,)).fetchall()
            with self.assertRaises(errors.ForeignKeyViolation):
                with conn.transaction():
                    conn.execute("""INSERT INTO t008_identity_decisions
                    (candidate_id,compared_candidate_id,title_evidence_id,artist_evidence_id,
                      decision,reviewer_id,rationale,title_digest,artist_digest)
                      VALUES(%s,%s,%s,%s,'same_recording','fixture','independently recorded', 'x','y')""",
                      (second,first,foreign[0][0],own[1][0]))
            conn.rollback()

    @unittest.skipUnless(PUBLISH_DSN,"nonowner publisher login missing")
    def test_nonowner_publisher_may_publish_but_cannot_edit_records(self):
        key=uuid.uuid4().hex
        _,cid=self.stage(key)
        with psycopg.connect(DSN) as conn:
            conn.execute("SELECT t008_review_mark(%s,'verified by reviewer',true)",(cid,))
            conn.execute("SELECT t008_approve_candidate(%s,'approved by reviewer')",(cid,))
            conn.commit()
        with psycopg.connect(PUBLISH_DSN) as conn:
            self.assertEqual(conn.execute("SELECT session_user").fetchone()[0],"t008_publish_login")
            self.assertEqual(conn.execute("SELECT t008_publish_preview(%s)",(cid,)).fetchone()[0],"published")
            conn.commit()
            with self.assertRaises(errors.InsufficientPrivilege):
                with conn.transaction():
                    conn.execute("UPDATE t008_active_publications SET candidate_id=%s WHERE candidate_id=%s",(uuid.uuid4(),cid))
            conn.rollback()
            with self.assertRaises(errors.InsufficientPrivilege):
                with conn.transaction():
                    conn.execute("SELECT t008_identity_decide(%s,%s,1,2,'same_recording','forged publication')",(cid,cid))
            conn.rollback()
if __name__=="__main__":unittest.main()
