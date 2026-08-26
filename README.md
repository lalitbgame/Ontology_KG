# UN Regulation 154 Knowledge Graph

A deterministic (no LLM, no NER, no embeddings) pipeline that turns the UN
Regulation No. 154 (WLTP), 04 series PDF into a queryable knowledge graph:
its clause hierarchy, §2 abbreviations, §3 definitions, and cross-references
between clauses. See `Ontology_KG_Project_Plan.md` for the full design
rationale and `schema.yaml` for the frozen ontology.

**Status:** Phases 0–5 of `task.md` are done, plus an interactive HTML
viewer (a Phase 7 item, built ahead of schedule). Phase 6 (formal QA) and
the rest of Phase 7 (Cypher-style query pack, static subgraph exports)
are not done yet — see [What's not done yet](#whats-not-done-yet).

## What's in the graph

| | Count |
|---|---:|
| Clauses (incl. one root pseudo-node per Division) | 3,737 |
| Abbreviations (§2.1/§2.2) | 116 |
| Definitions (§3.x) | 151 |
| `HAS_CHILD` edges (clause containment) | 3,681 |
| `HAS_ABBREVIATION` / `HAS_DEFINITION` edges | 116 / 151 |
| `REFERENCES` edges (resolved cross-references) | 2,170 of 2,980 detected (73%) |

Only `Clause`, `Abbreviation`, and `Definition` nodes are populated.
`schema.yaml` also defines `Standard`, `Version`, a standalone `Division`,
`ScopeParagraph`, `Area`, `Attributes`, `Constraints`, `Table`, and `Figure`
— none of these have an extraction phase built yet (a `Clause` depth-0
"division root" pseudo-node stands in for `Division` for now). Term
reconciliation (merging a §2 abbreviation with its matching §3 definition,
e.g. `NOVC-FCHV`) and term-usage linking (`MENTIONED_IN`) are deliberately
deferred — see `schema.yaml`'s `term-model-deferral` decision.

## Repo layout

```
schema.yaml                 The frozen ontology: node/edge types, ID scheme, decisions log
task.md                     Phase-by-phase build checklist and status
Ontology_KG_Project_Plan.md Original design doc (source-document findings, rationale)
Document/                   Source PDF (154-04 without 1C 1.pdf)

pipeline/                   One script per phase, run in order
  phase1_extract.py           PDF -> pages.jsonl (layout-aware text extraction)
  phase2_parse.py             pages.jsonl -> clauses.jsonl (hierarchical parser)
  phase3_terms.py             -> abbreviations.jsonl, definitions.jsonl
  phase4_references.py        clauses.jsonl -> references.jsonl (cross-ref resolution)
  phase5_assemble.py          -> nodes.jsonl, edges.jsonl, graph.pickle, graph.graphml
  build_viz_data.py           -> viz_data.json (feeds kg_explorer.html; not a numbered phase)

output/                     Every generated artifact (see below), plus:
  PHASE1_2_NOTES.md            Implementation notes: bugs found & fixed, known limitations
  kg_explorer.html             Self-contained interactive graph viewer — open in a browser

tests/                      unittest suite: per-phase unit tests + one real-PDF integration test
```

## Setup

Requires Python 3.11+ (developed/tested on 3.14).

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

That's the only setup — no database, no Docker, no API keys. The graph
store is NetworkX/JSON, not Neo4j (see `schema.yaml`'s
`graph-store-choice` decision), so there's no server to stand up.

## Running the pipeline end-to-end

Run from the repo root, in order — each phase reads the previous one's
output from `output/`:

```bash
.venv/bin/python pipeline/phase1_extract.py
.venv/bin/python pipeline/phase2_parse.py
.venv/bin/python -m pipeline.phase3_terms      # note: -m, not a direct path (imports phase2_parse)
.venv/bin/python pipeline/phase4_references.py
.venv/bin/python pipeline/phase5_assemble.py
.venv/bin/python pipeline/build_viz_data.py
```

Each script prints a one-line summary (counts, resolution rates, warnings)
to stderr as it runs. Total run time is under a minute on the full 668-page
PDF. Every script also accepts explicit input/output paths as positional
arguments if you want to point it at a different file — see each script's
`run()` signature.

To point the whole pipeline at a different PDF, drop it in `Document/` and
pass its path to `phase1_extract.py`; `tests/test_integration.py` will also
pick it up automatically (see [Tests](#tests)).

## Exploring the output

**Easiest: open `output/kg_explorer.html` in a browser.** No server, no
build step — it's a single self-contained file with the graph data
embedded. Search for a clause, abbreviation, or definition, or browse the
tree (grouped the way the source document's own table of contents is:
Regulation Body, Appendices to the Regulation, Annexes Parts A/B/C). Select
any node to see its full text, metadata, containment, and resolved
references in both directions, plus a small local-neighborhood diagram.

**The raw data**, if you want to script against it — every `output/*.jsonl`
file is one JSON object per line:

```python
import json
clauses = [json.loads(l) for l in open("output/clauses.jsonl")]
```

**The graph object**, for NetworkX-based analysis:

```python
import pickle
g = pickle.load(open("output/graph.pickle", "rb"))
g.number_of_nodes(), g.number_of_edges()
g.nodes["REG154.04.BODY.3.3.20.1"]                 # node properties
list(g.out_edges("REG154.04.BODY.2.1", data=True))  # e.g. HAS_ABBREVIATION targets
```

`output/graph.graphml` opens the same graph in Gephi or any GraphML-
compatible tool.

## Tests

```bash
.venv/bin/python -m unittest discover -s tests -t .
```

51 tests: fast unit tests per phase on synthetic data, plus one integration
test that runs the real pipeline end-to-end against every PDF found in
`Document/` and checks invariants that must hold for any input (no orphan
clauses, no duplicate IDs, every reference either resolves to a real node
or is honestly marked unresolved, etc.). Several real bugs were found and
fixed this way — see `output/PHASE1_2_NOTES.md` for the specifics, which
is also a reasonable place to start if you're picking this project back up
after a break.

## What's not done yet

- **Phase 6 (formal QA)** hasn't run: structural-completeness sampling,
  full review of the 220 logged numbering-irregularity warnings, tracked-
  changes spot-checking (N/A — see below), and term/reference-precision
  sampling are all still open. `output/PHASE1_2_NOTES.md` has informal
  findings from building Phases 1–5, but nothing at Phase 6's rigor yet.
- **Query pack and static subgraph exports** (rest of Phase 7) — not
  written. `kg_explorer.html` covers interactive exploration instead of a
  Neo4j Browser/Bloom setup, since there's no Neo4j in this project.
- **Tracked-changes tagging** was investigated and found not applicable —
  this particular PDF carries no detectable insertion/deletion markup (see
  `output/PHASE1_2_NOTES.md`'s Phase 0 spike write-up). Every clause is
  `status: "active"`.
- **Table/Figure nodes** are never populated, so every `Table`/`Figure`
  cross-reference is honestly unresolved (0% by design, not a bug — see
  the reference-resolution breakdown in `output/PHASE1_2_NOTES.md`).
- **One open decision**: whether to ingest the prior 03-series text of
  Reg. 154 to exercise `Version`/`SUPERSEDES` — still unresolved, see
  `schema.yaml`'s `open_decisions`.
