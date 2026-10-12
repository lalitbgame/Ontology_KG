"""Unit tests for pipeline/phase5_assemble.py - synthetic data, no PDF needed."""
import unittest

from pipeline import phase5_assemble as p5


class Validate(unittest.TestCase):
    def test_bad_edges_are_dropped_and_reported(self):
        nodes = [{"id": "A"}, {"id": "B"}]
        edges = [{"from": "A", "to": "B", "type": "HAS_CHILD"}, {"from": "A", "to": "Z", "type": "REFERENCES"}]
        good, bad, dup = p5.validate(nodes, edges)
        self.assertEqual(len(good), 1)
        self.assertEqual(bad[0]["to"], "Z")
        self.assertEqual(dup, [])

    def test_duplicate_node_ids_are_reported(self):
        _, _, dup = p5.validate([{"id": "A"}, {"id": "A"}], [])
        self.assertEqual(dup, ["A"])


class ToNetworkx(unittest.TestCase):
    def test_parallel_same_type_edges_are_not_collapsed(self):
        # v1 regression: keying edges by type made the second of two
        # REFERENCES between the same clauses overwrite the first
        nodes = [{"id": "A", "type": "Clause"}, {"id": "B", "type": "Clause"}]
        edges = [{"from": "A", "to": "B", "type": "REFERENCES", "raw_text": "paragraph 1."},
                 {"from": "A", "to": "B", "type": "REFERENCES", "raw_text": "paragraph 1. (again)"}]
        self.assertEqual(p5.to_networkx(nodes, edges).number_of_edges(), 2)

    def test_graphml_safe_serialises_lists(self):
        nodes = [{"id": "A", "type": "Equation", "glossary": [{"symbol": "x"}], "lhs": None}]
        g = p5.to_networkx(nodes, [], graphml_safe=True)
        self.assertEqual(g.nodes["A"]["glossary"], '[{"symbol": "x"}]')
        self.assertEqual(g.nodes["A"]["lhs"], "")


class ExternalIds(unittest.TestCase):
    def test_external_nodes_are_namespaced_per_graph(self):
        self.assertEqual(p5.ext_node_id("EU2026-1762", "EXT:UNR-179"), "EU2026-1762/EXT:UNR-179")


if __name__ == "__main__":
    unittest.main()
