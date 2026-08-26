"""Unit tests for pipeline/phase4_references.py - synthetic data, no PDF needed."""
import unittest

from pipeline import phase4_references as p4


def clause(qualified_id, division, body_text):
    return {"qualified_id": qualified_id, "division": division, "body_text": body_text}


class AnnexBase(unittest.TestCase):
    def test_extracts_the_annex_code(self):
        self.assertEqual(p4.annex_base("ANNEX-B6.APP1"), "B6")
        self.assertEqual(p4.annex_base("ANNEX-B6"), "B6")
        self.assertIsNone(p4.annex_base("BODY"))
        self.assertIsNone(p4.annex_base("APPENDIX-5"))


class ResolveAppendix(unittest.TestCase):
    def test_explicit_to_annex_wins(self):
        self.assertEqual(p4.resolve_appendix("BODY", "4", "B8"), "ANNEX-B8.APP4")

    def test_bare_appendix_inside_an_annex_means_that_annexs_own_appendix(self):
        self.assertEqual(p4.resolve_appendix("ANNEX-B6", "1", None), "ANNEX-B6.APP1")
        self.assertEqual(p4.resolve_appendix("ANNEX-B6.APP2", "1", None), "ANNEX-B6.APP1")

    def test_bare_appendix_outside_any_annex_means_appendix_to_the_regulation(self):
        self.assertEqual(p4.resolve_appendix("BODY", "5", None), "APPENDIX-5")
        self.assertEqual(p4.resolve_appendix("APPENDIX-2", "5", None), "APPENDIX-5")


class ResolveParagraphScope(unittest.TestCase):
    def test_of_this_regulation_overrides_to_body(self):
        self.assertEqual(p4.resolve_paragraph_scope("ANNEX-B1", " of this Regulation."), "BODY")

    def test_of_named_annex_overrides(self):
        self.assertEqual(p4.resolve_paragraph_scope("BODY", " of Annex B6;"), "ANNEX-B6")

    def test_of_appendix_to_annex_overrides(self):
        self.assertEqual(p4.resolve_paragraph_scope("BODY", " of Appendix 4 to Annex B8."), "ANNEX-B8.APP4")

    def test_no_cue_defaults_to_referencing_clauses_own_division(self):
        self.assertEqual(p4.resolve_paragraph_scope("ANNEX-B6", " and some other text."), "ANNEX-B6")


class ExtractReferences(unittest.TestCase):
    def test_resolved_paragraph_reference(self):
        clauses = [
            clause("REG154.04.BODY.6.1", "BODY", 'see paragraph 6.2. for details.'),
            clause("REG154.04.BODY.6.2", "BODY", 'Target clause.'),
        ]
        refs = p4.extract_references(clauses)
        para_refs = [r for r in refs if r["raw_text"].startswith("paragraph")]
        self.assertEqual(len(para_refs), 1)
        self.assertEqual(para_refs[0]["status"], "resolved")
        self.assertEqual(para_refs[0]["to"], "REG154.04.BODY.6.2")

    def test_unresolved_reference_keeps_raw_text_and_null_target(self):
        clauses = [clause("REG154.04.BODY.6.1", "BODY", 'see paragraph 9.9.9. for details.')]
        refs = p4.extract_references(clauses)
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0]["status"], "unresolved")
        self.assertIsNone(refs[0]["to"])
        self.assertEqual(refs[0]["raw_text"], "paragraph 9.9.9.")

    def test_table_and_figure_references_are_always_unresolved(self):
        clauses = [clause("REG154.04.BODY.6.1", "BODY",
                           'see Table A1/1 and Figure 1 for details.')]
        refs = p4.extract_references(clauses)
        self.assertEqual(len(refs), 2)
        self.assertTrue(all(r["status"] == "unresolved" and r["to"] is None for r in refs))

    def test_table_reference_stops_at_punctuation_not_swept_into_next_word(self):
        clauses = [clause("REG154.04.BODY.6.1", "BODY", 'see Table 1B) for the limits.')]
        refs = p4.extract_references(clauses)
        self.assertEqual(refs[0]["raw_text"], "Table 1B")

    def test_bare_annex_mention_resolves_to_its_division_root(self):
        clauses = [
            clause("REG154.04.BODY.6.1", "BODY", 'as specified in Annex B6.'),
            clause("REG154.04.ANNEX-B6", "ANNEX-B6", ""),
        ]
        refs = p4.extract_references(clauses)
        annex_refs = [r for r in refs if r["raw_text"].startswith("Annex")]
        self.assertEqual(annex_refs[0]["to"], "REG154.04.ANNEX-B6")

    def test_empty_body_text_is_skipped(self):
        clauses = [clause("REG154.04.BODY.6.1", "BODY", "")]
        self.assertEqual(p4.extract_references(clauses), [])


if __name__ == "__main__":
    unittest.main()
