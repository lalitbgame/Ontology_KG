"""Phase 6 - QA report per document (plan.md §11.5).

Writes output/<doc_id>/qa_report.md: generic invariants, text coverage,
reference resolution by kind (+ the unresolved list), dedupe merges,
equation parse status, the PDF outline vs the parsed divisions, and the
document's hand-verified expectations (tests/expectations/<doc_id>.yaml).
"""
import collections
import re
import sys

from . import expectations
from .common import read_jsonl

PH = re.compile(r"\[(?:TABLE|FIGURE|EQ|FORM):[^\]]+\]")


def invariants(ctx, f):
    units = list(f["units"].values())
    doc = ctx.doc_id
    sigs = ctx.manifest.get("phases", {}).get("phase1_extract", {}).get("header_footer_signatures", [])
    bodies_with_header = 0
    for u in units:
        body = re.sub(r"\d+", "#", (u.get("body_text") or "").lower())
        if any(len(s) > 6 and s in body for s in sigs):
            bodies_with_header += 1
    eqs = list(f["equations"].values())
    return [
        (all(u["qualified_id"].startswith(doc + ".") for u in units), f"every unit id starts with '{doc}.'"),
        (f["counts"]["orphans"] == 0, f"0 orphan units (got {f['counts']['orphans']})"),
        (len(f["units"]) == len(units), "no duplicate unit ids"),
        (f["counts"]["dropped_edges"] == 0, f"0 edges dropped at assembly (got {f['counts']['dropped_edges']})"),
        (bodies_with_header == 0, f"no body contains a stripped header/footer signature (got {bodies_with_header})"),
        (all(e.get("image_path") for e in eqs), f"every equation has an image crop ({sum(1 for e in eqs if e.get('image_path'))}/{len(eqs)})"),
        (all(r["to"] is None or r["to"] in f["nodes"] for r in f["refs"]), "every resolved reference targets a real node"),
    ]


def coverage(ctx):
    lines = read_jsonl(ctx.path("lines.jsonl"))
    regions = read_jsonl(ctx.path("regions.jsonl"))
    units = read_jsonl(ctx.path("units.jsonl"))
    toc = {i for r in regions if r["kind"] == "toc" for i in r["line_ids"]}
    total = sum(len(l["text"]) for l in lines if l["id"] not in toc and not l.get("is_footnote"))
    in_units = sum(len(PH.sub("", u.get("body_text") or "")) + len(u.get("title") or "") for u in units)
    region_ids = {i for r in regions if r["kind"] in ("table", "figure", "equation")
                  for i in r.get("line_ids", []) + r.get("caption_line_ids", []) + r.get("glossary_line_ids", [])}
    in_regions = sum(len(l["text"]) for l in lines if l["id"] in region_ids)
    return total, in_units, in_regions


def outline_diff(ctx, f):
    """PDF bookmarks that name a division vs parsed units with that label."""
    rows = []
    labels = collections.defaultdict(set)
    for u in f["units"].values():
        labels[u["unit_type"]].add((u.get("local_label") or "").upper())
    for lvl, title, page in ctx.manifest.get("outline", []):
        m = re.match(r"^(ANNEX|Annex|Appendix|Article|CHAPTER|Chapter)\s+([A-Z]?\d+[a-z]?|[IVXLC]+)\b", title)
        if not m:
            continue
        kind = {"annex": "Annex", "appendix": "Appendix", "article": "Article", "chapter": "Chapter"}[m.group(1).lower()]
        found = m.group(2).upper() in labels[kind]
        rows.append((found, f"outline '{title[:60]}' (p{page}) -> {kind} {m.group(2)}"))
    return rows


def run(ctx):
    f = expectations.facts(ctx.out)
    ph = ctx.manifest.get("phases", {})
    inv = invariants(ctx, f)
    total, in_units, in_regions = coverage(ctx)
    exp = expectations.load(ctx.doc_id)
    checks = expectations.check(exp, f) if exp is not None else []
    out = [f"# QA report — {ctx.doc_id}", "",
           f"Source: `{ctx.manifest.get('source_file')}` · profile `{ctx.family}` · "
           f"{ctx.manifest.get('page_count')} pages · pipeline commit `{ctx.manifest.get('pipeline_commit')}` · "
           f"run {ctx.manifest.get('run_at')}", ""]
    if not ctx.manifest.get("registry_confirmed"):
        out += ["> **Registry entry not confirmed** — this PDF is not in `documents.yaml`; profile and doc_id "
                "were auto-detected.", ""]

    out += ["## Summary", "", "| | |", "|---|---:|"]
    for k, v in f["counts"].items():
        out.append(f"| {k.replace('_', ' ')} | {v} |")
    ut = ", ".join(f"{k} {v}" for k, v in f["unit_types"].most_common())
    out += ["", f"Unit types: {ut}", ""]

    out += ["## Invariants", ""] + [f"- {'✅' if ok else '❌'} {msg}" for ok, msg in inv] + [""]

    cov = (in_units + in_regions) / total if total else 0
    out += ["## Text coverage", "",
            f"{in_units:,} chars in unit titles/bodies + {in_regions:,} in tables/figures/equations, "
            f"of {total:,} chars of non-TOC, non-footnote page text: **{cov:.1%}** "
            "(heading labels such as 'Article 4' or 'Annex B6' are structure, not body text, so 100% is not expected).", ""]

    p4 = ph.get("phase4_references", {})
    out += ["## Reference resolution", "",
            f"Internal references: {p4.get('resolved')}/{p4.get('references')} resolved "
            f"({(p4.get('rate') or 0):.1%}); {p4.get('masked_external_spans', 0)} external-citation spans were masked "
            "so they could not resolve internally.", "", "| kind | resolved | total | rate |", "|---|---:|---:|---:|"]
    for k, v in sorted((p4.get("by_kind") or {}).items()):
        out.append(f"| {k} | {v['resolved']} | {v['total']} | {v['rate']:.0%} |")
    unres = collections.Counter((r["raw_text"], r.get("qualifier") or "") for r in f["refs"] if r["status"] == "unresolved")
    if unres:
        out += ["", "<details><summary>Unresolved references (never guessed) — top 60</summary>", "",
                "| reference | qualifier | count |", "|---|---|---:|"]
        for (raw, q), n in unres.most_common(60):
            out.append(f"| {raw} | {q} | {n} |")
        out += ["", "</details>"]
    out.append("")

    p4a = ph.get("phase4a_external", {})
    out += ["## External documents", "",
            f"{p4a.get('external_docs')} external documents ({', '.join(f'{k} {v}' for k, v in (p4a.get('by_kind') or {}).items())}), "
            f"{p4a.get('provisions')} cited provisions, {p4a.get('citations')} citations; "
            f"{p4a.get('self_citations_filtered')} self-citations filtered; document-level edges "
            f"{p4a.get('document_edges')}. Full list: `external_citations.csv`.", ""]

    p2 = ph.get("phase2_parse", {})
    out += ["## Structure", "",
            f"Dedupe merges (each one is a parse defect, merged — never dropped): **{p2.get('dedupe_merges')}**. "
            f"Parser warnings: {p2.get('warnings')}.", ""]
    if p2.get("merges"):
        out += ["<details><summary>Merged ids</summary>", ""] + \
               [f"- `{mm['qualified_id']}` (pages {mm['pages']})" for mm in p2["merges"][:100]] + ["", "</details>", ""]
    od = outline_diff(ctx, f)
    if od:
        found = sum(ok for ok, _ in od)
        out += [f"PDF outline cross-check: {found}/{len(od)} bookmarked divisions found in the parse.", ""]
        out += [f"- {'✅' if ok else '❌'} {msg}" for ok, msg in od if not ok] + [""]

    p3b = ph.get("phase3b_equations", {})
    if p3b.get("equations"):
        out += ["## Equations", "",
                f"{p3b['equations']} equations ({p3b.get('kinds')}); parse status {p3b.get('parse_status')}; "
                f"{p3b.get('with_lhs')} with an identified left-hand side, {p3b.get('with_glossary')} with a parsed "
                f"'where' glossary, {p3b.get('depends_on_edges')} DEPENDS_ON links, {p3b.get('crops')} image crops. "
                "`partial` = reconstructed but not sympy-parseable; review against the crop in `equations/`.", ""]

    if exp is None:
        out += ["## Expectations", "", f"_No `tests/expectations/{ctx.doc_id}.yaml` — invariants only._", ""]
    else:
        passed = sum(ok for ok, _ in checks)
        out += ["## Expectations", "", f"**{passed}/{len(checks)} passed** (`tests/expectations/{ctx.doc_id}.yaml`).", ""]
        out += [f"- {'✅' if ok else '❌'} {msg}" for ok, msg in checks] + [""]

    ctx.path("qa_report.md").write_text("\n".join(out), encoding="utf-8")
    ctx.record("phase6_qa", invariants_passed=sum(ok for ok, _ in inv), invariants=len(inv),
               expectations_passed=sum(ok for ok, _ in checks), expectations=len(checks),
               failed_expectations=[msg for ok, msg in checks if not ok], coverage=round(cov, 3))
    print(f"[{ctx.doc_id}] phase6: invariants {sum(ok for ok, _ in inv)}/{len(inv)}, "
          f"expectations {sum(ok for ok, _ in checks)}/{len(checks)}, coverage {cov:.1%}", file=sys.stderr)
    for ok, msg in inv + checks:
        if not ok:
            print(f"    FAIL {msg}", file=sys.stderr)
