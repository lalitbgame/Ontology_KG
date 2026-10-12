# QA report — EU2026-1762

Source: `OJ_L_202601762_EN_TXT.pdf` · profile `eu_oj_act` · 17 pages · pipeline commit `7420169` · run 2026-10-12T19:29:57

## Summary

| | |
|---|---:|
| units | 61 |
| definitions | 0 |
| abbreviations | 1 |
| abbreviations table | 0 |
| footnotes | 10 |
| tables | 2 |
| captioned tables | 2 |
| figures | 0 |
| equations | 0 |
| equations with lhs | 0 |
| equation crops | 0 |
| variables | 0 |
| external docs | 18 |
| external provisions | 46 |
| dedupe merges | 0 |
| orphans | 0 |
| dropped edges | 0 |
| recitals | 7 |

Unit types: Clause 20, Article 9, ArticleParagraph 9, Appendix 8, Recital 7, Annex 4, Point 2, Preamble 1, Body 1

## Invariants

- ✅ every unit id starts with 'EU2026-1762.'
- ✅ 0 orphan units (got 0)
- ✅ no duplicate unit ids
- ✅ 0 edges dropped at assembly (got 0)
- ✅ no body contains a stripped header/footer signature (got 0)
- ✅ every equation has an image crop (0/0)
- ✅ every resolved reference targets a real node

## Text coverage

15,471 chars in unit titles/bodies + 487 in tables/figures/equations, of 16,083 chars of non-TOC, non-footnote page text: **99.2%** (heading labels such as 'Article 4' or 'Annex B6' are structure, not body text, so 100% is not expected).

## Reference resolution

Internal references: 22/23 resolved (95.7%); 60 external-citation spans were masked so they could not resolve internally.

| kind | resolved | total | rate |
|---|---:|---:|---:|
| annex | 11 | 11 | 100% |
| appendix | 3 | 3 | 100% |
| article | 8 | 8 | 100% |
| paragraph | 0 | 1 | 0% |

<details><summary>Unresolved references (never guessed) — top 60</summary>

| reference | qualifier | count |
|---|---|---:|
| paragraph 7.2 |  | 1 |

</details>

## External documents

18 external documents (ec_regulation 3, eu_directive 2, eu_regulation 10, treaty 1, un_regulation 2), 46 cited provisions, 96 citations; 0 self-citations filtered; document-level edges {'IMPLEMENTS': 1, 'LEGAL_BASIS': 1}. Full list: `external_citations.csv`.

## Structure

Dedupe merges (each one is a parse defect, merged — never dropped): **0**. Parser warnings: {}.

PDF outline cross-check: 12/12 bookmarked divisions found in the parse.


## Expectations

**56/56 passed** (`tests/expectations/EU2026-1762.yaml`).

- ✅ Recital units == 7 (got 7)
- ✅ Article units == 9 (got 9)
- ✅ Annex units == 4 (got 4)
- ✅ Appendix units == 8 (got 8)
- ✅ dedupe_merges <= 0 (got 0)
- ✅ orphans <= 0 (got 0)
- ✅ node exists: EU2026-1762.ANNEX-IV.TABLE-1
- ✅ node exists: EU2026-1762.ANNEX-IV.TABLE-2
- ✅ node exists: EU2026-1762.ART-1.PT-2
- ✅ parent(EU2026-1762.ANNEX-I.APP-1) == EU2026-1762.ANNEX-I (got EU2026-1762.ANNEX-I)
- ✅ parent(EU2026-1762.ANNEX-II.APP-2) == EU2026-1762.ANNEX-II (got EU2026-1762.ANNEX-II)
- ✅ parent(EU2026-1762.ANNEX-III.APP-3) == EU2026-1762.ANNEX-III (got EU2026-1762.ANNEX-III)
- ✅ parent(EU2026-1762.ART-4.3) == EU2026-1762.ART-4 (got EU2026-1762.ART-4)
- ✅ EU2026-1762.ANNEX-II.APP-2.is_form == True (got True)
- ✅ title(EU2026-1762.ART-9) == 'Entry into force' (got 'Entry into force')
- ✅ title(EU2026-1762.ANNEX-IV) == 'TRANSPARENCY LIST' (got 'TRANSPARENCY LIST')
- ✅ external doc: EXT:UNR-179
- ✅ external doc: EXT:UNR-83
- ✅ external doc: EXT:EU.REG.2024-1257
- ✅ external doc: EXT:EU.REG.2018-858
- ✅ external doc: EXT:EU.REG.2020-683
- ✅ external doc: EXT:EU.REG.2025-1706
- ✅ external doc: EXT:EU.REG.2016-679
- ✅ external doc: EXT:EU.REG.2018-1725
- ✅ external doc: EXT:TFEU
- ✅ no external doc: EXT:EU.REG.2026-1762
- ✅ provision: EXT:UNR-179#3.0
- ✅ provision: EXT:UNR-179#4.4
- ✅ provision: EXT:UNR-179#7
- ✅ provision: EXT:UNR-179#7.1
- ✅ provision: EXT:UNR-179#7.1.3
- ✅ provision: EXT:UNR-179#7.2
- ✅ provision: EXT:UNR-179#8
- ✅ provision: EXT:UNR-179#9.1
- ✅ provision: EXT:UNR-179#9.4
- ✅ provision: EXT:UNR-179#10
- ✅ provision: EXT:UNR-179#PT-3.7.19
- ✅ provision: EXT:UNR-179#ANNEX-1
- ✅ provision: EXT:UNR-179#ANNEX-1.APP-1
- ✅ provision: EXT:UNR-179#ANNEX-1.APP-2
- ✅ provision: EXT:UNR-179#ANNEX-1.APP-3
- ✅ provision: EXT:UNR-179#ANNEX-4.APP-1
- ✅ provision: EXT:UNR-179#ANNEX-4.APP-2
- ✅ provision: EXT:UNR-179#ANNEX-5
- ✅ provision: EXT:EU.REG.2024-1257#ART-4.2
- ✅ provision: EXT:EU.REG.2024-1257#ART-4.5
- ✅ provision: EXT:EU.REG.2024-1257#ART-5
- ✅ provision: EXT:EU.REG.2024-1257#ART-7.1
- ✅ provision: EXT:EU.REG.2024-1257#ART-10.1
- ✅ provision: EXT:EU.REG.2024-1257#ART-14.1
- ✅ provision: EXT:EU.REG.2024-1257#ART-14.3.PT-i
- ✅ provision: EXT:EU.REG.2024-1257#ART-14.4.PT-a
- ✅ provision: EXT:EU.REG.2024-1257#ANNEX-V.TABLE-11
- ✅ document edge: IMPLEMENTS -> EXT:EU.REG.2024-1257
- ✅ reference resolution[all] >= 90% (got 95.7%)
- ✅ internally resolved refs matching /^Annex (?:1|4|5|12)$/ <= 0 (got 0)
