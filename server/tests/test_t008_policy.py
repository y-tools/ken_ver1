"""Offline safety regressions; run: python -m unittest server.tests.test_t008_policy -v"""
import unittest
from server.t008_policy import SourcePolicy, acquisition_allowed, publication_allowed, Identity, decide_identity

class T008PolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = SourcePolicy("fixture", "local_dump", "CC0", "reviewed fixture terms",
                                   frozenset({"title","artist"}), True, True, True, True)

    def test_unknown_access_denied(self):
        p = SourcePolicy("x","api","CC0","unknown",frozenset({"title"}))
        self.assertFalse(acquisition_allowed(p,"api"))
    def test_wrong_method_denied(self):
        self.assertFalse(acquisition_allowed(self.policy,"api"))
    def test_unknown_publication_denied(self):
        p = SourcePolicy("x","dump","CC0","terms",frozenset({"title"}),True,True,None,True)
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

if __name__ == "__main__":
    unittest.main()
