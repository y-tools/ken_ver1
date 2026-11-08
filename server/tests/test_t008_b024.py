"""B-024 isolated legacy API shadow and single-entry revocation audit regressions."""
import os,uuid,unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from datetime import datetime,timedelta,timezone
import psycopg
from fastapi.testclient import TestClient
from server.t008_policy import SourcePolicy
from server.t008_stage_import import Candidate,stage_candidates

DSN=os.getenv("KEN_T008_TEST_DATABASE_URL","")
@unittest.skipUnless(DSN and os.getenv("KEN_T008_ALLOW_DISPOSABLE")=="YES","disposable database only")
class B024Tests(unittest.TestCase):
    def fixture(self):
        source="b014_b024_"+uuid.uuid4().hex
        now=datetime.now(timezone.utc)
        pol=SourcePolicy(source,"local_dump","test-only","fixture approved",
          frozenset({"title","artist"}),True,True,True,True,
          now-timedelta(minutes=1),now+timedelta(hours=1))
        with psycopg.connect(DSN) as conn:
            assert conn.execute("SELECT current_database()").fetchone()[0]=="ken_test"
            conn.execute("""INSERT INTO t008_source_policies
                (source_code,acquisition_method,content_license,access_terms,
                 allowed_fields,automated_access_allowed,storage_allowed,
                 publication_allowed,reviewed_at,expires_at,policy_version)
                VALUES(%s,'local_dump','test-only','fixture approved',
                %s,true,true,true,%s,%s,1)""",
                (source,["title","artist"],pol.reviewed_at,pol.expires_at))
            conn.commit()
        return pol
    def stage_published(self,pol):
        key=uuid.uuid4().hex
        batch=uuid.uuid4()
        with psycopg.connect(DSN) as conn:
            stage_candidates(conn,batch,[Candidate("B024 Revocation","Singer",key)],pol)
            conn.commit()
            cid=conn.execute("SELECT id FROM t008_candidates WHERE batch_id=%s",(batch,)).fetchone()[0]
            conn.execute("SELECT t008_review_mark(%s,'fixture review complete',true)",(cid,))
            conn.execute("SELECT t008_approve_candidate(%s,'fictional approval')",(cid,))
            conn.execute("SELECT t008_publish_preview(%s)",(cid,))
            conn.commit()
        return cid

    def test_concurrent_revocation_exactly_one_audit_event(self):
        pol=self.fixture()
        cid=self.stage_published(pol)
        with psycopg.connect(DSN) as conn:
            conn.execute("""INSERT INTO t008_source_policies
                (source_code,acquisition_method,content_license,access_terms,
                 allowed_fields,automated_access_allowed,storage_allowed,
                 publication_allowed,reviewed_at,expires_at,policy_version)
                VALUES(%s,'local_dump','test-only','fixture approved',
                %s,true,true,false,%s,%s,2)""",
                (pol.source_code,["title","artist"],pol.reviewed_at,pol.expires_at))
            conn.commit()
        ready=Event()
        def worker():
            with psycopg.connect(DSN) as conn:
                conn.execute("SET lock_timeout='5s'")
                conn.commit()
                ready.wait(5)
                result=conn.execute("SELECT t008_reconcile_visibility(%s)",(cid,)).fetchone()[0]
                conn.commit()
                return result
        with ThreadPoolExecutor(max_workers=2) as pool:
            a=pool.submit(worker)
            b=pool.submit(worker)
            ready.set()
            self.assertEqual(set([a.result(timeout=9),b.result(timeout=9)]),
                             {"revoked","not_active"})
        with psycopg.connect(DSN) as conn:
            self.assertEqual(conn.execute("""SELECT count(*) FROM t008_publication_history
                WHERE candidate_id=%s AND action='revoke'""",(cid,)).fetchone()[0],1)
            self.assertEqual(conn.execute("""SELECT count(*) FROM t008_audit
                WHERE action='license_visibility_revoked'
                AND details->>'candidate_id'=%s""",(str(cid),)).fetchone()[0],1)
            self.assertEqual(conn.execute("""SELECT count(*) FROM t008_active_publications
                WHERE candidate_id=%s""",(cid,)).fetchone()[0],0)

    def test_existing_api_contract_unchanged_by_isolated_candidate(self):
        # Shadow comparison only: production's /api/v1/search remains entirely unchanged.
        from server.api.main import app as legacy
        prefix="b024shadow"+uuid.uuid4().hex[:12]
        title=prefix+" melody"
        artist=prefix+" ensemble"
        with psycopg.connect(DSN) as conn:
            artist_id=conn.execute("""INSERT INTO artists(name,name_key)
                VALUES(%s,%s) RETURNING id""",(artist,artist.replace(' ',''))).fetchone()[0]
            song_id=conn.execute("""INSERT INTO songs(title,title_key,primary_artist_id,
                release_year,release_precision) VALUES(%s,%s,%s,2024,'year')
                RETURNING id""",(title,title.replace(' ',''),artist_id)).fetchone()[0]
            conn.execute("""INSERT INTO song_names(song_id,kind,value,search_key,verification)
                 VALUES(%s,'hiragana','しゃどうてすと','しゃどうてすと','estimated')""",(song_id,))
            conn.execute("""INSERT INTO song_names(song_id,kind,value,search_key,verification)
                 VALUES(%s,'katakana','シャドウテスト','しゃどうてすと','estimated')""",(song_id,))
            conn.execute("""INSERT INTO song_names(song_id,kind,value,search_key,verification)
                 VALUES(%s,'romaji','shadow test','shadowtest','estimated')""",(song_id,))
            conn.execute("""INSERT INTO artist_names(artist_id,kind,value,search_key,verification)
                 VALUES(%s,'romaji','shadow ensemble','shadowensemble','estimated')""",(artist_id,))
            conn.commit()
        with TestClient(legacy) as client:
            title_path="/api/v1/search"
            baseline_title=client.get(title_path,params={"q":title,"mode":"title"})
            baseline_artist=client.get(title_path,params={"q":artist,"mode":"artist"})
            self.assertEqual(baseline_title.status_code,200,baseline_title.text)
            self.assertEqual(baseline_artist.status_code,200,baseline_artist.text)
            self.assertEqual(len(baseline_title.json()["items"]),1,baseline_title.text)
            self.assertEqual(baseline_title.json()["items"][0]["id"],song_id)
            self.assertEqual(baseline_title.json()["items"][0]["releaseDate"],"2024")
            self.assertIn("hiragana",baseline_title.json()["items"][0]["readings"]["title"])
            pol=self.fixture()
            batch=uuid.uuid4()
            with psycopg.connect(DSN) as conn:
                stage_candidates(conn,batch,[Candidate(title,artist,uuid.uuid4().hex)],pol)
                conn.commit()
            after_title=client.get(title_path,params={"q":title,"mode":"title"})
            after_artist=client.get(title_path,params={"q":artist,"mode":"artist"})
            self.assertEqual(after_title.status_code,200,after_title.text)
            self.assertEqual(after_artist.status_code,200,after_artist.text)
            self.assertEqual(after_title.json(),baseline_title.json())
            self.assertEqual(after_artist.json(),baseline_artist.json())
        print("B024_SHADOW title+artist legacy HTTP schema and id/readings unchanged")
if __name__=="__main__":
    unittest.main()
