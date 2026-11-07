"""B-022 isolated PostgreSQL and HTTP regressions: no real VPS connection."""
import os,time,uuid,unittest
from datetime import datetime,timedelta,timezone
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import psycopg
from psycopg import errors
from fastapi.testclient import TestClient
from server.t008_preview_api import create_preview_app
from server.t008_policy import SourcePolicy
from server.t008_stage_import import Candidate,stage_candidates

DSN=os.getenv("KEN_T008_TEST_DATABASE_URL","")
SEARCH_DSN=os.getenv("KEN_T008_SEARCH_LOGIN_DSN","")
REVIEW_DSN=os.getenv("KEN_T008_REVIEW_LOGIN_DSN","")
@unittest.skipUnless(DSN and os.getenv("KEN_T008_ALLOW_DISPOSABLE")=="YES","disposable PostgreSQL required")
class B022Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with psycopg.connect(DSN) as con:
            assert con.execute("SELECT current_database()").fetchone()[0]=="ken_test"
    def fixture(self,expires_in=120):
        source="b014_b022_"+uuid.uuid4().hex
        now=datetime.now(timezone.utc)
        policy=SourcePolicy(source,"local_dump","test-only","fixture approved",
            frozenset({"title","artist"}),True,True,True,True,
            now-timedelta(minutes=1),now+timedelta(seconds=expires_in))
        with psycopg.connect(DSN) as con:
            with con.cursor() as cur:
                cur.execute("""INSERT INTO t008_source_policies(source_code,acquisition_method,
                  content_license,access_terms,allowed_fields,automated_access_allowed,
                  storage_allowed,publication_allowed,reviewed_at,expires_at,policy_version)
                  VALUES(%s,'local_dump','test-only','fixture approved',
                  %s,true,true,true,%s,%s,1) RETURNING id""",
                  (source,["title","artist"],policy.reviewed_at,policy.expires_at))
                polid=cur.fetchone()[0]
            con.commit()
        return policy,polid
    def published(self,policy):
        key=uuid.uuid4().hex
        batch=uuid.uuid4()
        with psycopg.connect(DSN) as con:
            result=stage_candidates(con,batch,[Candidate("B022 Hidden License Song","Singer",key)],policy)
            self.assertEqual(result["inserted"],1)
            con.commit()
            with con.cursor() as cur:
                cid=cur.execute("SELECT id FROM t008_candidates WHERE batch_id=%s",(batch,)).fetchone()[0]
                cur.execute("SELECT t008_review_mark(%s,'fixture fields verified',true)",(cid,))
                cur.execute("SELECT t008_approve_candidate(%s,'fictional approval')",(cid,))
                cur.execute("SELECT t008_publish_preview(%s)",(cid,))
                self.assertEqual(cur.fetchone()[0],"published")
            con.commit()
        return cid,key

    def test_wall_clock_expiration_inside_long_open_transaction(self):
        policy,polid=self.fixture(expires_in=4)
        cid,_=self.published(policy)
        with psycopg.connect(DSN) as con:
            con.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
            self.assertTrue(con.execute("SELECT t008_policy_storage_ok(%s,%s,'local_dump')",
                 (polid,policy.source_code)).fetchone()[0])
            self.assertEqual(con.execute("SELECT count(*) FROM t008_visible_publications WHERE candidate_id=%s",(cid,)).fetchone()[0],1)
            # Holding the same DB transaction is essential: now() would remain
            # fixed at its start even after this boundary passes.
            remaining=(policy.expires_at-datetime.now(timezone.utc)).total_seconds()
            time.sleep(max(.1,remaining+.15))
            self.assertFalse(con.execute("SELECT t008_policy_storage_ok(%s,%s,'local_dump')",
                 (polid,policy.source_code)).fetchone()[0])
            self.assertEqual(con.execute("SELECT count(*) FROM t008_visible_publications WHERE candidate_id=%s",(cid,)).fetchone()[0],0)

    @unittest.skipUnless(SEARCH_DSN,"isolated search DB login absent")
    def test_http_search_uses_only_protected_view_and_denies_raw_tables(self):
        policy,_=self.fixture()
        cid,_=self.published(policy)
        with psycopg.connect(SEARCH_DSN) as con:
            self.assertEqual(con.execute("SELECT session_user").fetchone()[0],"t008_search_login")
            with self.assertRaises(errors.InsufficientPrivilege):
                with con.transaction():
                    con.execute("SELECT count(*) FROM t008_active_publications")
            con.rollback()
            with self.assertRaises(errors.InsufficientPrivilege):
                with con.transaction():
                    con.execute("SELECT count(*) FROM t008_publication_preview")
            con.rollback()
        with TestClient(create_preview_app(SEARCH_DSN)) as client:
            response=client.get("/t008/isolated-preview/search",params={"q":"B022 Hidden License Song"})
            self.assertEqual(response.status_code,200,response.text)
            self.assertIn(str(cid),[x["candidate_id"] for x in response.json()["items"]])
            with psycopg.connect(DSN) as con:
                con.execute("""INSERT INTO t008_source_policies(source_code,acquisition_method,
                   content_license,access_terms,allowed_fields,automated_access_allowed,
                   storage_allowed,publication_allowed,reviewed_at,expires_at,policy_version)
                   VALUES(%s,'local_dump','test-only','fixture approved',
                    %s,true,true,false,%s,%s,2)""",
                    (policy.source_code,["title","artist"],policy.reviewed_at,policy.expires_at))
                con.commit()
            response=client.get("/t008/isolated-preview/search",params={"q":"B022 Hidden License Song"})
            self.assertEqual(response.status_code,200,response.text)
            self.assertNotIn(str(cid),[x["candidate_id"] for x in response.json()["items"]])

    def test_repeatable_read_can_retain_stale_policy_snapshot(self):
        # Negative control: clock_timestamp() alone does NOT refresh RR snapshots.
        policy,_=self.fixture(expires_in=100)
        cid,_=self.published(policy)
        with psycopg.connect(DSN) as stale:
            stale.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            self.assertEqual(stale.execute(
                "SELECT count(*) FROM t008_visible_publications WHERE candidate_id=%s",
                (cid,)).fetchone()[0],1)
            with psycopg.connect(DSN) as writer:
                writer.execute("""INSERT INTO t008_source_policies(source_code,acquisition_method,
                    content_license,access_terms,allowed_fields,automated_access_allowed,
                    storage_allowed,publication_allowed,reviewed_at,expires_at,policy_version)
                    VALUES(%s,'local_dump','test-only','fixture approved',
                    %s,true,true,false,%s,%s,2)""",
                    (policy.source_code,["title","artist"],policy.reviewed_at,policy.expires_at))
                writer.commit()
            self.assertEqual(stale.execute("SELECT current_setting('transaction_isolation')").fetchone()[0],
                             "repeatable read")
            self.assertEqual(stale.execute(
                "SELECT count(*) FROM t008_visible_publications WHERE candidate_id=%s",
                (cid,)).fetchone()[0],1)
            # A new READ COMMITTED statement does see the newly committed denial.
            with psycopg.connect(DSN) as fresh:
                self.assertEqual(fresh.execute(
                    "SELECT count(*) FROM t008_visible_publications WHERE candidate_id=%s",
                    (cid,)).fetchone()[0],0)

    @unittest.skipUnless(SEARCH_DSN,"isolated search DB login absent")
    def test_http_cache_headers_and_conditional_rerequest(self):
        policy,_=self.fixture()
        cid,_=self.published(policy)
        path="/t008/isolated-preview/search"
        with TestClient(create_preview_app(SEARCH_DSN)) as client:
            first=client.get(path,params={"q":"B022 Hidden License Song"})
            self.assertEqual(first.status_code,200,first.text)
            for response in (first,client.get(path,params={"q":"B022 Hidden License Song"},
                       headers={"If-None-Match":'"cached-before-revocation"',
                                "If-Modified-Since":"Wed, 21 Oct 2015 07:28:00 GMT"})):
                self.assertEqual(response.status_code,200,response.text)
                self.assertIn("no-store",response.headers["cache-control"])
                self.assertEqual(response.headers["surrogate-control"],"no-store")
                self.assertEqual(response.headers["pragma"],"no-cache")
                self.assertEqual(response.headers["expires"],"0")
                self.assertNotIn("etag",response.headers)
            with psycopg.connect(DSN) as con:
                con.execute("""INSERT INTO t008_source_policies(source_code,acquisition_method,
                    content_license,access_terms,allowed_fields,automated_access_allowed,
                    storage_allowed,publication_allowed,reviewed_at,expires_at,policy_version)
                    VALUES(%s,'local_dump','test-only','fixture approved',
                    %s,true,true,false,%s,%s,2)""",
                    (policy.source_code,["title","artist"],policy.reviewed_at,policy.expires_at))
                con.commit()
            second=client.get(path,params={"q":"B022 Hidden License Song"},
                headers={"If-None-Match":'"cached-before-revocation"',
                         "If-Modified-Since":"Wed, 21 Oct 2015 07:28:00 GMT"})
            self.assertEqual(second.status_code,200,second.text)
            self.assertNotIn(str(cid),[x["candidate_id"] for x in second.json()["items"]])
            self.assertIn("no-store",second.headers["cache-control"])
            bad=client.get(path,params={"q":""})
            self.assertEqual(bad.status_code,422)
            self.assertIn("no-store",bad.headers["cache-control"])
        with TestClient(create_preview_app(DSN)) as invalid_client:
            denied=invalid_client.get(path,params={"q":"B022"})
            self.assertEqual(denied.status_code,503)
            self.assertIn("no-store",denied.headers["cache-control"])

    def test_reactivation_policy_races_with_reconciliation(self):
        policy,_=self.fixture()
        cid,key=self.published(policy)
        entered=Event();release=Event()
        def change_policy():
            with psycopg.connect(DSN) as con:
                with con.transaction():
                    con.execute("""INSERT INTO t008_source_policies(source_code,acquisition_method,
                       content_license,access_terms,allowed_fields,
                       automated_access_allowed,storage_allowed,publication_allowed,
                       reviewed_at,expires_at,policy_version)
                       VALUES(%s,'local_dump','test-only','fixture approved',%s,
                       true,true,false,%s,%s,2)""",
                       (policy.source_code,["title","artist"],policy.reviewed_at,policy.expires_at))
                    entered.set()
                    self.assertTrue(release.wait(8))
        def reconcile():
            with psycopg.connect(DSN) as con:
                con.execute("SET lock_timeout='6s'")
                con.commit()
                outcome=con.execute("SELECT t008_reconcile_visibility(%s)",(cid,)).fetchone()[0]
                con.commit()
                return outcome
        with ThreadPoolExecutor(max_workers=2) as pool:
            first=pool.submit(change_policy)
            self.assertTrue(entered.wait(8))
            second=pool.submit(reconcile)
            time.sleep(.15)
            release.set()
            first.result(timeout=10)
            self.assertEqual(second.result(timeout=10),"revoked")
        with psycopg.connect(DSN) as con:
            self.assertEqual(con.execute("SELECT count(*) FROM t008_active_publications WHERE candidate_id=%s",(cid,)).fetchone()[0],0)
            self.assertEqual(con.execute("SELECT count(*) FROM t008_publication_history WHERE candidate_id=%s AND action='revoke'",(cid,)).fetchone()[0],1)

    def test_reauthorization_races_with_reconcile_but_old_proof_not_reused(self):
        policy,_=self.fixture()
        cid,key=self.published(policy)
        entered=Event();release=Event()
        def deny_then_reauthorize():
            with psycopg.connect(DSN) as con:
                with con.transaction():
                    for revision,allowed in ((2,False),(3,True)):
                        con.execute("""INSERT INTO t008_source_policies(source_code,acquisition_method,
                            content_license,access_terms,allowed_fields,
                            automated_access_allowed,storage_allowed,publication_allowed,
                            reviewed_at,expires_at,policy_version)
                            VALUES(%s,'local_dump','test-only','fixture approved',%s,
                            true,true,%s,%s,%s,%s)""",
                            (policy.source_code,["title","artist"],allowed,
                             policy.reviewed_at,policy.expires_at,revision))
                    entered.set()
                    self.assertTrue(release.wait(8))
        def reconcile():
            with psycopg.connect(DSN) as con:
                con.execute("SET lock_timeout='6s'")
                con.commit()
                result=con.execute("SELECT t008_reconcile_visibility(%s)",(cid,)).fetchone()[0]
                con.commit()
                return result
        with ThreadPoolExecutor(max_workers=2) as pool:
            first=pool.submit(deny_then_reauthorize)
            self.assertTrue(entered.wait(8))
            second=pool.submit(reconcile)
            time.sleep(.12)
            release.set()
            first.result(timeout=10)
            # A newer allowed policy does NOT legitimize earlier-version proofs:
            # the prior candidate must still be retired until new evidence
            # is separately verified via an independent new candidate.
            self.assertEqual(second.result(timeout=10),"revoked")
        with psycopg.connect(DSN) as con:
            self.assertEqual(con.execute("SELECT count(*) FROM t008_visible_publications WHERE candidate_id=%s",(cid,)).fetchone()[0],0)
            self.assertEqual(con.execute("SELECT count(*) FROM t008_publication_history WHERE candidate_id=%s AND action='revoke'",(cid,)).fetchone()[0],1)
            self.assertEqual(con.execute("SELECT max(policy_version) FROM t008_source_policies WHERE source_code=%s",(policy.source_code,)).fetchone()[0],3)

    @unittest.skipUnless(REVIEW_DSN,"review login absent")
    def test_nonowner_cannot_forge_identity_using_other_candidate_evidence(self):
        policy,_=self.fixture()
        original,_=self.published(policy)
        batch=uuid.uuid4()
        with psycopg.connect(DSN) as con:
            stage_candidates(con,batch,[Candidate("Unrelated song","Singer",uuid.uuid4().hex)],policy)
            con.commit()
            second=con.execute("SELECT id FROM t008_candidates WHERE batch_id=%s",(batch,)).fetchone()[0]
            proof=con.execute("SELECT id FROM t008_evidence WHERE candidate_id=%s ORDER BY id",(original,)).fetchall()
        with psycopg.connect(REVIEW_DSN) as con:
            with self.assertRaises((errors.RaiseException,errors.ForeignKeyViolation)):
                with con.transaction():
                    con.execute("SELECT t008_identity_decide(%s,%s,%s,%s,'same_recording',%s)",
                        (second,original,proof[0][0],proof[1][0],
                        "Fabricated cross candidate evidence"))
            con.rollback()
if __name__=="__main__":
    unittest.main()
