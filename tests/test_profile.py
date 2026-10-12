"""Unit tests for pipeline/profile.py (Phase 0) - no PDF needed."""
import unittest

from pipeline import profile as pr


class Profiles(unittest.TestCase):
    def test_every_shipped_profile_loads(self):
        profiles = pr.all_profiles()
        for fam in ("unece_regulation", "un_gtr", "eu_oj_act", "generic"):
            self.assertIn(fam, profiles)

    def test_unknown_key_fails_loudly(self):
        p = {"family": "x", "detect": {"any": []}, "structure": {"levels": []}, "structur": {}}
        with self.assertRaises(pr.ProfileError):
            pr.validate_profile(p, "x")

    def test_bad_level_regex_fails(self):
        p = {"family": "x", "detect": {"any": []},
             "structure": {"levels": [{"name": "a", "unit_type": "A", "match": "(", "id": "A"}]}}
        with self.assertRaises(pr.ProfileError):
            pr.validate_profile(p, "x")


class Detection(unittest.TestCase):
    def setUp(self):
        self.profiles = pr.all_profiles()

    def best(self, text):
        scores = {f: pr.score_profile(p, text) for f, p in self.profiles.items() if f != "generic"}
        return max(scores, key=scores.get)

    def test_eu_oj(self):
        self.assertEqual(self.best("Official Journal of the European Union L series ELI: http://data.europa.eu/eli/reg/2024/1257/oj "
                                   "REGULATION (EU) 2024/1257"), "eu_oj_act")

    def test_gtr(self):
        self.assertEqual(self.best("Global Registry ... Addendum 22: United Nations Global Technical Regulation No. 22 "
                                   "ECE/TRANS/180/Add.22"), "un_gtr")

    def test_unece_regulation(self):
        self.assertEqual(self.best("ECE/TRANS/WP.29/GRPE/2025/15 Proposal for a new 04 series of amendments to "
                                   "UN Regulation No. 154"), "unece_regulation")


class Templates(unittest.TestCase):
    def test_slash_becomes_dash(self):
        self.assertEqual(pr.format_template("EU{number}", {"number": "2024/1257"}), "EU2024-1257")

    def test_missing_field_gives_none(self):
        self.assertIsNone(pr.format_template("UNR{number}.{series}", {"number": "154"}))


class Registry(unittest.TestCase):
    def test_registry_covers_the_corpus(self):
        reg = pr.Registry()
        ids = {e["doc_id"] for e in reg.entries}
        self.assertTrue({"REG154.04", "GTR22", "EU2024-1257", "EU2026-1762"} <= ids)
        for e in reg.entries:
            self.assertTrue(e.get("self_ids"), f"{e['doc_id']} needs self_ids (plan §9a.2 step 3)")


if __name__ == "__main__":
    unittest.main()
