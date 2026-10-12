"""Phase 3c - Table and Figure nodes at caption level (plan.md §8).

regions.jsonl + anchors.jsonl -> tables.jsonl, figures.jsonl.

One node per caption within its division (Euro 7 restarts "Table 1" in every
Annex, so the id carries the division). Several detected blocks under one
caption, or a table continued on the next page, are one node with several
regions. `cell_text` is the table's text, row by row with ' | ' between
cells - searchable, deliberately NOT structured values (v1 non-goal).
"""
import collections
import sys

from .common import read_jsonl, write_jsonl


def run(ctx):
    regions = {r["id"]: r for r in read_jsonl(ctx.path("regions.jsonl"))}
    anchors = read_jsonl(ctx.path("anchors.jsonl"))
    units = {u["qualified_id"]: u for u in read_jsonl(ctx.path("units.jsonl"))}
    nodes = {"table": collections.OrderedDict(), "figure": collections.OrderedDict()}
    for a in anchors:
        if a["kind"] not in nodes or not a.get("node_id"):
            continue
        r = regions[a["region_id"]]
        store = nodes[a["kind"]]
        n = store.get(a["node_id"])
        if n is None:
            unit = units.get(a["unit_id"], {})
            n = store[a["node_id"]] = {
                "id": a["node_id"],
                "caption_id": r.get("caption_id"),
                "caption": r.get("caption"),
                "defining_unit": a["unit_id"],
                "division": unit.get("division"),
                "pages": [],
                "regions": [],
                "normative": unit.get("normative", True),
            }
            if a["kind"] == "table":
                n["cell_text"] = []
                n["flow_text"] = []
                n["caption_only"] = bool(r.get("caption_only"))
            else:
                n["figure_labels"] = []
        if r["page"] not in n["pages"]:
            n["pages"].append(r["page"])
        n["regions"].append({"region_id": r["id"], "page": r["page"], "bbox": r.get("bbox")})
        if a["kind"] == "table" and r.get("cell_text"):
            n["cell_text"].append(r["cell_text"])
            n["flow_text"].append(r.get("flow_text") or "")
            n["caption_only"] = False
        if a["kind"] == "figure":
            n["figure_labels"] += r.get("figure_labels", [])
            n["caption"] = n["caption"] or r.get("caption")
    tables = list(nodes["table"].values())
    for t in tables:
        t["cell_text"] = "\n".join(t["cell_text"]) or None
        t["flow_text"] = " ".join(x for x in t.get("flow_text", []) if x) or None
        t["page"] = t["pages"][0]
    figures = list(nodes["figure"].values())
    for f in figures:
        f["page"] = f["pages"][0]
        f["figure_labels"] = [x for x in f["figure_labels"] if x.strip()]
    write_jsonl(ctx.path("tables.jsonl"), tables)
    write_jsonl(ctx.path("figures.jsonl"), figures)
    ctx.record("phase3c_tables", tables=len(tables),
               captioned_tables=sum(1 for t in tables if t["caption_id"]),
               caption_only_tables=sum(1 for t in tables if t.get("caption_only")),
               figures=len(figures))
    print(f"[{ctx.doc_id}] phase3c: {len(tables)} tables "
          f"({sum(1 for t in tables if t['caption_id'])} captioned), {len(figures)} figures", file=sys.stderr)
    return tables, figures
