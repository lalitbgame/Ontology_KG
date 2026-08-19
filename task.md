# Task List — Ontology-Based Knowledge Graph Build

Derived from `Ontology_KG_Project_Plan.md`. Organized by pipeline phase, in build order — each phase gates the next. Section references (§) point back to the plan doc.

---

## Phase 0 — Verification & schema lock (blocking, do first)

- [ ] Write `schema.yaml` — the formal ontology spec: all node types (`Standard`, `Version`, `Division`, `Clause`, `Term`, `Table`, `Figure`), the `Paragraph` label rule, all relationship types, and the qualified-ID scheme from §3.4. Treat this as reviewed/frozen before any extraction code is written.
- [ ] **Tracked-changes spike (highest-risk item):** using PyMuPDF, pull `page.get_drawings()` + per-span `color` for 5–10 pages known to contain amendments; confirm whether deletions/insertions can be reliably distinguished from vector line-overlays and font color. Document the detection rule (or the fallback if it's not reliable).
- [ ] Confirm the "no OCR needed" assumption by spot-checking text extraction on ~10 random pages spread across the 668 (already sampled a few — extend the sample).
- [ ] Decide the open questions from plan §9:
  - [ ] Graph store: Neo4j (Docker) vs. NetworkX/JSON-only for now
  - [ ] Deleted/footnote text: kept as audit-only properties vs. dropped
  - [ ] Whether to ingest the prior 03-series text of Reg. 154 alongside this one now, to exercise `Version`/`supersedes`

## Phase 1 — Layout-aware text extraction

- [ ] Set up PyMuPDF (`fitz`) extraction script; pull per-span text + bbox + font + size + color via `page.get_text("dict")`.
- [ ] Detect and strip repeating headers/footers (lines repeating at ~same y-position on >90% of pages, e.g. `ECE/TRANS/WP.29/GRPE/2025/15`, bare page numbers).
- [ ] Implement footnote separation (font-size threshold + bottom-of-page y-position); attach each footnote to its annotating clause.
- [ ] Implement tracked-changes tagging per the Phase 0 spike's rule; mark spans `status: "deleted"` and exclude from `body_text` (retain in `superseded_text`).
- [ ] Implement x-coordinate column clustering for the two-column Abbreviations table (§2.1/§2.2), specifically handling the page-6/7 boundary breakage found during planning.
- [ ] Normalize chemical-formula spacing artifacts (`CH 4` → `CH4`, `C2 H 6` → `C2H6`, etc.).
- [ ] Output `pages.jsonl` (ordered, cleaned text spans + style metadata retained).
- [ ] Spot-check `pages.jsonl` against 5 raw pages side-by-side for extraction fidelity.

## Phase 2 — Hierarchical structural parsing

- [ ] Write numbering-token regexes: decimal clauses (`^\d+(\.\d+)*\.`), lettered sub-items (`^\([a-z]\)`), roman sub-items (`^\([ivx]+\)`).
- [ ] Write Division-boundary detector (`^Annex\s+[A-Z]?\d+[ab]?`, `^Appendix\s+\d+`) and cross-check the resulting Division list against the document's own Table of Contents for completeness.
- [ ] Implement the stack-based hierarchical parser: push/pop clause depth, reset numbering stack at each Division boundary, append non-numbered lines to the current deepest clause's `body_text`.
- [ ] Implement graceful degradation for numbering irregularities (skipped depth, typo'd numbers) — log a warning and attach as best-guess sibling instead of failing.
- [ ] Implement lettered/roman sub-items as structured list data inside the parent `Paragraph.body_text` (not separate nodes), per §3.6.
- [ ] Apply the `Paragraph` label rule: any `Clause` with non-empty `body_text` gets the additional label, regardless of depth.
- [ ] Assign qualified IDs to every `Clause` per the §3.4 scheme (`REG154.04.<DIVISION>.<local-number-path>`).
- [ ] Output `clauses.jsonl` (qualified_id, depth, parent_id, title, body_text, has_body).
- [ ] QA: verify clause count against a manual page-sample count; verify no orphan clauses; verify numbering monotonicity (see Phase 6 for the full checklist — do a first-pass check here before moving on).

## Phase 3 — Term extraction (abbreviations & definitions)

- [ ] Parse §2.1/§2.2 Abbreviations from the bbox-column data (not reflowed text) into `(surface_form, expansion, category)` triples.
- [ ] Parse §3.x Definitions via `^"([^"]+)"\s+means` regex; capture optional inline `(ABBREV)`.
- [ ] Implement the reconciliation/merge rule (§3.5): when a definition's parenthetical abbreviation exactly matches an abbreviation-table entry, merge into one `Term` node (`term_type: "merged"`) with two `DEFINES` edges; otherwise link near-matches with `SAME_AS` for human review.
- [ ] Output `terms.jsonl` and the `DEFINES` edges.
- [ ] Manually review the merge list once — confirm no false merges (e.g. two genuinely different concepts sharing an abbreviation string).

## Phase 4 — Term usage & cross-reference linking

- [ ] Compile whole-word regex per `Term`; case-sensitive for ALL-CAPS short abbreviations.
- [ ] Build and apply the short-abbreviation stoplist/low-confidence rule for ≤2-character terms (e.g. `AC`, `DC`) — tag matches `confidence: low` rather than a plain edge.
- [ ] Scan all `Paragraph` nodes for term occurrences (excluding the defining clause) → `MENTIONED_IN` edges.
- [ ] Implement cross-reference regexes: `paragraph\s+[\dA-Za-z.]+\.`, `Annex\s+[A-Z]?\d+[ab]?`, `Appendix\s+\d+(\s+to\s+Annex\s+[A-Z]?\d+)?`, `Table\s+\S+`, `Figure\s+\S+`.
- [ ] Implement the scope-resolution heuristic (§6.4): default same-Division; override on explicit `"of this Regulation"` / `"to this Regulation"` / named Annex/Appendix.
- [ ] For anything left ambiguous, write a `REFERENCES {status: "unresolved", raw_text: ...}` record — never guess.
- [ ] Output `edges.jsonl` (mentions + references, resolved and unresolved).

## Phase 5 — Graph assembly & load

- [ ] Merge `clauses.jsonl` + `terms.jsonl` + `edges.jsonl` into final node/edge sets; assign any remaining global IDs.
- [ ] Run referential-integrity validation: every edge endpoint must resolve to a real node ID before load.
- [ ] Stand up Neo4j Community Edition (Docker) *if* that's the chosen store from Phase 0.
- [ ] Write the batched loader (`UNWIND $rows AS row MERGE ...`) via the Python Neo4j driver.
- [ ] Create uniqueness constraints/indexes on `Clause.qualified_id` and `Term.surface_form`.
- [ ] Export GraphML (Gephi) and a NetworkX pickle as secondary, infra-free outputs.

## Phase 6 — Validation & QA

- [ ] Structural completeness: parsed clause count vs. manual page-sample count (target within ~2%).
- [ ] Orphan check: every non-root `Clause` has a resolvable `parent_id` (target 100%).
- [ ] Numbering monotonicity: no unexplained depth jumps >1 (all flagged jumps reviewed).
- [ ] Text coverage: % of body text captured in some `Paragraph.body_text` vs. raw page text, excluding TOC/headers/footers (target ~100%).
- [ ] Tracked-changes spot check: manually verify 10 known-amended pages against `status="deleted"` tagging (target 100% match).
- [ ] Term precision: manually review 30 sampled `MENTIONED_IN` edges per Division (target ≥95% true positive); tune the stoplist from Phase 4 based on findings.
- [ ] Reference resolution rate: % of detected cross-refs resolved to a real node (target ≥90%; review the unresolved list).
- [ ] Write up QA results as a short report alongside the deliverables.

## Phase 7 — Query, visualization & delivery

- [ ] Write the example Cypher query pack (definition-chain lookup, term-usage lookup, division cross-reference lookup, clause ancestor/breadcrumb path).
- [ ] Set up Neo4j Bloom/Browser (or equivalent) for interactive exploration.
- [ ] Produce static Mermaid/Graphviz exports of representative subgraphs for documentation.
- [ ] Write the project README covering: how to run the pipeline end-to-end, how to query the graph, and where the QA report lives.
- [ ] Package final deliverables: `schema.yaml`, pipeline scripts (one per phase), `nodes.jsonl`/`edges.jsonl`, Neo4j load script, query pack, README.

---

## Not in scope for v1 (do not schedule unless priorities change)

- Semantic search / embeddings / vector index
- Structured extraction of table *contents* (numeric WLTC cycle data etc.) — captions + defining-clause links only
- OCR
- Automated multi-version diffing logic (schema supports it; the diff engine itself is a later project)
