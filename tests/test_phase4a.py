"""Unit tests for pipeline/phase4a_external.py (plan §9a.5) - no PDF needed."""
import unittest

from pipeline import phase4a_external as ex


def scan(text, self_ids=(), unit="D.U1"):
    col = ex.Collector("D", set(self_ids), {})
    ex.scan_text(col, unit, text, None)
    return col


def ids(col):
    return set(col.docs)


def provisions(col):
    return set(col.provisions)


class Grammar(unittest.TestCase):
    def test_kinds_and_canonical_ids(self):
        col = scan("as defined in Regulation (EU) 2018/858, Directive 2007/46/EC, UN Regulation No. 83, "
                   "UN GTR No. 15, ISO 8178-1:2020, SAE J1711, the Treaty on the Functioning of the European Union "
                   "and document ECE/TRANS/WP.29/AC.3/57.")
        self.assertTrue({"EXT:EU.REG.2018-858", "EXT:EC.DIR.2007-46", "EXT:UNR-83", "EXT:UNGTR-15",
                         "EXT:ISO.8178-1", "EXT:SAE.J1711", "EXT:TFEU", "EXT:ECE.TRANS.WP29.AC.3.57"} <= ids(col), ids(col))

    def test_gtr_aliases_collapse(self):
        col = scan("GTR15 Annex 8; UN GTR No.15; Global Technical Regulation No 15.")
        self.assertEqual(ids(col), {"EXT:UNGTR-15"})
        self.assertEqual(col.docs["EXT:UNGTR-15"]["mention_count"], 3)

    def test_gtr_paragraph_number_is_not_a_citation(self):
        # "F. Future development of the GTR 57. The mandate..." (GTR 22)
        self.assertEqual(ids(scan("Future development of the GTR 57. The mandate for development")), set())

    def test_global_technical_regulation_is_not_un_regulation(self):
        self.assertEqual(ids(scan("United Nations Global Technical Regulation No. 22")), {"EXT:UNGTR-22"})

    def test_shared_head_list(self):
        col = scan("repealing Regulations (EC) No 715/2007 and (EC) No 595/2009 of the European Parliament")
        self.assertEqual(ids(col), {"EXT:EC.REG.715-2007", "EXT:EC.REG.595-2009"})
        col = scan("arising from UN Regulations No 83 and No 179.")
        self.assertEqual(ids(col), {"EXT:UNR-83", "EXT:UNR-179"})

    def test_self_citation_is_filtered(self):
        col = scan("a new 04 series of amendments to UN Regulation No. 154", self_ids={"EXT:UNR-154"})
        self.assertEqual(ids(col), set())
        self.assertEqual(col.self_hits, 1)


class Pinpoints(unittest.TestCase):
    def test_paragraph_of_annex_of_regulation(self):
        col = scan("according to paragraph 3.1.2. of Annex 5 of UN Regulation No. 83.")
        self.assertIn("EXT:UNR-83#ANNEX-5.3.1.2", provisions(col))

    def test_article_point(self):
        col = scan("as defined in Article 3, point 49, of Regulation (EU) 2018/858 and")
        self.assertIn("EXT:EU.REG.2018-858#ART-3.PT-49", provisions(col))

    def test_paragraph_list_without_trailing_dot(self):
        col = scan("shall also comply with paragraphs 9.1 and 9.4 of UN Regulation No 179.")
        self.assertTrue({"EXT:UNR-179#9.1", "EXT:UNR-179#9.4"} <= provisions(col))

    def test_article_list_with_paragraphs(self):
        col = scan("in accordance with Articles 7(1) and 10(1) of Regulation (EU) 2024/1257, manufacturers")
        self.assertTrue({"EXT:EU.REG.2024-1257#ART-7.1", "EXT:EU.REG.2024-1257#ART-10.1"} <= provisions(col))

    def test_right_hand_chain(self):
        col = scan("UBE value shall be determined according to GTR15 Annex 8, Table A8/11 Step no. 1.")
        self.assertIn("EXT:UNGTR-15#ANNEX-8.TABLE-A8/11.STEP-1", provisions(col))

    def test_connector_words_are_never_ids(self):
        col = scan("as defined in Article 3, point 49, of Regulation (EU) 2018/858")
        self.assertFalse(any("PT-of" in p for p in provisions(col)))


class BackReferences(unittest.TestCase):
    def test_thereto(self):
        col = scan("under Article 14(1) of Regulation (EU) 2024/1257 and Table 11 of Annex V thereto, drawn up")
        self.assertIn("EXT:EU.REG.2024-1257#ANNEX-V.TABLE-11", provisions(col))

    def test_having_regard_binds_to_governing_act(self):
        text = ("Having regard to Regulation (EU) 2024/1257 of the European Parliament, repealing Commission "
                "Implementing Regulation (EU) 2022/1362, and in particular Articles 14(3), point (i), and 14(4), "
                "points (a) and (q), thereof,")
        col = scan(text)
        self.assertTrue({"EXT:EU.REG.2024-1257#ART-14.3.PT-i", "EXT:EU.REG.2024-1257#ART-14.4.PT-a",
                         "EXT:EU.REG.2024-1257#ART-14.4.PT-q"} <= provisions(col), provisions(col))
        self.assertFalse(any(p.startswith("EXT:EU.REG.2022-1362#") for p in provisions(col)))

    def test_plain_prose_thereof_is_ignored(self):
        col = scan("oxidation catalyst or combinations thereof in a single unit")
        self.assertEqual(col.citations, [])


class Roles(unittest.TestCase):
    def test_requirement_source(self):
        col = scan("manufacturers shall comply with the requirements laid down in paragraph 10 of UN Regulation No 179.")
        self.assertEqual(col.citations[0]["role"], "requirement_source")

    def test_neighbouring_citation_does_not_leak_cues(self):
        # "Implementing" belongs to the NEXT citation's name, not a cue for this one
        col = scan("Commission Regulation (EU) 2017/2400 and Commission Implementing Regulation (EU) 2022/1362")
        roles = {c["external_doc"]: c["role"] for c in col.citations}
        self.assertEqual(roles["EXT:EU.REG.2017-2400"], "cites")


class FootnoteMeta(unittest.TestCase):
    def test_oj_footnote(self):
        m = ex.footnote_meta("Regulation (EU) 2018/858 of the European Parliament and of the Council of 30 May 2018 on "
                             "the approval of motor vehicles (OJ L 151, 14.6.2018, p. 1, ELI: http:// "
                             "data.europa.eu/eli/reg/2018/858/oj).")
        self.assertEqual(m["adoption_date"], "30 May 2018")
        self.assertEqual(m["oj_ref"], "OJ L 151, 14.6.2018, p. 1")
        self.assertEqual(m["eli"], "http://data.europa.eu/eli/reg/2018/858/oj")
        self.assertTrue(m["title"].startswith("Regulation (EU) 2018/858"))

    def test_un_title(self):
        m = ex.footnote_meta("UN Regulation No 179 – Uniform provisions concerning the approval of light duty "
                             "vehicles with regards to brake emissions [2026/1044] (OJ L, 2026/1044, 18.5.2026).")
        self.assertTrue(m["title"].startswith("Uniform provisions concerning"))


class Mask(unittest.TestCase):
    def test_mask_covers_chain_and_citation(self):
        text = "according to Annex 4 to UN Regulation No 49 and paragraph 3.2. of this Regulation"
        col = scan(text)
        (s, e, ext), = col.masks["D.U1"]
        self.assertEqual(text[s:e], "Annex 4 to UN Regulation No 49")
        self.assertEqual(ext, "EXT:UNR-49")


if __name__ == "__main__":
    unittest.main()
