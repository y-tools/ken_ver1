"""Offline source trust checks + disposable PostgreSQL queue smoke tests."""
from __future__ import annotations

import json
import os
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from server.research_worker import (Client,artist_identity,credits_include_artist,key,
                                    safe_title,valid_mbid,valid_qid,init_artist_rows,run_forever,artist_lane,song_lane)
import psycopg

MBID="6114677c-fa8f-4d87-960a-3f1169aaef89"

class ResearchValidationTests(unittest.TestCase):
    def test_names_and_versions(self):
        self.assertEqual(key("Ｂ'ｚ"),"b'z")
        self.assertTrue(safe_title("unravel"))
        self.assertFalse(safe_title("unravel (live)"))
        self.assertFalse(safe_title("interview 2"))
        self.assertFalse(safe_title("documentary: extra"))
        self.assertTrue(valid_mbid(MBID))
        self.assertFalse(valid_mbid("not-a-uuid"))
        self.assertTrue(valid_qid("Q1234"))
        self.assertFalse(valid_qid("Q1/../anything"))

    def test_musicbrainz_recording_requires_artist_credits(self):
        c=Client()
        requested=[]
        c.get=lambda url: (requested.append(url) or {"recordings":[]})
        self.assertEqual(c.recordings(MBID,offset=25,limit=10),[])
        from urllib.parse import parse_qs,urlparse
        args=parse_qs(urlparse(requested[0]).query)
        self.assertEqual(args.get("inc"),["artist-credits"])
        self.assertEqual(args.get("offset"),["25"])

    def test_artist_credit(self):
        self.assertTrue(credits_include_artist(
            {"artist-credit":[{"artist":{"id":MBID}}]},MBID))
        self.assertFalse(credits_include_artist(
            {"artist-credit":[{"artist":{"id":str(uuid.uuid4())}}]},MBID))
        self.assertFalse(credits_include_artist({"artist-credit":[]} ,MBID))

    def test_independent_identity_required(self):
        artist={"id":MBID,"name":"TK from 凛として時雨","country":"JP",
                "relations":[
                  {"type":"wikidata","url":{"resource":"https://www.wikidata.org/wiki/Q123"}},
                  {"type":"official homepage","url":{"resource":"https://example.org/"}}]}
        fake=Mock()
        fake.wikidata.return_value={"entities":{"Q123":{
            "claims":{"P434":[{"mainsnak":{"datavalue":{"value":MBID}}}]}}}}
        self.assertEqual(artist_identity(fake,artist)[:2],(True,"Q123"))
        fake.wikidata.return_value={"entities":{"Q123":{"claims":{"P434":[]}}}}
        self.assertEqual(artist_identity(fake,artist)[0],False)
        artist["country"]="US"
        self.assertEqual(artist_identity(fake,artist)[0],False)

    def test_url_allowlist_no_untrusted_url(self):
        client=Client()
        for url in ["http://musicbrainz.org/ws/2/artist",
                    "https://www.wikidata.org/wiki/Q1",
                    "https://evil.example/ws/2/recording"]:
            with self.assertRaises(ValueError):
                client.get(url)

class ContinuousWorkerTests(unittest.TestCase):
    def test_two_lanes_run_back_to_back(self):
        invoked=[]
        def fake_lane(db, client, lane, budget):
            invoked.append((lane,budget))
            return (0,0,0)
        pauses=[]
        with patch("server.research_worker.execute_lane",side_effect=fake_lane):
            run_forever(object(),object(),max_cycles=2,sleep=pauses.append)
        self.assertEqual(invoked,[
            ("artists",5),("songs",25),("artists",5),("songs",25)])
        self.assertEqual(pauses,[1.5,1.5,1.5,1.5])

    def test_transient_error_uses_bounded_backoff(self):
        sequence=[]
        def fake_lane(db,client,lane,budget):
            sequence.append(lane)
            if lane=="artists":
                raise ValueError("API response malformed")
            return (0,0,0)
        pauses=[]
        fake_db=Mock()
        fake_db.closed=False
        with patch("server.research_worker.execute_lane",side_effect=fake_lane):
            run_forever(fake_db,object(),max_cycles=1,sleep=pauses.append)
        self.assertEqual(sequence,["artists","songs"])
        self.assertEqual(pauses,[15,1.5,1.5])


class ResearchDatabaseTests(unittest.TestCase):
    def test_jp_musicbrainz_artist_uses_provisional_direct_registration(self):
        url=os.environ.get("KEN_IMPORT_DATABASE_URL")
        if not url:
            self.skipTest("Requires disposable CI database")
        test_id=str(uuid.uuid4())
        fake=Mock()
        fake.artist_search.return_value=[{"id":test_id}]
        fake.artist.return_value={
            "id":test_id,"name":"Ken自動調査架空試験音楽グループ"+test_id[:8],
            "country":"JP","type":"Group","relations":[]}
        with psycopg.connect(url,autocommit=True,row_factory=psycopg.rows.dict_row) as con:
            with con.transaction():
                found,staged,promoted=artist_lane(con,fake,budget=1)
                self.assertEqual((found,staged,promoted),(1,1,1))
                state=con.execute("SELECT status,master_artist_id FROM ken_research_artists WHERE artist_mbid=%s",(test_id,)).fetchone()
                self.assertEqual(state["status"],"registered")
                artist=con.execute("SELECT identity_status FROM artists WHERE id=%s",(state["master_artist_id"],)).fetchone()
                self.assertEqual(artist["identity_status"],"provisional")
                # Keep test CI database pristine.
                con.execute("DELETE FROM ken_research_events WHERE item_id=%s",(test_id,))
                con.execute("DELETE FROM ken_research_artists WHERE artist_mbid=%s",(test_id,))
                con.execute("DELETE FROM artists WHERE id=%s",(state["master_artist_id"],))
                con.execute("DELETE FROM ken_research_state WHERE key='artist_offset'")

    def test_song_cursor_and_registration_after_known_recording(self):
        url=os.environ.get("KEN_IMPORT_DATABASE_URL")
        if not url:
            self.skipTest("Requires disposable CI database")
        import psycopg.rows
        aid=str(uuid.uuid4())
        old_id=str(uuid.uuid4())
        new_id=str(uuid.uuid4())
        class RollbackProbe(Exception):
            pass
        with psycopg.connect(url,autocommit=True,row_factory=psycopg.rows.dict_row) as con:
            try:
                with con.transaction():
                    artist=con.execute("""INSERT INTO artists(name,name_key,identity_status)
                        VALUES(%s,%s,'provisional') RETURNING id""",
                        ("Ken統合試験"+aid[:8],"ken_test_"+aid)).fetchone()["id"]
                    con.execute("""INSERT INTO ken_research_artists(
                        artist_mbid,name,country,source_url,status,master_artist_id)
                        VALUES(%s,%s,'JP',%s,'registered',%s)""",
                        (aid,"Ken統合試験"+aid[:8],"https://musicbrainz.org/artist/"+aid,artist))
                    existing=con.execute("""INSERT INTO songs(title,title_key,primary_artist_id)
                        VALUES('Existing Test Song',%s,%s) RETURNING id""",
                        ("existingtestsong",artist)).fetchone()["id"]
                    con.execute("""INSERT INTO recordings(song_id,musicbrainz_recording_id)
                        VALUES(%s,%s)""",(existing,old_id))
                    fake=Mock()
                    def recording(recording_id,title):
                        return {"id":recording_id,"title":title,"length":180000,"video":False,
                                "artist-credit":[{"artist":{"id":aid}}]}
                    fake.recordings.return_value=[
                        recording(old_id,"Existing Test Song"),
                        recording(new_id,"New Verified Test Song")]
                    with patch("server.research_worker.init_artist_rows"):
                        discovered,staged,promoted=song_lane(con,fake,budget=2)
                    self.assertEqual((discovered,staged,promoted),(2,2,1))
                    self.assertEqual(fake.recordings.call_args.args[1:],(0,2))
                    self.assertEqual(con.execute(
                        "SELECT value FROM ken_research_state WHERE key=%s",
                        ("song_offset:"+aid,)).fetchone()["value"],"2")
                    self.assertEqual(con.execute(
                        "SELECT COUNT(*) AS n FROM recordings WHERE musicbrainz_recording_id=%s",
                        (new_id,)).fetchone()["n"],1)
                    raise RollbackProbe()
            except RollbackProbe:
                pass

    def test_private_queue_tables_and_bounded_initial_state(self):
        url=os.environ.get("KEN_IMPORT_DATABASE_URL")
        if not url:
            self.skipTest("Requires disposable CI database")
        with psycopg.connect(url) as con:
            for table in ("ken_research_runs","ken_research_artists",
                          "ken_research_songs","ken_research_state","ken_research_events"):
                self.assertEqual(con.execute("SELECT count(*) FROM "+table).fetchone()[0],0)
            exists=con.execute("""SELECT count(*) FROM information_schema.columns
               WHERE table_name='ken_research_artists' AND column_name='review_reason'""").fetchone()[0]
            self.assertEqual(exists,1)
            # FK and uniqueness reject mismatched/duplicate identifiers.
            aid=str(uuid.uuid4())
            con.execute("""INSERT INTO ken_research_artists(artist_mbid,name,source_url)
                           VALUES(%s,'Mock JP artist',%s)""",
                        (aid,"https://musicbrainz.org"))
            n=con.execute("SELECT count(*) FROM ken_research_artists").fetchone()[0]
            self.assertEqual(n,1)
            con.rollback()

if __name__=="__main__":
    unittest.main()
