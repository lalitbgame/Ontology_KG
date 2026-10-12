"""End-to-end test: runs the whole pipeline (python -m pipeline.run phases)
against every PDF in Document/ - including any file a developer drops in
there - into a temporary directory, then checks:

  * generic invariants that must hold for ANY input (ids namespaced by
    doc_id, no orphans, no duplicate ids, every edge endpoint exists, every
    resolved reference targets a real node, every equation has a crop);
  * the document's hand-verified expectations, when
    tests/expectations/<doc_id>.yaml exists (counts, parents, titles,
    external documents/provisions, resolution rates ... - plan.md §11).

A PDF without a documents.yaml entry still runs (auto-detected profile)
and gets the invariant checks only.

Runtime is dominated by Reg 154 (668 pages, ~2 min).
"""
import glob
import json
import pickle
import tempfile
import unittest
from pathlib import Path

import networkx as nx

from pipeline import expectations
from pipeline.profile import Registry
from pipeline.run import PHASES, run_document

REPO_ROOT = Path(__file__).resolve().parent.parent
PDFS = sorted(glob.glob(str(REPO_ROOT / "Document" / "*.pdf")))


def jl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


@unittest.skipUnless(PDFS, "no PDF found under Document/")
class PipelineOnEveryProvidedPdf(unittest.TestCase):

    def test_pipeline_end_to_end(self):
        registry = Registry()
        for pdf in PDFS:
            entry = registry.entry_for(pdf)
            with self.subTest(pdf=Path(pdf).name, doc_id=entry["doc_id"]):
                with tempfile.TemporaryDirectory() as tmp:
                    out = Path(tmp) / entry["doc_id"]
                    run_document(Path(pdf), entry, PHASES, out_dir=out)
                    self._invariants(out, entry["doc_id"])
                    exp = expectations.load(entry["doc_id"])
                    if exp is not None:
                        failed = [msg for ok, msg in expectations.check(exp, expectations.facts(out)) if not ok]
                        self.assertEqual(failed, [], f"{entry['doc_id']} expectations failed")

    def _invariants(self, out, doc_id):
        units = jl(out / "units.jsonl")
        self.assertGreater(len(units), 0, "phase2 produced no units")
        ids = [u["qualified_id"] for u in units]
        self.assertEqual(len(ids), len(set(ids)), "duplicate qualified_id")
        idset = set(ids)
        for u in units:
            self.assertTrue(u["qualified_id"].startswith(doc_id + "."), u["qualified_id"])
            self.assertIsInstance(u["has_body"], bool)
            if u["parent_id"] is not None:
                self.assertIn(u["parent_id"], idset, f"orphan: {u['qualified_id']}")

        nodes = jl(out / "nodes.jsonl")
        node_ids = [n["id"] for n in nodes]
        self.assertEqual(len(node_ids), len(set(node_ids)), "duplicate node id")
        node_set = set(node_ids)
        edges = jl(out / "edges.jsonl")
        for e in edges:
            self.assertIn(e["from"], node_set, e)
            self.assertIn(e["to"], node_set, e)

        for r in jl(out / "references.jsonl"):
            self.assertIn(r["status"], ("resolved", "unresolved"))
            self.assertTrue(r["raw_text"].strip())
            if r["status"] == "resolved":
                self.assertIn(r["to"], node_set)
            else:
                self.assertIsNone(r["to"])

        for e in jl(out / "equations.jsonl"):
            self.assertTrue(e["image_path"] and (out / e["image_path"]).exists(), e["id"])
            self.assertTrue(e["id"].startswith(e["unit_id"] + ".EQ-"), e["id"])

        for d in jl(out / "definitions.jsonl"):
            self.assertTrue(d["quoted_term"].strip() and d["gloss"].strip())
            self.assertIn(d["source_clause"], idset)
        for a in jl(out / "abbreviations.jsonl"):
            self.assertTrue(a["surface_form"].strip() and a["expansion"].strip(), a)

        with open(out / "graph.pickle", "rb") as f:
            g = pickle.load(f)
        self.assertEqual(g.number_of_nodes(), len(nodes))
        self.assertEqual(g.number_of_edges(), len(edges))
        g2 = nx.read_graphml(out / "graph.graphml")
        self.assertEqual(g2.number_of_nodes(), len(nodes))
        self.assertEqual(g2.number_of_edges(), len(edges))
        self.assertTrue((out / "kg_explorer.html").exists())
        self.assertTrue((out / "qa_report.md").exists())


if __name__ == "__main__":
    unittest.main()
