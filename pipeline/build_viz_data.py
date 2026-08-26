"""Builds a compact JSON dataset for the HTML knowledge-graph explorer from
Phase 5's nodes.jsonl/edges.jsonl. Not a numbered pipeline phase - a
one-off data-prep step for the viewer artifact.

Produces:
  - nodes: {id: {t, ...trimmed properties}}
  - tree: nested {id, label, children:[...]} - HAS_CHILD + HAS_ABBREVIATION
    + HAS_DEFINITION edges, all "contains" semantically, plus synthetic
    grouping nodes (Regulation Body / Appendices / Annexes Part A/B/C) and
    nesting "Annex X - Appendix N" divisions under their parent Annex,
    since that relationship isn't in the real edge set (each division root
    is otherwise parentless).
  - references: [{f, to, rt}] - REFERENCES edges only, for the detail
    panel's local-neighborhood view.
  - stats: precomputed counts for the summary bar.
"""
import json

NODES_PATH = "output/nodes.jsonl"
EDGES_PATH = "output/edges.jsonl"
OUT_PATH = "output/viz_data.json"

def load(path):
    with open(path) as f:
        return [json.loads(l) for l in f]


def compact_node(n):
    if n["type"] == "Clause":
        return {"t": "C", "div": n["division"], "depth": n["depth"], "num": n["local_number"],
                "body": n["body_text"], "foot": n.get("footnote_text"),
                "labels": n["labels"], "page": n["page"]}
    if n["type"] == "Abbreviation":
        return {"t": "A", "sf": n["surface_form"], "exp": n["expansion"],
                "cat": n.get("category"), "src": n["source_clause"]}
    return {"t": "D", "term": n["quoted_term"], "abbr": n.get("abbreviation"),
            "gloss": n["gloss"], "src": n["source_clause"]}


def annex_group(division):
    """'ANNEX-B6' -> 'B'; used to bucket into Annexes Part A/B/C."""
    return division[len("ANNEX-"):][0]


def division_label(div):
    if div == "BODY":
        return "Regulation Body"
    if div.startswith("APPENDIX-"):
        return f"Appendix {div.split('-')[1]}"
    if div.startswith("ANNEX-") and "." in div:
        annex, app = div[len("ANNEX-"):].split(".APP")
        return f"Appendix {app} to Annex {annex}"
    return f"Annex {div[len('ANNEX-'):]}"


def numeric_key(num):
    """'6.3.20' -> (6, 3, 20); non-numeric or missing sorts last."""
    if not num:
        return (float("inf"),)
    try:
        return tuple(int(p) for p in num.split("."))
    except ValueError:
        return (float("inf"),)


def build_tree(nodes):
    children = {}  # parent id -> [child id]
    for nid, n in nodes.items():
        parent = None
        if n["t"] == "C" and n.get("_parent_id"):
            parent = n["_parent_id"]
        elif n["t"] in ("A", "D"):
            parent = n["src"]
        if parent:
            children.setdefault(parent, []).append(nid)

    # Nest "ANNEX-X.APPN" division roots under their parent Annex "ANNEX-X".
    division_roots = {n["div"]: nid for nid, n in nodes.items()
                      if n["t"] == "C" and n["depth"] == 0}
    for div, nid in division_roots.items():
        if div.startswith("ANNEX-") and "." in div:
            parent_div = div.split(".")[0]
            if parent_div in division_roots:
                children.setdefault(division_roots[parent_div], []).append(nid)

    def label_for(nid):
        n = nodes[nid]
        if n["t"] == "A":
            return f"{n['sf']} — {n['exp']}"
        if n["t"] == "D":
            return f"“{n['term']}”"
        if n["depth"] == 0:
            return division_label(n["div"])
        prefix = f"{n['num']}. " if n["num"] else ""
        return prefix + (n["body"][:70] or "(no title)")

    def sort_key(cid):
        n = nodes[cid]
        if n["t"] != "C":
            return (2, 0, n.get("sf") or n.get("term") or "")
        if n["depth"] == 0:
            return (1, 0, n["div"])  # nested Annex-appendix divisions sort after real clauses
        return (0, numeric_key(n["num"]), "")

    def node(nid):
        kids = sorted(children.get(nid, []), key=sort_key)
        return {"id": nid, "label": label_for(nid), "t": nodes[nid]["t"],
                "children": [node(c) for c in kids]}

    body_id = division_roots.get("BODY")
    appendix_ids = sorted((nid for div, nid in division_roots.items()
                           if div.startswith("APPENDIX-")),
                          key=lambda nid: int(nodes[nid]["div"].split("-")[1]))
    annex_top = [(div, nid) for div, nid in division_roots.items()
                if div.startswith("ANNEX-") and "." not in div]

    def annex_sort_key(div_nid):
        div = div_nid[0][len("ANNEX-"):]  # e.g. "B10" or "B6a"
        num = "".join(c for c in div if c.isdigit())
        return (div[0], int(num) if num else 0, div)

    parts = {"A": [], "B": [], "C": []}
    for div, nid in sorted(annex_top, key=annex_sort_key):
        parts[annex_group(div)].append(nid)

    root_children = []
    if body_id:
        root_children.append(node(body_id))
    if appendix_ids:
        root_children.append({"id": "$group:appendix", "label": "Appendices to the Regulation",
                              "t": "G", "children": [node(n) for n in appendix_ids]})
    for part in "ABC":
        if parts[part]:
            root_children.append({"id": f"$group:annex{part}", "label": f"Annexes Part {part}",
                                  "t": "G", "children": [node(n) for n in parts[part]]})

    return {"id": "$root", "label": "UN Regulation No. 154 — 04 series",
            "t": "G", "children": root_children}


def run(nodes_path=NODES_PATH, edges_path=EDGES_PATH, out_path=OUT_PATH):
    raw_nodes = load(nodes_path)
    raw_edges = load(edges_path)

    nodes = {n["id"]: compact_node(n) for n in raw_nodes}
    for n in raw_nodes:
        if n["type"] == "Clause":
            nodes[n["id"]]["_parent_id"] = n["parent_id"]

    tree = build_tree(nodes)
    for n in nodes.values():
        n.pop("_parent_id", None)

    references = [{"f": e["from"], "to": e["to"], "rt": e["raw_text"]}
                  for e in raw_edges if e["type"] == "REFERENCES"]

    type_counts = {}
    for n in raw_nodes:
        type_counts[n["type"]] = type_counts.get(n["type"], 0) + 1
    edge_counts = {}
    for e in raw_edges:
        edge_counts[e["type"]] = edge_counts.get(e["type"], 0) + 1

    with open("output/references.jsonl") as f:
        all_refs = [json.loads(l) for l in f]
    resolved = sum(1 for r in all_refs if r["status"] == "resolved")

    data = {
        "nodes": nodes, "tree": tree, "references": references,
        "stats": {"nodeCounts": type_counts, "edgeCounts": edge_counts,
                  "refTotal": len(all_refs), "refResolved": resolved},
    }

    with open(out_path, "w") as f:
        json.dump(data, f, separators=(",", ":"), ensure_ascii=False)
    print(f"{len(nodes)} nodes, {len(references)} references -> {out_path}")


if __name__ == "__main__":
    run()
