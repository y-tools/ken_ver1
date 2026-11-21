"""Offline tests for safe MusicBrainz retries and no silent metadata corruption."""
import io
import json
import unittest
import urllib.error
from unittest.mock import patch

from server.musicbrainz_bz_fetch import get_json, fetch_recordings, MB_HOST


class FakeResponse:
    def __init__(self, payload):
        self.content = io.BytesIO(json.dumps(payload).encode())
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self, size=-1):
        return self.content.read(size)


class MusicBrainzRetryTests(unittest.TestCase):
    def test_503_retried_then_succeeds(self):
        calls = []
        pauses = []
        def opener(req, timeout):
            calls.append(req.full_url)
            self.assertIn("KenDenmokuResearch", req.headers["User-agent"])
            if len(calls) < 3:
                raise urllib.error.HTTPError(req.full_url, 503, "busy", {}, None)
            return FakeResponse({"recordings": []})
        value = get_json(MB_HOST + "/ws/2/recording?fmt=json", open_url=opener,
                         sleep=pauses.append)
        self.assertEqual(value, {"recordings": []})
        self.assertEqual(len(calls), 3)
        self.assertEqual(len(pauses), 2)
        self.assertTrue(all(wait >= 2 for wait in pauses))

    def test_400_not_retried(self):
        def opener(req, timeout):
            raise urllib.error.HTTPError(req.full_url, 400, "bad", {}, None)
        with self.assertRaises(urllib.error.HTTPError):
            get_json(MB_HOST + "/ws/2/recording", open_url=opener, sleep=lambda _: self.fail("should not retry"))

    def test_503_exhaustion_is_error(self):
        calls = []
        def opener(req, timeout):
            calls.append(1)
            raise urllib.error.HTTPError(req.full_url, 503, "busy", {}, None)
        with self.assertRaises(urllib.error.HTTPError):
            get_json(MB_HOST + "/ws/2/recording", open_url=opener, max_attempts=3, sleep=lambda _: None)
        self.assertEqual(len(calls), 3)

    def test_only_musicbrainz_host(self):
        with self.assertRaises(ValueError):
            get_json("https://example.com/ws/2/recording")

    def test_recordings_preserve_identity_and_pagination(self):
        events = []
        def fetch(url):
            events.append(url)
            if len(events) == 1:
                return {"recordings": [{"id": "uuid-a", "title": "Same Song"}]}
            return {"recordings": [{"id": "uuid-b", "title": "Same Song"}]}
        delays = []
        rows = fetch_recordings("the-artist", limit=1, max_pages=2, fetch=fetch, sleep=delays.append)
        self.assertEqual(len(rows), 2)
        self.assertNotEqual(rows[0]["recording_mbid"], rows[1]["recording_mbid"])
        self.assertEqual(delays, [1.2])
        self.assertTrue(all(r["verification"] == "unreviewed" for r in rows))


if __name__ == "__main__":
    unittest.main()
