"""Repeated B-014 contention tests on disposable PostgreSQL with a strict pool limit."""
from concurrent.futures import ThreadPoolExecutor
from threading import BoundedSemaphore
from datetime import datetime,timedelta,timezone
import os,statistics,time,unittest,uuid
import psycopg
from server.t008_policy import SourcePolicy
from server.t008_stage_import import Candidate,stage_candidates

DSN=os.environ.get("KEN_T008_TEST_DATABASE_URL","")
@unittest.skipUnless(DSN and os.environ.get("KEN_T008_ALLOW_DISPOSABLE")=="YES","test DB only")
class T008RepeatedLoadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source="b014_"+uuid.uuid4().hex
        now=datetime.now(timezone.utc)
        cls.policy=SourcePolicy(cls.source,"local_dump","test-only","fixture approved",
             frozenset({"title","artist"}),True,True,True,True,
             now-timedelta(minutes=1),now+timedelta(hours=1))
        with psycopg.connect(DSN) as conn:
            with conn.cursor() as cur:
                cur.execute("""INSERT INTO t008_source_policies
                  (source_code,acquisition_method,content_license,access_terms,allowed_fields,
                   automated_access_allowed,storage_allowed,publication_allowed,reviewed_at,
                   expires_at,policy_version) VALUES (%s,'local_dump','test-only',
                   'fixture approved',%s,true,true,true,%s,%s,1)""",
                   (cls.source,["title","artist"],cls.policy.reviewed_at,cls.policy.expires_at))
            conn.commit()

    def test_repeated_20_and_50_requests_with_pool_cap_10(self):
        # Concurrent logical requests are deliberately capped to 10 *DB sessions*.
        # This is a CI policy fixture, NOT a measured real-VPS connection budget.
        cap=BoundedSemaphore(10)
        for clients in (20,50):
            for repeat in range(3):
                source_id=f"stress-{clients}-{repeat}-{uuid.uuid4().hex}"
                def insert(i):
                    started=time.perf_counter()
                    with cap:
                        with psycopg.connect(DSN) as conn:
                            with conn.cursor() as cur:
                                cur.execute("SET lock_timeout='5s'")
                            conn.commit()
                            outcome=stage_candidates(conn,uuid.uuid4(),
                                [Candidate(f"Same ID variant {i}","Singer",source_id)],self.policy)
                            conn.commit()
                    return outcome,(time.perf_counter()-started)*1000
                with ThreadPoolExecutor(max_workers=clients) as executor:
                    outcomes=list(executor.map(insert,range(clients)))
                with psycopg.connect(DSN) as conn:
                    with conn.cursor() as cur:
                        cur.execute("""SELECT count(*) FROM t008_candidates
                            WHERE external_source=%s AND external_id=%s""",
                            (self.source,source_id))
                        self.assertEqual(cur.fetchone()[0],clients)
                        cur.execute("""SELECT count(*) FROM t008_evidence e
                          JOIN t008_candidates c ON e.candidate_id=c.id
                          WHERE c.external_source=%s AND c.external_id=%s""",
                          (self.source,source_id))
                        self.assertEqual(cur.fetchone()[0],2*clients)
                self.assertEqual(sum(x["collision"] for x,_ in outcomes),clients-1)
                samples=sorted(t for _,t in outcomes)
                p95=samples[min(clients-1,int(.95*(clients-1)))]
                print("B014_LOAD clients=%s run=%s pool_cap=10 complete=%s failure=0 p50_ms=%.2f p95_ms=%.2f max_ms=%.2f"%
                      (clients,repeat+1,clients,statistics.median(samples),p95,max(samples)))
if __name__=="__main__":
    unittest.main()
