"""Disposable PostgreSQL test: 500 synthetic candidate rows and rollback."""
import os
import uuid
import unittest
from datetime import datetime, timedelta, timezone
import psycopg
from psycopg import errors
from server.t008_policy import SourcePolicy
from server.t008_stage_import import Candidate, stage_candidates

DSN = os.environ.get("KEN_T008_TEST_DATABASE_URL","")

@unittest.skipUnless(DSN and os.environ.get("KEN_T008_ALLOW_DISPOSABLE") == "YES",
                     "Requires explicitly enabled disposable ken_test database")
class T008DatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conn=psycopg.connect(DSN)
        with cls.conn.cursor() as cur:
            cur.execute("SELECT current_database()")
            if cur.fetchone()[0] not in ("ken_test","t008_test"):
                raise RuntimeError("Not a disposable database")
        cls.conn.commit()
        now=datetime.now(timezone.utc)
        cls.policy=SourcePolicy("synthetic_fixture","local_dump","CC0-test","test-only",
            frozenset({"title","artist"}),True,True,True,True,
            now-timedelta(hours=1),now+timedelta(hours=1))

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def _count(self, table, batch):
        with self.conn.cursor() as cur:
            column = "id" if table == "t008_batches" else "batch_id"
            cur.execute("SELECT COUNT(*) FROM "+table+" WHERE "+column+"=%s",(batch,))
            result=cur.fetchone()[0]
        self.conn.commit()
        return result

    def test_500_idempotency_and_query_isolation(self):
        batch=uuid.uuid4()
        # Includes repeat titles / artists, distinct recording IDs, covers, live
        # and remixes; staging keeps all 500 and does not use legacy songs.
        rows=[Candidate("Same Title" if i%10==0 else f"Fictional Song {i}",
                        "Same Artist" if i%10==0 else f"Fictional Artist {i%23}",
                        f"recording-{i}") for i in range(500)]
        result=stage_candidates(self.conn,batch,rows,self.policy)
        self.conn.commit()
        self.assertEqual(result,{"inserted":500,"duplicate":0,"rejected":0})
        self.assertEqual(self._count("t008_candidates",batch),500)
        second=stage_candidates(self.conn,batch,rows,self.policy)
        self.conn.commit()
        self.assertEqual(second,{"inserted":0,"duplicate":500,"rejected":0})
        self.assertEqual(self._count("t008_candidates",batch),500)
        with self.conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM t008_evidence e JOIN t008_candidates c ON e.candidate_id=c.id WHERE c.batch_id=%s",(batch,))
            self.assertEqual(cur.fetchone()[0],1000)
            cur.execute("SELECT COUNT(*) FROM songs WHERE title='Same Title'")
            self.assertEqual(cur.fetchone()[0],0)
        self.conn.commit()

    def test_injected_failure_rolls_back(self):
        batch=uuid.uuid4()
        rows=[Candidate(f"Rollback {i}","Test Artist",f"rollback-{i}") for i in range(15)]
        with self.assertRaisesRegex(RuntimeError,"injected"):
            stage_candidates(self.conn,batch,rows,self.policy,fail_after=6)
        self.conn.rollback()
        self.assertEqual(self._count("t008_candidates",batch),0)
        self.assertEqual(self._count("t008_batches",batch),0)

    def test_permission_and_fk_rejections(self):
        # Foreign key requires registered source policy.
        batch=uuid.uuid4()
        stage_candidates(self.conn,batch,[Candidate("Proof","Singer",str(uuid.uuid4()))],self.policy)
        self.conn.commit()
        with self.conn.cursor() as cur:
            cur.execute("SELECT id FROM t008_candidates WHERE batch_id=%s",(batch,))
            candidate_id=cur.fetchone()[0]
        self.conn.commit()
        with self.assertRaises(errors.ForeignKeyViolation):
            with self.conn.transaction():
                with self.conn.cursor() as cur:
                    cur.execute("""INSERT INTO t008_evidence(candidate_id,field_name,source_code,
                        acquisition_method,original_data_hash,source_policy_id)
                        VALUES(%s,'title','synthetic_fixture','local_dump','hash',-1)""",(candidate_id,))
        self.conn.rollback()
        with self.conn.cursor() as cur:
            cur.execute("SELECT id FROM t008_evidence WHERE candidate_id=%s LIMIT 1",(candidate_id,))
            first=cur.fetchone()[0]
        self.conn.commit()
        other=uuid.uuid4()
        stage_candidates(self.conn,other,[Candidate("Other","Singer",str(uuid.uuid4()))],self.policy)
        self.conn.commit()
        with self.conn.cursor() as cur:
            cur.execute("SELECT id FROM t008_candidates WHERE batch_id=%s",(other,))
            other_id=cur.fetchone()[0]
            cur.execute("SELECT id FROM t008_source_policies WHERE source_code='synthetic_fixture'")
            policy_id=cur.fetchone()[0]
        self.conn.commit()
        with self.assertRaises((errors.CheckViolation,errors.ForeignKeyViolation)):
            with self.conn.transaction():
                with self.conn.cursor() as cur:
                    cur.execute("""INSERT INTO t008_evidence(candidate_id,field_name,source_code,
                        acquisition_method,original_data_hash,source_policy_id,original_evidence_id,
                        original_candidate_id)
                        VALUES(%s,'title','synthetic_fixture','local_dump','hash',%s,%s,%s)""",
                        (other_id,policy_id,first,other_id))
        self.conn.rollback()

    def test_bad_rights_block_before_insert(self):
        from dataclasses import replace
        batch=uuid.uuid4()
        with self.assertRaises(PermissionError):
            stage_candidates(self.conn,batch,[Candidate("Denied","Artist","denied")],
                             replace(self.policy, access_terms="unknown"))
        self.assertEqual(self._count("t008_batches",batch),0)

if __name__ == "__main__":
    unittest.main()
