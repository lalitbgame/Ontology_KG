"""Per-document expectations (plan.md §11): hand-verified facts about each
document, checked against a pipeline run. Used by Phase 6's QA report and
by tests/test_integration.py, so the same file gates both.

tests/expectations/<doc_id>.yaml keys (all optional):

  units_by_type:      {Article: 21, Annex: 6}      exact counts per unit_type
  min_units_by_type:  {Clause: 120}
  units_total:        [low, high]                  inclusive range
  counts:             {definitions: 23, abbreviations_table: 11, ...}   exact
  min_counts:         {equations: 15, ...}
  max_counts:         {dedupe_merges: 0, ...}
  exists:             [node ids that must exist]
  absent:             [node ids that must NOT exist]
  parents:            {child_id: parent_id}         misattribution guard
  titles:             {unit_id: "exact title"}
  unit_props:         {unit_id: {prop: value}}      e.g. is_form: true
  definitions_include: [quoted terms]
  abbreviations_include: {SURFACE: "expansion substring"}
  external_docs_include / external_docs_exclude: [EXT ids]
  provisions_include: [EXT provision ids]
  doc_edges_include:  [[TYPE, EXT id], ...]
  reference_rate_min: {all: 0.9, paragraph: 0.9}
  equations_include:  [{id: ..., lhs: ..., kind: ...}]
  internal_resolved_max: {pattern: regex, max: 0}   e.g. external refs never resolved internally
"""
import collections
import re
from pathlib import Path

import yaml

from .common import PROJECT_DIR, read_json, read_jsonl

EXPECT_DIR = PROJECT_DIR / "tests" / "expectations"


def load(doc_id):
    p = EXPECT_DIR / f"{doc_id}.yaml"
    if not p.exists():
        return None
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def facts(out_dir):
    """Everything an expectation can refer to, from one run's output."""
    out = Path(out_dir)
    m = read_json(out / "manifest.json", {})
    units = read_jsonl(out / "units.jsonl")
    abbrs = read_jsonl(out / "abbreviations.jsonl")
    refs = read_jsonl(out / "references.jsonl")
    cits = read_jsonl(out / "citations.jsonl")
    eqs = read_jsonl(out / "equations.jsonl")
    nodes = {n["id"]: n for n in read_jsonl(out / "nodes.jsonl")}
    ph = m.get("phases", {})
    counts = {
        "units": len(units),
        "definitions": len(read_jsonl(out / "definitions.jsonl")),
        "abbreviations": len(abbrs),
        "abbreviations_table": sum(1 for a in abbrs if a.get("source") == "table"),
        "footnotes": len(read_jsonl(out / "footnotes.jsonl")),
        "tables": len(read_jsonl(out / "tables.jsonl")),
        "captioned_tables": sum(1 for t in read_jsonl(out / "tables.jsonl") if t.get("caption_id")),
        "figures": len(read_jsonl(out / "figures.jsonl")),
        "equations": len(eqs),
        "equations_with_lhs": sum(1 for e in eqs if e.get("lhs")),
        "equation_crops": sum(1 for e in eqs if e.get("image_path")),
        "variables": len(read_jsonl(out / "variables.jsonl")),
        "external_docs": len(read_jsonl(out / "external_docs.jsonl")),
        "external_provisions": len(read_jsonl(out / "external_provisions.jsonl")),
        "dedupe_merges": ph.get("phase2_parse", {}).get("dedupe_merges", 0),
        "orphans": ph.get("phase2_parse", {}).get("orphans", 0),
        "dropped_edges": ph.get("phase5_assemble", {}).get("dropped_edges", 0),
        "recitals": sum(1 for u in units if u["unit_type"] == "Recital"),
    }
    rate = collections.defaultdict(lambda: [0, 0])
    for r in refs:
        for k in ("all", r["kind"]):
            rate[k][1] += 1
            rate[k][0] += r["status"] == "resolved"
    return {
        "manifest": m, "units": {u["qualified_id"]: u for u in units}, "nodes": nodes,
        "unit_types": collections.Counter(u["unit_type"] for u in units), "counts": counts,
        "definitions": {d["quoted_term"] for d in read_jsonl(out / "definitions.jsonl")},
        "abbreviations": {a["surface_form"]: a["expansion"] for a in abbrs},
        "external_docs": {d["id"] for d in read_jsonl(out / "external_docs.jsonl")},
        "provisions": {p["id"] for p in read_jsonl(out / "external_provisions.jsonl")},
        "doc_edges": {(c["type"], c["to"]) for c in cits if c["type"] != "CITES"},
        "rates": {k: (a / b if b else None) for k, (a, b) in rate.items()},
        "refs": refs, "equations": {e["id"]: e for e in eqs},
    }


def check(exp, f):
    """-> list of (ok, description)."""
    res = []

    def add(ok, msg):
        res.append((bool(ok), msg))

    for t, n in (exp.get("units_by_type") or {}).items():
        add(f["unit_types"].get(t, 0) == n, f"{t} units == {n} (got {f['unit_types'].get(t, 0)})")
    for t, n in (exp.get("min_units_by_type") or {}).items():
        add(f["unit_types"].get(t, 0) >= n, f"{t} units >= {n} (got {f['unit_types'].get(t, 0)})")
    if exp.get("units_total"):
        lo, hi = exp["units_total"]
        add(lo <= f["counts"]["units"] <= hi, f"units in [{lo}, {hi}] (got {f['counts']['units']})")
    for k, n in (exp.get("counts") or {}).items():
        add(f["counts"].get(k) == n, f"{k} == {n} (got {f['counts'].get(k)})")
    for k, n in (exp.get("min_counts") or {}).items():
        add((f["counts"].get(k) or 0) >= n, f"{k} >= {n} (got {f['counts'].get(k)})")
    for k, n in (exp.get("max_counts") or {}).items():
        add((f["counts"].get(k) or 0) <= n, f"{k} <= {n} (got {f['counts'].get(k)})")
    for nid in exp.get("exists") or []:
        add(nid in f["nodes"], f"node exists: {nid}")
    for nid in exp.get("absent") or []:
        add(nid not in f["nodes"], f"node absent: {nid}")
    for child, parent in (exp.get("parents") or {}).items():
        got = f["units"].get(child, {}).get("parent_id")
        add(got == parent, f"parent({child}) == {parent} (got {got})")
    for uid, props in (exp.get("unit_props") or {}).items():
        u = f["units"].get(uid, {})
        for k, v in props.items():
            add(u.get(k) == v, f"{uid}.{k} == {v!r} (got {u.get(k)!r})")
    for uid, title in (exp.get("titles") or {}).items():
        got = f["units"].get(uid, {}).get("title")
        add(got == title, f"title({uid}) == {title!r} (got {got!r})")
    for term in exp.get("definitions_include") or []:
        add(term in f["definitions"], f"definition: {term}")
    for sf, sub in (exp.get("abbreviations_include") or {}).items():
        got = f["abbreviations"].get(sf)
        add(got is not None and sub.lower() in got.lower(), f"abbreviation {sf} ~ {sub!r} (got {got!r})")
    for e in exp.get("external_docs_include") or []:
        add(e in f["external_docs"], f"external doc: {e}")
    for e in exp.get("external_docs_exclude") or []:
        add(e not in f["external_docs"], f"no external doc: {e}")
    for p in exp.get("provisions_include") or []:
        add(p in f["provisions"], f"provision: {p}")
    for t, e in exp.get("doc_edges_include") or []:
        add((t, e) in f["doc_edges"], f"document edge: {t} -> {e}")
    for k, v in (exp.get("reference_rate_min") or {}).items():
        got = f["rates"].get(k)
        add(got is not None and got >= v, f"reference resolution[{k}] >= {v:.0%} (got {got if got is None else f'{got:.1%}'})")
    for spec in exp.get("equations_include") or []:
        e = f["equations"].get(spec["id"])
        ok = e is not None and all(e.get(k) == v for k, v in spec.items() if k != "id")
        add(ok, f"equation {spec}" + ("" if e else " (missing)") + (f" (got lhs={e.get('lhs')}, kind={e.get('kind')})" if e else ""))
    for spec in exp.get("internal_resolved_max") or []:
        rx = re.compile(spec["pattern"])
        n = sum(1 for r in f["refs"] if r["status"] == "resolved" and rx.search(r["raw_text"] + " " + (r.get("qualifier") or "")))
        add(n <= spec["max"], f"internally resolved refs matching /{spec['pattern']}/ <= {spec['max']} (got {n})")
    return res
