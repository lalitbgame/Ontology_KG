"""Unit tests for pipeline/phase1_extract.py - synthetic data, no PDF needed."""
import unittest

from pipeline import phase1_extract as p1


class NormalizeChem(unittest.TestCase):
    def test_examples_from_task_md(self):
        self.assertEqual(p1.normalize_chem("CH 4"), "CH4")
        self.assertEqual(p1.normalize_chem("C2 H 6"), "C2H6")

    def test_ordinary_prose_is_untouched(self):
        self.assertEqual(p1.normalize_chem("Table 1"), "Table 1")
        self.assertEqual(p1.normalize_chem("paragraph 6.3.2 of this Regulation"),
                          "paragraph 6.3.2 of this Regulation")


class HeaderFooterSignatures(unittest.TestCase):
    def _line(self, page, y0, text):
        return {"page": page, "x0": 0, "y0": y0, "text": text, "size": 10}

    def test_repeating_line_is_flagged(self):
        n_pages = 10
        words = "alpha beta gamma delta epsilon zeta eta theta iota kappa".split()
        lines = []
        for page in range(n_pages):
            lines.append(self._line(page, 50.0, "ECE/TRANS/WP.29/GRPE/2025/15"))
            lines.append(self._line(page, 800.0, str(page + 1)))  # bare page number
            lines.append(self._line(page, 100.0, f"unique body text about {words[page]}"))
        sigs = p1.header_footer_signatures(lines, n_pages)
        # digit runs are normalized to '#' before comparing across pages
        self.assertIn((50.0, "ECE/TRANS/WP.#/GRPE/#/#"), sigs)
        self.assertIn((800.0, "#"), sigs)
        self.assertEqual(len(sigs), 2)

    def test_below_threshold_is_not_flagged(self):
        n_pages = 10
        lines = [self._line(p, 50.0, "occasional note") for p in range(8)]
        sigs = p1.header_footer_signatures(lines, n_pages)
        self.assertEqual(sigs, set())


class TagFootnotes(unittest.TestCase):
    def test_small_bottom_text_is_a_footnote(self):
        lines = [
            {"page": 0, "y0": 100.0, "size": 10.0, "page_height": 800.0},  # body
            {"page": 0, "y0": 750.0, "size": 7.0, "page_height": 800.0},   # footnote
            {"page": 0, "y0": 760.0, "size": 10.0, "page_height": 800.0},  # small but not bottom -> body-sized, big
        ]
        p1.tag_footnotes(lines)
        self.assertFalse(lines[0]["is_footnote"])
        self.assertTrue(lines[1]["is_footnote"])
        self.assertFalse(lines[2]["is_footnote"])


if __name__ == "__main__":
    unittest.main()
