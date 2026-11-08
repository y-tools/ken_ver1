"""Disposable PostgreSQL tests for authenticated editor.

These credentials and records are test-only, never for production.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from uuid import uuid4

from argon2 import PasswordHasher
from fastapi.testclient import TestClient
import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
os.environ.setdefault("KEN_ADMIN_DATABASE_URL", os.environ.get("KEN_DATABASE_URL", "postgresql://postgres:test@127.0.0.1:5432/ken_test"))
os.environ["KEN_ADMIN_PASSWORD_HASH"] = PasswordHasher().hash("integration-admin-password")
os.environ.setdefault("KEN_ALLOWED_ORIGINS", "https://y-tools.github.io")

from server.admin_api import app


class EditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)

    def test_auth_and_artist_edit(self):
        suffix = uuid4().hex[:12]
        artist_name = "管理テスト歌手" + suffix
        song_title = "管理テスト楽曲" + suffix
        with psycopg.connect(os.environ["KEN_ADMIN_DATABASE_URL"]) as conn:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO artists(name,name_key) VALUES (%s,%s) RETURNING id", (artist_name, artist_name))
                artist_id = cur.fetchone()[0]
                cur.execute("INSERT INTO songs(title,title_key,primary_artist_id) VALUES (%s,%s,%s) RETURNING id",
                            (song_title, song_title, artist_id))
                song_id = cur.fetchone()[0]

        stats_unauthorized=self.client.get("/api/admin/stats")
        self.assertEqual(stats_unauthorized.status_code,401)
        unauthorized = self.client.get("/api/admin/artists", params={"q":"管理テスト"})
        self.assertEqual(unauthorized.status_code, 401)
        wrong = self.client.post("/api/admin/login", json={"password":"definitely-wrong-pass"})
        self.assertEqual(wrong.status_code, 401)
        login = self.client.post("/api/admin/login", json={"password":"integration-admin-password"})
        self.assertEqual(login.status_code, 200, login.text)
        token = login.json()["token"]
        headers={"Authorization":"Bearer "+token, "Origin":"https://y-tools.github.io"}
        with psycopg.connect(os.environ["KEN_ADMIN_DATABASE_URL"]) as conn:
            expected_artists=conn.execute("SELECT COUNT(*) FROM artists").fetchone()[0]
            expected_songs=conn.execute("SELECT COUNT(*) FROM songs").fetchone()[0]
        stats=self.client.get("/api/admin/stats",headers=headers)
        self.assertEqual(stats.status_code,200,stats.text)
        self.assertEqual(stats.json(),{"artists":expected_artists,"songs":expected_songs})
        bad_origin = self.client.get("/api/admin/artists",params={"q":"管理テスト"},headers={**headers,"Origin":"https://evil.example"})
        self.assertEqual(bad_origin.status_code,403)
        list_resp=self.client.get("/api/admin/artists", params={"q":"管理テスト"},headers=headers)
        self.assertEqual(list_resp.status_code,200,list_resp.text)
        detail=self.client.get("/api/admin/artists/"+str(artist_id),headers=headers)
        self.assertEqual(detail.status_code,200,detail.text)
        original=detail.json()["artist"]
        edited_name=artist_name+"改"
        updated=self.client.post("/api/admin/artists/"+str(artist_id),
            json={"name":edited_name,"version":original["version"]}, headers=headers)
        self.assertEqual(updated.status_code,200,updated.text)
        stale=self.client.post("/api/admin/artists/"+str(artist_id),
            json={"name":edited_name+"失敗","version":original["version"]},headers=headers)
        self.assertEqual(stale.status_code,409,stale.text)

        # A research date is explicit and independent from ordinary artist-name edits.
        detail_after_name=self.client.get("/api/admin/artists/"+str(artist_id),headers=headers)
        self.assertIsNone(detail_after_name.json()["artist"]["lastResearchedOn"])
        research_auth=self.client.post("/api/admin/artists/"+str(artist_id)+"/research",
            json={"version":detail_after_name.json()["artist"]["version"],
                  "lastResearchedOn":"2026-11-08"})
        self.assertEqual(research_auth.status_code,401)
        research=self.client.post("/api/admin/artists/"+str(artist_id)+"/research",
            json={"version":detail_after_name.json()["artist"]["version"],
                  "lastResearchedOn":"2026-11-08"},headers=headers)
        self.assertEqual(research.status_code,200,research.text)
        self.assertEqual(research.json()["artist"]["lastResearchedOn"],"2026-11-08")
        stale_research=self.client.post("/api/admin/artists/"+str(artist_id)+"/research",
            json={"version":detail_after_name.json()["artist"]["version"],
                  "lastResearchedOn":None},headers=headers)
        self.assertEqual(stale_research.status_code,409,stale_research.text)
        future=self.client.post("/api/admin/artists/"+str(artist_id)+"/research",
            json={"version":research.json()["artist"]["version"],
                  "lastResearchedOn":"2099-01-01"},headers=headers)
        self.assertEqual(future.status_code,422,future.text)
        research_log=self.client.get("/api/admin/audit",
            params={"entityType":"artist","entityId":artist_id},headers=headers)
        self.assertEqual(research_log.status_code,200,research_log.text)
        self.assertTrue(any(x["action"]=="artist_research_date_update" for x in research_log.json()["items"]))
        cleared=self.client.post("/api/admin/artists/"+str(artist_id)+"/research",
            json={"version":research.json()["artist"]["version"],
                  "lastResearchedOn":None},headers=headers)
        self.assertEqual(cleared.status_code,200,cleared.text)
        self.assertIsNone(cleared.json()["artist"]["lastResearchedOn"])

        song=self.client.get("/api/admin/songs/"+str(song_id),headers=headers)
        self.assertEqual(song.status_code,200,song.text)
        result=self.client.post("/api/admin/songs/"+str(song_id),headers=headers,json={
            "title":song_title+"改","version":song.json()["song"]["version"],
            "releasePrecision":"day","releaseYear":2024,"releaseMonth":3,"releaseDay":15,
            "releaseSourceUrl":"https://musicbrainz.org/release/example"
        })
        self.assertEqual(result.status_code,200,result.text)
        alias=self.client.post("/api/admin/aliases",headers=headers,json={
            "side":"song","entityId":song_id,"kind":"hiragana","value":"かんりてすときょく",
            "sourceUrl":"https://musicbrainz.org/release/example"
        })
        self.assertEqual(alias.status_code,200,alias.text)
        alias_edit=self.client.post("/api/admin/aliases",headers=headers,json={
            "side":"song","entityId":song_id,"kind":"hiragana","value":"かんりてすとのきょく",
            "oldId":alias.json()["alias"]["id"]
        })
        self.assertEqual(alias_edit.status_code,200,alias_edit.text)
        audit=self.client.get("/api/admin/audit",params={"entityType":"song","entityId":song_id},headers=headers)
        self.assertGreaterEqual(len(audit.json()["items"]),2)
        logout=self.client.post("/api/admin/logout",headers=headers,json={})
        self.assertEqual(logout.status_code,200)
        after=self.client.get("/api/admin/artists",params={"q":"管理テスト"},headers=headers)
        self.assertEqual(after.status_code,401)


if __name__=="__main__":
    unittest.main()
