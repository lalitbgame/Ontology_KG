# QA report — GTR22

Source: `ECE_TRANS_180a22e.pdf` · profile `un_gtr` · 32 pages · pipeline commit `7420169` · run 2026-10-12T19:29:48

## Summary

| | |
|---|---:|
| units | 146 |
| definitions | 23 |
| abbreviations | 36 |
| abbreviations table | 11 |
| footnotes | 2 |
| tables | 21 |
| captioned tables | 3 |
| figures | 5 |
| equations | 19 |
| equations with lhs | 16 |
| equation crops | 19 |
| variables | 66 |
| external docs | 7 |
| external provisions | 19 |
| dedupe merges | 0 |
| orphans | 0 |
| dropped edges | 0 |
| recitals | 0 |

Unit types: Clause 134, Section 6, Annex 3, Part 2, FrontMatter 1

## Invariants

- ✅ every unit id starts with 'GTR22.'
- ✅ 0 orphan units (got 0)
- ✅ no duplicate unit ids
- ✅ 0 edges dropped at assembly (got 0)
- ✅ no body contains a stripped header/footer signature (got 0)
- ✅ every equation has an image crop (19/19)
- ✅ every resolved reference targets a real node

## Text coverage

59,073 chars in unit titles/bodies + 15,387 in tables/figures/equations, of 74,176 chars of non-TOC, non-footnote page text: **100.4%** (heading labels such as 'Article 4' or 'Annex B6' are structure, not body text, so 100% is not expected).

## Reference resolution

Internal references: 30/31 resolved (96.8%); 60 external-citation spans were masked so they could not resolve internally.

| kind | resolved | total | rate |
|---|---:|---:|---:|
| annex | 8 | 8 | 100% |
| article | 0 | 1 | 0% |
| equation | 1 | 1 | 100% |
| figure | 5 | 5 | 100% |
| paragraph | 13 | 13 | 100% |
| table | 3 | 3 | 100% |

<details><summary>Unresolved references (never guessed) — top 60</summary>

| reference | qualifier | count |
|---|---|---:|
| Article 6 |  | 1 |

</details>

## External documents

7 external documents (standard 1, un_gtr 1, un_regulation 1, unece_document 4), 19 cited provisions, 31 citations; 48 self-citations filtered; document-level edges {}. Full list: `external_citations.csv`.

## Structure

Dedupe merges (each one is a parse defect, merged — never dropped): **0**. Parser warnings: {}.

## Equations

19 equations ({'equation': 16, 'decision_rule': 3}); parse status {'parsed': 16, 'partial': 3}; 16 with an identified left-hand side, 12 with a parsed 'where' glossary, 15 DEPENDS_ON links, 19 image crops. `partial` = reconstructed but not sympy-parseable; review against the crop in `equations/`.

## Expectations

**61/61 passed** (`tests/expectations/GTR22.yaml`).

- ✅ Part units == 2 (got 2)
- ✅ Section units == 6 (got 6)
- ✅ Annex units == 3 (got 3)
- ✅ definitions == 23 (got 23)
- ✅ abbreviations_table == 11 (got 11)
- ✅ captioned_tables == 3 (got 3)
- ✅ figures == 5 (got 5)
- ✅ footnotes >= 1 (got 2)
- ✅ equations >= 15 (got 19)
- ✅ dedupe_merges <= 0 (got 0)
- ✅ orphans <= 0 (got 0)
- ✅ node exists: GTR22.RATIONALE.1
- ✅ node exists: GTR22.RATIONALE.60
- ✅ node exists: GTR22.BODY.1
- ✅ node exists: GTR22.BODY.7.2
- ✅ node exists: GTR22.BODY.3.23
- ✅ node exists: GTR22.BODY.6.3.3
- ✅ node exists: GTR22.ANNEX-3.3.1.1
- ✅ node exists: GTR22.BODY.TABLE-3
- ✅ parent(GTR22.RATIONALE.SEC-C) == GTR22.RATIONALE (got GTR22.RATIONALE)
- ✅ parent(GTR22.RATIONALE.14) == GTR22.RATIONALE.SEC-C (got GTR22.RATIONALE.SEC-C)
- ✅ parent(GTR22.RATIONALE.57) == GTR22.RATIONALE.SEC-F (got GTR22.RATIONALE.SEC-F)
- ✅ parent(GTR22.BODY.6.3.2) == GTR22.BODY.6.3 (got GTR22.BODY.6.3)
- ✅ parent(GTR22.ANNEX-3.2.1.1) == GTR22.ANNEX-3.2.1 (got GTR22.ANNEX-3.2.1)
- ✅ GTR22.ANNEX-1.is_form == True (got True)
- ✅ GTR22.RATIONALE.normative == False (got False)
- ✅ title(GTR22.BODY.3) == 'Definitions' (got 'Definitions')
- ✅ title(GTR22.BODY.4) == 'Abbreviations' (got 'Abbreviations')
- ✅ title(GTR22.BODY.7) == 'Rounding' (got 'Rounding')
- ✅ title(GTR22.ANNEX-1) == 'Vehicle Survey' (got 'Vehicle Survey')
- ✅ title(GTR22.RATIONALE.SEC-F) == 'Future development of the GTR' (got 'Future development of the GTR')
- ✅ definition: Battery
- ✅ definition: Originally installed battery
- ✅ definition: Usable Battery energy
- ✅ definition: Certified usable battery energy
- ✅ definition: On-board SOCR
- ✅ definition: Maximum charging power
- ✅ abbreviation REESS ~ 'Rechargeable Electrical Energy Storage System' (got 'Rechargeable Electrical Energy Storage System')
- ✅ abbreviation SOCE ~ 'State of Certified Energy' (got 'State of Certified Energy')
- ✅ abbreviation V2L ~ 'Vehicle to Load' (got 'Vehicle to Load')
- ✅ abbreviation UBE ~ 'Usable Battery Energy' (got 'Usable Battery Energy')
- ✅ external doc: EXT:UNGTR-15
- ✅ external doc: EXT:UNR-154
- ✅ external doc: EXT:SAE.J1711
- ✅ external doc: EXT:ECE.TRANS.WP29.AC.3.57
- ✅ no external doc: EXT:UNGTR-22
- ✅ no external doc: EXT:UNGTR-57
- ✅ no external doc: EXT:UNGTR-1
- ✅ provision: EXT:UNGTR-15#ANNEX-8.TABLE-A8/10.STEP-1
- ✅ provision: EXT:UNGTR-15#ANNEX-8.TABLE-A8/11.STEP-1
- ✅ reference resolution[all] >= 90% (got 96.8%)
- ✅ equation {'id': 'GTR22.BODY.6.3.2.EQ-1', 'lhs': 'SOCE_measured', 'kind': 'equation'} (got lhs=SOCE_measured, kind=equation)
- ✅ equation {'id': 'GTR22.BODY.6.3.2.EQ-2', 'lhs': 'SOCR_measured', 'kind': 'equation'} (got lhs=SOCR_measured, kind=equation)
- ✅ equation {'id': 'GTR22.BODY.6.3.3.EQ-1', 'lhs': 'x_i', 'kind': 'equation'} (got lhs=x_i, kind=equation)
- ✅ equation {'id': 'GTR22.BODY.6.3.3.EQ-2', 'lhs': 'X_tests', 'kind': 'equation'} (got lhs=X_tests, kind=equation)
- ✅ equation {'id': 'GTR22.BODY.6.3.3.EQ-3', 'lhs': 's', 'kind': 'equation'} (got lhs=s, kind=equation)
- ✅ equation {'id': 'GTR22.BODY.6.3.3.EQ-4', 'kind': 'decision_rule', 'outcome': 'pass'} (got lhs=None, kind=decision_rule)
- ✅ equation {'id': 'GTR22.BODY.6.3.3.EQ-5', 'kind': 'decision_rule', 'outcome': 'fail'} (got lhs=None, kind=decision_rule)
- ✅ equation {'id': 'GTR22.BODY.6.3.3.EQ-6', 'kind': 'decision_rule', 'outcome': 'continue'} (got lhs=None, kind=decision_rule)
- ✅ equation {'id': 'GTR22.ANNEX-3.3.1.1.EQ-2', 'lhs': 'UBE_measured,nc', 'kind': 'equation'} (got lhs=UBE_measured,nc, kind=equation)
- ✅ equation {'id': 'GTR22.ANNEX-3.3.2.1.EQ-1', 'lhs': 'EAER_measured', 'kind': 'equation'} (got lhs=EAER_measured, kind=equation)
