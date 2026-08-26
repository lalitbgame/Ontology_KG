"""Phase 5 - graph assembly & load (task.md Phase 5).

Merges clauses.jsonl + abbreviations.jsonl + definitions.jsonl into one
node set, and clause parent_id + references.jsonl (resolved only, since an
unresolved reference has no real target) into one edge set, validates
referential integrity, then builds the graph in NetworkX - the chosen
store for v1 (schema.yaml graph-store-choice: NetworkX/JSON, no Neo4j
server). The Neo4j-specific task.md bullets (stand up Docker, Cypher
loader, DB constraints) are skipped for that reason.

Also NOT part of v1's actual graph: Standard, Version, Division (proper),
ScopeParagraph, Area, Attributes, Constraints, Table, Figure - schema.yaml
defines these node types but no phase populates them yet (see
output/PHASE1_2_NOTES.md). The Clause depth-0 "division root" pseudo-node
stands in for Division.
"""
import sys
import json
import pickle

import networkx as nx

CLAUSES_PATH = "output/clauses.jsonl"
ABBR_PATH = "output/abbreviations.jsonl"
DEF_PATH = "output/definitions.jsonl"
REFS_PATH = "output/references.jsonl"

NODES_OUT = "output/nodes.jsonl"
EDGES_OUT = "output/edges.jsonl"
GRAPHML_OUT = "output/graph.graphml"
PICKLE_OUT = "output/graph.pickle"


def abbr_id(surface_form):
    return f"ABBR:{surface_form}"


def def_id(source_clause):
    return f"DEF:{source_clause}"


def build_nodes(clauses, abbreviations, definitions):
    nodes = []
    for c in clauses:
        nodes.append({"id": c["qualified_id"], "type": "Clause",
                      **{k: v for k, v in c.items() if k != "qualified_id"}})
    for a in abbreviations:
        nodes.append({"id": abbr_id(a["surface_form"]), "type": "Abbreviation", **a})
    for d in definitions:
        nodes.append({"id": def_id(d["source_clause"]), "type": "Definition", **d})
    return nodes


def build_edges(clauses, abbreviations, definitions, references):
    edges = []
    for c in clauses:
        if c["parent_id"]:
            edges.append({"from": c["parent_id"], "to": c["qualified_id"], "type": "HAS_CHILD"})
    for a in abbreviations:
        edges.append({"from": a["source_clause"], "to": abbr_id(a["surface_form"]),
                      "type": "HAS_ABBREVIATION"})
    for d in definitions:
        edges.append({"from": d["source_clause"], "to": def_id(d["source_clause"]),
                      "type": "HAS_DEFINITION"})
    for r in references:
        if r["status"] == "resolved":
            edges.append({"from": r["from"], "to": r["to"], "type": "REFERENCES",
                          "raw_text": r["raw_text"]})
    return edges


def validate(nodes, edges):
    """Referential-integrity check (task.md): every edge endpoint must
    resolve to a real node id. Bad edges are dropped, never silently kept -
    a graph edge pointing at nothing is worse than a missing edge."""
    ids = {n["id"] for n in nodes}
    good, bad = [], []
    for e in edges:
        (good if e["from"] in ids and e["to"] in ids else bad).append(e)
    return good, bad


def _graphml_safe(value):
    """GraphML attributes must be a scalar type; None/list don't qualify."""
    if value is None:
        return ""
    if isinstance(value, list):
        return "|".join(str(v) for v in value)
    return value


def to_networkx(nodes, edges, graphml_safe=False):
    g = nx.MultiDiGraph()
    conv = _graphml_safe if graphml_safe else (lambda v: v)
    for n in nodes:
        g.add_node(n["id"], **{k: conv(v) for k, v in n.items() if k != "id"})
    for e in edges:
        # No explicit `key=`: two REFERENCES edges between the same pair of
        # clauses (e.g. "paragraph 6.3.2." mentioned twice) are genuinely
        # distinct edges - keying by type alone made the second add_edge
        # silently overwrite the first instead of adding a parallel edge.
        g.add_edge(e["from"], e["to"],
                   **{k: conv(v) for k, v in e.items() if k not in ("from", "to")})
    return g


def run(clauses_path=CLAUSES_PATH, abbr_path=ABBR_PATH, def_path=DEF_PATH,
        refs_path=REFS_PATH, nodes_out=NODES_OUT, edges_out=EDGES_OUT,
        graphml_out=GRAPHML_OUT, pickle_out=PICKLE_OUT):
    with open(clauses_path) as f:
        clauses = [json.loads(l) for l in f]
    with open(abbr_path) as f:
        abbreviations = [json.loads(l) for l in f]
    with open(def_path) as f:
        definitions = [json.loads(l) for l in f]
    with open(refs_path) as f:
        references = [json.loads(l) for l in f]

    nodes = build_nodes(clauses, abbreviations, definitions)
    edges = build_edges(clauses, abbreviations, definitions, references)
    edges, bad = validate(nodes, edges)
    if bad:
        print(f"WARN dropped {len(bad)} edges with an unresolved endpoint "
              f"(should be 0 - upstream phases are supposed to guarantee this)",
              file=sys.stderr)

    with open(nodes_out, "w") as f:
        for n in nodes:
            f.write(json.dumps(n) + "\n")
    with open(edges_out, "w") as f:
        for e in edges:
            f.write(json.dumps(e) + "\n")

    g = to_networkx(nodes, edges, graphml_safe=True)
    nx.write_graphml(g, graphml_out)
    with open(pickle_out, "wb") as f:
        pickle.dump(to_networkx(nodes, edges), f)

    print(f"{len(nodes)} nodes, {len(edges)} edges -> {nodes_out}, {edges_out} | "
          f"graph -> {graphml_out}, {pickle_out}", file=sys.stderr)


if __name__ == "__main__":
    run(*sys.argv[1:])
