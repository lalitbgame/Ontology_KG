"""Unit tests for pipeline/phase4_references.py - synthetic units."""
import unittest

from pipeline import phase4_references as p4


def U(qid, unit_type="Clause", parent=None, label=None, number=None, body="", level=None):
    return {"qualified_id": qid, "unit_type": unit_type, "parent_id": parent, "local_label": label,
            "local_number": number, "level": level or ("decimal" if number else unit_type.lower()),
            "body_text": body, "title": None}


def resolve(units, masks=None, tables=(), equations=()):
    idx = p4.Index("D", units, list(tables), [], list(equations), {})
    refs = p4.extract(idx, units, masks or {})
    return [(r["raw_text"], r["to"]) for r in refs]


class Eu(unittest.TestCase):
    def units(self, body):
        return [U("D.BODY", "Body"), U("D.ART-4", "Article", "D.BODY", "4"),
                U("D.ART-4.2", "ArticleParagraph", "D.ART-4", "2"),
                U("D.ART-5", "Article", "D.BODY", "5"),
                U("D.ART-5.1", "ArticleParagraph", "D.ART-5", "1", body=body),
                U("D.ART-5.2", "ArticleParagraph", "D.ART-5", "2"),
                U("D.ANNEX-IV", "Annex", None, "IV"),
                U("D.ANNEX-II", "Annex", None, "II"), U("D.ANNEX-II.APP-2", "Appendix", "D.ANNEX-II", "2")]

    def test_article_with_paragraph(self):
        self.assertIn(("Article 4(2)", "D.ART-4.2"), resolve(self.units("as set out in Article 4(2), the")))

    def test_roman_annex_list(self):
        r = resolve(self.units("set out in Annexes II and IV"))
        self.assertIn(("Annex II", "D.ANNEX-II"), r)
        self.assertIn(("Annex IV", "D.ANNEX-IV"), r)

    def test_appendix_to_annex(self):
        self.assertIn(("Appendix 2 to Annex II", "D.ANNEX-II.APP-2"),
                      resolve(self.units("the model set out in Appendix 2 to Annex II to this Regulation")))

    def test_paragraph_inside_an_article_means_that_article(self):
        self.assertIn(("paragraph 2", "D.ART-5.2"), resolve(self.units("referred to in paragraph 2, the")))

    def test_masked_external_span_is_not_resolved(self):
        body = "in accordance with Annex IV to Implementing Regulation (EU) 2020/683"
        masks = {"D.ART-5.1": [(19, 70, "EXT:EU.REG.2020-683")]}
        self.assertEqual(resolve(self.units(body), masks), [])


class Unece(unittest.TestCase):
    def units(self, body):
        return [U("D.BODY", "Body"), U("D.BODY.3", parent="D.BODY", number="3"),
                U("D.BODY.3.2", parent="D.BODY.3", number="3.2"),
                U("D.BODY.6", parent="D.BODY", number="6"),
                U("D.ANNEX-B6", "Annex", None, "B6"), U("D.ANNEX-B6.1", parent="D.ANNEX-B6", number="1"),
                U("D.ANNEX-B6.2", parent="D.ANNEX-B6", number="2", body=body),
                U("D.ANNEX-B6.APP1", "Appendix", None, "1"), U("D.APPENDIX-1", "Appendix", None, "1"),
                U("D.ANNEX-B8", "Annex", None, "B8"), U("D.ANNEX-B8.APP2", "Appendix", None, "2"),
                U("D.ANNEX-B8.APP2.3", parent="D.ANNEX-B8.APP2", number="3")]

    def test_default_scope_is_own_division(self):
        self.assertIn(("paragraph 1.", "D.ANNEX-B6.1"), resolve(self.units("as in paragraph 1. above")))

    def test_of_this_regulation(self):
        self.assertIn(("paragraph 3.2.", "D.BODY.3.2"), resolve(self.units("see paragraph 3.2. of this Regulation")))

    def test_of_appendix_to_annex(self):
        self.assertIn(("paragraph 3.", "D.ANNEX-B8.APP2.3"),
                      resolve(self.units("according to paragraph 3. of Appendix 2 to Annex B8")))

    def test_bare_appendix_inside_annex_is_that_annexs_appendix(self):
        self.assertIn(("Appendix 1", "D.ANNEX-B6.APP1"), resolve(self.units("as described in Appendix 1")))

    def test_missing_target_is_unresolved_never_guessed(self):
        self.assertIn(("paragraph 9.9.", None), resolve(self.units("see paragraph 9.9. of this Regulation")))

    def test_table_in_same_division(self):
        tables = [{"id": "D.ANNEX-B6.TABLE-A6/1", "caption_id": "Table A6/1", "defining_unit": "D.ANNEX-B6.1"}]
        self.assertIn(("Table A6/1", "D.ANNEX-B6.TABLE-A6/1"), resolve(self.units("listed in Table A6/1"), tables=tables))

    def test_equation_in_paragraph(self):
        eqs = [{"id": "D.BODY.3.2.EQ-1", "unit_id": "D.BODY.3.2"}]
        r = resolve(self.units("using the equation in paragraph 3.2. of this Regulation"), equations=eqs)
        self.assertIn(("equation in paragraph 3.2.", "D.BODY.3.2.EQ-1"), r)


class Ranges(unittest.TestCase):
    def test_range_expands_over_existing_siblings(self):
        ids, is_range = p4.expand_paragraph_ids("32. to 35.")
        self.assertTrue(is_range)
        self.assertEqual(ids, ["32", "33", "34", "35"])


if __name__ == "__main__":
    unittest.main()
