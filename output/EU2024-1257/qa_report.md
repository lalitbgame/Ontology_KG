# QA report — EU2024-1257

Source: `OJ_L_202401257_EN_TXT.pdf` · profile `eu_oj_act` · 49 pages · pipeline commit `7420169` · run 2026-10-12T19:29:52

## Summary

| | |
|---|---:|
| units | 244 |
| definitions | 77 |
| abbreviations | 38 |
| abbreviations table | 0 |
| footnotes | 30 |
| tables | 33 |
| captioned tables | 32 |
| figures | 0 |
| equations | 0 |
| equations with lhs | 0 |
| equation crops | 0 |
| variables | 0 |
| external docs | 63 |
| external provisions | 21 |
| dedupe merges | 0 |
| orphans | 0 |
| dropped edges | 0 |
| recitals | 44 |

Unit types: ArticleParagraph 82, Point 80, Recital 44, Article 21, Chapter 7, Annex 6, Clause 2, Preamble 1, Body 1

## Invariants

- ✅ every unit id starts with 'EU2024-1257.'
- ✅ 0 orphan units (got 0)
- ✅ no duplicate unit ids
- ✅ 0 edges dropped at assembly (got 0)
- ✅ no body contains a stripped header/footer signature (got 0)
- ✅ every equation has an image crop (0/0)
- ✅ every resolved reference targets a real node

## Text coverage

91,109 chars in unit titles/bodies + 25,503 in tables/figures/equations, of 116,811 chars of non-TOC, non-footnote page text: **99.8%** (heading labels such as 'Article 4' or 'Annex B6' are structure, not body text, so 100% is not expected).

## Reference resolution

Internal references: 166/175 resolved (94.9%); 89 external-citation spans were masked so they could not resolve internally.

| kind | resolved | total | rate |
|---|---:|---:|---:|
| annex | 48 | 48 | 100% |
| article | 27 | 27 | 100% |
| paragraph | 29 | 34 | 85% |
| table | 62 | 66 | 94% |

<details><summary>Unresolved references (never guessed) — top 60</summary>

| reference | qualifier | count |
|---|---|---:|
| paragraph 3 |  | 2 |
| paragraph 2 |  | 2 |
| Table 2 |  | 1 |
| Table 4 |  | 1 |
| Table 6 |  | 1 |
| Table 8 |  | 1 |
| paragraph 1 |  | 1 |

</details>

## External documents

63 external documents (ec_regulation 9, eu_decision 2, eu_directive 10, eu_regulation 32, treaty 1, un_gtr 3, un_regulation 5, unece_agreement 1), 21 cited provisions, 175 citations; 0 self-citations filtered; document-level edges {'AMENDS': 1, 'REPEALS': 6, 'LEGAL_BASIS': 1}. Full list: `external_citations.csv`.

## Structure

Dedupe merges (each one is a parse defect, merged — never dropped): **0**. Parser warnings: {'sequence_rejected:article_paragraph': 3}.

PDF outline cross-check: 6/6 bookmarked divisions found in the parse.


## Expectations

**62/62 passed** (`tests/expectations/EU2024-1257.yaml`).

- ✅ Recital units == 44 (got 44)
- ✅ Chapter units == 7 (got 7)
- ✅ Article units == 21 (got 21)
- ✅ Annex units == 6 (got 6)
- ✅ definitions == 77 (got 77)
- ✅ captioned_tables >= 31 (got 32)
- ✅ footnotes >= 20 (got 30)
- ✅ dedupe_merges <= 0 (got 0)
- ✅ orphans <= 0 (got 0)
- ✅ node exists: EU2024-1257.RECITAL-1
- ✅ node exists: EU2024-1257.RECITAL-44
- ✅ node exists: EU2024-1257.ART-3.PT-1
- ✅ node exists: EU2024-1257.ART-3.PT-77
- ✅ node exists: EU2024-1257.ART-4.6
- ✅ node exists: EU2024-1257.ANNEX-I.TABLE-9
- ✅ node exists: EU2024-1257.ANNEX-II.TABLE-3
- ✅ node exists: EU2024-1257.ANNEX-V.TABLE-12
- ✅ parent(EU2024-1257.RECITAL-17) == EU2024-1257.PREAMBLE (got EU2024-1257.PREAMBLE)
- ✅ parent(EU2024-1257.ART-1) == EU2024-1257.CH-I (got EU2024-1257.CH-I)
- ✅ parent(EU2024-1257.ART-4) == EU2024-1257.CH-II (got EU2024-1257.CH-II)
- ✅ parent(EU2024-1257.ART-10) == EU2024-1257.CH-III (got EU2024-1257.CH-III)
- ✅ parent(EU2024-1257.ART-3.PT-48) == EU2024-1257.ART-3 (got EU2024-1257.ART-3)
- ✅ parent(EU2024-1257.ART-4.2) == EU2024-1257.ART-4 (got EU2024-1257.ART-4)
- ✅ EU2024-1257.RECITAL-1.normative == False (got False)
- ✅ title(EU2024-1257.ART-1) == 'Subject matter' (got 'Subject matter')
- ✅ title(EU2024-1257.ART-2) == 'Scope' (got 'Scope')
- ✅ title(EU2024-1257.ART-3) == 'Definitions' (got 'Definitions')
- ✅ definition: emission type-approval
- ✅ definition: conformity of production
- ✅ definition: in-service conformity
- ✅ definition: tyre abrasion
- ✅ definition: option
- ✅ abbreviation CoP ~ 'conformity of production' (got 'conformity of production')
- ✅ abbreviation ISC ~ 'in-service conformity' (got 'in-service conformity')
- ✅ abbreviation PEV ~ 'pure electric vehicle' (got 'pure electric vehicle')
- ✅ abbreviation SOH ~ 'state of health' (got 'state of health')
- ✅ external doc: EXT:EU.REG.2018-858
- ✅ external doc: EXT:EC.REG.715-2007
- ✅ external doc: EXT:EC.REG.595-2009
- ✅ external doc: EXT:EU.REG.582-2011
- ✅ external doc: EXT:EU.REG.2017-1151
- ✅ external doc: EXT:EU.REG.2017-2400
- ✅ external doc: EXT:EU.REG.2022-1362
- ✅ external doc: EXT:TFEU
- ✅ external doc: EXT:UNR-49
- ✅ external doc: EXT:UNR-117
- ✅ external doc: EXT:UNGTR-15
- ✅ no external doc: EXT:EU.REG.2024-1257
- ✅ provision: EXT:EU.REG.2018-858#ART-3.PT-49
- ✅ provision: EXT:EU.REG.2018-858#ANNEX-II
- ✅ provision: EXT:TFEU#ART-114
- ✅ provision: EXT:UNR-49#ANNEX-4.7.2.1
- ✅ document edge: AMENDS -> EXT:EU.REG.2018-858
- ✅ document edge: REPEALS -> EXT:EC.REG.715-2007
- ✅ document edge: REPEALS -> EXT:EC.REG.595-2009
- ✅ document edge: REPEALS -> EXT:EU.REG.582-2011
- ✅ document edge: REPEALS -> EXT:EU.REG.2017-1151
- ✅ document edge: REPEALS -> EXT:EU.REG.2017-2400
- ✅ document edge: REPEALS -> EXT:EU.REG.2022-1362
- ✅ document edge: LEGAL_BASIS -> EXT:TFEU
- ✅ reference resolution[all] >= 90% (got 94.9%)
- ✅ reference resolution[annex] >= 95% (got 100.0%)
