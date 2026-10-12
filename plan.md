# Plan: Generalizing the KG Workflow to All Documents (+ Equations as Nodes)

**Goal.** One deterministic pipeline that turns *any* regulatory PDF in `Document/` into its
own correct knowledge graph: Reg 154, UN GTR 22, EU 2024/1257 (Euro 7), EU 2026/1762, and
future UNECE, GTR and EU acts. Equations and their variables become first-class nodes.

**Not in this plan:** combining or merging graphs across documents. Each document gets
its own graph in its own output folder. The plan does record cross-document references
as data (targets are `ExternalDocument` stubs), so merging later is a join, not a re-parse.

**Principles kept from v1:** no LLM, NER or embeddings in the pipeline; never guess (anything
ambiguous is stored as `unresolved` / `partial` with the raw text); every phase writes
inspectable JSONL; tests guard every fix.

**New principle: profiles, not patches.** Document-specific grammar (heading words, numbering
style, definition phrasing, reference grammar, header/footer style) moves out of the Python
code into **document-family profiles** (YAML). The code becomes a generic, layout-aware
engine. Adding a new family means adding a profile, not editing phase scripts.

Limitation ids (`L4.3`, …) refer to `limitation.md`.

---

## 1. Target architecture

```
Document/*.pdf
   │
   ▼
Phase 0  Document registry + profile detection  ──► output/<doc_id>/manifest.json
   │        (documents.yaml, pipeline/profiles/*.yaml)
   ▼
Phase 1  Layout extraction (span-level)          ──► spans.jsonl, lines.jsonl
   │        line merging, header/footer, footnotes, unicode normalisation
   ▼
Phase 1b Region classification                    ──► regions.jsonl
   │        table | figure | form | equation | footnote | toc | text
   ▼
Phase 2  Structural parse (profile-driven)        ──► units.jsonl   (all structural nodes)
   │        Part/Chapter/Article/Annex/Appendix/Clause/Point/Recital
   ▼
Phase 3  Terms (definitions + abbreviations)      ──► definitions.jsonl, abbreviations.jsonl
Phase 3b Equations + variables                    ──► equations.jsonl, variables.jsonl, equations/*.png
Phase 3c Tables / figures (caption-level)         ──► tables.jsonl, figures.jsonl
   │
   ▼
Phase 4  References (internal + external)         ──► references.jsonl, external_docs.jsonl
   ▼
Phase 5  Assembly + validation                    ──► nodes.jsonl, edges.jsonl, graph.graphml, graph.pickle
   ▼
Phase 6  QA against per-document expectations     ──► qa_report.md
   ▼
Viz / app (doc-aware)                             ──► kg_explorer.html (doc selector), Streamlit doc selector
```

Single entry point: `python -m pipeline.run --doc <file|doc_id>` or `--all`. Each phase
keeps its `run(...)` signature with explicit paths, so the existing unit-test style
still works.

---

## 2. Phase 0 — Document registry, profiles, identity (fixes L2.1–L2.3, L7.5)

### 2.1 `documents.yaml` (new, repo root)
One entry per PDF: `file`, `doc_id`, `profile` (optional override), and metadata the
detector can't reliably infer. `doc_id` is the id namespace for every node of that document.

| File | `doc_id` | Profile |
|---|---|---|
| `154-04 without 1C 1.pdf` | `REG154.04` (unchanged, so existing ids and the app keep working) | `unece_regulation` |
| `ECE_TRANS_180a22e.pdf` | `GTR22` | `un_gtr` |
| `OJ_L_202401257_EN_TXT.pdf` | `EU2024-1257` | `eu_oj_act` |
| `OJ_L_202601762_EN_TXT.pdf` | `EU2026-1762` | `eu_oj_act` |

If a PDF has no entry, the pipeline auto-detects the profile (2.3) and derives `doc_id`
from metadata, then writes a suggested entry to the manifest for a human to confirm.

### 2.2 Profiles: `pipeline/profiles/<family>.yaml`
Each profile declares, as data:

- `detect`: first-page and metadata signatures. Examples: `"Official Journal of the European Union"` / `ELI:` → `eu_oj_act`; `"Global Technical Regulation"` / `ECE/TRANS/180` → `un_gtr`; `ECE/TRANS/WP.29` / `"UN Regulation No"` → `unece_regulation`.
- `metadata`: regexes for title, number, series/amendment, date, issuing body, region.
- `layout`: header/footer strategy (`parity_aware: true` for OJ), footnote marker style (`(n)` vs superscript), numbering-column tolerance.
- `structure.levels`: ordered heading levels. Each level has a `regex`, a `style` predicate (relative size, bold, italic, centred, standalone line), `id_segment` template, `resets` (which counters reset), and `parent` rule. Examples:
  - EU: `PREAMBLE`, `RECITAL (n)`, `CHAPTER <roman>`, `SECTION <roman>`, `Article <n>`, article paragraph `<n>.` (scoped to its Article), point `(<n>)` / `(<a>)` / `(<i>)`, `ANNEX <roman>`, `Appendix <n>` (child of the current Annex).
  - GTR: `I.`/`II.` parts (`II. Text of the GTR` → BODY, `I.` → RATIONALE), lettered sections `A.`–`F.` in the rationale, rationale paragraphs `<n>.`, decimal clauses, `Annex <n>`.
  - UNECE Reg: today's rules (`Annex <L><n>[a]`, `Annex X - Appendix N`, `Appendix N`, decimal clauses).
- `terms`: how to locate the definitions/abbreviations sections **by heading title** (`Definitions`, `Abbreviations`, `Article 3 Definitions`), definition patterns, and inline-abbreviation patterns.
- `references`: the grammar list (2.6 below), self-reference words (`this Regulation`, `this GTR`, `this Annex`), back-references (`thereof`, `thereto`), external-document patterns.
- `equations`: math font names and the variable-glossary trigger (`where:`, `Where`).

Add `pyyaml` to `requirements.txt`, plus a JSON-schema check for profile files so a typo fails loudly.

### 2.3 Profile detection + manifest
`pipeline/profile.py`: score each profile's `detect` rules against page 0–1 text and PDF
metadata, pick the best, and record the score. If no profile matches well, use a
`generic` fallback profile (decimal clauses plus `Annex`/`Appendix` in any numbering,
relative-size headings). `output/<doc_id>/manifest.json` records the input file hash,
profile and score, page count, outline (bookmarks), per-phase counts and warnings, and
the pipeline git commit.

### 2.4 Per-document outputs
`output/<doc_id>/…` replaces flat `output/*.jsonl`. Reg 154's current files move to
`output/REG154.04/`. Keep a compatibility symlink or copy for one release so `app/` and
`kg_explorer.html` keep working until §8 lands.

### 2.5 Document identity nodes (fixes L2.3, L7.1)
Phase 0 emits a `Document` node (`doc_id`, title, number, series, date, issuing body, region,
family, source file, sha256) and the existing schema's `Standard` → `Version` chain.
Document `HAS_DIVISION` / `HAS_PART` → top-level units. This is the root of each graph.

### 2.6 Reference grammar as profile data (used by Phase 4)
Each grammar entry has a `pattern`, a `kind` (paragraph, article, annex, appendix, table,
figure, equation, point), `list_expansion: true` (handles `Articles 27, 33 and 34`,
`paragraphs 32. to 37.`), and `qualifier_patterns` (`of Annex IV`, `to Annex II`,
`of this GTR`, `thereof`).

---

## 3. Phase 1 — Span-level layout extraction (fixes L3.1–L3.4, L3.9–L3.11)

1. **Keep spans, not just lines.** Write `spans.jsonl` with text, bbox, font, size, flags (bold/italic), and baseline origin. Lines in `lines.jsonl` reference their spans. Later phases need style (headings), sub/superscripts (equations, footnote markers) and fonts (math).
2. **Merge same-baseline fragments** (L3.3). Join "lines" on the same page whose baselines differ by less than 1.5 pt and whose x-gaps are smaller than a column gap. This turns justified word-per-line output back into real lines. The column gap is learned per page from the x-gap histogram, so the numbering column and body column stay separate.
3. **Body-style statistics per document.** Compute the dominant body size, font and left margin(s), and the **numbering column** (x-cluster of lines that start with a number token). Store them in the manifest. Phase 2 heading predicates are relative to these numbers (e.g. `size >= body * 1.2 OR bold OR (italic AND centred AND standalone)`), never absolute 12 pt (L4.2).
4. **Header/footer detection v2** (L3.1). Normalise the text (digits → `#`, dates → `<date>`), then count how often a text signature appears **within a top/bottom band** of the page, separately for odd and even pages and for portrait vs landscape. Strip signatures that appear on ≥ 60 % of pages in their parity/orientation group. Also strip the PDF's per-page `ELI:` / `OJ L` lines when the profile says so.
5. **Footnotes v2** (L3.2). A footnote block is: below a short horizontal separator rule (from `get_drawings()`), **or** in the bottom band with size < body size, **and** starting with a marker (`(n)` / superscript n / `*` / `†`). Footnote marker spans in the body (superscript or `(n)` immediately after a word) are recorded as `footnote_ref` so Phase 5 can add `HAS_FOOTNOTE` edges. Footnotes become `Footnote` nodes (`<doc>.FN-<n>@p<page>`) instead of being merged into the open clause's text.
6. **Unicode normalisation** (L3.9). Keep `raw_text`, and add `text` = NFKC (math italic → ASCII), with soft hyphens removed, NBSP → space, curly quotes kept but regexes made quote-agnostic, and line-end hyphen joins. Thousands separators (`10 000`) are kept but recognised by numeric regexes.
7. **Chemical normalisation is profile-gated** (L3.11). On for `unece_regulation`, and tested against EU vehicle-category tokens (`M1`, `N1`, `C1`) so they never merge.
8. **Outline capture** (L3.10). Store `doc.get_toc()` in the manifest. Phase 2 uses it to cross-check division boundaries and their pages, never as the only source.
9. **Text-layer check** (L3.12). If a page has an image covering more than 80 % of it and fewer than N characters, record `needs_ocr`. The doc-level QA flags it; no OCR is added.

## 4. Phase 1b — Region classification (fixes L3.5–L3.8)

Classify each block or region on each page as `text | table | figure | form | equation |
footnote | toc`, so Phase 2 only builds clause text from `text` regions and the others get
their own extractors:

- **table:** `page.find_tables()` (PyMuPDF), plus a caption anchor (`Table <id>[:.]` within N pt above). Covers the Euro 7 annex tables, GTR Tables 1–3 and Reg 154 `Table A8/5`.
- **figure / flowchart:** a dense cluster of vector drawings or a large image, plus a `Figure <id>` caption. Text inside the bbox is captured as `figure_labels`, not body text (GTR Fig. 1/2, Reg 154 p.617).
- **form:** dot leaders / `…` fill-ins, `x =`-grid tables, `SECTION I/II` certificate templates, or a profile hint (`Model information document`, `CERTIFICATE`). These become a `Form` unit with raw text and are not parsed into clauses (GTR Annex 1, EU 2026/1762 Annex II App. 2).
- **equation:** see §7.
- **toc:** dot-leader density **or** an outline match on early pages. This replaces the "first 10 pages" rule (L4.8).

Output: `regions.jsonl` (page, bbox, kind, caption, anchor line ids).

---

## 5. Phase 2 — Profile-driven structural parse (fixes L4.1–L4.12)

### 5.1 Generic unit model
Replace "clause with a decimal number" with a **Unit** record. It has `unit_type` (Part,
Chapter, Section, Article, ArticleParagraph, Point, Recital, Annex, Appendix, Clause,
Form, Preamble), `local_label` as printed (`4`, `IV`, `(48)`, `6.3.2.`), `qualified_id`,
`parent_id`, `title`, `body_text`, `page_start`/`page_end`, and `numbering_scope`.

`Clause` stays the `unit_type` for decimal-numbered paragraphs, so Reg 154 output is
unchanged apart from the extra fields.

### 5.2 Stack machine driven by profile levels
- A heading is a line that matches a level's regex **and** satisfies its style predicate (relative to the document's body statistics) **and** is standalone (no prose after it, or a title on the next line).
- Each level declares which counters it resets. EU `Article` resets the paragraph counter, which removes the 73 Euro 7 merges (L4.3). GTR `II.` starts the BODY tree and `I.` the RATIONALE tree, which removes the 24 GTR merges.
- `Appendix N` resolves to the **current Annex's** appendix when the profile says so (EU), and to `APPENDIX-N` of the regulation otherwise (Reg 154) (L4.10).
- Parenthesised points `(1)`, `(a)`, `(i)` become `Point` units **when the profile enables them** (EU Article 3 definitions, recitals). Otherwise they stay inline as today (L4.4).
- **Numbering-column rule** (L4.6, L4.7): a decimal or Article-paragraph number is a heading only if it starts at the document's numbering column (± tolerance) **and** is a plausible successor of the open stack (same depth +1, child, or ancestor-sibling). Implausible jumps (e.g. `2032.` after `5.`) are kept as body text and logged. `dedupe()` stays only as a last-resort safety net, and every merge it makes counts as a QA failure, not a silent fix.
- **Title vs body** (L4.9): a heading line's trailing text, or the next line if the heading is number-only and that line is short with no closing period, becomes `title`.

### 5.3 Qualified-id scheme v2 (fixes L4.11, L7.3; update `schema.yaml`)

```
<doc_id>.<unit-path>
REG154.04.ANNEX-B6.APP1.2.4          (unchanged)
GTR22.BODY.6.3.2                     GTR text §6.3.2   ("of this GTR" resolves here)
GTR22.RATIONALE.C.14                 rationale ¶14 under section C
GTR22.ANNEX-3.2.1.1
EU2024-1257.PREAMBLE
EU2024-1257.RECITAL-17
EU2024-1257.CH-II                    chapter (container only)
EU2024-1257.ART-4.6                  Article 4(6)
EU2024-1257.ART-3.PT-48.b            Article 3, point 48(b)
EU2024-1257.ANNEX-IV
EU2026-1762.ANNEX-II.APP-2
EU2024-1257.FN-23
```

Articles are numbered globally in EU acts, so `ART-n` is not nested under its chapter in the
id. The Chapter → Article containment is an edge. This keeps `Article 4(2)` references
trivial to resolve.

### 5.4 Labels
Depth labels become profile-defined. Reg 154 keeps Section/Subsection/Provision. EU uses
Article/Paragraph/Point. `Paragraph` (has_body) stays universal.

---

## 6. Phase 3 — Terms generalized (fixes L5.1–L5.7)

1. **Locate sections by title, not number.** The definitions scope is any unit whose title matches the profile's definition-heading regex (`Definitions`), plus its descendants. Abbreviation sections are found the same way (`Abbreviations`, `General abbreviations`, `Chemical symbols`). This removes the hard-coded `2.1.` / `2.2.` / `3.` / `BODY` (L5.1, L5.3).
2. **Definition patterns** (profile list, quote-agnostic: `"` `“` `”` `‘` `’`). L5.4/L5.5 are fixed by these:
   - `Q(term)Q [ (ABBR) | or Q(ABBR)Q ] (means|refers to|is|shall mean) gloss`
   - The term and abbreviation may also come from `(UBEcertified)`-style symbol abbreviations.
3. **Abbreviation tables:** two-column split by x-gap clustering per table region (L5.2), using the Phase 1b `table` region when one exists.
4. **Inline abbreviations:** harvest `X (ABBR)` and `‘x’ or ‘ABBR’` occurrences from definitions **and** body text. These go into `abbreviations.jsonl` with `source: inline` and the defining unit as `source_clause`. For EU acts this is the main abbreviation source.
5. **Imported definitions** (L5.6): `the relevant definitions in <ExternalDoc> apply` and `as defined in <ExternalDoc>` produce an `IMPORTS_DEFINITIONS_FROM` edge (Document/Unit → ExternalDocument), and Definition `defined_by_reference: true` with `external_ref`.
6. **Definition scope** (L5.7): `scope_unit` = nearest unit stating "For the purposes of this <Annex|Regulation|…>". Default is the document.
7. Node ids get a document namespace: `<doc_id>.ABBR:<surface_form>` and `<doc_id>.DEF:<unit>` (L7.3). Merging and `SAME_AS` across documents stay deferred.

---

## 7. Equations as nodes (fixes L8.1–L8.9)

### 7.1 Schema additions (`schema.yaml`)

**`Equation` node** — id `<unit_qualified_id>.EQ-<n>` (n = order within the unit). If the
document prints a number, the id becomes `…EQ-(<label>)` and `label` is stored as well.

| Property | Meaning |
|---|---|
| `kind` | `equation` \| `inequality` \| `decision_rule` \| `assignment` (e.g. "SOCE shall be set to 100 per cent") |
| `raw_text` | exactly as extracted (math-italic Unicode kept) |
| `linear` | normalised linear form, e.g. `SOCE_measured = UBE_measured / UBE_certified * 100` |
| `latex` | best-effort LaTeX, e.g. `SOCE_{measured} = \frac{UBE_{measured}}{UBE_{certified}} \times 100` |
| `lhs` | left-hand symbol (if any) |
| `symbols` | list of normalised symbols used |
| `source` | `text_layer` \| `image` \| `inline` |
| `parse_status` | `parsed` (sympy round-trips) \| `partial` \| `image_only` \| `unparsed` |
| `page`, `bbox` | location |
| `image_path` | crop under `output/<doc_id>/equations/<id>.png`, **always** written so a reviewer can compare the parse to the rendering |
| `context_before` | the lead-in sentence ("…shall be calculated as follows:") |
| `condition` | case text when the equation is one branch of "In cases where…" / "for PEVs" |

**`Variable` node** — id `<doc_id>.VAR:<normalised_symbol>`, with `symbol` (normalised,
`UBE_measured`), `display` (`UBEmeasured`), `latex`.

The **meaning lives on the edge**: the same symbol (`s`, `N`, `A`, `i`) means different
things in different equations. A per-document node keeps symbols queryable without
pretending they're globally unique.

**Edges**

| Edge | From → To | Properties / meaning |
|---|---|---|
| `HAS_EQUATION` | Unit → Equation | equation appears in that clause / article paragraph / annex unit |
| `DEFINES` | Equation → Variable | the lhs symbol (what the equation computes) |
| `USES` | Equation → Variable | rhs symbols, `role: operand` |
| `DESCRIBED_AS` | Equation → Variable | from the "where:" glossary: `description`, `unit` (`Wh`, `km`, `per cent`), `index_meaning` (`i is the index number of the considered battery`) |
| `DEPENDS_ON` | Equation → Equation | derived: an rhs variable of A is the lhs of B **in the same document**. Gives computation chains, e.g. `UBE_measured,nc → UBE_measured → SOCE_measured → x_i → X_tests → pass/fail` in GTR 22. |
| `USES_TABLE` | Equation → Table | "where the parameters tP1,N … are taken from Table 3" |
| `REFERENCES` (kind=equation) | Unit → Equation | "according to the equation in paragraph 7.1." resolves to the Equation(s) of that unit; "(see equation (3))" resolves to the label |
| `SAME_TERM_AS` (candidate) | Variable → Abbreviation/Definition | `SOCE` variable ↔ `SOCE` abbreviation / "State of certified energy" definition. Stored with `status: candidate`, same "never guess" rule. |

### 7.2 Detection (Phase 1b, `equation` regions)
An equation region is a vertical cluster of lines (gap < 1.5 × line height) where at least
one of these holds:

- spans use a math font (`CambriaMath`, `SymbolMT`, `*Math*`, profile-listed);
- text contains Mathematical Alphanumeric Symbols (U+1D400–U+1D7FF) or operators `= ≤ ≥ < > × ∙ · ∑ √ ∆ ∫ ±`;
- a thin horizontal vector rule (fraction bar: height < 1.5 pt) lies inside the cluster;
- an image of equation size (h < 60 pt, w > 40 pt) sits between a lead-in (`as follows:`, `equation below`, `calculated using`, `:` line end) and a `where:` line, or is centred in the body column.

It must **not** be prose: a long line with ≥ 6 dictionary words and no math font is
rejected. Each region records its anchor (preceding text line) so Phase 2 can attach it
to the right unit, and its lines are **removed from the body text** and replaced with the
placeholder `[EQ:<id>]`. The body stays readable and search no longer matches garbage.

### 7.3 Reconstruction (2-D layout → linear / LaTeX), Phase 3b
Deterministic, rule-based, on the span geometry:

1. **Baseline grouping:** spans with size < 0.8 × base size and baseline offset above/below give `^{}` / `_{}`. This fixes `FECS,c,1` → `FE_{CS,c,1}` and `6x1011` → `6x10^{11}` (L8.3, L8.9).
2. **Fractions:** for each fraction-bar rule, the spans whose x-range overlaps the bar and sit just above it form the numerator, and those just below form the denominator. Recurse for nested fractions (L8.2).
3. **Big operators:** `∑` / `∏` with stacked small spans above and below become limits (`\sum_{i=1}^{n}`) (L8.4).
4. **Roots:** a `√` glyph plus the extent of the overline rule gives the radicand (GTR §6.3.3 standard deviation).
5. **Brackets / multi-line:** delimiters `( [ {` spanning several lines; `=` alignment for multi-line derivations.
6. **Symbol normalisation:** NFKC math italic → ASCII, then join a base symbol with its subscript into `UBE_measured`. Greek letters and `∆` are kept as names (`Delta_E_REESS,i`).
7. **Validation:** try `sympy.parsing` on `linear` (optional dependency, deterministic). If it round-trips, mark `parsed`, otherwise `partial`. Nothing is dropped.
8. **Classification:** `≤ ≥ < >` give `inequality`. Inequalities inside "Pass the family if … / Fail …" give `decision_rule`, with `outcome` (`pass` / `fail` / `continue`).

### 7.4 Variable glossaries ("where:" blocks)
After an equation region, parse the following `where:` / `Where` block as a two-column
table (symbol column x-cluster | description column), reusing the Phase 3 abbreviation
column splitter. Patterns:

- `<sym> is the <description>, <unit>;`
- `<sym> <description> [<unit>]`
- `<sym> (<unit>) is the …`
- `and:` continuations

Units come from a small profile-level unit list (`Wh, kWh, km, g/km, mg/km, #/km, per cent, %, litres, s, K, °C`). The block's lines are removed from the body text and become `DESCRIBED_AS` edges.

### 7.5 Image-only equations
1. Always crop to PNG and create an `Equation` node with `source: image` and `parse_status: image_only`, linked via `HAS_EQUATION`. Its `where:` glossary is still parsed, so the variables and their `DESCRIBED_AS` edges exist even when the formula itself is an image (Reg 154 p.85 OBFCM accuracy).
2. **Optional, off by default:** a math-OCR adapter (e.g. `pix2tex`) behind `--equation-ocr`. It is an ML model, so it conflicts with the "no ML" principle. Its output would be stored as `latex_ocr` with `parse_status: ocr_unverified`, never as `latex`. **Decision needed** (see §11).

### 7.6 Inline equations
Prose-embedded expressions (`A = (1 + tolerance)`, `L2 + L4 (mg/km)`, `CO2 test-i`) are
**not** separate nodes in this plan's first cut. Their sub/superscripts are still fixed
by 7.3 step 1 so the text is correct. They are a candidate for a later `inline: true` pass.

### 7.7 Equation acceptance targets (golden set)
- **GTR 22:** §5.2 virtual distance (1 fraction), §6.3.2 SOCE_measured / SOCR_measured (2 fractions), §6.3.3 `x_i`, `X_tests` (fraction with a sum), `s` (root of a fraction), pass/fail/continue (3 decision rules), Annex 3 `UBE_certified = UBE_measured × AF_PER` (×2), `UBE_measured,nc = ∑ ∆E_REESS,i`, and the OVC-HEV correction. Each must have the correct `lhs`, a `where:`-derived description for every symbol, and `DEPENDS_ON` chains as in 7.1.
- **Reg 154:** a 30-equation hand-checked sample stratified across Annexes B4–B8 and Appendix 2, plus 10 image-only equations. Targets: ≥ 90 % correct `lhs` and symbol sets, 100 % of equations with an image crop, 0 equation fragments left in `body_text` for the sample.
- **EU acts:** no display equations expected. Assert 0 false-positive equation regions in Euro 7's tables (`L2 + L4`, `6x1011`).

---

## 8. Phase 3c — Tables and figures at caption level (fixes L6.7, L3.5, L3.6)

`Table` / `Figure` nodes as already defined in `schema.yaml`, from Phase 1b regions:
`caption_id` as printed (`Table A8/5`, `Table 3`, `Table 1: …`), and a scoped id
`<unit>.TABLE-<n>`, because Euro 7 restarts numbering per Annex. Also `caption`,
`defining_unit`, `page`, `bbox`, and **`cell_text`** (flattened `find_tables()` output, as a
text property only: no structured values, which keeps the v1 non-goal). Edges: `HAS_TABLE`,
`HAS_FIGURE`. This makes the 663 Table/Figure references in Reg 154 resolvable and takes
table cell soup out of clause bodies. Structured table values and Constraints stay out of
scope (limitation §9).

---

## 9. Phase 4 — References generalized (fixes L6.1–L6.10)

1. **Detect external citations first.** This is a separate phase (`phase4a_external.py`), fully specified in **§9a**. Phase 4 reads its `external_mask.jsonl` and skips any internal-style match that overlaps an external citation's span, so "Annex 4 to UN Regulation No 49" is never resolved internally. This closes the false-positive class in L6.1.
2. **Article grammar** (L6.2): `Article <n>[(<p>)][, point (<x>)][, first subparagraph]` and plurals/lists (`Articles 7(1) and 10(1)`, `Articles 27, 33 and 34`). Resolves to `ART-n[.p][.PT-x]`.
3. **Roman / numeric annex grammar** (L6.3), lists (`Annexes I, II and III`), and appendix qualifiers `Appendix N (to|of) Annex X` (L6.6).
4. **Paragraph grammar without a mandatory trailing dot** (L6.4), plus lists and ranges (`paragraphs 32. to 37.` → expand the range only when both ends exist as siblings; otherwise unresolved) (L6.5).
5. **Qualifier resolution order:** explicit target (`of Annex IV`), then external (`of UN Regulation No 179`), then back-reference (`thereof` / `thereto` → the previously cited document in the same sentence), then self (`of this GTR` → the document's BODY tree), then the profile default scope (same division / same article).
6. **Targets:** Table/Figure (§8), Equation (§7.1), Footnote, and Recital refs. GTR's "paragraph 6.3.2. of this GTR" resolves into `GTR22.BODY`, not the rationale.
7. Output `references.jsonl` rows gain `kind` and `qualifiers`. They are internal only: external targets live in §9a's `citations.jsonl`. The "never guess" rule is unchanged.

---

## 9a. External documents & cited provisions (fixes L6.1, L6.9, L6.11, L5.6)

**Goal.** Every document the regulation points to outside itself becomes a node, together
with the specific article / paragraph / annex / table that is cited:

- regulations, directives, decisions, UN GTRs
- ISO/EN/SAE/IEC standards
- ECE/TRANS working documents, agreements, treaties

The cited external provisions often hold the actual requirement text, so this is the list
of outside text a requirement depends on.

**Decisions taken:**
- **All** external document kinds are recorded.
- A node is created for each external document **even if that document is also in `Document/`**.
- There is **no edge** into another document's graph; graphs stay separate.

### 9a.1 Evidence (survey of the 4 PDFs, 2026-10-12)

| Doc | UN Regs | GTRs | EU/EC acts | Directives | Standards | ECE/TRANS docs | Example pinpointed refs |
|---|---|---|---|---|---|---|---|
| Reg 154 | 67 mentions / 15 unique (**incl. itself, R154**) | 5 / 3 | 0 | 0 | 205 / **86** (EN-ISO 3405, ISO 4259…) | 672 (mostly the running header) | `paragraph 3.1.2. of Annex 5 of UN Regulation No. 83`, `Annex B6 to UN Regulation…` |
| GTR 22 | 4 (R154; "Global Technical Regulation **No. 22**" = **itself**) | 27 / 7 (`GTR15`, `UN GTR No.15`; false hits `GTR 57`, `GTR 1` = "of the GTR" + ¶ number) | 0 | 0 | SAE J1711 | 36 / 5 | `GTR15 Annex 8, Table A8/11 Step no. 1` |
| EU 2024/1257 | 24 / 10 | 3 | 80 / 24 | 17 / 8 | 0 | 0 | `Article 3, point 49, of Regulation (EU) 2018/858`, `Annex II to Regulation (EU) 2018/858`, TFEU `Article 114 thereof` |
| EU 2026/1762 | 33 / 2 (R179, R83) | 0 | 32 / 12 | 2 | 0 | 0 | `paragraphs 9.1 and 9.4 of UN Regulation No 179`, `Articles 7(1) and 10(1) of Regulation (EU) 2024/1257`, `Table 11 of Annex V thereto`, `Figure A1/1 thereof` |

Other observations:
- **EU footnotes** give the full title, adoption date, OJ reference and ELI URL, e.g. `(7) Regulation (EU) 2019/1242 … of 20 June 2019 setting CO2 … (OJ L 198, 25.7.2019, p. 202)`.
- **Shared-head lists** are common: `Regulations (EC) No 443/2009 and (EU) No 510/2011`.
- **`thereof` also appears in plain prose** ("combinations thereof").

### 9a.2 New phase `pipeline/phase4a_external.py` (runs before Phase 4)
- **Inputs:** `units.jsonl` (or today's `clauses.jsonl`), `footnotes.jsonl` (§3 step 5), the `Document` node, and the profile.
- **Outputs** in `output/<doc_id>/`: `external_docs.jsonl`, `external_provisions.jsonl`, `citations.jsonl`, `external_mask.jsonl`, and `external_citations.csv` (flat review list).

1. **Citation recognizer.** Profile-driven grammar, one entry per `doc_kind`:
   - `un_regulation`: `(UN )?Regulation No\.? N`, also `Regulation No N of the Economic Commission for Europe`, and series qualifiers (`, 07 series of amendments`)
   - `un_gtr`: `UN GTR No. N`, `GTR\d+`, `(UN )?Global Technical Regulation No N`. Guard: needs `No` or a digit attached to `GTR`, which rejects "of the GTR 57."
   - `eu_regulation`, `eu_implementing_regulation`, `eu_delegated_regulation`, and legacy `ec_regulation`: `(Commission (Implementing|Delegated) )?Regulation \((EU|EC|EEC)\) (No )?YYYY/N | N/YYYY`
   - `eu_directive`: `Directive (\(EU\) )?YYYY/N(/EC|/EEC)?`
   - `eu_decision`
   - `treaty`: TFEU
   - `unece_agreement`: the 1958 and 1998 Agreements
   - `unece_document`: `ECE/TRANS/…`
   - `standard`: `ISO|EN|EN-ISO|SAE|IEC|ASTM` plus a number, optional `-part`, `:year`
   - **Shared-head list expansion:** `Regulations (EC) No 715/2007 and (EC) No 595/2009`, `UN Regulations No 83 and No 179`.
   - **Exclusions:** the running header/footer (already stripped by §3 step 4), and the document's own cover / metadata block.
2. **Canonical ids + alias merge.** All spellings collapse to one id:
   - `EXT:UNR-83`, `EXT:UNGTR-15` (`GTR15` = `UN GTR No.15` = `Global Technical Regulation No 15`)
   - `EXT:EU.REG.2018-858`, `EXT:EU.IMPL.2020-683`, `EXT:EC.REG.715-2007`, `EXT:EU.DIR.2007-46`
   - `EXT:TFEU`, `EXT:ISO.3405`, `EXT:ECE.TRANS.WP29.AC3.57`

   Every surface form seen is kept in `aliases`. The series of amendments goes on the citation edge (`version`), not into the id.
3. **Self-citation filter.** `documents.yaml` gets `self_ids` per document: `REG154.04` → `EXT:UNR-154`, `GTR22` → `EXT:UNGTR-22`, `EU2024-1257` → `EXT:EU.REG.2024-1257`, `EU2026-1762` → `EXT:EU.IMPL.2026-1762`. A self match becomes an *internal scope qualifier* passed to Phase 4, not a node.
4. **Pinpoint (cited article / provision) parsing.** Scan left from the citation along the `of` / `to` / `,` connector chain, bounded to the sentence. Parse the chain into structured locators:
   - `article`, `paragraph`, `subparagraph`, `point`, `annex`, `appendix`, `table`, `figure`, `step`, `section`
   - Examples: `Articles 14(3), point (i), and 14(4), points (a), (q), (s), (u) and (v), thereof` (list + back-reference to EU 2024/1257), `Article 3, point 49`, `paragraph 3.1.2. of Annex 5`, `Appendix 1 of Annex 4`, `Table A8/11 Step no. 1`
   - Lists and ranges expand to one pinpoint each: `Articles 7(1) and 10(1)`, `paragraphs 9.1 and 9.4`, `points (a), (q), (s)`
   - `raw_text` is always kept.

   The qualifier-chain logic reuses and extends `OF_ANNEX_RE` / `OF_APPENDIX_RE` / `resolve_paragraph_scope` in `pipeline/phase4_references.py`.
5. **Back-references.** `thereof`, `thereto`, `of that Regulation` and `the said Directive` bind to the most recent external citation in the same sentence (or the previous sentence for "that Regulation"), **only when a locator comes right before them**. Plain prose `thereof` is ignored. Examples:
   - `Table 11 of Annex V thereto` → EU 2024/1257
   - `Article 114 thereof` → TFEU
   - `Figure A1/1 thereof` → UN R179 Annex 1
6. **Footnote enrichment.** When a citation carries a footnote marker, or a footnote starts with a citation, parse the footnote for:
   - `title` (text up to `(OJ`)
   - `adoption_date` (`of 30 May 2018`)
   - `oj_ref` (`OJ L 151, 14.6.2018, p. 1`)
   - `eli` URL
   - UN titles after `—` / `–` ("Uniform provisions concerning…")

   Each property records the footnote it came from.
7. **Role classification.** Deterministic cue phrases in the citing sentence, or in the document title / preamble for document-level roles:

   | role | cues |
   |---|---|
   | `amends` | amending |
   | `repeals` | repealing |
   | `implements` | for the application of, implementing, supplementing |
   | `legal_basis` | Having regard to |
   | `definition_source` | as defined in, definitions in … apply |
   | `requirement_source` | shall apply, shall comply with, in accordance with, according to, determined according to, as specified in |
   | `replaces` | replaces |
   | `cites` | default when no cue matches |

   `requirement_source` marks external text as a candidate for requirement generation.
8. **Masking for Phase 4.** Write per-unit character spans of each external citation plus its pinpoint chain to `external_mask.jsonl`. Phase 4 skips internal matches that overlap these spans.

### 9a.3 Schema additions (`schema.yaml`)

- **`ExternalDocument`**
  - `id`, `doc_kind`, `issuer` (UNECE WP.29, EU, ISO, CEN, SAE…), `number`, `year`, `title`, `adoption_date`, `oj_ref`, `eli`
  - `aliases[]`, `mention_count`, `first_cited_in`
  - `in_corpus` + `corpus_doc_id`: informational properties only, **no edge** to the other graph.
- **`ExternalProvision`** (the cited article / paragraph / annex / table)
  - id `<ext_id>#<locator-path>`, e.g. `EXT:EU.REG.2018-858#ART-3.PT-49`, `EXT:UNR-179#ANNEX-1.APP-2`, `EXT:UNGTR-15#ANNEX-8.TABLE-A8/11.STEP-1`
  - properties: `locator` (structured), `label` as printed, `raw_text`
- **Edges**

  | Edge | From → To | Properties / notes |
  |---|---|---|
  | `HAS_PROVISION` | ExternalDocument → ExternalProvision | — |
  | `CITES` | Unit → ExternalProvision (or → ExternalDocument when there is no pinpoint) | `role`, `raw_text`, `sentence`, `version`, `via` (`direct` / `back_reference` / `footnote`) |
  | `AMENDS`, `REPEALS`, `IMPLEMENTS`, `LEGAL_BASIS` | Document → ExternalDocument | document-level |
  | `IMPORTS_DEFINITIONS_FROM` | — | the edge in §6.5 becomes `CITES {role: definition_source}`, so there is one mechanism |

- **Ids are namespaced per document graph**, e.g. `EU2026-1762/EXT:UNR-179`. Each graph stays self-contained, and the shared `EXT:` suffix makes a future merge a simple join.

### 9a.4 Downstream
- **`build_viz_data.py` / explorer:** an "External documents" group in the tree, as ExternalDocument → provisions → citing units. Node colour per `doc_kind`.
- **`app/kg_retrieval.py` (`build_structured_prompt`):** adds an "External provisions referenced" block for matched units: document title, pinpoint, role, footnote title and ELI.
- **`pipeline/phase5_assemble.py` (`build_nodes` / `build_edges` / `validate`):** emits the new node and edge types, with the same referential-integrity check.
- **`external_citations.csv`:** one row per (external doc, provision), with mention count, roles and citing units. This is the hand-off list of documents to acquire next.

### 9a.5 Expectations (go into §11; counts to verify by hand before freezing)
- **Unit tests:** each grammar entry; GTR15 alias variants; the self filter; `GTR 57` rejection; shared-head list expansion; pinpoint chains (`Articles 14(3), point (i), and 14(4), points (a), (q), (s), (u) and (v), thereof`, `paragraph 3.1.2. of Annex 5 of`, `Table 11 of Annex V thereto`); plain-prose `thereof` ignored; footnote parser (OJ ref, ELI, date); role cues; mask overlap with Phase 4.
- **`EU2026-1762`:**
  - External docs include UNR-179, UNR-83, EU.REG.2024-1257, EU.REG.2018-858, EU.IMPL.2020-683, EU.IMPL.2025-1706, EU.REG.2016-679, EU.REG.2018-1725 and TFEU.
  - UNR-179 provisions include ¶3.0, 4.4, 7, 7.1, 7.1.3, 7.2, 8, 9.1, 9.4, 10, point 3.7.19, Annex 1 (+ App 1–3), Annex 4 App 1–2, and Annex 5.
  - EU.REG.2024-1257 provisions include Art. 4(2), 4(5), 5, 7(1), 10(1), 14(1), 14(3)(i), 14(4)(a/q/s/u/v), and Annex V Table 11.
  - `IMPLEMENTS` → EU.REG.2024-1257.
  - **0** of these resolved internally.
- **`EU2024-1257`:**
  - ~24 EU acts, 8 directives, ~10 UN Regs, 3 GTRs, and TFEU Art. 114 (`legal_basis`).
  - `REPEALS` → 715/2007, 595/2009, 582/2011, 2017/1151, 2017/2400, 2022/1362.
  - `AMENDS` → 2018/858.
  - A footnote title for every footnoted act.
- **`GTR22`:** UNGTR-15 (+ Annex 8, Tables A8/10 and A8/11 steps), UNR-154, SAE J1711, the ECE/TRANS AC.3 documents; **no** UNGTR-22 node (self); **no** `GTR 57` / `GTR 1`.
- **`REG154.04`:** UNR-83, 85, 101, 117, 177 …, ~86 standards, UNGTR-15/19; **no** UNR-154 node (self); the running header `ECE/TRANS/WP.29/GRPE/2025/15` is not counted 600+ times.

---

## 10. Phase 5, viz, app (fixes L2.4–L2.6, L7.1–L7.3)

- **Phase 5:** assemble every node type from the new files. Referential-integrity validation stays as is. Write `output/<doc_id>/nodes.jsonl`, `edges.jsonl`, `graph.graphml`, `graph.pickle`, and add per-type counts to the manifest.
- **`build_viz_data.py`:** take a `doc_id` argument and read the manifest. Build the tree from the **real** containment edges (Document → Part/Chapter/Annex → …) instead of the hard-coded "Annexes Part A/B/C" grouping. Group annexes using the profile's `viz.groups` (Reg 154 keeps A/B/C). Remove the direct `output/references.jsonl` read.
- **`kg_explorer.html`:** one file per document (`output/<doc_id>/kg_explorer.html`) plus a small `output/index.html` listing the documents. New node colours and detail panels for Article, Recital, Equation (rendered LaTeX via KaTeX, with the crop image shown next to it), Variable, Table, Figure and ExternalDocument.
- **`kg_illustrate.py`:** drop the `REG154.04.` prefix logic. Derive the label from the node's `unit_type` / `local_label`, and the doc label from the `Document` node. Add `--doc`.
- **`app/`:** document selector (from `output/*/manifest.json`), with `STANDARD_LABEL` from the Document node. Search also covers Equation `linear` / Variable descriptions. The prompt builder includes the equations attached to matched units (linear + LaTeX + variable glossary).

---

## 11. Tests & QA (fixes L7.4, L7.6)

1. **Per-document expectations** in `tests/expectations/<doc_id>.yaml`. These are hand-verified counts and spot facts, checked by `test_integration` for every PDF that has an expectation file (PDFs without one still get invariant checks):

   | doc_id | Expectations (to verify by hand before freezing) |
   |---|---|
   | `REG154.04` | today's numbers (56 divisions, 3,737 units ±2 %, 116 abbr, 151 defs) must not regress |
   | `GTR22` | Parts I + II; rationale sections A–F, ¶1–60; BODY §1–7; 23 definitions (3.1–3.23); 11 abbreviations (§4); 3 annexes; Tables 1–3; Figures I/1–I/3, 1, 2; equations per §7.7; **0 dedupe merges** |
   | `EU2024-1257` | 7 chapters, 21 articles, 77 definition points in Art. 3, 6 annexes, Annex tables I:9, II:3, III:5, IV:2, V:12; recital count; **0 dedupe merges**; no header/footer text (`ELI:`, `OJ L`) in any body |
   | `EU2026-1762` | 7 recitals, 9 articles, 4 annexes, 8 appendices (I:3, II:2, III:3), Annex IV Tables 1–2, certificate as one `Form` unit; external refs to UN R179 ≥ 20 and resolved internally = 0 |

   External-citation expectations for all four documents are listed in **§9a.5** and go into the same files.
2. **Generic invariants (all docs):** `qualified_id` matches `^<doc_id>\.`. No orphans. No duplicate ids. `dedupe()` merge count = 0 is asserted for docs with expectations. No body text contains a stripped header/footer signature. Every `REFERENCES` row targeting `EXT:` has `to` = an ExternalDocument node. Every Equation has an image crop.
3. **Misattribution guard** (the blind spot noted in `PHASE1_2_NOTES.md`): expectations include 5–10 `unit → parent` spot facts per document (e.g. `EU2024-1257.ART-4.6` parent is `ART-4`; `REG154.04.BODY.8.1.3` parent is `BODY.8.1`).
4. **Unit tests per new module:** profile loader/detector, line merger, header/footer v2 (odd/even fixture), footnote v2, heading predicate, numbering-column plausibility (the `2032.` case), each reference grammar entry, definition patterns (one fixture per quote/verb form above), equation reconstruction (synthetic span layouts for a fraction, sub/superscript, sum with limits, root), and the where-block parser.
5. **Phase 6 QA report** per document (`output/<doc_id>/qa_report.md`): coverage (body chars vs page chars excluding stripped regions), resolution rates by reference kind, unresolved list, merge list, equation parse-status breakdown, and the outline-vs-parsed division diff.

---

## 12. Implementation order (milestones)

Each milestone ends with all tests green and Reg 154 output unchanged except where a
change is intended and documented.

| # | Milestone | Main changes | Done when |
|---|---|---|---|
| M1 | **Plumbing** | `documents.yaml`, profile loader/detector, `pipeline/run.py`, per-doc output dirs, `doc_id` threaded through every phase, `Document` node; Reg 154 profile reproduces today's output byte-for-byte (except paths) | `REG154.04` regression test passes from the new runner; tests no longer hard-code `REG154` |
| M2 | **Layout v2** | spans.jsonl, same-baseline merge, body statistics + numbering column, header/footer v2, footnotes v2, unicode normalisation, outline capture | EU docs: headers/footers stripped, footnotes tagged; GTR word-per-line gone |
| M3 | **Regions** | tables / figures / forms / toc classification (equations come in M6) | no table cell text in any clause body for the 4 docs |
| M4 | **Structure v2** | Unit model, profile levels, scoped numbering, points/recitals, numbering-column plausibility, title/body split, id scheme v2, `schema.yaml` v0.2 | all four expectation files' structure counts pass; 0 dedupe merges for the 3 new docs |
| M5 | **Terms v2** | title-located sections, definition pattern set, inline abbreviations, imported definitions, scope | GTR 23/23 defs + 11 abbr; Euro 7 77/77 defs; 0 junk abbreviations |
| M6 | **Equations** | equation regions, 2-D reconstruction, where-block parser, image crops, Equation/Variable nodes + edges, body placeholders | §7.7 targets met |
| M7a | **External citations** (§9a) | `phase4a_external.py`: grammar, canonical ids, self filter, pinpoints, back-refs, footnote enrichment, roles, mask; ExternalDocument/ExternalProvision nodes + CITES/AMENDS/REPEALS/IMPLEMENTS/LEGAL_BASIS edges. Depends on M1 (`self_ids`), M2 (footnotes, header stripping), M4 (units). Optional early win: steps 1–3 and 6 can run on today's Reg 154 `clauses.jsonl` | §9a.5 expectations pass for all 4 docs |
| M7 | **Tables/Figures + References v2** | caption-level Table/Figure nodes, external docs, Article/roman/list grammars, qualifier chain, equation/table refs | Reg 154 ≥ 90 % internal resolution incl. Table/Figure; EU docs ≥ 90 % internal, 0 internal false positives on the external sample |
| M8 | **Viz + app** | doc-aware viz data, explorer per doc + index, illustrate `--doc`, Streamlit doc selector, equation rendering | each doc browsable; prompts cite the right document |
| M9 | **QA** | Phase 6 report per doc; update README, `task.md`, `PHASE1_2_NOTES.md` → `NOTES.md` | QA reports committed for all 4 docs |

M2 and M3 can be built in parallel. M6 depends on M2 (spans) and M3 (region framework).
M7's equation references depend on M6. M7 consumes M7a's `external_mask.jsonl`, so M7a comes first.

---

## 13. Decisions needed from you

1. **Math OCR for image-only equations:** keep "no ML" (crop + `image_only` + parsed glossary only), or allow an opt-in `pix2tex` adapter whose output is marked `ocr_unverified`? *Default taken in this plan: no ML, adapter left as a stub.*
2. **`doc_id` naming:** keep `REG154.04` for Reg 154 (no churn), or rename everything to a uniform `UNR154.04` style? *Default: keep.*
3. **EU points as nodes:** make every `(a)`/`(i)` point a node (finer citations, many more nodes), or only numbered points `(1)…(n)` in Articles 3/definitions and recitals? *Default: numbered points + recitals only; lettered points stay inline as in v1.*
4. **GTR Part I (rationale):** include it in the graph as a `RATIONALE` tree (non-normative, flagged `normative: false`), or skip it? *Default: include, flagged.*
5. **New dependencies:** `pyyaml` (required), `sympy` (optional, for equation validation). OK?
6. **Table cell text:** store flattened `cell_text` on Table nodes (searchable, not structured), or keep tables caption-only as in v1? *Default: store `cell_text`.*
7. **Standard ids:** should ExternalDocument ids for standards include part and year (`ISO 8178-1:2020`), or only the base number (`ISO 8178`)? *Default: id = number plus part (`EXT:ISO.8178-1`); the year goes on the citation edge's `version`.*

**Already decided (2026-10-12):** every kind of external document is recorded as a node. An external document that is also in `Document/` still gets its own node, and there is no edge into the other document's graph (§9a).

---

## 14. Implementation status (2026-10-12)

All milestones M1–M9 (incl. M7a) are implemented; `python -m pipeline.run --all`
builds the four graphs and every document passes its invariants and its
`tests/expectations/<doc_id>.yaml` (Reg 154 30/30, GTR 22 61/61,
EU 2024/1257 62/62, EU 2026/1762 56/56). §13 defaults were taken as listed.

**Where the implementation deviates from this plan (and why):**

| Plan | Implemented | Why |
|---|---|---|
| §3.1 separate `spans.jsonl` | spans stored inside `lines.jsonl`, only for lines with mixed styles or math | halves the size; single-style lines don't need spans |
| §5.3 `GTR22.RATIONALE.C.14` | `GTR22.RATIONALE.14` (section `SEC-C` is a *transparent* parent) | rationale paragraphs are numbered 1–60 across sections, so references ("paragraphs 32. to 37.") resolve without knowing the section |
| §9a.2 `EXT:EU.IMPL.2020-683`, `EXT:EU.DIR.2007-46` | `EXT:EU.REG.2020-683` (+ `subtype: implementing`), `EXT:EC.DIR.2007-46` (org as printed) | a bare "Regulation (EU) 2020/683" and "Commission Implementing Regulation (EU) 2020/683" must be one node |
| §4 `Form` unit | `is_form: true` on the Annex/Appendix whose title matches `form_titles`; its numbered fields stay unparsed text | keeps the division as the node people cite |
| §6.5 `IMPORTS_DEFINITIONS_FROM` edge | `CITES {role: definition_source}` (as §9a.3 already proposed) + `definition_imports` in the manifest | one mechanism |
| §9 resolution by building target ids | lookup in indexes built from parsed units (annex label, (annex, appendix), container + number, article number) | profile-agnostic; no Reg-154-shaped id strings |
| §8 table id `<unit>.TABLE-<n>` | `<division unit>.TABLE-<caption number>` (uncaptioned: `<unit>.TABLE-U<n>`) | captions are what references cite, and EU annexes restart numbering |
| §2.4 compatibility copy of flat `output/*.jsonl` | removed; app, explorer, illustrate all read `output/<doc_id>/` | §10 landed in the same change |

**Not met / open:** §7.7 Reg 154 30-equation hand audit not done (52% of its
535 equations are sympy-`parsed`; the rest `partial`, each with a crop);
image-only equations are detected only when framed by a lead-in or "where";
Reg 154 keeps 15 dedupe merges (listed in its QA report).
