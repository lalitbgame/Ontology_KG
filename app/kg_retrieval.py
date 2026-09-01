"""No-LLM retrieval layer over the UN Reg. 154 knowledge graph.

Turns a plain requirement keyword/phrase into a structured, citation-backed
context block ready to be handed to an LLM as a prompt. Everything here is
deterministic: whole-word/substring matching and graph traversal only. No
embeddings, no NER, no LLM call - consistent with the pipeline's own
"no LLM anywhere in the pipeline" constraint (see Ontology_KG_Project_Plan.md).
This module only *builds* the prompt text; sending it to a model is left to
whatever chain is added later.

Graph shape this module actually walks (the graph pipeline/phase5_assemble.py
produces today, not the full aspirational schema.yaml - see that module's
docstring for what's deferred):

  Nodes
    Clause        id = qualified_id (e.g. "REG154.04.BODY.6.3.2")
                  division, depth, parent_id, local_number, page,
                  body_text, footnote_text, has_body, labels
    Abbreviation  id = "ABBR:<surface_form>"
                  surface_form, expansion, category, source_clause
    Definition    id = "DEF:<source_clause>"
                  quoted_term, abbreviation, gloss, source_clause

  Edges
    HAS_CHILD          Clause -> Clause          containment / hierarchy
    HAS_ABBREVIATION   Clause -> Abbreviation     clause defines an abbreviation
    HAS_DEFINITION     Clause -> Definition       clause defines a term
    REFERENCES         Clause -> Clause           resolved cross-reference, raw_text
"""

from __future__ import annotations

import json
import re
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

import networkx as nx

REPO_ROOT = Path(__file__).resolve().parent.parent
NODES_PATH = REPO_ROOT / "output" / "nodes.jsonl"
EDGES_PATH = REPO_ROOT / "output" / "edges.jsonl"

STANDARD_LABEL = "UN Regulation No. 154 (WLTP), 04 series of amendments"


# ----------------------------------------------------------------------------
# Graph loading
# ----------------------------------------------------------------------------

def _iter_jsonl(path: Path):
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def load_graph(nodes_path: Path = NODES_PATH, edges_path: Path = EDGES_PATH) -> nx.MultiDiGraph:
    """Rebuild the MultiDiGraph straight from nodes.jsonl / edges.jsonl.

    Deliberately does NOT unpickle output/graph.pickle: jsonl is portable
    across networkx versions and doesn't execute arbitrary code on load,
    which matters more for a Streamlit app someone else might point at
    their own output/ directory.
    """
    nodes_path, edges_path = Path(nodes_path), Path(edges_path)
    for p in (nodes_path, edges_path):
        if not p.exists():
            raise FileNotFoundError(f"{p} not found - run the pipeline first (pipeline/phase5_assemble.py).")

    g = nx.MultiDiGraph()
    for n in _iter_jsonl(nodes_path):
        g.add_node(n.pop("id"), **n)
    for e in _iter_jsonl(edges_path):
        g.add_edge(e["from"], e["to"], **{k: v for k, v in e.items() if k not in ("from", "to")})
    return g


# ----------------------------------------------------------------------------
# Search
# ----------------------------------------------------------------------------

def _word_pattern(word: str) -> re.Pattern:
    return re.compile(r"\b" + re.escape(word) + r"\b", re.IGNORECASE)


def _snippet(text: str, terms: list[str], width: int = 220) -> str:
    """Short window of `text` centred on the first matched term, deterministic."""
    if not text:
        return ""
    for term in terms:
        m = _word_pattern(term).search(text)
        if m:
            start = max(0, m.start() - width // 2)
            end = min(len(text), m.end() + width // 2)
            snippet = text[start:end].strip()
            prefix = "… " if start > 0 else ""
            suffix = " …" if end < len(text) else ""
            return f"{prefix}{snippet}{suffix}"
    return textwrap.shorten(text, width=width, placeholder="…")


@dataclass
class Match:
    node_id: str          # id of the node that actually matched (Clause/Definition/Abbreviation)
    node_type: str        # "Clause" | "Definition" | "Abbreviation"
    citation_id: str      # qualified_id of the citable Clause (== node_id for Clause matches,
                           # == source_clause for Definition/Abbreviation matches)
    score: int
    hits: dict = field(default_factory=dict)   # term -> occurrence count
    snippet: str = ""


# node type -> searchable text fields on that node's own data dict
_SEARCH_FIELDS = {
    "Clause": ("body_text",),
    "Definition": ("quoted_term", "gloss"),
    "Abbreviation": ("surface_form", "expansion"),
}


def search(
    graph: nx.MultiDiGraph,
    query: str,
    *,
    require_all_terms: bool = True,
    divisions: Optional[Iterable[str]] = None,
    max_results: int = 10,
) -> list[Match]:
    """Deterministic keyword search across Clause / Definition / Abbreviation text.

    Scoring = sum of whole-word occurrence counts of each query term across
    the node's searchable fields, plus a bonus for an exact multi-word
    phrase hit. No stemming, no fuzzy matching, no embeddings - regex only.
    """
    terms = [t for t in re.split(r"\s+", query.strip()) if t]
    if not terms:
        return []
    patterns = [_word_pattern(t) for t in terms]
    phrase_pattern = re.compile(re.escape(query.strip()), re.IGNORECASE) if len(terms) > 1 else None
    division_filter = set(divisions) if divisions else None

    results: list[Match] = []
    for node_id, data in graph.nodes(data=True):
        ntype = data.get("type")
        if ntype not in _SEARCH_FIELDS:
            continue
        if ntype == "Clause":
            if not data.get("has_body"):
                continue
            citation_id = node_id
        else:
            citation_id = data.get("source_clause")
        if division_filter and graph.nodes.get(citation_id, {}).get("division") not in division_filter:
            continue

        fields = {k: data.get(k) or "" for k in _SEARCH_FIELDS[ntype]}
        hits: dict[str, int] = {}
        for term, pat in zip(terms, patterns):
            count = sum(len(pat.findall(v)) for v in fields.values())
            if count:
                hits[term] = count
        if not hits:
            continue
        if require_all_terms and len(hits) < len(terms):
            continue

        score = sum(hits.values())
        if phrase_pattern:
            phrase_hits = len(phrase_pattern.findall(" ".join(fields.values())))
            score += phrase_hits * 5  # exact-phrase bonus; still a plain count, no ranking model

        results.append(Match(
            node_id=node_id,
            node_type=ntype,
            citation_id=citation_id,
            score=score,
            hits=hits,
            snippet=_snippet(next((v for v in fields.values() if v), ""), terms),
        ))

    results.sort(key=lambda m: (-m.score, m.citation_id or ""))
    return results[:max_results]


# ----------------------------------------------------------------------------
# Hierarchy / area-of-requirement traversal
# ----------------------------------------------------------------------------

def ancestor_chain(graph: nx.MultiDiGraph, clause_id: str) -> list[str]:
    """Root-to-node list of Clause ids, walking the `parent_id` property."""
    chain, node_id, seen = [], clause_id, set()
    while node_id and node_id in graph.nodes and node_id not in seen:
        seen.add(node_id)
        chain.append(node_id)
        node_id = graph.nodes[node_id].get("parent_id")
    return list(reversed(chain))


def clause_label(graph: nx.MultiDiGraph, clause_id: str, width: int = 110) -> str:
    """Short human-readable label for a clause: its number + a text snippet."""
    data = graph.nodes.get(clause_id, {})
    local = data.get("local_number")
    text = (data.get("body_text") or "").strip()
    if not text:
        return f"{local or clause_id} (heading, no body text)"
    return f"{local}. {textwrap.shorten(text, width=width, placeholder='…')}" if local \
        else textwrap.shorten(text, width=width, placeholder="…")


def area_of_requirement(graph: nx.MultiDiGraph, clause_id: str) -> dict:
    """Division + nearest depth==1 'Section' ancestor - the top-level area a clause sits under."""
    chain = ancestor_chain(graph, clause_id)
    section_id = next((n for n in chain if graph.nodes[n].get("depth") == 1), None)
    return {
        "division": graph.nodes.get(clause_id, {}).get("division"),
        "division_root": chain[0] if chain else None,
        "section_id": section_id,
        "section_label": clause_label(graph, section_id) if section_id else None,
    }


def defined_terms(graph: nx.MultiDiGraph, clause_id: str) -> list[tuple[str, dict]]:
    """Definitions/Abbreviations this clause introduces (HAS_DEFINITION / HAS_ABBREVIATION)."""
    if clause_id not in graph.nodes:
        return []
    return [(t, graph.nodes[t]) for _, t, d in graph.out_edges(clause_id, data=True)
            if d.get("type") in ("HAS_DEFINITION", "HAS_ABBREVIATION")]


def cross_references(graph: nx.MultiDiGraph, clause_id: str):
    """(outgoing, incoming) REFERENCES edges for this clause, each as (other_id, raw_text)."""
    if clause_id not in graph.nodes:
        return [], []
    outgoing = [(t, d.get("raw_text")) for _, t, d in graph.out_edges(clause_id, data=True) if d.get("type") == "REFERENCES"]
    incoming = [(s, d.get("raw_text")) for s, _, d in graph.in_edges(clause_id, data=True) if d.get("type") == "REFERENCES"]
    return outgoing, incoming


def build_abbreviation_index(graph: nx.MultiDiGraph) -> dict[str, tuple[str, dict]]:
    """surface_form -> (node_id, node_data) for every Abbreviation node in the graph."""
    return {d["surface_form"]: (n, d) for n, d in graph.nodes(data=True)
            if d.get("type") == "Abbreviation" and d.get("surface_form")}


def mentioned_abbreviations(graph: nx.MultiDiGraph, abbr_index: dict, clause_id: str, exclude_ids: set) -> list[tuple[str, str, str]]:
    """Known abbreviations whose surface form literally occurs (whole word) in this clause's
    body text, excluding ones already surfaced via `defined_terms`. Mirrors the plan's deferred
    MENTIONED_IN edge (§6.5), computed at query time instead of materialized in the graph."""
    text = graph.nodes.get(clause_id, {}).get("body_text") or ""
    if not text:
        return []
    return sorted(
        (surface, data.get("expansion", ""), node_id)
        for surface, (node_id, data) in abbr_index.items()
        if node_id not in exclude_ids and _word_pattern(surface).search(text)
    )


# ----------------------------------------------------------------------------
# Structured prompt assembly
# ----------------------------------------------------------------------------

def _match_lines(
    graph: nx.MultiDiGraph,
    i: int,
    total: int,
    m: Match,
    abbr_index: dict,
    include_glossary: bool,
    include_references: bool,
) -> list[str]:
    """Full text block for a single match: Area of Requirement -> Requirement
    Hierarchy -> Citation Paragraph -> (optional) defined/used terms ->
    (optional) cross-references."""
    citation_id = m.citation_id
    if citation_id not in graph.nodes:
        return []
    clause = graph.nodes[citation_id]
    area = area_of_requirement(graph, citation_id)
    chain = ancestor_chain(graph, citation_id)

    lines = [
        f"## MATCH {i} of {total}  (relevance score {m.score}, matched terms: {', '.join(m.hits) or '-'})",
        "",
        "### Area of Requirement",
        f"- Division: {area['division']}  (division root: {area['division_root']})",
    ]
    if area["section_id"]:
        lines.append(f"- Top-level Section: {area['section_id']} — {area['section_label']}")
    lines.append("")

    lines.append("### Requirement Hierarchy")
    lines += [
        f"{'>>' if node_id == citation_id else '  '}{'  ' * d}- {node_id}  {clause_label(graph, node_id, width=90)}"
        for d, node_id in enumerate(chain)
    ]
    lines.append("")

    lines.append("### Citation Paragraph")
    lines.append(f"[{citation_id}]  (page {clause.get('page')})")
    lines.append(f'"{(clause.get("body_text") or "").strip()}"')
    if clause.get("footnote_text"):
        lines.append(f"Footnote: {clause['footnote_text']}")
    if m.node_type == "Definition":
        td = graph.nodes[m.node_id]
        lines.append(f'Defined term in this citation: "{td.get("quoted_term")}" means {td.get("gloss")}  [{m.node_id}]')
    elif m.node_type == "Abbreviation":
        td = graph.nodes[m.node_id]
        lines.append(f'Abbreviation in this citation: {td.get("surface_form")} = {td.get("expansion")}  [{m.node_id}]')
    lines.append("")

    if include_glossary:
        terms = defined_terms(graph, citation_id)
        if terms:
            lines.append("### Terms Defined in This Clause")
            lines += [
                f'- "{td.get("quoted_term")}" — {td.get("gloss")}  [{tid}]' if td.get("type") == "Definition"
                else f'- {td.get("surface_form")} — {td.get("expansion")}  [{tid}]'
                for tid, td in terms
            ]
            lines.append("")

        mentioned = mentioned_abbreviations(graph, abbr_index, citation_id, exclude_ids={tid for tid, _ in terms})
        if mentioned:
            lines.append("### Abbreviations Used in This Paragraph")
            lines += [f"- {surface} — {expansion}  [{tid}]" for surface, expansion, tid in mentioned]
            lines.append("")

    if include_references:
        out_refs, in_refs = cross_references(graph, citation_id)
        if out_refs:
            lines.append("### Cross-References From This Clause")
            lines += [f'- → {tgt}  (as "{raw}")' for tgt, raw in out_refs]
            lines.append("")
        if in_refs:
            lines.append("### Cross-References To This Clause")
            lines += [f'- ← {src}  (as "{raw}")' for src, raw in in_refs]
            lines.append("")

    lines += ["---", ""]
    return lines


def build_structured_prompt(
    graph: nx.MultiDiGraph,
    query: str,
    matches: list[Match],
    *,
    include_glossary: bool = True,
    include_references: bool = True,
) -> str:
    """Assemble the final structured, citation-backed prompt text. Pure string
    formatting over graph data - no LLM call."""
    abbr_index = build_abbreviation_index(graph) if include_glossary else {}

    lines = [
        f"# STRUCTURED REQUIREMENT CONTEXT — {STANDARD_LABEL}",
        f'# Query keyword(s): "{query}"',
        "# Retrieval method: deterministic keyword search + graph traversal over the",
        "#   ontology knowledge graph (no LLM, embeddings, or NER used to build this prompt)",
        f"# Matched paragraphs: {len(matches)}",
        "",
        "## TASK",
        (f'You are a regulatory-compliance assistant. Using ONLY the context provided below '
         f'(do not use outside knowledge), answer the requirement described by the keyword(s) '
         f'"{query}". Every factual claim must cite the paragraph id(s) it is based on in square '
         f'brackets, e.g. [REG154.04.BODY.6.3.2]. If the context below does not fully cover the '
         f'requirement, say so explicitly instead of guessing.'),
        "",
    ]
    for i, m in enumerate(matches, 1):
        lines += _match_lines(graph, i, len(matches), m, abbr_index, include_glossary, include_references)

    return "\n".join(lines)
