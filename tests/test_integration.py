"""End-to-end test: runs the real Phase 1 + Phase 2 pipeline against every
PDF found in Document/ - including any additional file a developer drops in
there - and checks structural invariants that must hold regardless of the
document's actual content.

Not exact-count assertions (those are content-specific, see
output/PHASE1_2_NOTES.md for this project's own numbers) - just the
guarantees the pipeline is supposed to provide for any input: every line
has the expected shape, every clause's parent resolves, every qualified_id
is well-formed, nothing is duplicated.
"""
import glob
import json
import pickle
import re
import tempfile
import unittest
from pathlib import Path

import networkx as nx

from pipeline import phase1_extract as p1
from pipeline import phase2_parse as p2
from pipeline import phase3_terms as p3
from pipeline import phase4_references as p4
from pipeline import phase5_assemble as p5

REPO_ROOT = Path(__file__).resolve().parent.parent
PDFS = sorted(glob.glob(str(REPO_ROOT / "Document" / "*.pdf")))
QUALIFIED_ID_RE = re.compile(r"^REG154\.04\.[A-Za-z0-9.\-]+$")


@unittest.skipUnless(PDFS, "no PDF found under Document/")
class PipelineOnEveryProvidedPdf(unittest.TestCase):
    """One sub-test per file in Document/, via subTest - add a new PDF there
    and this test picks it up automatically, no code changes needed."""

    def test_pipeline_end_to_end(self):
        for pdf_path in PDFS:
            with self.subTest(pdf=Path(pdf_path).name):
                self._check_one(pdf_path)

    def _check_one(self, pdf_path):
        with tempfile.TemporaryDirectory() as tmp:
            pages_path = str(Path(tmp) / "pages.jsonl")
            clauses_path = str(Path(tmp) / "clauses.jsonl")

            p1.run(pdf_path, pages_path)
            with open(pages_path) as f:
                pages = [json.loads(l) for l in f]
            self.assertGreater(len(pages), 0, "phase1 produced no lines")
            for l in pages:
                self.assertIsInstance(l["text"], str)
                self.assertTrue(l["text"].strip())
                self.assertIsInstance(l["is_footnote"], bool)
                self.assertGreaterEqual(l["page"], 0)

            p2.run(pages_path, clauses_path)
            with open(clauses_path) as f:
                clauses = [json.loads(l) for l in f]
            self.assertGreater(len(clauses), 0, "phase2 produced no clauses")

            ids = [c["qualified_id"] for c in clauses]
            self.assertEqual(len(ids), len(set(ids)), "duplicate qualified_id")
            for c in clauses:
                self.assertRegex(c["qualified_id"], QUALIFIED_ID_RE)
                self.assertGreaterEqual(c["depth"], 0)
                self.assertIsInstance(c["has_body"], bool)
                self.assertEqual(c["has_body"], bool(c["body_text"]))
                if c["parent_id"] is not None:
                    self.assertIn(c["parent_id"], ids,
                                  f"orphan: {c['qualified_id']} -> {c['parent_id']}")

            # Phase 3 is UN Reg 154-specific (looks for §2.1/§2.2/§3
            # headings) - on an unrelated PDF it degrades to an empty
            # result rather than crashing, so this stays a safe invariant
            # check for "any file provided by the developer".
            abbr_path = str(Path(tmp) / "abbreviations.jsonl")
            def_path = str(Path(tmp) / "definitions.jsonl")
            p3.run(pages_path, clauses_path, abbr_path, def_path)

            with open(abbr_path) as f:
                for row in (json.loads(l) for l in f):
                    self.assertTrue(row["surface_form"].strip())
                    self.assertTrue(row["expansion"].strip())

            with open(def_path) as f:
                for row in (json.loads(l) for l in f):
                    self.assertTrue(row["quoted_term"].strip())
                    self.assertTrue(row["gloss"].strip())
                    if row["source_clause"] is not None:
                        self.assertIn(row["source_clause"], ids)

            refs_path = str(Path(tmp) / "references.jsonl")
            p4.run(clauses_path, refs_path)
            with open(refs_path) as f:
                for row in (json.loads(l) for l in f):
                    self.assertIn(row["from"], ids)
                    self.assertIn(row["status"], ("resolved", "unresolved"))
                    self.assertTrue(row["raw_text"].strip())
                    if row["status"] == "resolved":
                        self.assertIn(row["to"], ids)
                    else:
                        self.assertIsNone(row["to"])

            nodes_path = str(Path(tmp) / "nodes.jsonl")
            edges_path = str(Path(tmp) / "edges.jsonl")
            graphml_path = str(Path(tmp) / "graph.graphml")
            pickle_path = str(Path(tmp) / "graph.pickle")
            p5.run(clauses_path, abbr_path, def_path, refs_path,
                   nodes_path, edges_path, graphml_path, pickle_path)

            with open(nodes_path) as f:
                nodes = [json.loads(l) for l in f]
            node_ids = [n["id"] for n in nodes]
            self.assertEqual(len(node_ids), len(set(node_ids)), "duplicate node id")
            with open(abbr_path) as f:
                n_abbr = sum(1 for _ in f)
            with open(def_path) as f:
                n_def = sum(1 for _ in f)
            self.assertEqual(len(nodes), len(clauses) + n_abbr + n_def)

            with open(edges_path) as f:
                edges = [json.loads(l) for l in f]
            node_id_set = set(node_ids)
            for e in edges:
                self.assertIn(e["from"], node_id_set)
                self.assertIn(e["to"], node_id_set)

            with open(pickle_path, "rb") as f:
                g = pickle.load(f)
            self.assertEqual(g.number_of_nodes(), len(nodes))
            self.assertEqual(g.number_of_edges(), len(edges))

            g2 = nx.read_graphml(graphml_path)
            self.assertEqual(g2.number_of_nodes(), len(nodes))
            self.assertEqual(g2.number_of_edges(), len(edges))


if __name__ == "__main__":
    unittest.main()
