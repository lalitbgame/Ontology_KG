# Limitations of the Current Workflow for Multi-Document Ingestion

The pipeline (`pipeline/phase1_extract.py` … `phase5_assemble.py`, `build_viz_data.py`,
`kg_illustrate.py`, `app/`) was built and tuned for one document only:
**UN Regulation No. 154, 04 series** (`Document/154-04 without 1C 1.pdf`). This file
lists what stops it from producing a correct knowledge graph for the other documents
now in `Document/`, and for regulatory PDFs in general.

All numbers below come from running the **unchanged** pipeline on each new PDF
(2026-10-12), with output written to a scratch directory, not `output/`.

## 0. The corpus

| File | Document | Pages | Family / layout style |
|---|---|---:|---|
| `154-04 without 1C 1.pdf` | UN Regulation No. 154, 04 series (WLTP), GRPE working draft | 668 | UNECE Regulation (Times, 9.8 pt body, 14.3 pt bold headings, decimal clauses, Annex `A1`/`B6a`) |
| `ECE_TRANS_180a22e.pdf` | UN GTR No. 22: In-vehicle Battery Durability (ECE/TRANS/180/Add.22) | 32 | UN GTR (Part I *rationale* numbered 1–60 under `A.`–`F.`, Part II *text* numbered 1.–7., Annexes `1`–`3`) |
| `OJ_L_202401257_EN_TXT.pdf` | Regulation (EU) 2024/1257 (Euro 7) | 49 | EU Official Journal act (recitals, Chapters I–VII, Articles 1–21, Annexes I–VI, mostly tables, landscape pages) |
| `OJ_L_202601762_EN_TXT.pdf` | Commission Implementing Regulation (EU) 2026/1762 (brake particle emissions) | 17 | EU Official Journal implementing act (Articles 1–9, Annexes I–IV each with Appendices, certificate form) |

## 1. What happens today when the new documents are run

| Metric | Reg 154 (baseline) | GTR 22 | EU 2024/1257 | EU 2026/1762 |
|---|---:|---:|---:|---:|
| Header/footer patterns stripped | 2 | 2 | **0** | 3 |
| Footnote lines tagged | yes | 4 | **0** | **0** |
| Divisions found | 56 | **1** (should be ~6: Part I, Part II, Annexes 1–3) | **1** (should be 7 chapters, 21 articles, 6 annexes) | **1** (should be 9 articles, 4 annexes, 8 appendices) |
| Clauses | 3,737 | 114 (24 merged duplicates) | **15** (73 merged duplicates) | 24 |
| Abbreviations | 116 | 28, **all garbage** (table cells from Annex 3) | 0 (should be ~60 inline) | 0 |
| Definitions | 151 | 18 of 23 | **0** of 77 | 0 |
| References resolved | 73 % | **14 %** | **0 %** | **15 %** |
| Qualified-id prefix | `REG154.04` | `REG154.04` (**wrong**) | `REG154.04` (**wrong**) | `REG154.04` (**wrong**) |

So the current workflow does not generalize. In practice it produces a wrong graph for
every document except Reg 154. The causes are grouped below.

---

## 2. Hard-coded single-document assumptions

| # | Limitation | Where | Effect on new docs |
|---|---|---|---|
| L2.1 | Qualified-id prefix `REG154.04` is a string literal | `phase2_parse.py` (`division_root`, `parse`), `phase4_references.py` (`make`), `phase3_terms.py` (`REG154.04.BODY.2.1`), `kg_illustrate.py`, `app/kg_retrieval.py` (`STANDARD_LABEL`), `tests/test_integration.py` (`QUALIFIED_ID_RE`) | Every document gets Reg 154 ids. Graphs from two documents could never coexist, and ids give the wrong provenance. |
| L2.2 | Default input/output paths are fixed (`Document/154-04 without 1C 1.pdf`, `output/*.jsonl`) | every phase's `PDF_PATH` / `*_PATH` constants | Running a second document overwrites the first document's outputs. There is no per-document output folder and no batch runner. |
| L2.3 | `Standard` / `Version` / `Division` nodes are never populated, and no document metadata is extracted (title, number, series, issuing body, date, region) | `phase5_assemble.py` | The graph has no document identity node. You can't tell which regulation a clause belongs to, except by the id string. |
| L2.4 | Viewer and illustration layer assume Reg 154's own TOC: "Annexes Part A/B/C", `annex_group()` = first letter of annex code, root label `"UN Regulation No. 154 — 04 series"`, `DOC_LABEL_DEFAULT` | `build_viz_data.py`, `kg_illustrate.py`, `pipeline/templates/graph_template.html` | Roman (`ANNEX-IV`) or numeric (`Annex 1`) annexes crash `annex_group()` or land in the wrong bucket. Articles, chapters and recitals have no place in the tree. |
| L2.5 | `build_viz_data.py` reads `output/references.jsonl` directly and takes no CLI arguments | `build_viz_data.py: run()` | Cannot be pointed at another document's output. |
| L2.6 | The Streamlit app loads one fixed `output/nodes.jsonl` and has no document selector | `app/kg_retrieval.py`, `app/streamlit_app.py` | Only one document can be queried, and the prompt always cites "UN Regulation No. 154". |

## 3. Phase 1 (layout extraction) limitations

| # | Limitation | Evidence |
|---|---|---|
| L3.1 | **Header/footer detection requires the same y-position on >90 % of pages.** OJ documents alternate header and footer sides between odd and even pages (`EN` at y=44 vs y=42 vs y=535; `ELI:` at y=813 / 377 / 42). Landscape pages (Euro 7 Annex V) move them again. | EU 2024/1257: **0 patterns stripped**, so `OJ L, 8.5.2024`, `EN`, `ELI: http://…`, `13/49` are mixed into clause bodies. |
| L3.2 | **Footnote detection uses an absolute ratio (<0.85 × page median size) plus the bottom 15 % of the page.** OJ footnotes are 8.5 pt against 9.6 pt body (ratio 0.885), and long footnote blocks start above the bottom 15 %. | EU docs: 0 footnote lines tagged. Footnotes such as `(23) Regulation No 117 …` are parsed as **definition points / recitals**, because they share the `(n)` marker format. |
| L3.3 | **Justified text is split into one line per word.** PyMuPDF returns each word as its own "line" with the same y0 (GTR p.2: `set` / `up` / `in` / `June` / `2012` …). Phase 1 never merges lines that share a baseline. | Word-per-line noise. A bare number token (`2012`) at the start of such a fragment can be mistaken for a clause number. |
| L3.4 | **Span-level information is discarded.** Only `line["spans"][0]["size"]` is kept. Font name, bold/italic flags, superscript/subscript size and baseline offsets are lost. | Headings can't be detected by style (EU headings are *italic*, not larger). Equation subscripts are flattened (`ECDC,first,i`), and footnote markers (`(23)`) look identical to text. |
| L3.5 | **No table detection.** Table cells are emitted as ordinary lines in reading order. | Euro 7 Annex I–V (≈20 tables) and GTR Tables 1–3 / Annex 3 parameter tables are dumped into clause bodies as cell soup. Phase 3 then reads the GTR Annex 3 table as an "abbreviation table" (all 28 abbreviations wrong). |
| L3.6 | **No figure/flowchart region detection.** Box labels inside vector diagrams are emitted as text. | GTR Fig. 1 / Fig. 2 flowchart labels (`YES`, `NO`, `Vehicle Procurement` …) land inside §6.5 and §7 bodies. Already noted for Reg 154 p.617. |
| L3.7 | **No form/template detection.** Questionnaires and certificate templates are parsed like normative text. | GTR Annex 1 vehicle-survey grid (`x = Exclusion Criteria`) and EU 2026/1762 Annex II App. 2 certificate (`0.1. Make: …`, `SECTION I/II`) create fake clauses `BODY.0.1`, `BODY.0.2.1`, … |
| L3.8 | **No equation awareness.** Math is flattened into prose (see §8). | — |
| L3.9 | **Unicode is not normalized.** Mathematical-italic letters (`𝑆𝑂𝐶𝐸𝑚𝑒𝑎𝑠𝑢𝑟𝑒𝑑`), soft hyphens (`mon­oxide`), non-breaking spaces (`ANNEX\xa0I`), curly quotes (`‘…’`, `"…”`) and thin-space thousands separators (`10 000`) are kept as-is. | Keyword search for `SOCE` misses math-italic occurrences, regexes miss curly-quoted definitions, and `Annex\s+` fails on NBSP in outline titles. |
| L3.10 | **The PDF outline (bookmarks) is ignored.** GTR 22, EU 2024/1257 and EU 2026/1762 all ship a usable outline (17, 7 and 13 entries) that names the annexes and appendices and gives their pages. | A free, reliable structural cross-check goes unused. |
| L3.11 | **Chemical-formula normalisation is tuned to Reg 154.** `normalize_chem` collapses any span of 1–2 capitals + digits separated by spaces. | Risk of corrupting EU identifiers such as `M1 N1` → `M1N1` or `C1 C2 C3`. Not yet measured. |
| L3.12 | **Scanned PDFs are not supported** (the "no OCR" decision). | Fine for the current corpus (all four have a text layer), but this is a precondition the code never checks or reports. |

## 4. Phase 2 (structural parsing) limitations

| # | Limitation | Evidence |
|---|---|---|
| L4.1 | **Division-heading regexes only know Reg 154's grammar:** `Annex <Letter><digits>[a]`, `Annex X - Appendix N`, `Appendix N`. They don't match `Annex 1` (GTR), `ANNEX I` … `ANNEX VI` (EU, roman, upper-case), `CHAPTER I`, `Article 4`, `SECTION I`, `Part I` / `I.` / `II. Text of the GTR`, or lettered rationale sections `A.`–`F.`. | All three new docs collapse into **one division, `BODY`**. |
| L4.2 | **Heading detection uses an absolute font-size threshold (`size >= 12`).** EU headings are 8.5 pt *italic, centred* (smaller than the 9.6 pt body). GTR headings are 12–14 pt bold. | Even with correct regexes, every EU heading would be rejected. Size has to be compared against the document's own body-text size and combined with weight/style/centring. |
| L4.3 | **Numbering is assumed to be one global decimal tree per division.** EU Articles restart paragraph numbering at `1.` in every Article. GTR Part I numbers rationale paragraphs 1–60, then Part II restarts at `1.`. | Duplicate ids collide and are silently **merged**: 73 merges in Euro 7 (Article paragraphs from different Articles glued together; `BODY.2` = 57,799 chars), 24 merges in GTR 22 (rationale ¶3 merged with GTR §3 *Definitions*). |
| L4.4 | **Parenthesised point numbering is not structure.** `(1)`, `(a)`, `(i)` always fall through into the parent body. In EU acts these carry the content: recitals `(1)…(n)`, definition points `(1)…(77)` in Article 3, sub-points `(a)…`. | Euro 7's 77 definitions sit inside one blob, so no individual citation such as "Article 3, point 48" is possible. |
| L4.5 | **No preamble / recital / citation / enacting-formula / signature handling.** | Euro 7's 8-page preamble and ~60 recitals all land in the `BODY` root (36,640 chars). |
| L4.6 | **The clause-number false-positive guard is weak.** It only rejects a line whose number is immediately followed by a digit. Years and quantities that wrap to the start of a line pass. | Euro 7 produces fake clauses `BODY.2032`, `BODY.2034`, `BODY.2036` from wrapped dates ("…29 November\n2032."). |
| L4.7 | **The numbering column is not used.** Real clause numbers sit in a fixed left column (Reg 154 x≈114, GTR x≈57–113, EU x≈67 with body at x≈89). Phase 2 accepts a number at any x. | Root cause of L4.6 and of the "wrapped cross-reference becomes heading" class already patched by `dedupe()`. |
| L4.8 | **TOC stripping assumes dot leaders on pages 0–10.** OJ acts have no TOC. GTR's TOC splits number / title / page number across 3 lines. | Works by accident for GTR. It would strip real content in a short document with a fill-in form in its first 10 pages. |
| L4.9 | **`title` vs `body_text` still isn't separated** (known since Phase 2). | Headings such as "Definitions" or "Scope" can't be used to locate sections by meaning, which Phase 3 needs to generalize (see L5.1). |
| L4.10 | **Annex appendices in EU acts are headed only `Appendix N`.** Their parent annex is implied by position. The current code maps a bare `Appendix N` heading to an *Appendix to the Regulation* (`APPENDIX-N`). | EU 2026/1762 Appendices 1–3 under Annex I / II / III would all collide as `APPENDIX-1..3`. |
| L4.11 | **Division ids assume the Reg 154 coding** (`ANNEX-B6.APP1`, `APPENDIX-3`). There is no representation for Part, Chapter, Section, Article, Recital, or Annex numbering that is roman or purely numeric. | No valid id scheme exists for 3 of 4 documents. |
| L4.12 | **Depth semantics are decimal-only** (`depth = count('.') + 1`) and labels are `Section` / `Subsection` / `Provision`. | Meaningless for Article → paragraph → point → sub-point hierarchies. |

## 5. Phase 3 (terms) limitations

| # | Limitation | Evidence |
|---|---|---|
| L5.1 | **Abbreviations are located by finding the literal lines `2.1.`, `2.2.` and `3.`.** This is Reg 154's numbering only. GTR has abbreviations in §4, with no 2.1/2.2. | In GTR it found `2.1.` / `2.2.` inside **Annex 3** and extracted a parameter table as 28 "abbreviations". In EU docs it finds nothing. |
| L5.2 | **The two-column split uses a fixed `x0 < 200`.** | GTR's §4 table has term x≈113 and expansion x≈227 (would work only by luck). Other layouts will fail. Column boundaries should be learned per table (x-gap clustering). |
| L5.3 | **Definitions are restricted to `division == "BODY"` and top-level clause `3`.** | GTR: works only by coincidence (§3 is Definitions). EU: definitions are numbered points `(1)…(77)` inside **Article 3**, so 0 found. |
| L5.4 | **`DEFINITION_RE` only accepts straight double quotes followed by `means`.** | Misses curly/single quotes (`‘emission type-approval’ means`, `"On-board SOCR” (SOCRread)`), `refers to` (GTR 3.4, 3.6, 3.7), `is` (Euro 7 (25), (26)), and the EU `‘X’ or ‘ABBR’ means` form. GTR: 18 of 23 found. EU: 0 of 77. |
| L5.5 | **Inline abbreviations are only captured as `"term" (ABBR) means`.** | Misses `‘conformity of production’ or ‘CoP’`, `"Certified usable battery energy" (UBEcertified) refers to`, and abbreviations introduced in running text ("Normal Usage Indices (NUI)"). For EU acts the inline form is the **only** source of abbreviations. |
| L5.6 | **Definitions imported by reference are not modelled.** | Euro 7 Art. 3: "the relevant definitions in Regulation (EU) 2018/858 apply". GTR 3.21/3.22: "as defined in UN GTR No. 15". |
| L5.7 | **Definitions have no scope.** | GTR Annex 3 redefines "battery" for that annex only ("For the purposes of this annex …"). A Definition node has no scope edge. |
| L5.8 | **Term reconciliation and term-usage linking (`MENTIONED_IN`, `SAME_AS`) are still deferred.** | The same term is defined in GTR 22 (`SOCE`, `MPR`), Euro 7 (`SOH`, `MPR` Annex II) and Reg 154 (`OVC-HEV`, `PEV`). Not needed until graphs are combined, but the per-document term nodes should be shaped for it now. |

## 6. Phase 4 (references) limitations

| # | Limitation | Evidence |
|---|---|---|
| L6.1 | **There is no notion of an external document.** Every `Annex N` / `paragraph N.` / `Appendix N` match is resolved *inside the current document*. | False links: "Annex 4 to UN Regulation No 49", "paragraph 7.2.1. of Annex 4 to UN Regulation No 49", "Annex 1 to UN Regulation No 179", "GTR15 Annex 8, Table A8/11", "Article 4 of Regulation (EU) 2018/858". They are unresolved today only because the internal division happens not to exist; once annexes are detected these **will resolve to the wrong node**. |
| L6.2 | **There is no `Article` reference grammar.** | `Article 4(2)`, `Article 3, point 49`, `Articles 7(1) and 10(1)`, `Article 14(3), point (i)`, `Article 18(5)` are all ignored. They are the main reference form in EU acts. |
| L6.3 | **Roman annex references are ignored.** `ANNEX_RE = Annex\s+([A-Z]?\d+[a-z]?)` requires a digit. | `Annex I`, `Annex III`, `Annexes I, II and III`, `Annex V, Tables 11 and 12` are all ignored, giving Euro 7 0 % resolution. |
| L6.4 | **`paragraph N.` requires a trailing dot.** EU acts write `paragraph 7.2 of UN Regulation No 179` and `paragraphs 7.1 and 7.2`. | Missed, or matched with the wrong extent. |
| L6.5 | **Plurals, lists and ranges are not expanded:** `paragraphs 32. to 37.`, `paragraphs 9.1 and 9.4`, `Annexes 4 and 12`, `Tables 1 and 2 of Annex III`. | Only the first item (or nothing) is captured. |
| L6.6 | **Qualified targets are ignored.** `Table 1 of Annex IV`, `Appendix 2 to Annex II`, `Appendix 1 of Annex II`, `point 3.7.19 of UN Regulation No 179`. | The scope-resolution window (60 chars after `paragraph`) only handles `of this Regulation`, `of Annex X`, `of Appendix N`. |
| L6.7 | **Table / Figure references are always unresolved** (no Table / Figure nodes). Captions differ per document: `Table A1/1` (Reg 154), `Table 3` (GTR), `Table 1: …` with numbering restarting per Annex (Euro 7), `Figure I/1` (GTR rationale). | 0 % by design. Numbering that restarts per annex needs scoped ids. |
| L6.8 | **No references to equations** ("equation in paragraph 7.1.", "the equation below", "parameters taken from Table 3"). | See §8. |
| L6.9 | **`this Regulation` / `this GTR` / `thereof` / `thereto` aren't handled per document.** The scope rule matches only `of this Regulation`. | GTR: "paragraph 6.3.2. of this GTR". EU: "Table 11 of Annex V thereto" (refers back to the *external* regulation just cited). |
| L6.10 | **Resolution depends on the division id strings `ANNEX-…`, `APPENDIX-…`, `BODY`.** | Must be rewritten once the id scheme generalizes (L4.11). |
| L6.11 | **Externally cited documents and their provisions are not captured at all.** No grammar exists for EU/EC acts, directives, UN GTRs, ISO/EN/SAE standards, ECE/TRANS documents or treaties. There is also none of the following: shared-head lists (`Regulations (EC) No 715/2007 and (EC) No 595/2009`); separating a document's citations of *itself* from external ones (Reg 154 cites "UN Regulation No. 154", GTR 22 cites "Global Technical Regulation No. 22"); `thereof`/`thereto` back-references; and the title, date, OJ reference and ELI carried by EU footnotes. | EU 2024/1257: 80 EU/EC act mentions (24 unique) and 17 directive mentions. EU 2026/1762: 33 citations of UN R179/R83 with pinpoints such as `paragraphs 9.1 and 9.4 of UN Regulation No 179`. Reg 154: 86 distinct standards. All are lost today. Plan: `plan.md` §9a. |

## 7. Phase 5, outputs and tests

| # | Limitation |
|---|---|
| L7.1 | Only `Clause`, `Abbreviation` and `Definition` are emitted. No `Document`/`Standard`/`Version`/`Division`/`Article`/`Recital`/`Annex`/`Table`/`Figure`/`Equation`/`ExternalDocument` node types exist in code. `schema.yaml` lacks most of these. |
| L7.2 | `schema.yaml` is titled and versioned for Reg 154 only (`qualified_id_scheme.pattern: <standard>.<version>.<division>.<local-number-path>`, `division_type: [body, appendix, annex, annex_appendix]`). It cannot describe EU or GTR structure. |
| L7.3 | Abbreviation node id `ABBR:<surface_form>` is not namespaced by document, so ids would collide once several documents are loaded side by side. The same goes for `DEF:<source_clause>` once the clause-id prefix changes. |
| L7.4 | `tests/test_integration.py` is document-agnostic only on paper. It asserts `^REG154\.04\.` ids. It only checks invariants (no orphans / no duplicate ids), and those **passed** while EU 2024/1257 was parsed into 15 merged clauses. `dedupe()` *hides* structural failure from the duplicate-id check. There are no per-document expectations (expected article/annex/definition counts). |
| L7.5 | Phase 3 is run as `python -m` while the others run as scripts. There is no single entry point (`run_all`), no per-document config, no run manifest (input hash, counts, warnings), and warnings only go to stderr. |
| L7.6 | QA (Phase 6) has never been run, so there is no QA harness to extend to the new documents. |

## 8. Equations — not represented at all

| # | Limitation | Evidence |
|---|---|---|
| L8.1 | **No Equation node type** in `schema.yaml` or code. Reg 154 has math fonts on **241 pages** (CambriaMath/SymbolMT), 479 `X = …` lines and 292 `where:` lines. GTR 22 has ~12 display equations / inequalities (§5.2, §6.3.2, §6.3.3, Annex 3). | Equations can't be queried, cited, or linked to their variables. |
| L8.2 | **Display equations are flattened into prose.** Fraction structure is lost: the fraction bar is a vector line (`page.get_drawings()`), not text, so `CO2_test-i / CO2_declared-i` becomes `𝐶𝑂2 𝑡𝑒𝑠𝑡−𝑖 𝐶𝑂2 𝑑𝑒𝑐𝑙𝑎𝑟𝑒𝑑−𝑖`. | Example: `REG154.04.APPENDIX-2.3.2.1`. |
| L8.3 | **Sub/superscripts are flattened.** They are separate smaller spans (6.8 pt vs 9.8 pt) with a baseline offset, concatenated without a marker. | `FECS,c,1`, `ECDC,first,i`. `UBEmeasured` vs `UBE_measured` can't be told apart. |
| L8.4 | **Multi-line constructs are scrambled by reading order:** summation limits (`∑∆EREESS,i` / `n` / `i=1` on three lines), square roots spanning lines (GTR §6.3.3 standard deviation), and the fraction numerator/denominator ordering (GTR §5.2 virtual distance). | — |
| L8.5 | **Some equations are raster images with no text layer:** Reg 154 has 144 small (h < 60 pt) images and GTR 22 has 17. Some are equations (e.g. Reg 154 p.85 OBFCM `Accuracy = …`). Others are small diagrams (p.189 approval-mark layout), so the exact equation count needs the classifier in plan §7.2. | Today these vanish completely. Only the surrounding "Where:" glossary survives. |
| L8.6 | **"Where:" variable glossaries are not parsed.** They are two-column (symbol \| description, unit) blocks, like the abbreviation table, but stay as body text. | Variables, their meanings and units (`Wh`, `km`, `litres`) are lost. |
| L8.7 | **Inequalities and decision rules aren't distinguished from equations** (GTR pass/fail: `Xtests ≤ A − (tP1,N + tP2,N)·s`). | These carry the normative pass/fail logic. |
| L8.8 | **Equation references aren't detected:** "equation in paragraph 7.1.", "the equation below", "according to the equation in paragraph 3.2.4.1.1.2.3." (≥35 occurrences in Reg 154), and equation numbers `(1)`, `(2)` at the right margin. | — |
| L8.9 | **Inline formulas in EU text are plain text** (`L2 + L4 (mg/km)`, `6x1011` for 6×10¹¹, where the superscript is lost, `THC + NOx`). | Without a layout-aware pass, exponents are silently corrupted. |

## 9. Out of scope today, and needed for "all documents" later

- **Table contents** (limit values, MPR percentages, Table 3 statistical constants) are
  excluded by the v1 non-goals. Euro 7's normative content is mostly tables, so a document
  like that is only partly represented until at least caption plus cell-text Table nodes exist.
- **Constraints / Attributes** (schema-defined, never extracted). Emission limits and MPR
  values are the natural first targets.
- **Amendment / supersession across documents.** Euro 7 *repeals* Regulations 715/2007 and
  595/2009, and 2026/1762 *implements* 2024/1257. This needs Version / `SUPERSEDES` /
  `IMPLEMENTS` edges. It's deliberately deferred because the graphs are not being combined yet.
- **Tracked changes:** the Reg 154 spike found none, and the other three are final published
  texts. If another working document with real tracked changes is added, detection must
  become per-document.

---

## Status after v2 (2026-10-12)

`plan.md` §1–§12 are implemented (see plan.md §14 for deviations). Re-running
the measurements of §1 on the new pipeline:

| Metric | Reg 154 | GTR 22 | EU 2024/1257 | EU 2026/1762 |
|---|---:|---:|---:|---:|
| Header/footer signatures stripped | 2 | 2 | 4 | 4 |
| Top-level divisions (+ structure) | 56 | Front, Part I (A–F, ¶1–60), Part II, Annexes 1–3 | Preamble (44 recitals), 7 chapters, 21 articles, 6 annexes | Preamble (7 recitals), 9 articles, 4 annexes, 8 appendices |
| Units | 3,756 | 146 | 244 | 61 |
| Dedupe merges | 15 (was ~30) | 0 (was 24) | 0 (was 73) | 0 |
| Definitions | 184 | 23 / 23 | 77 / 77 | — |
| Abbreviations | 185 (116 table) | 36 (11 table) | 38 | 1 |
| Internal references resolved | 94% (was 73%) | 97% (was 14%) | 95% (was 0%) | 96% (was 15%) |
| Equations (parsed) | 535 (278) | 19 (16) | 0 | 0 |
| External documents / provisions | 95 / 7 | 7 / 19 | 63 / 21 | 18 / 46 |
| Qualified-id prefix | `REG154.04` | `GTR22` | `EU2024-1257` | `EU2026-1762` |

**Resolved:** L2.1–L2.6, L3.1–L3.11, L4.1–L4.12, L5.1–L5.7 (L5.8 stays a
deliberate deferral), L6.1–L6.11, L7.1–L7.6, L8.1–L8.8.

**Partly resolved / remaining:**
- **L3.12** — no OCR (by decision); pages without a text layer are flagged `needs_ocr` in the manifest.
- **L8.4** — nested multi-line constructs (integrals with stacked limits inside fractions, Reg 154 Annex B4–B8 formulas) are reconstructed `partial`; the crop is always attached.
- **L8.5** — image-only equations are detected only when framed by a lead-in (`… as follows:`) or a `where:` line; their glossary is parsed, the formula itself is not (math OCR declined).
- **L8.9** — inline prose formulas are not nodes (plan §7.6); their sub/superscripts are fixed in the text.
- **§9** — table values, Constraints/Attributes, multi-version and cross-document graphs remain out of scope.
