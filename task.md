# Task List — Ontology-Based Knowledge Graph Build

Derived from `Ontology_KG_Project_Plan.md`. Organized by pipeline phase, in build order — each phase gates the next. Section references (§) point back to the plan doc.

---

## Phase 0 — Verification & schema lock (blocking, do first)

- [x] Write `schema.yaml` — reconciled against `Knowledge Graph Architecture.png`, all six open decisions resolved (2026-08-26).
- [x] **Tracked-changes spike (highest-risk item):** sampled span colors across ~96 pages + inspected `get_drawings()` on 8 pages. Finding: no reliable tracked-changes markup exists in this PDF's body — the only non-black text is the cover page's informal-document notice; vector paths correlate with table borders, not strike/underline decoration. **Fallback adopted:** no detection is implemented; every Clause defaults to `status: "active"` (schema.yaml). (2026-08-26)
- [x] Confirmed "no OCR needed": extended spot-check to ~30 pages across the doc (0, 5–7, 15, 61–64, 100–188, 300, 400, 500, 544–626, 663) via `page.get_text("dict")` — all return clean, real text. (2026-08-26)
- [ ] Decide the open questions from plan §9:
  - [x] Graph store: Neo4j (Docker) vs. NetworkX/JSON-only for now — **NetworkX/JSON for now** (2026-08-26)
  - [x] Deleted/footnote text: kept as audit-only properties vs. dropped — **kept as audit-only properties** (2026-08-26)
  - [ ] Whether to ingest the prior 03-series text of Reg. 154 alongside this one now, to exercise `Version`/`supersedes`

## Phase 1 — Layout-aware text extraction

`pipeline/phase1_extract.py` — see `output/PHASE1_2_NOTES.md` for details/caveats. (2026-08-26)

- [x] Set up PyMuPDF extraction script; pull per-line text + bbox + font size via `page.get_text("dict")`.
- [x] Detect and strip repeating headers/footers (>90%-of-pages signature match) — 2 patterns stripped (running title, bare page number).
- [x] Implement footnote separation (font-size threshold + bottom-of-page y-position) — tagged `is_footnote`; routed to the open clause's `footnote_text` in Phase 2.
- [x] Tracked-changes tagging — N/A, implemented as a no-op per the Phase 0 spike's fallback (no reliable markup to tag).
- [ ] x-coordinate column clustering for the two-column Abbreviations table (§2.1/§2.2) — **deferred to Phase 3** (term extraction is where this table actually gets consumed); bbox/x0 is retained per line so Phase 3 can do it without re-extracting.
- [x] Normalize chemical-formula spacing artifacts (`CH 4` → `CH4`, `C2 H 6` → `C2H6`).
- [x] Output `pages.jsonl` (51,979 lines).
- [x] Spot-checked against manual page previews (page 5/6/7/15/61/100/182 etc.) — matches.

## Phase 2 — Hierarchical structural parsing

`pipeline/phase2_parse.py` — see `output/PHASE1_2_NOTES.md` for details/caveats. (2026-08-26)

- [x] Numbering-token regex: decimal clauses (`^\d+(\.\d+)*\.`). Lettered/roman sub-items need no separate regex — see next item.
- [x] Division-boundary detector (`^Annex ... - Appendix N$`, `^Annex ...$`, `^Appendix N$`) — cross-checked against the document's own TOC (pages ~2–4): all 56 divisions accounted for; the one apparent gap (Annex C1 – Appendix 1) is confirmed intentionally absent, matching the source file's own name ("...without 1C 1").
- [x] Stack-based hierarchical parser, resets at each Division boundary.
- [x] Graceful degradation: depth jumps logged as warnings (220) and attached to the nearest open ancestor rather than failing.
- [x] Lettered/roman sub-items — fall through to plain-text append automatically (they never match the digit-leading clause regex), landing inline in the parent's `body_text` per §3.6, with no special-case code needed.
- [x] `Paragraph` label rule — implemented, **with a known gap**: `title` vs `body_text` aren't yet distinguished (everything lands in `body_text`), so `has_body` is ~100% true rather than the plan's expected ~95%. Flagged for Phase 6.
- [x] Qualified IDs per §3.4 — verified via a depth-8 clause's full parent chain.
- [x] Output `clauses.jsonl` (3,737 clauses; includes a synthetic depth-0 "division root" clause per division, not in the original plan, added so unnumbered content — e.g. declaration-form Annex appendices — isn't silently dropped).
- [x] First-pass QA: 0 orphans, 0 duplicate qualified_ids (both enforced by `tests/test_integration.py`, not just eyeballed); page-15 manual sample matches exactly; a numeric false-positive class (e.g. "273.15K" parsed as clause "273.") and a duplicate-id class (TOC entries parsed as fake clauses; wrapped cross-references landing as spurious headings) were found — via the test suite, see `output/PHASE1_2_NOTES.md` — and fixed. Full monotonicity review of the 220 flagged jumps and per-division clause-count sampling deferred to Phase 6 as scoped.
- [x] **Retroactive fix (found during Phase 4, 2026-08-27):** the division-boundary detector had the same wrapped-line false-positive class as Phase 2's other regexes — a wrapped in-prose reference ("...paragraph 3.4. of\nAppendix 2") landing "Appendix 2" alone on its own line was indistinguishable from a real heading by text alone, and mis-reset the division mid-BODY, silently reparenting real content (§8.1.3–8.4, ~40 clauses) under the wrong Annex/Appendix. Fixed with the same discriminator used for footnotes: real headings render at 14.3pt vs ~9.8pt body text, so `division_code()` now requires `size >= 12`. Paragraph-reference resolution in Phase 4 went from 76%→94% after this fix alone — see `output/PHASE1_2_NOTES.md`.
- [x] **Test suite** (`tests/`, unittest, no extra dependency): unit tests for both phases' pure functions on synthetic input, plus an integration test that runs the real pipeline end-to-end against every PDF found under `Document/` and checks structural invariants (no orphans, no duplicate ids, well-formed qualified_ids, `has_body == bool(body_text)`) — so dropping a different/updated PDF into `Document/` re-validates automatically, no test-code changes needed. Run: `.venv/bin/python -m unittest discover -s tests -t .`.

## Phase 3 — Term extraction (abbreviations & definitions)

**Scope note (2026-08-27):** term-model-deferral (schema.yaml) means no merge/
reconciliation and no `DEFINES`/`SAME_AS` edges in v1 — `Abbreviation` (§2)
and `Definition` (§3, added to schema.yaml this phase) stay two separate,
unconnected node types. The plan's §3.5 merge-rule and reconciliation-review
bullets are superseded by that decision; not scheduled for v1.

`pipeline/phase3_terms.py` (run via `python -m pipeline.phase3_terms`) — see `output/PHASE1_2_NOTES.md` for details/caveats. (2026-08-27)

- [x] Parse §2.1/§2.2 Abbreviations from the bbox-column data (not reflowed text) into `(surface_form, expansion, category)` triples — 116 entries (98 general, 18 chemical).
- [x] Parse §3.x Definitions via `^"([^"]+)"\s+means` regex; capture optional inline `(ABBREV)` — 151 entries (31 with an inline abbreviation), verified against the plan's own NOVC-FCHV example.
- [x] Output `abbreviations.jsonl` and `definitions.jsonl` (no merge, no edges — see scope note above).

## Phase 4 — Term usage & cross-reference linking

**Scope note (2026-08-27):** term-usage linking (first 3 bullets below) is
**not implemented** — schema.yaml's term-model-deferral already marks
`MENTIONED_IN` deferred (no merged `Term` node to scan for yet, per
`deferred_relationship_types`). Only the cross-reference half (last 3
bullets, `REFERENCES` edges) is in scope this phase.

`pipeline/phase4_references.py` — see `output/PHASE1_2_NOTES.md` for details/caveats. (2026-08-27)

- [ ] ~~Compile whole-word regex per `Term`; case-sensitive for ALL-CAPS short abbreviations.~~ deferred, see scope note.
- [ ] ~~Build and apply the short-abbreviation stoplist/low-confidence rule for ≤2-character terms.~~ deferred, see scope note.
- [ ] ~~Scan all `Paragraph` nodes for term occurrences → `MENTIONED_IN` edges.~~ deferred, see scope note.
- [x] Implement cross-reference regexes: `paragraph\s+[\dA-Za-z.]+\.`, `Annex\s+[A-Z]?\d+[ab]?`, `Appendix\s+\d+(\s+to\s+Annex\s+[A-Z]?\d+)?`, `Table\s+\S+`, `Figure\s+\S+` (Table/Figure tightened to an identifier-shaped token — see notes).
- [x] Implement the scope-resolution heuristic (§6.4): default same-Division; override on explicit `"of this Regulation"` / a named Annex/Appendix immediately following ("paragraph N. of ..."); a bare `Appendix N` inside an Annex resolves to that Annex's own appendix.
- [x] For anything left ambiguous, write a `REFERENCES {status: "unresolved", raw_text: ...}` record — never guess.
- [x] Output `references.jsonl` (2,980 references; 73% resolved overall — Table/Figure are 0% by design, no phase populates Table/Figure nodes yet; paragraph/Annex/Appendix alone resolve at 94%/94%/90%, already at or near the Phase 6 ≥90% target).

## Phase 5 — Graph assembly & load

**Scope note (2026-08-27):** graph-store-choice (schema.yaml, confirmed
Phase 0) is NetworkX/JSON, no Neo4j server — so the Neo4j bullets below are
**not implemented**, and the plan's "secondary, infra-free" NetworkX/GraphML
exports become the primary deliverable instead. `terms.jsonl` doesn't exist
either (term-model-deferral): the node merge is `clauses.jsonl` +
`abbreviations.jsonl` + `definitions.jsonl`. Also note what's *not* in this
graph: `Standard`, `Version`, a proper `Division`, `ScopeParagraph`, `Area`,
`Attributes`, `Constraints`, `Table`, `Figure` are schema.yaml node types
with no extraction phase built for them yet — only `Clause` (with its
depth-0 division-root pseudo-node standing in for `Division`),
`Abbreviation`, and `Definition` are populated. See `output/PHASE1_2_NOTES.md`.

`pipeline/phase5_assemble.py` — (2026-08-27)

- [x] Merge `clauses.jsonl` + `abbreviations.jsonl` + `definitions.jsonl` into one node set (4,004 nodes); `HAS_CHILD` (from `parent_id`) + `HAS_ABBREVIATION` + `HAS_DEFINITION` + resolved `REFERENCES` into one edge set (6,118 edges). IDs are already globally unique and deterministic (`qualified_id`, `ABBR:<surface_form>`, `DEF:<source_clause>`) — no new ID assignment needed.
- [x] Referential-integrity validation: every edge endpoint checked against the node id set before the graph is built; bad edges are dropped (not silently kept) and counted — 0 on the real document.
- [ ] ~~Stand up Neo4j Community Edition (Docker).~~ not applicable, see scope note.
- [ ] ~~Write the batched Neo4j loader.~~ not applicable, see scope note.
- [ ] ~~Create Neo4j uniqueness constraints/indexes.~~ not applicable — node-id and edge-endpoint uniqueness/validity are enforced in Python instead (see referential-integrity bullet above and `tests/test_integration.py`).
- [x] Export GraphML (Gephi) and a NetworkX pickle — now primary outputs, not secondary. Also outputs the flat `nodes.jsonl`/`edges.jsonl` the plan's later phases (6, 7) expect.

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
- [x] **Set up interactive exploration** (2026-08-27, done out of order, ahead of Phase 6 — built on request): no Neo4j, so no Bloom/Browser — built `output/kg_explorer.html` instead, a self-contained interactive HTML viewer (collapsible clause-hierarchy tree grouped by Division, search, and a per-node local-graph panel showing parent/children/references). Data comes from `pipeline/build_viz_data.py`, which reshapes Phase 5's `nodes.jsonl`/`edges.jsonl` into `output/viz_data.json` (embedded inline in the HTML — fully self-contained, no server needed). **Note:** Phase 6 QA hasn't run yet, so this shows the graph as currently assembled, warts (known limitations from `output/PHASE1_2_NOTES.md`) included.
- [ ] Produce static Mermaid/Graphviz exports of representative subgraphs for documentation.
- [ ] Write the project README covering: how to run the pipeline end-to-end, how to query the graph, and where the QA report lives.
- [ ] Package final deliverables: `schema.yaml`, pipeline scripts (one per phase), `nodes.jsonl`/`edges.jsonl`, Neo4j load script, query pack, README.

---

## Not in scope for v1 (do not schedule unless priorities change)

- Semantic search / embeddings / vector index
- Structured extraction of table *contents* (numeric WLTC cycle data etc.) — captions + defining-clause links only
- OCR
- Automated multi-version diffing logic (schema supports it; the diff engine itself is a later project)
