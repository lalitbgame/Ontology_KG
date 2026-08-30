"""
Generate a knowledge-graph illustration (static PNG + interactive HTML)
for any branch of the ontology, rooted at a given clause/annex/appendix id.

Usage
-----
  # See every top-level component (Body, each Annex, each Appendix) with
  # its total descendant count, to pick a scope that's a reasonable size:
  python pipeline/kg_illustrate.py --list

  # Drill into the subsections of one component to find a smaller scope:
  python pipeline/kg_illustrate.py --list-under REG154.04.ANNEX-B8

  # Generate both outputs for a chosen root:
  python pipeline/kg_illustrate.py --root REG154.04.ANNEX-B8.1

  # Static PNG only, custom output name:
  python pipeline/kg_illustrate.py --root REG154.04.BODY.6 --no-html --out-name specs_and_tests

Outputs land in output/kg_illustration_<slug>.png and
output/kg_illustration_<slug>.html, where <slug> is derived from --root
(or set explicitly with --out-name).
"""
import argparse
import collections
import json
import math
import re
from pathlib import Path

PIPELINE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = PIPELINE_DIR.parent
NODES_PATH = PROJECT_DIR / "output" / "nodes.jsonl"
EDGES_PATH = PROJECT_DIR / "output" / "edges.jsonl"
TEMPLATE_PATH = PIPELINE_DIR / "templates" / "graph_template.html"
OUTPUT_DIR = PROJECT_DIR / "output"

DOC_LABEL_DEFAULT = "UN Reg. No. 154 (WLTP) · Rev.04"


# --------------------------------------------------------------------------
# Data loading
# --------------------------------------------------------------------------

def load_graph_data():
    nodes = {}
    with open(NODES_PATH) as f:
        for line in f:
            d = json.loads(line)
            nodes[d["id"]] = d
    edges = []
    with open(EDGES_PATH) as f:
        for line in f:
            edges.append(json.loads(line))
    return nodes, edges


def build_indexes(edges, nodes):
    has_child = collections.defaultdict(list)
    references = []
    definitions = {}   # clause_id -> quoted_term
    def_gloss = {}      # clause_id -> gloss text
    for e in edges:
        if e["type"] == "HAS_CHILD":
            has_child[e["from"]].append(e["to"])
        elif e["type"] == "REFERENCES":
            references.append(e)
        elif e["type"] == "HAS_DEFINITION":
            dnode = nodes.get(e["to"], {})
            term = dnode.get("quoted_term")
            if term:
                definitions[e["from"]] = term
                def_gloss[e["from"]] = dnode.get("gloss")
    return has_child, references, definitions, def_gloss


def descendant_ids(root, has_child):
    seen = set()
    stack = [root]
    while stack:
        n = stack.pop()
        if n in seen:
            continue
        seen.add(n)
        stack.extend(has_child.get(n, []))
    return seen


# --------------------------------------------------------------------------
# Discovery helpers (--list / --list-under)
# --------------------------------------------------------------------------

def cmd_list(nodes, has_child):
    roots = [d for d in nodes.values() if "DivisionRoot" in d.get("labels", [])]
    rows = [(len(descendant_ids(d["id"], has_child)), d["id"]) for d in roots]
    rows.sort(reverse=True)
    print(f"{'nodes':>6}  component id")
    print("-" * 46)
    for n, r in rows:
        print(f"{n:6d}  {r}")
    print("\nUse --list-under <id> to see the subsections inside one component,")
    print("or --root <id> to generate an illustration rooted there directly.")


def cmd_list_under(nodes, has_child, under):
    if under not in nodes:
        raise SystemExit(f"Unknown id: {under}")
    kids = has_child.get(under, [])
    if not kids:
        raise SystemExit(f"{under} has no children (it may itself be a leaf clause).")
    rows = [(len(descendant_ids(k, has_child)), k) for k in kids]
    rows.sort(reverse=True)
    print(f"Subsections of {under}:\n")
    print(f"{'nodes':>6}  id{'':38s}heading")
    print("-" * 90)
    for n, r in rows:
        d = nodes[r]
        heading = (d.get("body_text") or "").strip().replace("\n", " ")[:55]
        print(f"{n:6d}  {r:40s}{heading}")


# --------------------------------------------------------------------------
# Subgraph extraction
# --------------------------------------------------------------------------

def build_subgraph(root, nodes, has_child, references, include_refs=True):
    if root not in nodes:
        raise SystemExit(
            f"Root id not found in nodes.jsonl: {root}\n"
            "Run with --list or --list-under <component> to find a valid id."
        )
    core = descendant_ids(root, has_child)

    ref_edges_used = []
    if include_refs:
        ref_edges_used = [e for e in references if e["from"] in core or e["to"] in core]

    child_edges_used = [
        (p, k) for p, kids in has_child.items() if p in core for k in kids if k in core
    ]
    return core, child_edges_used, ref_edges_used


def short_label(node_id, nodes, definitions):
    if node_id in definitions:
        term = definitions[node_id]
        return term if len(term) <= 34 else term[:31] + "..."
    d = nodes.get(node_id)
    if d is None:
        return node_id.split(".")[-1]
    local = d.get("local_number")
    if node_id.startswith("REG154.04.ANNEX-"):
        rest = node_id[len("REG154.04.ANNEX-"):]
        annex_id = rest.split(".")[0]
        if "." in rest:
            return f"Annex {annex_id} §{local}" if local else f"Annex {annex_id}"
        return f"Annex {annex_id}"
    if node_id.startswith("REG154.04.APPENDIX-"):
        return "Appendix " + node_id[len("REG154.04.APPENDIX-"):]
    if local:
        return f"§{local}"
    return node_id.split(".")[-1]


def human_title(root, nodes):
    label = short_label(root, nodes, {})
    d = nodes.get(root, {})
    heading = (d.get("body_text") or "").strip().replace("\n", " ")
    if heading:
        cut = heading[:48]
        if len(heading) > 48:
            cut = cut.rsplit(" ", 1)[0]
        return f"{label} — {cut}"
    return label


def slugify(root):
    tail = root
    if tail.startswith("REG154.04."):
        tail = tail[len("REG154.04."):]
    tail = tail.lower().replace("annex-", "annex").replace("appendix-", "appendix")
    tail = re.sub(r"[^a-z0-9]+", "-", tail).strip("-")
    return tail or "graph"


# --------------------------------------------------------------------------
# Export payload shared by both renderers
# --------------------------------------------------------------------------

def build_payload(root, nodes, core, child_edges_used, ref_edges_used,
                   definitions, def_gloss):
    node_ids = set()
    for p, k in child_edges_used:
        node_ids.add(p)
        node_ids.add(k)
    for e in ref_edges_used:
        node_ids.add(e["from"])
        node_ids.add(e["to"])
    node_ids |= core  # keep isolated core nodes too (e.g. a childless leaf root)

    degree = collections.Counter()
    for p, k in child_edges_used:
        degree[p] += 1
        degree[k] += 1
    for e in ref_edges_used:
        degree[e["from"]] += 1
        degree[e["to"]] += 1

    out_nodes = []
    for nid in sorted(node_ids):
        d = nodes.get(nid, {})
        is_core = nid in core
        label = short_label(nid, nodes, definitions)
        text = None
        if nid in definitions:
            text = def_gloss.get(nid)
        elif d.get("body_text"):
            bt = d["body_text"]
            text = bt if len(bt) <= 600 else bt[:597] + "..."
        out_nodes.append({
            "id": nid,
            "label": label,
            "core": is_core,
            "term": definitions.get(nid),
            "text": text,
            "local": d.get("local_number"),
            "labels": d.get("labels", []),
            "degree": degree[nid] or 1,
        })

    out_edges = []
    for p, k in child_edges_used:
        out_edges.append({"source": p, "target": k, "kind": "child"})
    for e in ref_edges_used:
        out_edges.append({
            "source": e["from"], "target": e["to"], "kind": "ref",
            "raw": e.get("raw_text"),
        })

    return {"root": root, "nodes": out_nodes, "edges": out_edges}


# --------------------------------------------------------------------------
# Renderers
# --------------------------------------------------------------------------

def render_static(payload, title, out_path):
    import networkx as nx
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    G = nx.Graph()
    for n in payload["nodes"]:
        G.add_node(n["id"], core=n["core"], label=n["label"])
    for e in payload["edges"]:
        G.add_edge(e["source"], e["target"], kind=e["kind"])
    G.remove_nodes_from(list(nx.isolates(G)))

    if G.number_of_nodes() == 0:
        print("Nothing to draw (empty graph) — skipping static render.")
        return

    degrees = dict(G.degree())
    sizes = {n: 90 + 55 * math.sqrt(degrees[n]) for n in G.nodes()}
    pos = nx.spring_layout(G, k=2.2 / math.sqrt(G.number_of_nodes()), iterations=200, seed=7)

    fig, ax = plt.subplots(figsize=(36, 23), dpi=200)
    ax.set_facecolor("white")
    fig.patch.set_facecolor("white")

    child_edges = [(u, v) for u, v, d in G.edges(data=True) if d["kind"] == "child"]
    ref_edges_g = [(u, v) for u, v, d in G.edges(data=True) if d["kind"] == "ref"]

    nx.draw_networkx_edges(G, pos, edgelist=child_edges, edge_color="#9aa0a6",
                            width=0.7, alpha=0.55, ax=ax)
    nx.draw_networkx_edges(G, pos, edgelist=ref_edges_g, edge_color="#c58b2a",
                            width=0.9, alpha=0.55, ax=ax, style="dashed")

    node_list = list(G.nodes())
    node_colors = ["#1f6fb2" if G.nodes[n]["core"] else "#7fb0d8" for n in node_list]
    node_sizes = [sizes[n] for n in node_list]

    nx.draw_networkx_nodes(G, pos, nodelist=node_list, node_color=node_colors,
                            node_size=node_sizes, linewidths=0, ax=ax)

    for n in node_list:
        x, y = pos[n]
        fs = 5.5 + 2.6 * math.log1p(degrees[n])
        ax.text(x, y, G.nodes[n]["label"], fontsize=min(fs, 12), ha="center",
                va="center", color="#111111", zorder=5)

    ax.set_title(title, fontsize=13, color="#222222", pad=14)
    ax.axis("off")
    plt.tight_layout()
    plt.savefig(out_path, facecolor="white")
    plt.close(fig)
    print(f"Saved static illustration: {out_path}  "
          f"({G.number_of_nodes()} nodes, {G.number_of_edges()} edges)")


def render_html(payload, doc_label, title, out_path):
    raw = json.dumps(payload, separators=(",", ":")).replace("</", "<\\/")
    template = TEMPLATE_PATH.read_text()
    html = (template
            .replace("__GRAPH_DATA__", raw)
            .replace("__PAGE_TITLE__", title)
            .replace("__DOC_LABEL__", doc_label))
    out_path.write_text(html)
    print(f"Saved interactive illustration: {out_path}  "
          f"({len(payload['nodes'])} nodes, {len(payload['edges'])} edges)")


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", help="Node id to root the illustration at "
                                        "(e.g. REG154.04.ANNEX-B8.1, REG154.04.BODY.6)")
    parser.add_argument("--list", action="store_true",
                         help="List every top-level component (Body/Annex/Appendix) "
                              "with its total descendant count, then exit")
    parser.add_argument("--list-under", metavar="ID",
                         help="List the subsections of a given component/clause id, then exit")
    parser.add_argument("--no-refs", action="store_true",
                         help="Exclude the one-hop REFERENCES periphery (core subtree only)")
    parser.add_argument("--no-static", action="store_true", help="Skip the PNG render")
    parser.add_argument("--no-html", action="store_true", help="Skip the interactive HTML render")
    parser.add_argument("--out-name", help="Output filename stem (default: derived from --root)")
    parser.add_argument("--title", help="Override the human-readable title used in both outputs")
    parser.add_argument("--doc-label", default=DOC_LABEL_DEFAULT,
                         help="Small eyebrow label shown above the title in the HTML header")
    args = parser.parse_args()

    nodes, edges = load_graph_data()
    has_child, references, definitions, def_gloss = build_indexes(edges, nodes)

    if args.list:
        cmd_list(nodes, has_child)
        return
    if args.list_under:
        cmd_list_under(nodes, has_child, args.list_under)
        return
    if not args.root:
        parser.error("--root is required (or use --list / --list-under to find one)")

    core, child_edges_used, ref_edges_used = build_subgraph(
        args.root, nodes, has_child, references, include_refs=not args.no_refs)

    payload = build_payload(args.root, nodes, core, child_edges_used,
                             ref_edges_used, definitions, def_gloss)

    total = len(payload["nodes"])
    if total > 600:
        print(f"Warning: {total} nodes in scope — labels will likely overlap heavily. "
              f"Consider --list-under {args.root} to find a smaller subsection, "
              f"or pass --no-refs to drop the reference periphery.")

    slug = args.out_name or slugify(args.root)
    title = args.title or human_title(args.root, nodes)

    if not args.no_static:
        render_static(payload, title, OUTPUT_DIR / f"kg_illustration_{slug}.png")
    if not args.no_html:
        render_html(payload, args.doc_label, title, OUTPUT_DIR / f"kg_illustration_{slug}.html")


if __name__ == "__main__":
    main()
