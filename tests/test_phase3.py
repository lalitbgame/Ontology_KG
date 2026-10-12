"""Unit tests for pipeline/phase3_terms.py - synthetic data, no PDF needed."""
import unittest

from pipeline import phase3_terms as p3


class ParseDefinition(unittest.TestCase):
    def test_straight_quotes_means(self):
        d = p3.parse_definition('"Peripheral devices" means energy consuming devices.')
        self.assertEqual(d["quoted_term"], "Peripheral devices")
        self.assertIsNone(d["abbreviation"])

    def test_inline_abbreviation_after_term(self):
        d = p3.parse_definition('"Not off-vehicle charging fuel cell hybrid vehicle" (NOVC-FCHV) means a fuel cell')
        self.assertEqual(d["abbreviation"], "NOVC-FCHV")

    def test_abbreviation_inside_the_quotes(self):
        # GTR 22 3.3: "Usable Battery energy (UBE)" means ...
        d = p3.parse_definition('"Usable Battery energy (UBE)" means the energy supplied by the battery')
        self.assertEqual((d["quoted_term"], d["abbreviation"]), ("Usable Battery energy", "UBE"))

    def test_refers_to_and_mixed_closing_quote(self):
        # GTR 22 3.4 / 3.15: 'refers to', and a straight-open curly-close quote
        d = p3.parse_definition('"Certified usable battery energy" (UBEcertified) refers to the UBE that was')
        self.assertEqual(d["verb"], "refers to")
        d = p3.parse_definition('"On-board SOCR” (SOCRread) means an estimate of state of certified range')
        self.assertEqual(d["quoted_term"], "On-board SOCR")

    def test_eu_or_form_with_curly_single_quotes(self):
        d = p3.parse_definition("‘conformity of production’ or ‘CoP’ means the activities carried out")
        self.assertEqual((d["quoted_term"], d["abbreviation"]), ("conformity of production", "CoP"))

    def test_eu_is_verb(self):
        d = p3.parse_definition("‘fuel consumption’ is the rate at which a vehicle uses fuel")
        self.assertEqual(d["verb"], "is")

    def test_prose_is_not_a_definition(self):
        self.assertIsNone(p3.parse_definition("The following definitions shall apply."))


class ExtractColumnPairs(unittest.TestCase):
    def _l(self, page, y0, x0, text):
        return {"page": page, "y0": y0, "x0": x0, "text": text}

    def test_basic_pairs(self):
        lines = [self._l(0, 100, 170, "AC"), self._l(0, 100, 227, "Alternating current"),
                 self._l(0, 112, 170, "APF"), self._l(0, 112, 227, "Assigned permeability"),
                 self._l(0, 124, 227, "factor")]
        pairs = p3.extract_column_pairs(lines)
        self.assertEqual([(p["surface_form"], p["expansion"]) for p in pairs],
                         [("AC", "Alternating current"), ("APF", "Assigned permeability factor")])

    def test_out_of_order_rows_are_resorted_by_position(self):
        # v1 regression: raw extraction order batched two term lines first
        lines = [self._l(0, 100, 170, "NOVC"), self._l(0, 112, 170, "NOVC-HEV"),
                 self._l(0, 100, 227, "Not off-vehicle charging"), self._l(0, 112, 227, "Not off-vehicle charging hybrid")]
        pairs = p3.extract_column_pairs(lines)
        self.assertEqual(pairs[0]["expansion"], "Not off-vehicle charging")
        self.assertEqual(pairs[1]["surface_form"], "NOVC-HEV")

    def test_column_split_is_learned_not_fixed(self):
        # L5.2: no x0 < 200 assumption
        lines = [self._l(0, 100 + 12 * i, 300, f"T{i}") for i in range(4)] + \
                [self._l(0, 100 + 12 * i, 400, f"Expansion {i}") for i in range(4)]
        self.assertEqual(len(p3.extract_column_pairs(lines)), 4)


class InlineAbbreviations(unittest.TestCase):
    def test_acronym_from_initials(self):
        self.assertEqual(p3.acronym_expansion("The Informal Working Group".split(), "IWG"), "Informal Working Group")

    def test_unrelated_parenthesis_is_ignored(self):
        self.assertIsNone(p3.acronym_expansion("the vehicle is tested".split(), "STP"))

    def test_harvest_from_units(self):
        units = [{"qualified_id": "D.1", "body_text": "the Joint Research Centre (JRC) has developed"}]
        out = p3.inline_abbreviations(units, "D")
        self.assertEqual([(a["surface_form"], a["expansion"]) for a in out], [("JRC", "Joint Research Centre")])


class SectionsByTitle(unittest.TestCase):
    def test_definitions_found_by_title_not_number(self):
        units = [
            {"qualified_id": "D.ART-3", "parent_id": None, "title": "Definitions", "body_text": "For the purposes:"},
            {"qualified_id": "D.ART-3.PT-1", "parent_id": "D.ART-3", "title": None,
             "body_text": "‘engine’ means the internal combustion engine of a vehicle;"},
            {"qualified_id": "D.ART-4", "parent_id": None, "title": "Obligations",
             "body_text": "‘x’ means something but not in a definitions section"},
        ]
        defs, _ = p3.extract_definitions(units, {"definition_sections": [r"^Definitions?\b"]}, "D")
        self.assertEqual([d["quoted_term"] for d in defs], ["engine"])
        self.assertEqual(defs[0]["id"], "D.DEF:ART-3.PT-1")


if __name__ == "__main__":
    unittest.main()
