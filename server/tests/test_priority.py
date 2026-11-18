"""Kenの優先リクエスト API (Supabase verification is stubbed)."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("KEN_DATABASE_URL", "postgresql://postgres:test@127.0.0.1:5432/ken_test")

import server.api.main as api


class PriorityTests(unittest.TestCase):
    def setUp(self):
        self._orig = api._supabase_get
        roles = {"admin-token-xxxxxxxxxxxxxxxx": "admin", "listener-token-xxxxxxxxxxxxx": "listener",
                 "other-admin-token-xxxxxxxxxx": "admin"}
        logins = {"admin-token-xxxxxxxxxxxxxxxx": "kenmorley", "other-admin-token-xxxxxxxxxx": "someone"}

        def fake(path, token):
            if path == "/auth/v1/user":
                if token not in roles:
                    raise ValueError("bad token")
                return {"id": "11111111-2222-3333-4444-555555555555"}
            return [{"role": roles[token], "display_name": "テスト管理者", "login_id": logins.get(token)}]
        api._supabase_get = fake
        api._ADMIN_CACHE.clear()

    def tearDown(self):
        api._supabase_get = self._orig

    def test_flow(self):
        admin = {"Authorization": "Bearer admin-token-xxxxxxxxxxxxxxxx"}
        with TestClient(api.app) as c:
            self.assertEqual(c.get("/api/v1/priority-requests").status_code, 401)
            self.assertEqual(c.get("/api/v1/priority-requests",
                headers={"Authorization": "Bearer listener-token-xxxxxxxxxxxxx"}).status_code, 403)
            self.assertEqual(c.get("/api/v1/priority-requests",
                headers={"Authorization": "Bearer other-admin-token-xxxxxxxxxx"}).status_code, 403)
            r = c.post("/api/v1/priority-requests", headers=admin,
                       json={"kind": "song", "artist": "テスト歌手P", "title": "テスト曲P"})
            self.assertEqual(r.status_code, 201, r.text)
            self.assertEqual(r.json()["item"]["status"], "requested")
            dup = c.post("/api/v1/priority-requests", headers=admin,
                         json={"kind": "song", "artist": "テスト歌手p ", "title": "テスト曲P"})
            self.assertEqual(dup.status_code, 409)
            self.assertEqual(c.post("/api/v1/priority-requests", headers=admin,
                json={"kind": "song", "artist": "X"}).status_code, 422)
            a = c.post("/api/v1/priority-requests", headers=admin,
                       json={"kind": "artist", "artist": "優先アーティストP", "title": "無視される"})
            self.assertEqual(a.status_code, 201, a.text)
            self.assertIsNone(a.json()["item"]["title"])
            items = c.get("/api/v1/priority-requests", headers=admin).json()["items"]
            self.assertTrue(any(i["artist"] == "優先アーティストP" for i in items))
            self.assertEqual(items[0]["requestedBy"], "テスト管理者")
            sid = r.json()["item"]["id"]
            self.assertEqual(c.post(f"/api/v1/priority-requests/{sid}/clear", headers=admin).status_code, 409)
            started = c.post(f"/api/v1/priority-requests/{sid}/status", headers=admin, json={"status": "in_progress"})
            self.assertEqual(started.status_code, 200, started.text)
            self.assertIsNotNone(started.json()["item"]["handledAt"])
            self.assertIsNone(started.json()["item"]["completedAt"])
            done = c.post(f"/api/v1/priority-requests/{sid}/status", headers=admin,
                          json={"status": "done", "addedArtistName": " テスト歌手P ", "addedSongCount": 12})
            self.assertEqual(done.status_code, 200, done.text)
            self.assertIsNotNone(done.json()["item"]["completedAt"])
            self.assertEqual(done.json()["item"]["addedArtistName"], "テスト歌手P")
            self.assertEqual(done.json()["item"]["addedSongCount"], 12)
            self.assertEqual(c.post(f"/api/v1/priority-requests/{a.json()['item']['id']}/status", headers=admin,
                json={"status": "done", "addedSongCount": -1}).status_code, 422)
            # After completion the same song may be requested again.
            again = c.post("/api/v1/priority-requests", headers=admin,
                           json={"kind": "song", "artist": "テスト歌手P", "title": "テスト曲P"})
            self.assertEqual(again.status_code, 201, again.text)
            cleared = c.post(f"/api/v1/priority-requests/{sid}/clear", headers=admin)
            self.assertEqual(cleared.status_code, 200, cleared.text)
            ids = [i["id"] for i in c.get("/api/v1/priority-requests", headers=admin).json()["items"]]
            self.assertNotIn(sid, ids)
            self.assertEqual(c.post(f"/api/v1/priority-requests/{sid}/clear",
                headers={"Authorization": "Bearer listener-token-xxxxxxxxxxxxx"}).status_code, 403)


if __name__ == "__main__":
    unittest.main()
