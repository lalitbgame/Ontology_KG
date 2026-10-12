"""Unit tests for pipeline/phase3b_equations.py - synthetic span layouts
modelled on real equations (GTR 22 §6.3.2/§6.3.3, Annex 3)."""
import unittest

from pipeline import phase3b_equations as eq


def it(t, x0, x1, base, size=10.0):
    return {"kind": "text", "t": eq.norm(t).strip(), "raw": t, "x0": x0, "x1": x1,
            "y0": base - 0.8 * size, "y1": base + 0.2 * size, "base": base, "size": size}


def build(items, rules=()):
    return eq.build_equation({}, items, list(rules), None)


class Reconstruct(unittest.TestCase):
    def test_fraction_and_subscripts(self):
        # SOCE_measured = UBE_measured / UBE_certified * 100   (GTR 22 6.3.2)
        items = [it("𝑆𝑂𝐶𝐸", 192, 216, 692.7), it("𝑚𝑒𝑎𝑠𝑢𝑟𝑒𝑑", 215.7, 250, 694.8, 7.0), it("= ", 254, 264, 692.7),
                 it("𝑈𝐵𝐸", 264, 283.6, 685.1), it("𝑚𝑒𝑎𝑠𝑢𝑟𝑒𝑑", 283.1, 317.7, 687.1, 7.0),
                 it("𝑈𝐵𝐸", 265.6, 285.2, 699.5), it("𝑐𝑒𝑟𝑡𝑖𝑓𝑖𝑒𝑑", 284.7, 316.1, 701.5, 7.0),
                 it("∗100", 323, 346.5, 692.7)]
        e = build(items, [[264.0, 689.6, 320.7]])
        self.assertEqual(e["linear"], "SOCE_measured=(UBE_measured)/(UBE_certified)*100")
        self.assertEqual(e["latex"], r"SOCE_{measured}=\frac{UBE_{measured}}{UBE_{certified}} \cdot 100")
        self.assertEqual(e["lhs"], "SOCE_measured")
        self.assertEqual(e["kind"], "equation")
        self.assertEqual(e["parse_status"], "parsed")
        self.assertIn("UBE_certified", e["symbols"])

    def test_sum_with_limits(self):
        # UBE_measured,nc = sum_{i=1}^{n} dE_REESS,i   (GTR 22 Annex 3)
        items = [it("UBEmeasured,nc = ", 200, 280, 300), it("∑∆E", 282, 300, 300), it("REESS,i", 300, 330, 302, 7.0),
                 it("n", 284, 289, 290, 7.0), it("i=1", 283, 296, 311, 7.0)]
        e = build(items)
        self.assertIn("sum_{i=1}^{n}", e["linear"])
        self.assertIn(r"\sum_{i=1}^{n}", e["latex"])

    def test_radical_over_a_fraction(self):
        # s = sqrt( (x1 - X)^2 / (N-1) )   (GTR 22 6.3.3)
        items = [it("s= ", 170, 188, 457.6), it("√(x", 188, 205, 456.1), it("1", 204.6, 208.7, 452.0, 7.0),
                 it(" -X)", 208.7, 230, 449.9), it("2", 230, 234, 446.9, 7.0), it("N-1", 289, 314, 464.3)]
        rules = [[195.6, 454.8, 408.0], [195.6, 436.6, 408.0]]
        e = build(items, rules)
        self.assertTrue(e["latex"].startswith(r"s=\sqrt{\frac{"), e["latex"])
        self.assertTrue(e["linear"].startswith("s=sqrt(("), e["linear"])

    def test_decision_rule(self):
        items = [it("Pass the family if ", 198, 270, 515.7), it("𝑋", 270.7, 277, 515.7), it("𝑡𝑒𝑠𝑡𝑠", 276.7, 293, 517.8, 7.0),
                 it("≤𝐴−𝑠", 296.7, 333.8, 515.7)]
        e = build(items)
        self.assertEqual(e["kind"], "decision_rule")
        self.assertEqual(e["outcome"], "pass")
        self.assertTrue(e["linear"].startswith("X_tests<="), e["linear"])


class Glossary(unittest.TestCase):
    def _l(self, text, x, base):
        return {"text": text, "x0": x, "x1": x + 6 * len(text), "base": base}

    def test_two_column_glossary_with_units(self):
        lines = [self._l("where:", 227, 342), self._l("∆E_REESS,i", 227, 356.6),
                 self._l("is the measured electric energy change of battery i, Wh;", 312, 356.6),
                 self._l("i", 227, 372.4), self._l("is the index number of the considered battery;", 312, 372.4),
                 self._l("n", 227, 387.4), self._l("is the total number of batteries;", 312, 387.4)]
        g = eq.parse_glossary(lines, 227)
        self.assertEqual([x["symbol"] for x in g], ["Delta_E_REESS,i", "i", "n"])
        self.assertEqual(g[0]["unit"], "Wh")
        self.assertEqual(g[1]["description"], "the index number of the considered battery")

    def test_wrapped_description_is_not_a_new_entry(self):
        lines = [self._l("Where:", 170, 100), self._l("UBE_measured,nc is the non-corrected usable battery energy of the", 170, 112),
                 self._l("charge-depleting test, Wh;", 170, 124)]
        g = eq.parse_glossary(lines, 170)
        self.assertEqual(len(g), 1)
        self.assertEqual(g[0]["unit"], "Wh")


class SymbolKey(unittest.TestCase):
    def test_variants_collapse(self):
        self.assertEqual(eq.symbol_key("SOC_{read,i}"), "SOC_read,i")
        self.assertEqual(eq.symbol_key("ΔE_{REESS,i}"), "Delta_E_REESS,i")


if __name__ == "__main__":
    unittest.main()
