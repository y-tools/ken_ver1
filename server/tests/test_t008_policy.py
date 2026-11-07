"""Offline safety regressions; run: python -m unittest server.tests.test_t008_policy -v"""
import unittest
from datetime import datetime, timedelta, timezone
from server.t008_policy import SourcePolicy, acquisition_allowed, publication_allowed, Identity, decide_identity

class T008PolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = SourcePolicy("fixture", "local_dump", "CC0", "reviewed fixture terms",
                                   frozenset({"title","artist"}), True, True, True, True,\n                                   datetime.now(timezone.utc) - timedelta(days=1),\n                                   datetime.now(timezone.utc) + timedelta(days=1))

    def test_unknown_access_denied(self):
        p = SourcePolicy("x","api","CC0","unknown",frozenset({"title"}))
        self.assertFalse(acquisition_allowed(p,"api"))
    def test_wrong_method_denied(self):
        self.assertFalse(acquisition_allowed(self.policy,"api"))
    def test_unknown_publication_denied(self):
        p = SourcePolicy("x","dump","CC0","terms",frozenset({"title"}),True,True,None,True,\n                         datetime.now(timezone.utc)-timedelta(days=1),\n                         datetime.now(timezone.utc)+timedelta(days=1))
        self.assertFalse(publication_allowed(p,"dump",{"title"},{"title"},True))
    def test_field_evidence_required(self):
        self.assertFalse(publication_allowed(self.policy,"local_dump",{"title","artist"},{"title"},True))
    def test_unverified_denied(self):
        self.assertFalse(publication_allowed(self.policy,"local_dump",{"title"},{"title"},False))
    def test_valid_fixture(self):
        self.assertTrue(publication_allowed(self.policy,"local_dump",{"title"},{"title"},True))
    def test_title_artist_no_merge(self):
        self.assertEqual(decide_identity(Identity("same","same"),Identity("same","same")),"review")
    def test_external_recording_link_only(self):
        a = Identity("same","same","recording","mb","rec-id",1)
        self.assertEqual(decide_identity(a,a),"link_recording")
    def test_same_work_is_not_same_recording(self):
        a = Identity("same","same","work","mb","work-id",1)
        self.assertEqual(decide_identity(a,a),"review")
    def test_different_recordings(self):
        a=Identity("same","same","recording","mb","rec-a",1)
        b=Identity("same","same","recording","mb","rec-b",1)
        self.assertEqual(decide_identity(a,b),"distinct_recording")
    def test_duplicate_external_id_collision(self):
        a=Identity("same","same","recording","mb","rec-a",2)
        self.assertEqual(decide_identity(a,a),"review")
    def test_manual_conflict(self):
        a=Identity("same","same","recording","mb","rec-a",1,True)
        self.assertEqual(decide_identity(a,a),"review")
    def test_cross_type_collision(self):
        a=Identity("same","same","recording","mb","id",1)
        b=Identity("same","same","work","mb","id",1)
        self.assertEqual(decide_identity(a,b),"review")
    def test_medley_no_auto_merge(self):
        a=Identity("medley","artist","recording","mb","id",1)
        b=Identity("medley","artist","work","mb","id",1)
        self.assertEqual(decide_identity(a,b),"review")


    def test_unknown_license_string(self):
        from dataclasses import replace
        for val in ("unknown", " UNKNOWN ", " ", "未確認", "pending"):
            with self.subTest(val=val):
                self.assertFalse(acquisition_allowed(replace(self.policy, content_license=val),"local_dump"))
                self.assertFalse(publication_allowed(replace(self.policy, content_license=val),"local_dump",{"title"},{"title"},True))

    def test_unknown_terms_string(self):
        from dataclasses import replace
        self.assertFalse(acquisition_allowed(replace(self.policy, access_terms="unknown"),"local_dump"))

    def test_expired_policy(self):
        from dataclasses import replace
        self.assertFalse(acquisition_allowed(replace(self.policy, expires_at=datetime.now(timezone.utc)-timedelta(seconds=1)),"local_dump"))

    def test_empty_publication_fields(self):
        self.assertFalse(publication_allowed(self.policy,"local_dump",set(),set(),True))

    def test_recording_metadata_conflict(self):
        a=Identity("alpha","artist","recording","mb","id",1)
        b=Identity("beta","artist","recording","mb","id",1)
        self.assertEqual(decide_identity(a,b),"review")

    def test_cross_source_recording_ids(self):
        a=Identity("same","same","recording","mb","id1",1)
        b=Identity("same","same","recording","wd","id2",1)
        self.assertEqual(decide_identity(a,b),"review")

    def test_missing_existing_with_manual_conflict(self):
        a=Identity("same","same","recording","mb","id1",0,True)
        self.assertEqual(decide_identity(a,None),"review")

if __name__ == "__main__":
    unittest.main()
