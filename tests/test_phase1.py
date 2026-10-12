"""Unit tests for pipeline/phase1_extract.py - synthetic data, no PDF needed."""
import unittest

from pipeline import phase1_extract as p1


def span(t, x0, x1, base=100.0, size=10.0, font="TimesNewRomanPSMT", flags=0):
    return {"t": t, "x0": x0, "x1": x1, "y0": base - size * 0.8, "y1": base + size * 0.2,
            "base": base, "size": size, "font": font, "flags": flags}


def frag(*spans):
    return {"spans": list(spans), "dir": [1.0, 0.0]}


class NormalizeChem(unittest.TestCase):
    def test_examples_from_task_md(self):
        self.assertEqual(p1.normalize_chem("CH 4"), "CH4")
        self.assertEqual(p1.normalize_chem("C2 H 6"), "C2H6")

    def test_ordinary_prose_is_untouched(self):
        self.assertEqual(p1.normalize_chem("Table 1"), "Table 1")
        self.assertEqual(p1.normalize_chem("paragraph 6.3.2 of this Regulation"),
                         "paragraph 6.3.2 of this Regulation")

    def test_vehicle_categories_are_never_glued(self):
        # L3.11: "M1 N1" is two EU vehicle categories, not a chemical formula
        self.assertEqual(p1.normalize_chem("M1 N1"), "M1 N1")
        self.assertEqual(p1.normalize_chem("C1 C2 C3"), "C1 C2 C3")


class MergeFragments(unittest.TestCase):
    def test_justified_word_per_line_is_rejoined(self):
        # L3.3: GTR 22 p.2 comes out one word per PyMuPDF "line"
        frags = [frag(span("was", 100, 115)), frag(span("set", 125, 138)), frag(span("up", 148, 158))]
        merged = p1.merge_fragments(frags)
        self.assertEqual(len(merged), 1)
        text, *_ = p1.build_text(merged[0])
        self.assertEqual(text, "was set up")

    def test_numbering_token_stays_on_its_own(self):
        # Phase 2 relies on number-only lines ("5.", "(23)") being separate
        frags = [frag(span("1.", 67, 75)), frag(span("This Regulation establishes", 89, 250))]
        self.assertEqual(len(p1.merge_fragments(frags)), 2)

    def test_column_gap_is_not_merged(self):
        frags = [frag(span("REESS", 170, 203)), frag(span("Rechargeable Electrical", 227, 330))]
        self.assertEqual(len(p1.merge_fragments(frags)), 2)

    def test_different_baselines_are_not_merged(self):
        frags = [frag(span("UBE", 264, 283, base=685)), frag(span("UBE", 265, 285, base=699))]
        self.assertEqual(len(p1.merge_fragments(frags)), 2)


class BuildText(unittest.TestCase):
    def test_subscript_is_marked(self):
        f = p1.merge_fragments([frag(span("SOC", 170, 188, base=329.2), span("read,i", 188, 208, base=331.2, size=7.0))])[0]
        self.assertEqual(p1.build_text(f)[0], "SOC_read,i")

    def test_chemical_subscripts_join(self):
        f = p1.merge_fragments([frag(span("CO", 170, 184), span("2", 184, 188, base=101.0, size=6.8),
                                     span(" emissions", 188, 230))])[0]
        self.assertEqual(p1.build_text(f)[0], "CO2 emissions")

    def test_superscript_after_word_is_a_footnote_ref(self):
        f = p1.merge_fragments([frag(span("vehicles", 100, 140), span("1", 140, 144, base=96.0, size=6.0),
                                     span(" shall", 144, 170))])[0]
        text, raw, refs, _ = p1.build_text(f)
        self.assertEqual(text, "vehicles shall")
        self.assertEqual(refs, ["1"])

    def test_oj_parenthesised_marker(self):
        f = p1.merge_fragments([frag(span("Committee (", 100, 150), span("1", 150, 154, base=96.0, size=6.0),
                                     span("),", 154, 160))])[0]
        text, raw, refs, _ = p1.build_text(f)
        self.assertEqual(text, "Committee (1),")
        self.assertEqual(refs, ["1"])

    def test_base_size_is_not_the_longest_subscript(self):
        spans = [span("SOC", 0, 18), span("measured,i", 18, 50, base=102, size=7.0)]
        self.assertEqual(p1.base_style(spans, 7.0, 102)[0], 10.0)


class HeaderFooter(unittest.TestCase):
    def _line(self, page, y0, text, x0=50.0):
        return {"page": page, "x0": x0, "x1": x0 + 100, "y0": y0, "y1": y0 + 10, "text": text}

    def test_alternating_odd_even_headers_are_found(self):
        # L3.1: OJ acts put 'EN' / 'OJ L, ...' on different sides on odd/even pages
        pages, dims = {}, {}
        for p in range(10):
            dims[p] = (595, 842)
            y = 44 if p % 2 else 813
            pages[p] = [self._line(p, y, "OJ L, 8.5.2024"), self._line(p, 400, f"body text {p} " * 3)]
        sigs = p1.header_footer_signatures(pages, dims)
        self.assertIn("oj l, #.#.#", sigs)
        self.assertEqual(len(sigs), 1)

    def test_body_text_is_never_a_header(self):
        pages = {p: [self._line(p, 400, "The manufacturer shall")] for p in range(10)}
        dims = {p: (595, 842) for p in range(10)}
        self.assertEqual(p1.header_footer_signatures(pages, dims), set())

    def test_vertical_running_head_on_landscape_page(self):
        line = {"x0": 782, "x1": 791, "y0": 496, "y1": 553, "dir": [0.0, 1.0], "text": "OJ L, 8.5.2024"}
        self.assertTrue(p1.in_edge_band(line, 842, 595))


class FootnoteSeparator(unittest.TestCase):
    def _l(self, y, text, size=8.5):
        return {"x0": 67, "x1": 500, "y0": y, "y1": y + 9, "text": text, "size": size}

    def test_short_rule_above_marker_lines(self):
        lines = [self._l(100, "body", 9.6), self._l(780, "(23) Regulation No 117 ...")]
        self.assertEqual(p1.footnote_rule_y(lines, [[67, 777, 118]], 595, 842, 9.6), 777)

    def test_table_border_is_not_a_separator(self):
        # L4/§3.5: a short table border followed by body-size text (Reg 154
        # p.268) must not turn the rest of the page into footnotes
        lines = [self._l(100, "body", 9.8), self._l(630, "a Other method", 8.2), self._l(648, "3.4.", 9.8)]
        self.assertIsNone(p1.footnote_rule_y(lines, [[67, 625, 200]], 595, 842, 9.8))

    def test_rule_with_more_rules_below_is_a_table(self):
        lines = [self._l(100, "body", 9.6), self._l(700, "(1) note")]
        self.assertIsNone(p1.footnote_rule_y(lines, [[67, 690, 118], [67, 720, 400]], 595, 842, 9.6))


if __name__ == "__main__":
    unittest.main()
