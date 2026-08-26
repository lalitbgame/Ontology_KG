"""Unit tests for pipeline/phase3_terms.py - synthetic data, no PDF needed."""
import unittest

from pipeline import phase3_terms as p3


def pline(x0, y0, text, page=5):
    return {"page": page, "x0": x0, "y0": y0, "text": text}


class ExtractColumnPairs(unittest.TestCase):
    def test_simple_pairs(self):
        lines = [pline(178, 10, "AC"), pline(305, 10, "Alternating current"),
                 pline(178, 20, "DC"), pline(305, 20, "Direct current")]
        entries = p3.extract_column_pairs(lines)
        self.assertEqual(entries, [
            {"surface_form": "AC", "expansion": "Alternating current"},
            {"surface_form": "DC", "expansion": "Direct current"},
        ])

    def test_multi_line_wrapped_expansion_is_joined(self):
        # e.g. real "CED" entry: expansion words land on separate lines
        lines = [pline(178, 10, "CED"), pline(305, 10, "Cycle"),
                 pline(339, 10, "energy demand"), pline(305, 20, "considering")]
        entries = p3.extract_column_pairs(lines)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["expansion"], "Cycle energy demand considering")

    def test_out_of_order_rows_are_resorted_by_position(self):
        # Real extraction quirk: two term-column lines can land in the raw
        # stream before either's expansion, even though each shares a y0
        # with its own expansion (e.g. real "NOVC"/"NOVC-HEV" entries).
        lines = [pline(178, 10, "NOVC"), pline(178, 20, "NOVC-HEV"),
                 pline(305, 10, "Not off-vehicle charging"),
                 pline(305, 20, "Not off-vehicle charging hybrid vehicle")]
        entries = p3.extract_column_pairs(lines)
        self.assertEqual(entries, [
            {"surface_form": "NOVC", "expansion": "Not off-vehicle charging"},
            {"surface_form": "NOVC-HEV", "expansion": "Not off-vehicle charging hybrid vehicle"},
        ])

    def test_leading_expansion_line_with_no_term_is_ignored(self):
        lines = [pline(305, 10, "orphan expansion, no term yet"),
                 pline(178, 20, "AC"), pline(305, 20, "Alternating current")]
        entries = p3.extract_column_pairs(lines)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["surface_form"], "AC")


class ExtractDefinitions(unittest.TestCase):
    def _clause(self, local_number, body_text, division="BODY"):
        return {"division": division, "local_number": local_number,
                "body_text": body_text, "qualified_id": f"REG154.04.{division}.{local_number}"}

    def test_plain_definition(self):
        clauses = [self._clause("3.4.3", '"Peripheral devices" means any energy consuming device.')]
        out = p3.extract_definitions(clauses)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["quoted_term"], "Peripheral devices")
        self.assertIsNone(out[0]["abbreviation"])
        self.assertEqual(out[0]["gloss"], "any energy consuming device.")

    def test_definition_with_inline_abbreviation(self):
        clauses = [self._clause(
            "3.3.20.1",
            '"Not off-vehicle charging fuel cell hybrid electric vehicle" (NOVC-FCHV) '
            'means a fuel cell hybrid electric vehicle that cannot be charged from an external source.')]
        out = p3.extract_definitions(clauses)
        self.assertEqual(out[0]["abbreviation"], "NOVC-FCHV")
        self.assertEqual(out[0]["quoted_term"], "Not off-vehicle charging fuel cell hybrid electric vehicle")

    def test_non_matching_body_is_skipped(self):
        clauses = [self._clause("3.5.2", "(Reserved)"), self._clause("3.5", "General")]
        self.assertEqual(p3.extract_definitions(clauses), [])

    def test_only_section_3_of_body_is_scanned(self):
        clauses = [
            self._clause("6.1", '"Not a real definition" means this is section 6, not 3.'),
            self._clause("3.1", '"Real definition" means this is section 3.', division="ANNEX-B1"),
        ]
        self.assertEqual(p3.extract_definitions(clauses), [])


if __name__ == "__main__":
    unittest.main()
