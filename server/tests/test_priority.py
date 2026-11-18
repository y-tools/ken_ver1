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
        roles = {"admin-token-xxxxxxxxxxxxxxxx": "admin", "listener-token-xxxxxxxxxxxxx": "listener"}

        def fake(path, token):
            if path == "/auth/v1/user":
                if token not in roles:
                    raise ValueError("bad token")
                return {"id": "11111111-2222-3333-4444-555555555555"}
            return [{"role": roles[token], "display_name": "テスト管理者"}]
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


if __name__ == "__main__":
    unittest.main()
