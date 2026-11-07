"""T008-01 G1: 30 fictional cases, semantics, identity, legacy HTTP shadow.
Runs on disposable CI PostgreSQL; NEVER deploy. Failing evidence is explicit.
"""
from __future__ import annotations
import json
import os
import unittest
import uuid
from pathlib import Path
from datetime import datetime, timedelta, timezone
from dataclasses import replace

from server.t008_policy import Identity, SourcePolicy, acquisition_allowed, decide_identity

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "t008_g1_30_cases.json"
CASES = json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]
BY_ID = {c["id"]: c for c in CASES}
G1_FIELDS = ("title", "artist", "release_year", "title_hiragana",
             "artist_hiragana", "title_katakana", "artist_katakana",
             "title_romaji", "artist_romaji", "title_english", "artist_english")


def assess(c):
    """Independent check of manifest value/evidence expectations."""
    errors = []
    observations = {}
    for side in ("title", "artist"):
        for kind in ("hiragana", "katakana", "romaji", "english"):
            name = c["names"][side][kind]
            key = side + "_" + kind
            if name is None:
                observations[key] = "unknown"
                if kind == "hiragana" and key not in c["missing_reasons"]:
                    errors.append("missing reason: " + key)
                continue
            observations[key] = "verified" if name["verification"] == "source_confirmed" else "derived"
            if not name.get("evidence_ref"):
                errors.append("missing evidence: " + key)
            if name["verification"] == "derived_from_confirmed":
                parent = name.get("derived_from")
                if not parent or not c["names"][side]["hiragana"]:
                    errors.append("missing derived parent: " + key)
            if kind == "english" and name["verification"] not in ("source_confirmed", "human_confirmed"):
                errors.append("unverified English: " + key)
    yr = c["year"]
    if yr["value"] is None:
        observations["release_year"] = "unknown"
        if yr["semantics"] != "unknown" or yr["precision"] != "unknown" or not yr.get("unknown_reason"):
            errors.append("invalid unknown year")
    else:
        observations["release_year"] = "verified"
        if yr["semantics"] == "unknown" or yr["precision"] != "year" or not (1850 <= yr["value"] <= 2100):
            errors.append("invalid known year")
    if c["id"] == "F10":
        if c["names"]["title"]["english"]["value"] == c["machine_translation"]:
            errors.append("machine translation accepted")
        if not c["expected"]["reject_translation"]:
            errors.append("missing negative translation expectation")
    return {"observations": observations, "errors": errors}


class G1ManifestTests(unittest.TestCase):
    def test_30_cases_per_group_and_required_anomalies(self):
        self.assertEqual(len(CASES), 30)
        self.assertEqual(len(BY_ID), 30)
        for group in ("normal", "orthography", "identity"):
            self.assertEqual(sum(c["group"] == group for c in CASES), 10)
        self.assertEqual(BY_ID["I02"]["expected"]["identity"], "distinct_recording")
        self.assertEqual(BY_ID["I08"]["expected"]["identity"], "review")
        self.assertTrue(BY_ID["F10"]["expected"]["reject_translation"])
        self.assertGreaterEqual(sum(c["year"]["value"] is None for c in CASES), 2)

    def test_case_by_case_expectations(self):
        passed = []
        field_denominators = {f: 0 for f in G1_FIELDS}
        field_correct = {f: 0 for f in G1_FIELDS}
        missing = {f: 0 for f in G1_FIELDS}
        for case in CASES:
            with self.subTest(case=case["id"]):
                self.assertTrue(case["synthetic"])
                self.assertTrue(case["expected"]["no_legacy_write"])
                self.assertTrue(case["expected"]["legacy_display_id_unchanged"])
                result = assess(case)
                self.assertEqual(result["errors"], [])
                for field in ("title", "artist"):
                    field_denominators[field] += 1
                    self.assertTrue(case[field] and any(cl["field"] == field and cl["evidence_ref"] for cl in case["claims"]))
                    field_correct[field] += 1
                for field in G1_FIELDS[2:]:
                    if field == "release_year":
                        value = case["year"]["value"]
                    else:
                        side, kind = field.split("_", 1)
                        value = case["names"][side][kind]
                    if value is None:
                        missing[field] += 1
                    else:
                        field_denominators[field] += 1
                        field_correct[field] += 1
                passed.append(case["id"])
        self.assertEqual(len(passed), 30)
        # No denominator-zero field is reported as 100%: it is NOT_EVALUATED.
        metrics = {
            key: {"evaluated": field_denominators[key], "correct": field_correct[key],
                  "missing": missing[key],
                  "accuracy": ("NOT_EVALUATED" if not field_denominators[key] else
                               field_correct[key] / field_denominators[key])}
            for key in G1_FIELDS}
        print("T008_G1_T1_MANIFEST_CASES=30/30", flush=True)
        print("T008_G1_T1_FIELD_METRICS=" + json.dumps(metrics, ensure_ascii=False, sort_keys=True), flush=True)
        self.assertEqual(metrics["artist_english"]["accuracy"], "NOT_EVALUATED")
        self.assertEqual(metrics["title_english"]["accuracy"], 1.0)

    def test_identity_collision_and_different_recordings(self):
        one = BY_ID["I01"]
        two = BY_ID["I02"]
        match = Identity(one["title"], one["artist"], "recording", one["source_code"], one["external_id"], 1)
        other = Identity(two["title"], two["artist"], "recording", two["source_code"], two["external_id"], 1)
        self.assertEqual(decide_identity(other, match), "distinct_recording")
        clash = BY_ID["I08"]
        first = BY_ID["I07"]
        a = Identity(first["title"], first["artist"], "recording", first["source_code"], first["external_id"], 1)
        b = Identity(clash["title"], clash["artist"], "recording", clash["source_code"], clash["external_id"], 1)
        self.assertEqual(decide_identity(b, a), "review")
        cross = BY_ID["I09"]
        cross_ident = Identity(cross["title"], cross["artist"], "recording", cross["source_code"], cross["external_id"], 1)
        self.assertEqual(decide_identity(cross_ident, a), "review")

    def test_policy_denial(self):
        now = datetime.now(timezone.utc)
        p = SourcePolicy("g1_test", "local_dump", "fictional-only", "fictional fixture",
            frozenset({"title", "artist"}), True, True, False, True,
            now-timedelta(minutes=1), now+timedelta(minutes=10))
        self.assertTrue(acquisition_allowed(p, "local_dump", {"title", "artist"}))
        self.assertFalse(acquisition_allowed(replace(p, storage_allowed=False), "local_dump", {"title", "artist"}))
        self.assertFalse(acquisition_allowed(replace(p, automated_access_allowed=False), "local_dump", {"title", "artist"}))
        self.assertFalse(acquisition_allowed(replace(p, expires_at=now-timedelta(seconds=1)), "local_dump", {"title", "artist"}))


DSN = os.getenv("KEN_T008_TEST_DATABASE_URL", "")
@unittest.skipUnless(DSN and os.getenv("KEN_T008_ALLOW_DISPOSABLE") == "YES",
                     "T2 requires disposable PostgreSQL only")
class G1ActualFastAPIShadowTests(unittest.TestCase):
    def test_existing_api_json_preserved_and_staging_rollback(self):
        import psycopg
        from fastapi.testclient import TestClient
        from server.api.main import app
        from server.t008_stage_import import Candidate, stage_candidates

        token = uuid.uuid4().hex[:14]
        artist = "G1 fictional singer " + token
        title = "G1 fictional title " + token
        now = datetime.now(timezone.utc)
        source = "b014_g1_" + token
        p = SourcePolicy(source, "local_dump", "fixture-only", "fictional rights",
                         frozenset({"title", "artist"}), True, True, False, True,
                         now-timedelta(minutes=1), now+timedelta(minutes=30))
        with psycopg.connect(DSN) as con:
            self.assertEqual(con.execute("SELECT current_database()").fetchone()[0], "ken_test")
            con.execute("""INSERT INTO t008_source_policies
                 (source_code,acquisition_method,content_license,access_terms,allowed_fields,
                  automated_access_allowed,storage_allowed,publication_allowed,reviewed_at,
                  expires_at,policy_version)
                 VALUES(%s,'local_dump','fixture-only','fictional rights',%s,
                        true,true,false,%s,%s,1)""",
                 (source,["title","artist"],p.reviewed_at,p.expires_at))
            # Include legacy estimated reading as intentional preserved API behavior.
            artist_id = con.execute("INSERT INTO artists(name,name_key) VALUES(%s,%s) RETURNING id",
                              (artist,artist.replace(" ","").lower())).fetchone()[0]
            sid = con.execute("""INSERT INTO songs
               (title,title_key,primary_artist_id,release_year,release_precision)
               VALUES(%s,%s,%s,2024,'year') RETURNING id""",
               (title,title.replace(" ","").lower(),artist_id)).fetchone()[0]
            con.execute("""INSERT INTO song_names(song_id,kind,value,search_key,verification)
                        VALUES(%s,'hiragana','かくうよみ','かくうよみ','estimated')""",(sid,))
            con.commit()
        with TestClient(app) as client:
            params={"q": title,"mode":"title"}
            before=client.get("/api/v1/search",params=params)
            before_artist=client.get("/api/v1/search",params={"q":artist,"mode":"artist"})
            self.assertEqual((before.status_code,before_artist.status_code),(200,200))
            base=before.json()
            self.assertEqual(len(base["items"]),1)
            item=base["items"][0]
            self.assertEqual(item["id"],sid)
            self.assertEqual(item["releaseDate"],"2024")
            self.assertEqual(item["releasePrecision"],"year")
            self.assertEqual(item["readings"]["type"],"verified_or_estimated")
            self.assertEqual(item["readings"]["title"]["hiraganaVerification"],"estimated")
            # Stage a candidate WITHOUT touching legacy songs; then rollback the whole batch.
            batch=uuid.uuid4()
            with psycopg.connect(DSN) as con:
                result=stage_candidates(con,batch,[Candidate(title,artist,"g1-"+token)],p)
                self.assertEqual(result["inserted"],1)
                # Outer transaction remains uncommitted; rollback on purpose.
                con.rollback()
                self.assertEqual(con.execute(
                    "SELECT count(*) FROM t008_candidates WHERE batch_id=%s",(batch,)).fetchone()[0],0)
                con.commit()
            after=client.get("/api/v1/search",params=params)
            after_artist=client.get("/api/v1/search",params={"q":artist,"mode":"artist"})
            self.assertEqual(after.status_code,200)
            self.assertEqual(after.json(),base)
            self.assertEqual(after_artist.json(),before_artist.json())
            print("T008_G1_T2_FASTAPI_SHADOW=PASS ID/schema/readings/release/rollback",flush=True)

if __name__ == "__main__":
    unittest.main()
