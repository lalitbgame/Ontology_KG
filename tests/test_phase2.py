"""Unit tests for pipeline/phase2_parse.py - synthetic lines, real profiles."""
import unittest

from pipeline import phase2_parse as p2
from pipeline.profile import load_profile

STATS = {"body_size": 10.0, "number_columns": [[114, 50]], "text_left": [170]}
PAGES = [{"page": p, "width": 595, "height": 842} for p in range(5)]


class Doc:
    """Builds lines top-to-bottom: L('text', x=..., size=...)."""

    def __init__(self):
        self.lines, self.y, self.page = [], 60.0, 0

    def L(self, text, x=170.0, size=10.0, bold=False, italic=False, same_row=False, centered=False, gap=False):
        if not same_row:
            self.y += 1.2 * size + (8 if gap else 0)     # real documents: ~1.2x leading, +8pt between paragraphs
        if centered:
            w = 6 * len(text)
            x = 297.6 - w / 2
        else:
            w = 6 * len(text)
        self.lines.append({"id": f"p{self.page}.{len(self.lines)}", "page": self.page, "x0": x, "x1": x + w,
                           "y0": self.y - size, "y1": self.y, "base": self.y, "size": size, "bold": bold,
                           "italic": italic, "text": text, "is_footnote": False})
        return self


def parse(doc_id, family, lines, regions=()):
    prof = load_profile(family)
    p, anchors, notes = p2.parse(doc_id, prof, lines, list(regions), STATS, PAGES)
    units = p2.finalize(p)
    return {u["qualified_id"]: u for u in units}, p


class UneceRegulation(unittest.TestCase):
    def test_annex_heading_needs_heading_style(self):
        # v1 bug: a wrapped "...paragraph 3.4. of\nAppendix 2" reset the division
        d = Doc()
        d.L("8.", x=114).L("Conformity", same_row=True).L("8.1.", x=114).L("Text of 8.1", same_row=True)
        d.L("Appendix 2", size=10.0)                      # body-size: a wrapped reference
        d.L("8.2.", x=114).L("More text", same_row=True)
        d.L("Annex B6", size=14.3, bold=True).L("Type 1 test procedure", size=14.3, bold=True)
        d.L("1.", x=114).L("General", same_row=True)
        units, _ = parse("REG154.04", "unece_regulation", d.lines)
        self.assertIn("REG154.04.BODY.8.2", units)
        self.assertNotIn("REG154.04.APPENDIX-2", units)
        self.assertEqual(units["REG154.04.ANNEX-B6"]["title"], "Type 1 test procedure")
        self.assertEqual(units["REG154.04.ANNEX-B6.1"]["parent_id"], "REG154.04.ANNEX-B6")

    def test_numeric_value_is_not_a_clause(self):
        d = Doc()
        d.L("1.", x=114).L("Scope", same_row=True).L("273.15 K (0 °C).", x=114)
        units, _ = parse("REG154.04", "unece_regulation", d.lines)
        self.assertNotIn("REG154.04.BODY.273", units)

    def test_title_vs_body(self):
        d = Doc()
        d.L("5.3.", x=114).L("Reference value of electric energy consumption", same_row=True)
        d.L("5.3.1.", x=114, gap=True).L("The DC electric energy consumption shall be determined according to", same_row=True)
        d.L("step 4 of Table A8/10.")
        units, _ = parse("REG154.04", "unece_regulation", d.lines)
        self.assertEqual(units["REG154.04.BODY.5.3"]["title"], "Reference value of electric energy consumption")
        self.assertFalse(units["REG154.04.BODY.5.3"]["has_body"])
        self.assertIsNone(units["REG154.04.BODY.5.3.1"]["title"])
        self.assertTrue(units["REG154.04.BODY.5.3.1"]["body_text"].startswith("The DC"))

    def test_part_restarts_numbering(self):
        d = Doc()
        d.L("Annex A1 - Appendix 1", size=14.3, bold=True)
        d.L("Part I", x=114).L("1.", x=114).L("Report", same_row=True)
        d.L("Part II", x=114).L("1.", x=114).L("Report again", same_row=True)
        units, p = parse("REG154.04", "unece_regulation", d.lines)
        self.assertIn("REG154.04.ANNEX-A1.APP1.PART-I.1", units)
        self.assertIn("REG154.04.ANNEX-A1.APP1.PART-II.1", units)


class EuOjAct(unittest.TestCase):
    def doc(self):
        d = Doc()
        d.L("REGULATION (EU) 2099/1 OF THE EUROPEAN PARLIAMENT", x=67)
        d.L("Whereas:", x=67)
        d.L("(1)", x=67).L("First recital text.", x=89, same_row=True)
        d.L("(2)", x=67).L("Second recital text.", x=89, same_row=True)
        d.L("HAVE ADOPTED THIS REGULATION:", x=67)
        d.L("CHAPTER I", size=8.5, centered=True).L("SUBJECT MATTER", size=8.5, centered=True)
        d.L("Article 1", italic=True, centered=True).L("Subject matter", italic=True, centered=True)
        d.L("1.", x=67).L("This Regulation establishes rules.", x=89, same_row=True)
        d.L("2.", x=67).L("It also lays down rules", x=89, same_row=True)
        d.L("2032.", x=67)                                   # wrapped year, number-only fragment
        d.L("Article 2", italic=True, centered=True).L("Definitions", italic=True, centered=True)
        d.L("For the purposes of this Regulation:", x=67)
        d.L("(1)", x=67).L("‘engine’ means the internal combustion engine;", x=89, same_row=True)
        d.L("(2) ‘emissions’ means exhaust and non-exhaust emissions;", x=67)
        d.L("1.", x=67).L("Paragraph one of Article 2.", x=89, same_row=True)
        d.L("ANNEX I", size=8.5, italic=True, centered=True).L("LIMITS", size=8.5, centered=True)
        d.L("1.", x=67).L("INTRODUCTION", x=89, same_row=True)
        d.L("Appendix 1", italic=True, centered=True).L("Report", italic=True, centered=True)
        d.L("Text of the appendix.", x=67)
        return d.lines

    def test_structure(self):
        units, p = parse("EUX", "eu_oj_act", self.doc())
        self.assertEqual(units["EUX.RECITAL-2"]["parent_id"], "EUX.PREAMBLE")
        self.assertEqual(units["EUX.ART-1"]["parent_id"], "EUX.CH-I")
        self.assertEqual(units["EUX.ART-1"]["title"], "Subject matter")
        self.assertEqual(units["EUX.CH-I"]["title"], "SUBJECT MATTER")
        self.assertIn("EUX.ANNEX-I.APP-1", units)
        self.assertEqual(units["EUX.ANNEX-I.1"]["title"], "INTRODUCTION")

    def test_article_paragraphs_are_scoped(self):
        # L4.3: "1." restarts in every Article - no collisions, no merges
        units, _ = parse("EUX", "eu_oj_act", self.doc())
        self.assertIn("EUX.ART-1.1", units)
        self.assertIn("EUX.ART-2.1", units)
        self.assertEqual(units["EUX.ART-2.1"]["parent_id"], "EUX.ART-2")

    def test_wrapped_year_is_rejected(self):
        # L4.6: "2032." on its own line after paragraph 2 is not paragraph 2032
        units, p = parse("EUX", "eu_oj_act", self.doc())
        self.assertFalse(any(u.endswith(".2032") for u in units))
        self.assertIn("2032.", units["EUX.ART-1.2"]["body_text"])

    def test_definition_points(self):
        units, _ = parse("EUX", "eu_oj_act", self.doc())
        self.assertIn("EUX.ART-2.PT-1", units)
        self.assertIn("EUX.ART-2.PT-2", units)
        self.assertTrue(units["EUX.ART-2.PT-2"]["body_text"].startswith("‘emissions’"))


class UnGtr(unittest.TestCase):
    def test_rationale_and_text_numbering_do_not_collide(self):
        d = Doc()
        d.L("I.", x=78, size=14, bold=True).L("Statement of technical rationale and justification", x=113, size=14, bold=True, same_row=True)
        d.L("A.", x=88, size=12, bold=True).L("Introduction", x=113, size=12, bold=True, same_row=True)
        d.L("1.", x=113).L("Owing to the pressing need", x=141, same_row=True)
        d.L("II. Text of the GTR", x=85, size=14, bold=True)
        d.L("1.", x=113, size=12).L("Purpose", x=170, size=12, same_row=True)
        d.L("Annex 1", x=57, size=14, bold=True, gap=True).L("Vehicle Survey", x=99, size=14, bold=True)
        d.L("The vehicle survey shall be used.", x=57)
        d.L("1.", x=113).L("Date", same_row=True)
        units, p = parse("GTR22", "un_gtr", d.lines)
        self.assertIn("GTR22.RATIONALE.1", units)
        self.assertEqual(units["GTR22.RATIONALE.1"]["parent_id"], "GTR22.RATIONALE.SEC-A")
        self.assertIn("GTR22.BODY.1", units)
        self.assertEqual(units["GTR22.BODY.1"]["title"], "Purpose")
        self.assertFalse(units["GTR22.RATIONALE"]["normative"])
        # Annex 1 is a form (profile form_titles): its "1." is not parsed as a clause
        self.assertTrue(units["GTR22.ANNEX-1"].get("is_form"))
        self.assertNotIn("GTR22.ANNEX-1.1", units)


class Dedupe(unittest.TestCase):
    def test_merge_is_reported_never_dropped(self):
        a = {"qualified_id": "X.1", "body_text": "a", "title": None, "has_body": True, "labels": ["Section"],
             "page": 1, "page_end": 1}
        b = {**a, "body_text": "b", "page": 2, "page_end": 2}
        out, merges = p2.dedupe([a, b])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["body_text"], "a b")
        self.assertEqual(merges[0]["pages"], [1, 2])


if __name__ == "__main__":
    unittest.main()
