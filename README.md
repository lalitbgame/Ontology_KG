# Regulation Knowledge Graphs

A deterministic (no LLM, no NER, no embeddings) pipeline that turns
regulatory PDFs into **one queryable knowledge graph per document**:
the document's structure (parts, chapters, articles, annexes, appendices,
numbered clauses, recitals), its definitions and abbreviations, footnotes,
tables and figures, **equations and their variables**, every resolved
internal cross-reference, and **every external document and provision it
cites** (other regulations, directives, GTRs, ISO/EN/SAE standards …).

Document-specific grammar lives in **profiles** (`pipeline/profiles/*.yaml`),
not in the code, so a new document family is a new profile rather than new
parsing code. Graphs are never merged across documents (see
`plan.md` and `schema.yaml`).

## The corpus today

| doc_id | Document | Pages | Units | Defs / abbr | Equations | Tables | Internal refs resolved | External docs (provisions) |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| `REG154.04` | UN Regulation No. 154 (WLTP), 04 series (GRPE draft) | 668 | 3,756 | 184 / 185 | 535 | 358 (90 captioned) | 2,802 / 2,992 (94%) | 95 (7) |
| `GTR22` | UN GTR No. 22, in-vehicle battery durability | 32 | 146 | 23 / 36 | 19 | 21 (3 captioned) | 30 / 31 (97%) | 7 (19) |
| `EU2024-1257` | Regulation (EU) 2024/1257 (Euro 7) | 49 | 244 | 77 / 38 | 0 | 33 (32 captioned) | 166 / 175 (95%) | 63 (21) |
| `EU2026-1762` | Commission Implementing Regulation (EU) 2026/1762 (brake particles) | 17 | 61 | 0 / 1 | 0 | 2 | 22 / 23 (96%) | 18 (46) |

Every document passes all its invariants and its hand-verified expectations
(`tests/expectations/<doc_id>.yaml`); details per document in
`output/<doc_id>/qa_report.md`. What the v1 (Reg 154-only) pipeline could
not do is listed in `limitation.md`; the plan that fixed it is `plan.md`.

## Pipeline

```
documents.yaml + pipeline/profiles/*.yaml     Phase 0: registry, profile, manifest
phase1_extract.py     PDF -> lines.jsonl          span-level layout, headers/footers, footnotes, sub/superscripts
phase1b_regions.py    -> regions.jsonl            TOC, tables, figures, equations, "where:" glossaries
phase2_parse.py       -> units.jsonl              profile-driven structure (stack machine), forms, footnote nodes
phase3_terms.py       -> definitions/abbreviations
phase3b_equations.py  -> equations.jsonl, variables.jsonl, equations/*.png
phase3c_tables.py     -> tables.jsonl, figures.jsonl
phase4a_external.py   -> external_docs/provisions, citations.jsonl, external_citations.csv
phase4_references.py  -> references.jsonl         internal cross-references (never guessed)
phase5_assemble.py    -> nodes.jsonl, edges.jsonl, graph.graphml, graph.pickle
phase6_qa.py          -> qa_report.md
build_viz_data.py     -> viz_data.json, kg_explorer.html (+ output/index.html)
```

**Equations** are rebuilt from span geometry: thin vector rules become
fraction bars or radical overlines, stacked small spans become sum/integral
limits, smaller shifted spans become sub/superscripts. Each equation gets a
`linear` form (`SOCE_measured=(UBE_measured)/(UBE_certified)*100`), best-effort
LaTeX, a sympy `parse_status`, its "where:" glossary as Variables with
descriptions and units, `DEPENDS_ON` links to the equations defining its
inputs, and always a PNG crop of the PDF to compare against. Inequalities
in pass/fail rules become `decision_rule`s with an outcome.

**External citations** are recognised for every kind of document, collapsed to
canonical ids (`GTR15` = `UN GTR No.15` = `EXT:UNGTR-15`), with the cited
article/paragraph/annex/table parsed into an `ExternalProvision`
(`EXT:EU.REG.2018-858#ART-3.PT-49`), `thereof`/`thereto` resolved, footnote
metadata (title, date, OJ reference, ELI) attached, and a role on every
citation (`requirement_source`, `definition_source`, `amends`, `repeals`,
`implements`, `legal_basis` …). A document's citations of itself are not
external. `output/<doc_id>/external_citations.csv` is the list of outside
texts a document's requirements depend on.

## Repo layout

```
documents.yaml              Registry: PDF -> doc_id, profile, self_ids, metadata
schema.yaml                 Ontology v0.2: id scheme, node/edge types, decisions
plan.md / limitation.md     The generalization plan and the v1 limitations it addresses
task.md                     Build log (v1 phases, v2 milestones)
Document/                   Source PDFs
pipeline/                   One module per phase (above), plus:
  run.py                      single entry point
  profile.py                  registry + profile loading/validation/detection, manifest
  profiles/*.yaml             unece_regulation, un_gtr, eu_oj_act, generic
  expectations.py             evaluator for tests/expectations/*.yaml (QA + tests)
  kg_illustrate.py            static PNG / interactive HTML of one branch
  templates/                  explorer + illustration page templates
app/                        Streamlit requirement -> structured prompt app
tests/                      unit tests per phase + end-to-end test over every PDF
  expectations/<doc_id>.yaml  hand-verified facts per document
output/
  index.html                  links to every document's explorer and QA report
  NOTES.md                    implementation notes (v2 and v1)
  <doc_id>/                   everything for one document (see "Outputs")
```

## Setup

Python 3.11+ (developed on 3.14).

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

No database, server or API keys (graph store: NetworkX/JSON + GraphML).

## Running

```bash
.venv/bin/python -m pipeline.run --all                     # every PDF in Document/ (~2.5 min, Reg 154 dominates)
.venv/bin/python -m pipeline.run --doc GTR22               # one document (doc_id, file name or path)
.venv/bin/python -m pipeline.run --all --from phase4a_external   # resume from a phase
.venv/bin/python -m pipeline.run --doc EU2026-1762 --only phase6_qa
```

Each phase prints a one-line summary; the full run record is
`output/<doc_id>/manifest.json`.

## Adding a document

1. Drop the PDF into `Document/`.
2. Add an entry to `documents.yaml` (`file`, `doc_id`, `profile`, `self_ids`,
   optional `metadata`). Without one the pipeline still runs: it
   auto-detects the profile and derives a doc_id, and flags the manifest
   `registry_confirmed: false`.
3. If it belongs to a new family (different heading words, numbering or
   definition phrasing), add `pipeline/profiles/<family>.yaml` — copy the
   closest existing profile. Profiles are validated on load, so an unknown
   key fails loudly.
4. Run it, read `output/<doc_id>/qa_report.md`, and add
   `tests/expectations/<doc_id>.yaml` with facts you verified in the PDF.

## Outputs (`output/<doc_id>/`)

| File | Contents |
|---|---|
| `kg_explorer.html` | Self-contained interactive viewer — open in a browser (equations render with KaTeX from a CDN, next to their PDF crop). Deep links: `kg_explorer.html#<node id>`. |
| `qa_report.md` | Invariants, coverage, resolution by kind + unresolved list, merges, equation stats, outline cross-check, expectations |
| `nodes.jsonl`, `edges.jsonl` | The graph (one JSON object per line) |
| `graph.graphml`, `graph.pickle` | Same graph for Gephi / NetworkX |
| `external_citations.csv` | Every external document + provision cited, with roles and citing units |
| `equations/*.png` | Crop of every equation from the PDF |
| `units.jsonl`, `definitions.jsonl`, `abbreviations.jsonl`, `footnotes.jsonl`, `tables.jsonl`, `figures.jsonl`, `equations.jsonl`, `variables.jsonl`, `references.jsonl`, `external_docs.jsonl`, `external_provisions.jsonl`, `citations.jsonl` | Per-phase outputs |
| `regions.jsonl`, `anchors.jsonl`, `external_mask.jsonl`, `manifest.json` | Intermediates / run record |
| `lines.jsonl`, `page_meta.jsonl` | Phase 1 intermediates (large; git-ignored, regenerated in seconds) |

```python
import pickle
g = pickle.load(open("output/GTR22/graph.pickle", "rb"))
g.nodes["GTR22.BODY.6.3.2.EQ-1"]["latex"]
[(v, d["type"]) for _, v, d in g.out_edges("EU2026-1762.ART-6.1", data=True)]   # CITES ...
```

## Requirement → structured prompt app

```bash
streamlit run app/streamlit_app.py
```

Pick a document, type a requirement phrase; the app does deterministic
keyword search over that document's graph and assembles a citation-backed
prompt: area of requirement → hierarchy → citation paragraph → terms →
**equations in the clause** → **external provisions it depends on (role,
title, ELI)** → cross-references. No LLM is called. The logic is in
`app/kg_retrieval.py` (no Streamlit dependency):

```python
from app.kg_retrieval import list_documents, load_graph, search, build_structured_prompt
g = load_graph("EU2026-1762")
print(build_structured_prompt(g, "conformity of production", search(g, "conformity of production", max_results=3)))
```

## Illustrating a branch

```bash
.venv/bin/python -m pipeline.kg_illustrate --doc REG154.04 --list
.venv/bin/python -m pipeline.kg_illustrate --doc REG154.04 --list-under REG154.04.ANNEX-B8
.venv/bin/python -m pipeline.kg_illustrate --doc REG154.04 --root REG154.04.BODY.3 --out-name body3-definitions
.venv/bin/python -m pipeline.kg_illustrate --doc EU2024-1257 --root EU2024-1257.CH-II --no-static
```

Writes `output/<doc_id>/kg_illustration_<slug>.png` / `.html`.

## Tests

```bash
.venv/bin/python -m unittest discover -s tests -t .
```

97 tests: unit tests per phase on synthetic input (layout merging,
header/footer parity, footnote separators, profile-driven structure for each
family, definition patterns, equation reconstruction, external-citation
grammar/pinpoints/back-references, reference scoping, assembly), plus one
end-to-end test that runs the full pipeline on **every** PDF in `Document/`
and checks invariants and that document's expectations file (~80 s).

## Known gaps

- Reg 154 equations: 278 of 535 round-trip through sympy (`parsed`); the
  rest are `partial` (deeply nested layouts) and always carry the PDF crop.
  Only image equations framed by a lead-in or "where" line are detected, and
  their formula text needs math OCR, which was deliberately not added
  (no-ML principle; plan §13).
- Reg 154 still has 15 duplicate-id merges (wrapped cross-references that
  look like headings), each listed in its QA report.
- Table *values* (limits, MPR percentages) are stored as text, not as
  structured Attributes/Constraints; no cross-document graph, no tracked
  changes, no Neo4j — see `schema.yaml` `deferred_relationship_types`.
