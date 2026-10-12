"""Phase 5 - graph assembly & validation (plan.md §10).

Every phase's output for ONE document -> output/<doc_id>/nodes.jsonl,
edges.jsonl, graph.graphml, graph.pickle. Graphs of different documents
are never combined (external documents are per-graph stub nodes, ids
prefixed '<doc_id>/EXT:...', so a later merge is a join on `ext_id`).

Node types: Standard, Document, every structural unit type (Clause,
Article, Annex, Appendix, Recital, ...), Abbreviation, Definition, Footnote,
Table, Figure, Equation, Variable, ExternalDocument, ExternalProvision.

Edges are validated before the graph is built: an edge whose endpoint is
not a node is dropped and counted (should be 0), never silently kept.
"""
import collections
import json
import pickle
import re
import sys

import networkx as nx

from .common import read_jsonl, write_jsonl
from .phase4_references import Index

UNIT_DROP = {"line_ranges", "number_path"}


def ext_node_id(doc_id, ext_id):
    return f"{doc_id}/{ext_id}"


def build(ctx):
    doc_id = ctx.doc_id
    m = ctx.manifest
    units = read_jsonl(ctx.path("units.jsonl"))
    defs = read_jsonl(ctx.path("definitions.jsonl"))
    abbrs = read_jsonl(ctx.path("abbreviations.jsonl"))
    notes = read_jsonl(ctx.path("footnotes.jsonl"))
    tables = read_jsonl(ctx.path("tables.jsonl"))
    figures = read_jsonl(ctx.path("figures.jsonl"))
    eqs = read_jsonl(ctx.path("equations.jsonl"))
    variables = read_jsonl(ctx.path("variables.jsonl"))
    refs = read_jsonl(ctx.path("references.jsonl"))
    ext_docs = read_jsonl(ctx.path("external_docs.jsonl"))
    provisions = read_jsonl(ctx.path("external_provisions.jsonl"))
    citations = read_jsonl(ctx.path("citations.jsonl"))
    meta = m.get("metadata", {})

    nodes, edges = [], []

    def node(nid, ntype, **props):
        nodes.append({"id": nid, "type": ntype, "doc_id": doc_id, **props})

    def edge(a, b, etype, **props):
        edges.append({"from": a, "to": b, "type": etype, **{k: v for k, v in props.items() if v is not None}})

    # --- identity (plan §2.5) -------------------------------------------
    std_id = f"{doc_id}.STANDARD"
    node(std_id, "Standard", document_name=meta.get("title"), standard_number=meta.get("number"),
         region=meta.get("region"), regulatory_body=meta.get("issuer"), family=m.get("profile"))
    node(doc_id, "Document", labels=["Document", "Version"], title=meta.get("title"), number=meta.get("number"),
         series=meta.get("series"), date=meta.get("date"), issuer=meta.get("issuer"), region=meta.get("region"),
         family=m.get("profile"), source_file=m.get("source_file"), sha256=m.get("sha256"),
         page_count=m.get("page_count"), registry_confirmed=m.get("registry_confirmed"))
    edge(std_id, doc_id, "HAS_VERSION")

    # --- structure --------------------------------------------------------
    for u in units:
        props = {k: v for k, v in u.items() if k not in UNIT_DROP and k != "qualified_id"}
        node(u["qualified_id"], u["unit_type"], **props)
        if u["parent_id"]:
            edge(u["parent_id"], u["qualified_id"], "HAS_CHILD")
        else:
            edge(doc_id, u["qualified_id"], "HAS_DIVISION")

    # --- terms --------------------------------------------------------------
    for d in defs:
        node(d["id"], "Definition", **{k: v for k, v in d.items() if k != "id"})
        edge(d["source_clause"], d["id"], "HAS_DEFINITION")
    for a in abbrs:
        node(a["id"], "Abbreviation", **{k: v for k, v in a.items() if k != "id"})
        edge(a["source_clause"], a["id"], "HAS_ABBREVIATION")
    for n in notes:
        node(n["id"], "Footnote", marker=n.get("marker"), text=n["text"], page=n["page"], unit_id=n["unit_id"])
        edge(n["unit_id"], n["id"], "HAS_FOOTNOTE")

    # --- tables / figures ---------------------------------------------------
    for t in tables:
        node(t["id"], "Table", **{k: v for k, v in t.items() if k not in ("id", "regions")},
             regions=t["regions"])
        edge(t["defining_unit"], t["id"], "HAS_TABLE")
    for f in figures:
        node(f["id"], "Figure", **{k: v for k, v in f.items() if k not in ("id", "regions")}, regions=f["regions"])
        edge(f["defining_unit"], f["id"], "HAS_FIGURE")

    # --- equations & variables (plan §7.1) ----------------------------------
    var_ids = {v["symbol"]: v["id"] for v in variables}
    for v in variables:
        node(v["id"], "Variable", **{k: x for k, x in v.items() if k != "id"})
    idx = Index(doc_id, units, tables, figures, eqs, ctx.profile)
    unit_by_id = {u["qualified_id"]: u for u in units}
    for e in eqs:
        props = {k: v for k, v in e.items() if k not in ("id", "depends_on")}
        node(e["id"], "Equation", **props)
        edge(e["unit_id"], e["id"], "HAS_EQUATION")
        if e.get("lhs") and e["lhs"] in var_ids:
            edge(e["id"], var_ids[e["lhs"]], "DEFINES")
        for s in dict.fromkeys(e.get("symbols", [])):
            if s != e.get("lhs") and s in var_ids:
                edge(e["id"], var_ids[s], "USES", role="operand")
        for g in e.get("glossary", []):
            if g["symbol"] in var_ids:
                edge(e["id"], var_ids[g["symbol"]], "DESCRIBED_AS", description=g.get("description"), unit=g.get("unit"))
        for d in e.get("depends_on", []):
            edge(e["id"], d, "DEPENDS_ON")
        cap = e.get("uses_table_caption")
        if cap:
            num = re.sub(r"^Table\s+", "", cap)
            cands = idx.tables.get(num, [])
            u = unit_by_id.get(e["unit_id"])
            a = idx.enclosing(u, "Annex") if u else None
            here = [t for t in cands if a and t["id"].startswith(a["qualified_id"] + ".")] or \
                   [t for t in cands if t["id"].startswith(idx.container(u) + ".")] if u else []
            pick = here or (cands if len(cands) == 1 else [])
            if pick:
                edge(e["id"], pick[0]["id"], "USES_TABLE", raw_text=cap)

    # Variable <-> Abbreviation / Definition candidates (same "never guess"
    # rule: status=candidate, for human review)
    abbr_by_sf = {a["surface_form"]: a["id"] for a in abbrs}
    def_by_abbr = {d["abbreviation"]: d["id"] for d in defs if d.get("abbreviation")}
    for v in variables:
        base = v["symbol"].split("_")[0]
        for key in (v["symbol"], base):
            if key in abbr_by_sf:
                edge(v["id"], abbr_by_sf[key], "SAME_TERM_AS", status="candidate", match=key)
                break
        for key in (v["symbol"], base):
            if key in def_by_abbr:
                edge(v["id"], def_by_abbr[key], "SAME_TERM_AS", status="candidate", match=key)
                break

    # --- internal references -------------------------------------------------
    for r in refs:
        if r["status"] == "resolved":
            edge(r["from"], r["to"], "REFERENCES", kind=r["kind"], raw_text=r["raw_text"],
                 qualifier=r.get("qualifier"), resolved_level=r.get("resolved_level"))

    # --- external documents (plan §9a.3) ---------------------------------------
    for d in ext_docs:
        node(ext_node_id(doc_id, d["id"]), "ExternalDocument", ext_id=d["id"],
             **{k: v for k, v in d.items() if k != "id"})
    for p in provisions:
        node(ext_node_id(doc_id, p["id"]), "ExternalProvision", ext_id=p["id"],
             **{k: v for k, v in p.items() if k != "id"})
        edge(ext_node_id(doc_id, p["external_doc"]), ext_node_id(doc_id, p["id"]), "HAS_PROVISION")
    for c in citations:
        edge(c["from"], ext_node_id(doc_id, c["to"]), c["type"], role=c.get("role"), raw_text=c.get("raw_text"),
             sentence=c.get("sentence"), version=c.get("version"), via=c.get("via"))
    return nodes, edges


def validate(nodes, edges):
    ids = collections.Counter(n["id"] for n in nodes)
    dup = [i for i, c in ids.items() if c > 1]
    good, bad = [], []
    for e in edges:
        (good if e["from"] in ids and e["to"] in ids else bad).append(e)
    return good, bad, dup


def _graphml_safe(value):
    if value is None:
        return ""
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return value


def to_networkx(nodes, edges, graphml_safe=False):
    g = nx.MultiDiGraph()
    conv = _graphml_safe if graphml_safe else (lambda v: v)
    for n in nodes:
        g.add_node(n["id"], **{k: conv(v) for k, v in n.items() if k != "id"})
    for e in edges:
        # no explicit key: parallel same-type edges (one clause citing
        # "paragraph 6.3.2." twice) must stay distinct edges
        g.add_edge(e["from"], e["to"], **{k: conv(v) for k, v in e.items() if k not in ("from", "to")})
    return g


def run(ctx):
    nodes, edges = build(ctx)
    edges, bad, dup = validate(nodes, edges)
    if bad:
        print(f"[{ctx.doc_id}] WARN dropped {len(bad)} edges with a missing endpoint "
              f"(e.g. {bad[0]['type']} {bad[0]['from']} -> {bad[0]['to']})", file=sys.stderr)
    if dup:
        print(f"[{ctx.doc_id}] WARN {len(dup)} duplicate node ids (e.g. {dup[0]})", file=sys.stderr)
    write_jsonl(ctx.path("nodes.jsonl"), nodes)
    write_jsonl(ctx.path("edges.jsonl"), edges)
    nx.write_graphml(to_networkx(nodes, edges, graphml_safe=True), ctx.path("graph.graphml"))
    with open(ctx.path("graph.pickle"), "wb") as f:
        pickle.dump(to_networkx(nodes, edges), f)
    nt = collections.Counter(n["type"] for n in nodes)
    et = collections.Counter(e["type"] for e in edges)
    ctx.record("phase5_assemble", nodes=len(nodes), edges=len(edges), node_types=dict(nt), edge_types=dict(et),
               dropped_edges=len(bad), dropped_examples=bad[:20], duplicate_node_ids=dup[:20])
    print(f"[{ctx.doc_id}] phase5: {len(nodes)} nodes, {len(edges)} edges, {len(bad)} dropped", file=sys.stderr)
    return nodes, edges
