"""Explorer data + page per document (plan.md §10), and output/index.html.

output/<doc_id>/nodes.jsonl + edges.jsonl -> output/<doc_id>/viz_data.json
and output/<doc_id>/kg_explorer.html (self-contained: data inlined; KaTeX
and fonts from a CDN). The tree is built from the graph's real containment
edges; top-level divisions are grouped by the profile's `viz.groups`.
"""
import collections
import html
import json
import re
import sys
from pathlib import Path

from .common import OUTPUT_DIR, numeric_key, read_json, read_jsonl

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
CONTAINS = ["HAS_DIVISION", "HAS_CHILD", "HAS_ABBREVIATION", "HAS_DEFINITION", "HAS_TABLE", "HAS_FIGURE",
            "HAS_EQUATION", "HAS_FOOTNOTE", "HAS_PROVISION"]
CODE = {"Abbreviation": "A", "Definition": "D", "Equation": "E", "Variable": "V", "Table": "T", "Figure": "F",
        "Footnote": "N", "ExternalDocument": "X", "ExternalProvision": "P", "Document": "R", "Standard": "R"}
BODY_MAX = 6000


def clip(s, n):
    s = re.sub(r"\s+", " ", s or "").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def unit_label(n):
    num = n.get("local_number")
    text = n.get("title") or re.sub(r"\[(?:TABLE|FIGURE|EQ|FORM):[^\]]+\]", "", n.get("body_text") or "").strip()
    if n.get("level") == "decimal" and num:
        return f"{num}. {clip(text, 80) or '(no title)'}"
    head = n["type"] + (f" {n['local_label']}" if n.get("local_label") else "")
    return f"{head} — {clip(text, 70)}" if text else head


def compact(n):
    t = CODE.get(n["type"], "U")
    c = {"t": t, "ty": n["type"]}
    if t == "U":
        c.update(lb=unit_label(n), title=n.get("title"), body=clip(n.get("body_text"), BODY_MAX) or None,
                 foot=n.get("footnote_text"), labels=n.get("labels"),
                 meta=[["Division", n.get("division")], ["Depth", n.get("depth")], ["Page", (n.get("page") or 0) + 1],
                       ["Normative", "yes" if n.get("normative", True) else "no"]] +
                      ([["Form", "yes"]] if n.get("is_form") else []))
    elif t == "A":
        c.update(lb=f"{n['surface_form']} — {clip(n.get('expansion'), 70)}", body=n.get("expansion"),
                 meta=[["Category", n.get("category")], ["Source", n.get("source")], ["Defined in", n.get("source_clause")]])
    elif t == "D":
        c.update(lb=f"“{n['quoted_term']}”", body=n.get("gloss"),
                 meta=[["Abbreviation", n.get("abbreviation")], ["Verb", n.get("verb")],
                       ["By reference", "yes" if n.get("defined_by_reference") else "no"], ["Scope", n.get("scope_unit")]])
    elif t == "E":
        c.update(lb=clip(n.get("linear") or "Equation (image only)", 90), latex=n.get("latex"), linear=n.get("linear"),
                 img=n.get("image_path"), gloss=[[g["symbol_text"], g.get("description"), g.get("unit")] for g in n.get("glossary") or []],
                 body=n.get("context_before"),
                 meta=[["Kind", n.get("kind")], ["Parse status", n.get("parse_status")], ["LHS", n.get("lhs")],
                       ["Source", n.get("source")], ["Page", (n.get("page") or 0) + 1], ["Outcome", n.get("outcome")],
                       ["Label", n.get("label")]])
    elif t == "V":
        c.update(lb=n["symbol"], extra=" | ".join(n.get("descriptions") or []) or None,
                 meta=[["Equations", n.get("equations")], ["LaTeX", n.get("latex")]])
    elif t == "T":
        c.update(lb=" ".join(x for x in (n.get("caption_id"), clip(n.get("caption"), 80)) if x) or "Table (uncaptioned)",
                 body=clip(n.get("cell_text"), BODY_MAX) if n.get("cell_text") else None,
                 meta=[["Pages", ", ".join(str(p + 1) for p in n.get("pages") or [])], ["Division", n.get("division")]])
    elif t == "F":
        c.update(lb=" ".join(x for x in (n.get("caption_id"), clip(n.get("caption"), 80)) if x) or "Figure",
                 body=" · ".join(n.get("figure_labels") or []) or None,
                 meta=[["Pages", ", ".join(str(p + 1) for p in n.get("pages") or [])]])
    elif t == "N":
        c.update(lb=f"Footnote {n.get('marker') or ''}".strip(), body=n.get("text"), meta=[["Page", (n.get("page") or 0) + 1]])
    elif t == "X":
        name = n.get("title") or (n.get("aliases") or [n.get("ext_id")])[0]
        c.update(lb=f"{n.get('ext_id', '')[4:]} — {clip(name, 70)}",
                 extra="Also written as: " + "; ".join(n.get("aliases") or []) + (f"\nELI: {n['eli']}" if n.get("eli") else ""),
                 meta=[["Kind", n.get("doc_kind")], ["Issuer", n.get("issuer")], ["Year", n.get("year")],
                       ["Mentions", n.get("mention_count")], ["Adopted", n.get("adoption_date")], ["OJ", n.get("oj_ref")],
                       ["Also in Document/", n.get("corpus_doc_id") or "no"]])
    elif t == "P":
        c.update(lb=f"{n.get('label')} — {n.get('external_doc', '')[4:]}", body=n.get("raw_text"),
                 meta=[["Mentions", n.get("mention_count")]])
    else:
        c.update(lb=n.get("title") or n.get("document_name") or n["id"],
                 meta=[[k, n.get(k)] for k in ("number", "series", "issuer", "region", "family", "page_count") if n.get(k)])
    return {k: v for k, v in c.items() if v not in (None, [], "")}


def build(doc_dir, profile=None):
    doc_dir = Path(doc_dir)
    manifest = read_json(doc_dir / "manifest.json", {})
    doc_id = manifest.get("doc_id")
    raw_nodes = read_jsonl(doc_dir / "nodes.jsonl")
    raw_edges = read_jsonl(doc_dir / "edges.jsonl")
    order = {n["id"]: i for i, n in enumerate(raw_nodes)}
    nodes = {n["id"]: compact(n) for n in raw_nodes}
    kids = collections.defaultdict(list)
    for e in raw_edges:
        if e["type"] in CONTAINS:
            kids[e["from"]].append(e["to"])

    def sort_children(cs):
        rank = {"U": 0, "D": 1, "A": 2, "E": 3, "T": 4, "F": 5, "N": 6, "P": 7}
        return sorted(cs, key=lambda c: (rank.get(nodes[c]["t"], 9), order.get(c, 0)))

    seen = set()

    def tree(nid, depth=0):
        if nid in seen or depth > 40:
            return {"id": nid, "label": nodes.get(nid, {}).get("lb", nid), "children": []}
        seen.add(nid)
        return {"id": nid, "label": clip(nodes[nid].get("lb", nid), 90),
                "children": [tree(c, depth + 1) for c in sort_children(kids.get(nid, []))]}

    top = sort_children(kids.get(doc_id, []))
    groups = (profile or {}).get("viz", {}).get("groups") or []
    grouped = collections.OrderedDict((g["label"], []) for g in groups)
    loose = []
    for t in top:
        suffix = t[len(doc_id) + 1:]
        g = next((g["label"] for g in groups if re.search(g["match"], suffix)), None)
        (grouped[g] if g else loose).append(t)
    children = [tree(t) for t in loose]
    for label, members in grouped.items():
        if members:
            members.sort(key=lambda m: numeric_key(m.split("-")[-1]) if "-" in m else ((9, m),))
            children.append({"id": f"$group:{label}", "label": label, "children": [tree(m) for m in members]})
    ext = sorted((i for i, n in nodes.items() if n["t"] == "X"), key=lambda i: (nodes[i]["meta"][0][1] or "", i))
    if ext:
        children.append({"id": "$group:external", "label": f"External documents ({len(ext)})",
                         "children": [tree(i) for i in ext]})
    var = sorted(i for i, n in nodes.items() if n["t"] == "V")
    if var:
        children.append({"id": "$group:variables", "label": f"Variables ({len(var)})",
                         "children": [tree(i) for i in var]})

    edges = []
    for e in raw_edges:
        if e["type"] in CONTAINS or e["type"] == "HAS_VERSION":
            continue
        text = e.get("raw_text") or e.get("description") or e.get("role") or e.get("match")
        edges.append([e["from"], e["to"], e["type"], clip(text, 140) if text else None])

    nt = collections.Counter(n["type"] for n in raw_nodes)
    et = collections.Counter(e["type"] for e in raw_edges)
    p4 = manifest.get("phases", {}).get("phase4_references", {})
    units = sum(v for k, v in nt.items() if CODE.get(k, "U") == "U")
    stats = [[units, "Structural units", "var(--clause)"],
             [nt.get("Definition", 0), "Definitions", "var(--def)"],
             [nt.get("Abbreviation", 0), "Abbreviations", "var(--abbr)"],
             [nt.get("Equation", 0), "Equations", "var(--eq)"],
             [nt.get("Table", 0), "Tables", "var(--tab)"],
             [nt.get("ExternalDocument", 0), "External docs", "var(--ext)"],
             [et.get("REFERENCES", 0), "References", "var(--ok)"],
             [f"{(p4.get('rate') or 0):.0%}", "Resolved", "var(--ok)" if (p4.get("rate") or 0) >= 0.9 else "var(--warn)"]]
    data = {"doc_id": doc_id, "nodes": nodes, "tree": {"id": "$root", "label": doc_id, "children": children},
            "edges": edges, "stats": stats}
    return data, manifest


def write_page(doc_dir, data, manifest, profile=None):
    doc_dir = Path(doc_dir)
    meta = manifest.get("metadata", {})
    title = meta.get("title") or data["doc_id"]
    kicker = (profile or {}).get("viz", {}).get("root_label") or title
    tpl = (TEMPLATE_DIR / "explorer_template.html").read_text(encoding="utf-8")
    script = (TEMPLATE_DIR / "explorer.js").read_text(encoding="utf-8")
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    page = (tpl.replace("__TITLE__", html.escape(f"{data['doc_id']} knowledge graph"))
               .replace("__KICKER__", html.escape(clip(kicker, 90)))
               .replace("__SCRIPT__", script)
               .replace("__DATA__", payload))
    (doc_dir / "kg_explorer.html").write_text(page, encoding="utf-8")


def write_index(out_root=None):
    root = Path(out_root) if out_root else OUTPUT_DIR
    rows = []
    for m in sorted(root.glob("*/manifest.json")):
        man = read_json(m, {})
        ph = man.get("phases", {})
        meta = man.get("metadata", {})
        d = m.parent.name
        qa = ph.get("phase6_qa", {})
        p5 = ph.get("phase5_assemble", {})
        rows.append(
            f"<tr><td><a href=\"{html.escape(d)}/kg_explorer.html\">{html.escape(d)}</a></td>"
            f"<td>{html.escape(clip(meta.get('title') or '', 90))}</td><td>{html.escape(man.get('profile') or '')}</td>"
            f"<td class=n>{man.get('page_count', '')}</td><td class=n>{p5.get('nodes', '')}</td><td class=n>{p5.get('edges', '')}</td>"
            f"<td class=n>{qa.get('expectations_passed', '')}/{qa.get('expectations', '')}</td>"
            f"<td><a href=\"{html.escape(d)}/qa_report.md\">QA report</a> · <a href=\"{html.escape(d)}/external_citations.csv\">external citations</a></td></tr>")
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Regulation knowledge graphs</title>
<style>
:root {{ --bg:#EEF1F5; --surface:#fff; --ink:#1B2430; --muted:#5B6774; --line:#D7DEE4; --accent:#1D5DA8; }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{ --bg:#0F171F; --surface:#16212C; --ink:#E5EAEF; --muted:#93A2AF; --line:#263441; --accent:#5FA0E8; }} }}
:root[data-theme="dark"] {{ --bg:#0F171F; --surface:#16212C; --ink:#E5EAEF; --muted:#93A2AF; --line:#263441; --accent:#5FA0E8; }}
body {{ margin:0; background:var(--bg); color:var(--ink); font:14.5px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif; }}
main {{ max-width:1100px; margin:0 auto; padding:32px 16px; }}
h1 {{ font-size:22px; margin:0 0 6px; }} p {{ color:var(--muted); margin:0 0 20px; }}
.wrap {{ overflow-x:auto; background:var(--surface); border:1px solid var(--line); border-radius:10px; }}
table {{ border-collapse:collapse; width:100%; font-size:13.5px; }}
th, td {{ text-align:left; padding:10px 12px; border-bottom:1px solid var(--line); vertical-align:top; }}
th {{ font-size:11px; text-transform:uppercase; letter-spacing:.06em; color:var(--muted); }}
td.n {{ text-align:right; font-variant-numeric:tabular-nums; }} a {{ color:var(--accent); }}
</style></head><body><main>
<h1>Regulation knowledge graphs</h1>
<p>One graph per document (no cross-document merging). Open an explorer, or read the document's QA report.</p>
<div class="wrap"><table><thead><tr><th>Document</th><th>Title</th><th>Profile</th><th>Pages</th><th>Nodes</th><th>Edges</th><th>Expectations</th><th></th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></div>
</main></body></html>"""
    (root / "index.html").write_text(page, encoding="utf-8")


def run(ctx):
    data, manifest = build(ctx.out, ctx.profile)
    with open(ctx.path("viz_data.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    write_page(ctx.out, data, manifest, ctx.profile)
    print(f"[{ctx.doc_id}] viz: {len(data['nodes'])} nodes, {len(data['edges'])} relation edges -> kg_explorer.html",
          file=sys.stderr)


if __name__ == "__main__":
    from .profile import Context, resolve_documents
    for pdf, entry in resolve_documents(sys.argv[1] if len(sys.argv) > 1 else "all"):
        run(Context(pdf, entry))
    write_index()
