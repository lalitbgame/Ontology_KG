"""Unit tests for pipeline/phase5_assemble.py - synthetic data, no PDF needed."""
import unittest

from pipeline import phase5_assemble as p5


def clause(qid, parent_id=None, division="BODY"):
    return {"qualified_id": qid, "type": "Clause", "division": division,
            "depth": qid.count("."), "parent_id": parent_id, "local_number": None,
            "page": 1, "body_text": "x", "footnote_text": None, "has_body": True,
            "labels": ["Section"]}


class BuildNodes(unittest.TestCase):
    def test_ids_and_types(self):
        clauses = [clause("REG154.04.BODY.1")]
        abbrs = [{"surface_form": "AC", "expansion": "Alternating current",
                  "category": "General", "source_clause": "REG154.04.BODY.2.1"}]
        defs = [{"quoted_term": "Scope", "gloss": "x", "abbreviation": None,
                 "source_clause": "REG154.04.BODY.3.1"}]
        nodes = p5.build_nodes(clauses, abbrs, defs)
        ids = {n["id"]: n["type"] for n in nodes}
        self.assertEqual(ids["REG154.04.BODY.1"], "Clause")
        self.assertEqual(ids["ABBR:AC"], "Abbreviation")
        self.assertEqual(ids["DEF:REG154.04.BODY.3.1"], "Definition")


class BuildEdges(unittest.TestCase):
    def test_has_child_from_parent_id(self):
        clauses = [clause("REG154.04.BODY.1"), clause("REG154.04.BODY.1.1", "REG154.04.BODY.1")]
        edges = p5.build_edges(clauses, [], [], [])
        self.assertEqual(edges, [{"from": "REG154.04.BODY.1", "to": "REG154.04.BODY.1.1",
                                  "type": "HAS_CHILD"}])

    def test_unresolved_references_are_excluded(self):
        refs = [{"from": "A", "to": "B", "status": "resolved", "raw_text": "x"},
                {"from": "A", "to": None, "status": "unresolved", "raw_text": "y"}]
        edges = p5.build_edges([], [], [], refs)
        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0]["to"], "B")


class Validate(unittest.TestCase):
    def test_drops_edges_with_a_missing_endpoint(self):
        nodes = [{"id": "A"}, {"id": "B"}]
        edges = [{"from": "A", "to": "B", "type": "X"}, {"from": "A", "to": "MISSING", "type": "X"}]
        good, bad = p5.validate(nodes, edges)
        self.assertEqual(len(good), 1)
        self.assertEqual(len(bad), 1)


class ToNetworkx(unittest.TestCase):
    def test_parallel_same_type_edges_are_not_collapsed(self):
        nodes = [{"id": "A"}, {"id": "B"}]
        edges = [{"from": "A", "to": "B", "type": "REFERENCES", "raw_text": "first"},
                 {"from": "A", "to": "B", "type": "REFERENCES", "raw_text": "second"}]
        g = p5.to_networkx(nodes, edges)
        self.assertEqual(g.number_of_edges(), 2)

    def test_graphml_safe_flattens_none_and_lists(self):
        nodes = [{"id": "A", "footnote_text": None, "labels": ["Section", "Paragraph"]}]
        g = p5.to_networkx(nodes, [], graphml_safe=True)
        self.assertEqual(g.nodes["A"]["footnote_text"], "")
        self.assertEqual(g.nodes["A"]["labels"], "Section|Paragraph")


if __name__ == "__main__":
    unittest.main()
