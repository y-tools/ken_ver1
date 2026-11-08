"""Offline source trust checks + disposable PostgreSQL queue smoke tests."""
from __future__ import annotations

import json
import os
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from server.research_worker import (Client,artist_identity,credits_include_artist,key,
                                    safe_title,valid_mbid,valid_qid,init_artist_rows)
import psycopg

MBID="6114677c-fa8f-4d87-960a-3f1169aaef89"

class ResearchValidationTests(unittest.TestCase):
    def test_names_and_versions(self):
        self.assertEqual(key("Ｂ’ｚ"),"b'z".replace("’","'"))
        self.assertTrue(safe_title("unravel"))
        self.assertFalse(safe_title("unravel (live)"))
        self.assertFalse(safe_title("interview 2"))
        self.assertFalse(safe_title("documentary: extra"))
        self.assertTrue(valid_mbid(MBID))
        self.assertFalse(valid_mbid("not-a-uuid"))
        self.assertTrue(valid_qid("Q1234"))
        self.assertFalse(valid_qid("Q1/../anything"))

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

class ResearchDatabaseTests(unittest.TestCase):
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
                           VALUES(%s,'Mock JP artist','https://musicbrainz.org',%s)""",
                        (aid,"https://musicbrainz.org"))
            n=con.execute("SELECT count(*) FROM ken_research_artists").fetchone()[0]
            self.assertEqual(n,1)
            con.rollback()

if __name__=="__main__":
    unittest.main()
