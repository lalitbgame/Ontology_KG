"""Unit tests for pipeline/phase2_parse.py - synthetic pages.jsonl-shaped
input, no PDF needed."""
import unittest

from pipeline import phase2_parse as p2


HEADING_SIZE = 14.3
BODY_SIZE = 9.8


def line(text, page=0, is_footnote=False, size=HEADING_SIZE):
    # size defaults to heading-sized so existing Annex/Appendix-boundary
    # tests below don't all need to state it explicitly.
    return {"page": page, "text": text, "is_footnote": is_footnote, "size": size}


class DivisionCode(unittest.TestCase):
    def test_matches(self):
        self.assertEqual(p2.division_code("Annex B1", HEADING_SIZE), "ANNEX-B1")
        self.assertEqual(p2.division_code("Annex B6a", HEADING_SIZE), "ANNEX-B6a")
        self.assertEqual(p2.division_code("Annex B1 - Appendix 1", HEADING_SIZE), "ANNEX-B1.APP1")
        self.assertEqual(p2.division_code("Appendix 5", HEADING_SIZE), "APPENDIX-5")

    def test_non_matches(self):
        self.assertIsNone(p2.division_code("Annexes Part A", HEADING_SIZE))
        self.assertIsNone(p2.division_code("as defined in Annex B6 to this Regulation", HEADING_SIZE))
        self.assertIsNone(p2.division_code("Ordinary body text.", HEADING_SIZE))

    def test_small_font_is_rejected_even_if_the_text_matches(self):
        # Real bug: "...in accordance with paragraph 3.4. of\nAppendix 2"
        # wraps so "Appendix 2" lands alone on its own line, body-sized.
        self.assertIsNone(p2.division_code("Appendix 2", BODY_SIZE))
        self.assertIsNone(p2.division_code("Annex B6", BODY_SIZE))


class StripToc(unittest.TestCase):
    def test_dense_dot_leaders_near_the_front_are_dropped(self):
        lines = [line(f"Section {i} .................. {i}", page=1) for i in range(5)]
        lines += [line("1."), line("Scope")]
        kept = p2.strip_toc(lines)
        self.assertEqual([l["text"] for l in kept], ["1.", "Scope"])

    def test_dense_dot_leaders_far_from_the_front_are_kept(self):
        # e.g. Annex A1's fill-in-the-blank form: "Test voltage: .......... V"
        lines = [line(f"Field {i}: .................. V", page=200) for i in range(5)]
        kept = p2.strip_toc(lines)
        self.assertEqual(len(kept), 5)

    def test_a_lone_dot_leader_line_is_not_enough_to_flag_a_page(self):
        lines = [line("Signature: .......... [Place]", page=1)]
        kept = p2.strip_toc(lines)
        self.assertEqual(len(kept), 1)


class LabelsFor(unittest.TestCase):
    def test_depth_labels(self):
        self.assertEqual(p2.labels_for(0, True), ["DivisionRoot", "Paragraph"])
        self.assertEqual(p2.labels_for(1, False), ["Section"])
        self.assertEqual(p2.labels_for(2, True), ["Subsection", "Paragraph"])
        self.assertEqual(p2.labels_for(5, True), ["Provision", "Paragraph"])


class Parse(unittest.TestCase):
    def test_basic_nesting_and_qualified_ids(self):
        lines = [
            line("1."), line("Scope"),
            line("This Regulation applies to vehicles."),
            line("1.1."), line("A sub-clause."),
        ]
        clauses = p2.parse(lines)
        p2.finalize(clauses)
        by_id = {c["qualified_id"]: c for c in clauses}
        self.assertIn("REG154.04.BODY.1", by_id)
        self.assertIn("REG154.04.BODY.1.1", by_id)
        self.assertEqual(by_id["REG154.04.BODY.1.1"]["parent_id"], "REG154.04.BODY.1")
        self.assertEqual(by_id["REG154.04.BODY.1"]["depth"], 1)
        self.assertEqual(by_id["REG154.04.BODY.1.1"]["depth"], 2)
        self.assertIn("Scope", by_id["REG154.04.BODY.1"]["body_text"])

    def test_wrapped_reference_fragment_does_not_reset_division(self):
        # "...paragraph 3.4. of\nAppendix 2" wrapping mid-sentence must not
        # be mistaken for a real "Appendix 2" heading.
        lines = [
            line("8.1.2."),
            line("The manufacturer shall check the accessibility of the parameters"),
            line("listed in paragraph 3. of", size=BODY_SIZE),
            line("Appendix 2", size=BODY_SIZE),
            line("in accordance with paragraph 5.1."),
            line("8.1.3."), line("CoP family"),
        ]
        clauses = p2.parse(lines)
        p2.finalize(clauses)
        divisions = {c["division"] for c in clauses}
        self.assertEqual(divisions, {"BODY"})
        target = next(c for c in clauses if c["qualified_id"] == "REG154.04.BODY.8.1.2")
        self.assertIn("Appendix 2", target["body_text"])
        self.assertIn("REG154.04.BODY.8.1.3",
                       {c["qualified_id"] for c in clauses})

    def test_division_boundary_resets_numbering(self):
        lines = [line("1."), line("Body clause."), line("Annex B1"), line("1."), line("Annex clause.")]
        clauses = p2.parse(lines)
        p2.finalize(clauses)
        ids = {c["qualified_id"] for c in clauses}
        self.assertIn("REG154.04.BODY.1", ids)
        self.assertIn("REG154.04.ANNEX-B1.1", ids)

    def test_unnumbered_division_content_is_not_dropped(self):
        # Some Annex appendices are pure declaration forms with no decimal
        # numbering at all - see output/PHASE1_2_NOTES.md.
        lines = [line("Appendix 3"), line("Manufacturer's Declaration."), line("Done at [Place].")]
        clauses = p2.parse(lines)
        p2.finalize(clauses)
        root = next(c for c in clauses if c["qualified_id"] == "REG154.04.APPENDIX-3")
        self.assertIn("Manufacturer's Declaration.", root["body_text"])
        self.assertIn("Done at [Place].", root["body_text"])

    def test_numeric_value_is_not_mistaken_for_a_clause(self):
        lines = [line("3.5.10."), line('"Reference temperature" means 273.15K (0 C).')]
        clauses = p2.parse(lines)
        p2.finalize(clauses)
        ids = {c["qualified_id"] for c in clauses}
        self.assertNotIn("REG154.04.BODY.273", ids)
        target = next(c for c in clauses if c["qualified_id"] == "REG154.04.BODY.3.5.10")
        self.assertIn("273.15K", target["body_text"])

    def test_lettered_sub_items_stay_inline_not_as_nodes(self):
        lines = [line("6.1.1."), line("The vehicle shall be prepared as follows:"),
                 line("(a)"), line("No leaks."), line("(b)"), line("May be cleaned.")]
        clauses = p2.parse(lines)
        p2.finalize(clauses)
        self.assertEqual(len(clauses), 2)  # division root + 6.1.1. only
        target = next(c for c in clauses if c["qualified_id"] == "REG154.04.BODY.6.1.1")
        self.assertIn("(a)", target["body_text"])
        self.assertIn("(b)", target["body_text"])

    def test_footnote_lines_are_kept_separate_from_body(self):
        lines = [line("1."), line("Main text."), line("a footnote", is_footnote=True)]
        clauses = p2.parse(lines)
        p2.finalize(clauses)
        target = next(c for c in clauses if c["qualified_id"] == "REG154.04.BODY.1")
        self.assertEqual(target["body_text"], "Main text.")
        self.assertEqual(target["footnote_text"], "a footnote")

    def test_skipped_depth_attaches_as_best_guess_instead_of_failing(self):
        lines = [line("1."), line("Top level."), line("1.1.1."), line("Skipped 1.1.")]
        clauses = p2.parse(lines)  # must not raise
        p2.finalize(clauses)
        deep = next(c for c in clauses if c["qualified_id"] == "REG154.04.BODY.1.1.1")
        self.assertEqual(deep["parent_id"], "REG154.04.BODY.1")


class Dedupe(unittest.TestCase):
    def test_duplicate_qualified_ids_are_merged_not_dropped(self):
        nodes = [
            {"qualified_id": "X", "depth": 1, "page": 1,
             "body_text": "", "footnote_text": None, "has_body": False, "labels": ["Section"]},
            {"qualified_id": "X", "depth": 1, "page": 2,
             "body_text": "Real content.", "footnote_text": None, "has_body": True, "labels": ["Section", "Paragraph"]},
        ]
        result = p2.dedupe(nodes)
        self.assertEqual(len(result), 1)
        self.assertIn("Real content.", result[0]["body_text"])
        self.assertTrue(result[0]["has_body"])


class Finalize(unittest.TestCase):
    def test_orphan_is_detected(self):
        nodes = [
            {"qualified_id": "A", "depth": 1, "parent_id": None,
             "body_lines": ["x"], "footnote_lines": []},
            {"qualified_id": "B", "depth": 2, "parent_id": "MISSING",
             "body_lines": ["y"], "footnote_lines": []},
        ]
        orphans = p2.finalize(nodes)
        self.assertEqual(orphans, 1)


if __name__ == "__main__":
    unittest.main()
