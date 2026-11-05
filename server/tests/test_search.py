"""Integration checks against a disposable PostgreSQL database in GitHub Actions."""
from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

import psycopg
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("KEN_DATABASE_URL", "postgresql://postgres:test@127.0.0.1:5432/ken_test")
os.environ.setdefault("KEN_IMPORT_DATABASE_URL", os.environ["KEN_DATABASE_URL"])

from server.api.main import app, norm
from server.import_catalog import normalize


class SearchTests(unittest.TestCase):
    def test_normalization(self):
        cases = [
            ("マツダ・ＡＢＣ", "まつだabc"),
            ("カタカナ", "かたかな"),
            ("テスト －", "てすと"),
            ("Hello World", "helloworld"),
        ]
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(norm(value), expected)
                self.assertEqual(normalize(value), expected)

    def test_search_and_readings(self):
        with psycopg.connect(os.environ["KEN_IMPORT_DATABASE_URL"]) as conn:
            with conn.cursor() as cur:
                cur.execute("""INSERT INTO artists(name,name_key)
                               VALUES('統合テスト歌手','とうごうてすとかしゅ')
                               ON CONFLICT(name_key) DO UPDATE SET name=EXCLUDED.name
                               RETURNING id""")
                artist = cur.fetchone()[0]
                cur.execute("""INSERT INTO songs(title,title_key,primary_artist_id)
                               VALUES('統合テスト曲','とうごうてすときょく',%s)
                               ON CONFLICT(title_key,primary_artist_id) DO UPDATE SET title=EXCLUDED.title
                               RETURNING id""", (artist,))
                song = cur.fetchone()[0]
                cur.execute("""INSERT INTO song_names(song_id,kind,value,search_key,verification)
                               VALUES(%s,'hiragana','とうごうてすときょく','とうごうてすときょく','estimated')
                               ON CONFLICT DO NOTHING""", (song,))
                cur.execute("""INSERT INTO artist_names(artist_id,kind,value,search_key,verification)
                               VALUES(%s,'romaji','Tougo Test','tougotest','estimated')
                               ON CONFLICT DO NOTHING""", (artist,))
                cur.execute("""INSERT INTO song_names(song_id,kind,value,search_key,verification,reviewed_by)
                               VALUES(%s,'english','Verified Sample English','verifiedsampleenglish',
                                      'human_confirmed','integration-test')
                               ON CONFLICT DO NOTHING""", (song,))
        with TestClient(app) as client:
            self.assertEqual(client.get("/api/v1/health").status_code, 200)
            title = client.get("/api/v1/search", params={"q": "とうご", "mode": "title"})
            self.assertEqual(title.status_code, 200, title.text)
            item = next((x for x in title.json()["items"] if x["title"] == "統合テスト曲"), None)
            self.assertIsNotNone(item)
            self.assertEqual(item["readings"]["title"]["hiraganaVerification"], "estimated")
            self.assertEqual(item["readings"]["title"]["english"], "Verified Sample English")
            self.assertEqual(item["readings"]["title"]["englishVerification"], "human_confirmed")
            artist_result = client.get("/api/v1/search", params={"q": "tougo", "mode": "artist"})
            self.assertEqual(artist_result.status_code, 200, artist_result.text)
            self.assertIn("統合テスト曲", [x["title"] for x in artist_result.json()["items"]])
            wrong_field = client.get("/api/v1/search", params={"q": "tougo", "mode": "title"})
            self.assertEqual(wrong_field.status_code, 200)
            self.assertNotIn("統合テスト曲", [x["title"] for x in wrong_field.json()["items"]])
            invalid = client.get("/api/v1/search", params={"q": "a", "mode": "title"})
            self.assertEqual(invalid.status_code, 422)

    def test_english_cannot_be_estimated(self):
        with psycopg.connect(os.environ["KEN_IMPORT_DATABASE_URL"]) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM songs LIMIT 1")
                song = cur.fetchone()[0]
                with self.assertRaises(psycopg.errors.CheckViolation):
                    with conn.transaction():
                        cur.execute("""INSERT INTO song_names(song_id,kind,value,search_key,verification)
                                        VALUES(%s,'english','Fake English','fakeenglish','estimated')""",
                                        (song,))


if __name__ == "__main__":
    unittest.main()
