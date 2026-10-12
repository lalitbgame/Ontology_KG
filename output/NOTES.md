# Implementation notes

## v2 (2026-10-12) — generalized pipeline

The flat `output/*.jsonl` files of v1 are replaced by one folder per
document, `output/<doc_id>/` (see README "Outputs"). Per-document QA lives in
`output/<doc_id>/qa_report.md`; the run record (counts, warnings, timings,
input hash, profile) in `manifest.json`. Notes worth keeping from building v2:

- **Absolute font-size heading detection could not generalize.** EU OJ
  headings (`Article 4`, `ANNEX I`, `CHAPTER II`) are 8.5 pt italic and
  centred — smaller than 9.6 pt body text. Heading style is now relative to
  each document's body statistics, with a `centered` predicate for EU acts.
- **A short table border followed by small-font table notes looked like a
  footnote separator** (Reg 154 p.268), which flagged the rest of the page as
  footnotes and lost clauses 3.4/3.5. Footnote separators now require every
  line below them to be set smaller than body text, and no further rules
  below. Caught by the clause-id diff against v1.
- **The numbering column alone can't reject wrapped numbers in EU acts**
  (paragraph numbers and continuation lines share x = 67). A number is a
  heading only as a plausible successor (EU article paragraphs: `prev + 1`),
  which rejects `2032.` after `2.`.
- **Mask external citations before resolving internal references.** In
  EU 2026/1762, "Annex 1 to UN Regulation No 179" would otherwise resolve to
  the act's own Annex I family as soon as numeric/roman annex lookup exists;
  Phase 4a writes the spans and Phase 4 skips them (expectation
  `internal_resolved_max` guards it).
- **"thereof" after "Having regard to" binds to the governing act**, not the
  last act cited in the sentence (EU 2026/1762 citations: Articles 14(3)/14(4)
  of Regulation 2024/1257, not of 2022/1362).
- **Equation reconstruction**: the radical's overline and an inner fraction
  bar can have identical extent; radicals are detected first (rule starting at
  a `√` glyph), fractions collapsed, radicals wrapped last. Baselines are
  weighted by characters (a `√(x` span is shifted by the glyph).
- **Reg 154 regressions checked against v1**: 3,756 units vs 3,737 (+0.5%);
  the 24 v1 ids no longer produced were all wrapped-reference false positives
  ("4.1.1. of Annex B6" inside Table A6/1, "6.1.8. of this Regulation.");
  116/116 abbreviations; definitions 151 → 184 (curly quotes, "refers to",
  abbreviations split out of terms); dedupe merges ~30 → 15 (the "Part I/II"
  numbering restart in Annex A1 Appendix 1 is now a level).

---

## v1 notes (Reg 154 only, 2026-08)


**Also present: `output/kg_explorer.html`** — a self-contained interactive
viewer for the graph (Phase 7 item, built ahead of schedule on request).
Generated via `pipeline/build_viz_data.py` (reshapes `nodes.jsonl`/
`edges.jsonl` into `output/viz_data.json`, embedded directly in the HTML —
open the file in any browser, nothing to run). See task.md Phase 7 for
what it does and doesn't cover.


Scripts: `pipeline/phase1_extract.py`, `pipeline/phase2_parse.py`, `pipeline/phase3_terms.py`, `pipeline/phase4_references.py`, `pipeline/phase5_assemble.py`.
Tests: `tests/` (`python -m unittest discover -s tests -t .`).
Run:
```
.venv/bin/python pipeline/phase1_extract.py
.venv/bin/python pipeline/phase2_parse.py
.venv/bin/python -m pipeline.phase3_terms   # needs -m: imports phase2_parse.strip_toc
.venv/bin/python pipeline/phase4_references.py
.venv/bin/python pipeline/phase5_assemble.py
```
Outputs: `output/pages.jsonl` (51,979 lines), `output/clauses.jsonl` (3,737
clauses), `output/abbreviations.jsonl` (116), `output/definitions.jsonl`
(151), `output/references.jsonl` (2,980 references, 73% resolved),
`output/nodes.jsonl` (4,004), `output/edges.jsonl` (6,118),
`output/graph.graphml`, `output/graph.pickle`.

## Phase 5 scope note

graph-store-choice (confirmed Phase 0) is NetworkX/JSON, not Neo4j, so
task.md's Neo4j bullets (Docker, Cypher loader, DB constraints) aren't
implemented — the plan's "secondary, infra-free" GraphML/pickle exports
become the actual deliverable. `abbreviations.jsonl` gained a
`source_clause` field this phase (backfilled in `phase3_terms.py`) so
`HAS_ABBREVIATION` edges have a real source, matching how `definitions.jsonl`
already worked.

**What's in the graph vs. what schema.yaml defines:** only `Clause`,
`Abbreviation`, and `Definition` nodes are populated — no phase extracts
`Standard`, `Version`, a real `Division`, `ScopeParagraph`, `Area`,
`Attributes`, `Constraints`, `Table`, or `Figure` yet. The `Clause` depth-0
"division root" pseudo-node stands in for `Division` (e.g. `HAS_CHILD`
edges from it look like a Division→Section relationship even though it's
still typed `Clause`). Worth flagging before Phase 7 packaging claims the
graph implements the full schema.

## Bug found while wiring up the NetworkX export

`to_networkx()` originally keyed each `MultiDiGraph` edge by its relationship
`type` (`g.add_edge(u, v, key=e["type"], ...)`). Two edges of the *same*
type between the *same* pair of nodes — e.g. a clause mentioning
"paragraph 6.3.2." twice, producing two `REFERENCES` edges with different
`raw_text` — share that key, so the second `add_edge` call silently
overwrote the first instead of adding a parallel edge: `edges.jsonl` had
6,118 rows but the graph only had 5,719. Fixed by not passing an explicit
key (NetworkX auto-assigns a unique one per edge); `type` stays available
as a regular edge attribute. All three outputs (`edges.jsonl`, the pickle,
the GraphML) now agree exactly at 6,118. Regression test:
`test_phase5.ToNetworkx.test_parallel_same_type_edges_are_not_collapsed`.

## Phase 4 scope note

Only the cross-reference half of Phase 4 is implemented. Term-usage linking
(`MENTIONED_IN`) is not — it needs a single scannable `Term` node, and
schema.yaml's term-model-deferral keeps `Abbreviation`/`Definition` as two
separate, unconnected node types in v1. See `deferred_relationship_types`.

## A retroactive Phase 2 bug, found while building Phase 4

Investigating why `paragraph 8.2.` / `paragraph 8.3.` references kept
coming up unresolved (§8 "Conformity of production" appeared to jump from
`8.1.2` straight to nothing) led to a real bug in `division_code()`, not a
gap in the source document. A footnote sentence — "...the accuracy of the
vehicle energy charged is assessed in accordance with paragraph 3.4. of
Appendix 2" — wrapped so **"Appendix 2" landed alone on its own line**,
which is textually indistinguishable from a real "Appendix 2" heading. That
false heading reset the division mid-page, silently reparenting all of
§8.1.3-8.4 (~40 real clauses) under `ANNEX-APPENDIX-2` instead of `BODY`.

Fixed the same way footnotes are already detected: real division headings
render at 14.3pt vs ~9.8pt body text, so `division_code()` now takes the
line's font `size` and requires `size >= 12`. Effect: clause count
3,729→3,737, and — the real signal this was worth fixing —
**paragraph-reference resolution went from 76% to 94%** once the missing
clauses were back in the right place. Regression test:
`test_phase2.DivisionCode.test_small_font_is_rejected_even_if_the_text_matches`
and `test_phase2.Parse.test_wrapped_reference_fragment_does_not_reset_division`.

This is also a live example of a blind spot in invariant-based testing: the
existing "0 orphans / 0 duplicate ids / well-formed ids" checks all still
passed while this bug was live, because misattributed clauses are still
valid, non-duplicate, non-orphaned nodes — just under the wrong parent.
Nothing currently in `tests/` would catch a similar misattribution again
without a specific regression test for it.

## Reference resolution breakdown (2,980 total, 73% resolved)

| Kind | Resolved | Rate |
|---|---|---|
| `paragraph N.` | 1,312 / 1,397 | 94% |
| `Annex XX` | 625 / 662 | 94% |
| `Appendix N` | 233 / 258 | 90% |
| `Table X` | 0 / 462 | 0% (by design — no phase populates `Table` nodes yet) |
| `Figure X` | 0 / 201 | 0% (by design — no phase populates `Figure` nodes yet) |

The structural three (paragraph/Annex/Appendix) are already at or near
task.md Phase 6's ≥90% target. The unresolved remainder in those three is a
mix of genuine gaps worth a Phase 6 review pass (a spot check of a handful
suggests some point at clause numbers that plausibly don't exist in this
particular amendment draft) and the wrapped-reference ambiguity class this
phase's scope-resolution heuristic can't fully disambiguate from a 60-char
lookahead window. Table/Figure will stay at 0% until a phase exists to
extract `Table`/`Figure` nodes from captions — not currently scheduled in
task.md.

## Phase 3 scope note

schema.yaml's term-model-deferral decision means `Abbreviation` (§2) and
`Definition` (§3, added to schema.yaml this phase) are two separate,
unconnected node types — no merge/reconciliation (plan §3.5), no
`DEFINES`/`MENTIONED_IN`/`SAME_AS` edges. `terms.jsonl` from the original
plan is therefore two files instead of one merged one.

## Bug the test suite found in Phase 3

`extract_column_pairs` assumed strict term-then-expansion reading order
within the abbreviation table, but raw extraction order occasionally
batches two term-column lines before either's expansion (real example:
"NOVC" and "NOVC-HEV" both appear before "Not off-vehicle charging..." /
"...hybrid vehicle", even though each term shares an exact y0 with its own
expansion). Fixed by sorting lines by `(page, y0, x0)` before the
term/expansion state machine runs, so same-row pairing no longer depends on
raw extraction order. Caught by `test_integration` (an abbreviation with an
empty `expansion`), reproduced as a unit test in
`test_phase3.ExtractColumnPairs.test_out_of_order_rows_are_resorted_by_position`.

## Phase 0 spike outcome (drives Phase 1's tracked-changes no-op)

Sampled span colors across ~96 pages and `page.get_drawings()` on 8 pages.
Only non-black text found is the cover page's "Updates ... are shown using
tracked changes" notice — nowhere in the body. Vector paths are dominated by
table-cell borders and thin filled rects that don't align with any text
span at strike/underline height. **Conclusion: this PDF's body carries no
detectable tracked-changes markup.** Every Clause keeps `status: "active"`
(schema.yaml default) — no deletion tagging is implemented, per the plan's
own fallback instruction for when detection isn't reliable.

## Bugs the test suite (`tests/`) found and fixed

1. **`normalize_chem` didn't actually normalize `"CH 4"`.** The original
   regex pair required the letter-group to be exactly one uppercase +
   optional one lowercase (`[A-Z][a-z]?`) — wrong shape for "CH" (two
   uppercase letters, no lowercase). Rewrote as a single span-based
   normalizer: find a maximal run of `[A-Z0-9 ]`, split on spaces, and only
   collapse it if every piece matches `[A-Z]{0,2}\d{0,3}` (an element symbol
   + subscript shape). The 2-letter cap is what keeps real abbreviations
   (`WLTC`, `REESS`, ...) untouched. Caught by `test_phase1.NormalizeChem`.

2. **Duplicate `qualified_id`s in `clauses.jsonl`** (3,959 rows but only
   3,733 unique ids in the pre-fix run) — caught by
   `test_integration`'s uniqueness assertion. Two independent causes:
   - The document's own **Table of Contents** (pages 1–3) is itself
     formatted as `"N."` on its own line followed by a dot-leadered title
     (`"Scope .......... 5"`), which is structurally identical to a real
     clause heading — so TOC entries were being parsed as real (fake)
     clauses, colliding with the real ones found later. Fixed with
     `strip_toc()`: pages near the front of the document with a high
     density of dot-leader lines are dropped before parsing. Dot-leader
     density alone isn't a safe signal on its own — Annex A1's fill-in-the
     -blank questionnaire ("Test voltage: .......... V") is just as dense —
     so a page only counts as TOC if it's *also* within the first 10 pages.
   - A residual class: an in-text cross-reference like `"...paragraph
     5.9."` can wrap so `"5.9."` starts the next physical line, which is
     indistinguishable from a real heading by position alone. Rather than
     guess which of two same-id nodes is "the real one" (and silently drop
     the other), `dedupe()` merges their `body_text`/`footnote_text` and
     logs every merge to stderr for audit. ~30 merges on the real PDF.

## Known limitations (candidates for Phase 6 QA)

1. **`title` vs `body_text` not distinguished.** Every line after a clause
   number — whether it's really a heading ("General") or actual prose —
   lands in `body_text`. `has_body` is therefore true for ~100% of clauses,
   not the plan's expected ~95%.
2. **Residual numeric/wrapped-reference noise** likely remains in a few
   large annexes despite the same-line-digit guard and the dedupe pass —
   flagged for Phase 6's per-division sampling, not chased further here to
   keep Phase 2 lean.
3. **One flowchart page (617, Figure C3/4)** has box-label text that looks
   like clause numbers; most were filtered, a few may still slip through.
4. **Column clustering for the §2.1/§2.2 Abbreviations table** is deferred
   to Phase 3, where it's actually consumed. `pages.jsonl` retains per-line
   `x0` so Phase 3 doesn't need to re-extract.

## Verified (via `tests/test_integration.py`, run against every PDF in
`Document/` — so this re-validates automatically if another file is added)

- 0 orphan clauses (every non-null `parent_id` resolves).
- 0 duplicate `qualified_id`s.
- Every `qualified_id` matches `REG154\.04\.[A-Za-z0-9.\-]+`.
- `has_body == bool(body_text)` holds for every clause.
- Deepest clause is 8 levels (`ANNEX-A1.3.2.4.2.9.3.1.1`).
- 56 divisions found, cross-checked by hand against the document's own TOC
  (pages ~2-4): complete except `ANNEX-C1.APP1`, which doesn't exist
  anywhere in the body either — consistent with the source file's own
  name, "154-04 **without 1C 1**.pdf".
