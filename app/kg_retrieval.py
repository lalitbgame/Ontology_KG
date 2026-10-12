"""No-LLM retrieval layer over the per-document regulation knowledge graphs.

Turns a plain requirement keyword/phrase into a structured, citation-backed
context block ready to be handed to an LLM as a prompt. Everything here is
deterministic: whole-word/substring matching and graph traversal only. No
embeddings, no NER, no LLM call - consistent with the pipeline's own
"no LLM anywhere in the pipeline" constraint (see Ontology_KG_Project_Plan.md).
This module only *builds* the prompt text; sending it to a model is left to
whatever chain is added later.

One graph per document: output/<doc_id>/nodes.jsonl + edges.jsonl, as built
by `python -m pipeline.run` (see pipeline/phase5_assemble.py for the full
node/edge model). This module walks:

  Structural units  Clause / Article / ArticleParagraph / Point / Annex /
                    Appendix / Recital / Part / ... (id = qualified id,
                    e.g. "REG154.04.BODY.6.3.2", "EU2024-1257.ART-4.2")
  Definition, Abbreviation, Equation (+ Variable glossary), Table,
  ExternalDocument / ExternalProvision (cited outside text)

  HAS_CHILD / HAS_DIVISION     containment
  HAS_DEFINITION / HAS_ABBREVIATION / HAS_EQUATION / HAS_TABLE
  REFERENCES                   resolved internal cross-reference
  CITES                        unit -> external document / provision (role, raw_text)
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
OUTPUT_DIR = REPO_ROOT / "output"
DEFAULT_DOC = "REG154.04"

# Node types that are not structural units of the document
NON_UNIT_TYPES = {"Standard", "Document", "Definition", "Abbreviation", "Footnote", "Table", "Figure",
                  "Equation", "Variable", "ExternalDocument", "ExternalProvision"}


def list_documents(output_dir: Path = OUTPUT_DIR) -> list[dict]:
    """Every document with a built graph: [{doc_id, title, profile, pages}]."""
    docs = []
    for m in sorted(Path(output_dir).glob("*/manifest.json")):
        if not (m.parent / "nodes.jsonl").exists():
            continue
        man = json.loads(m.read_text(encoding="utf-8"))
        docs.append({"doc_id": man.get("doc_id", m.parent.name),
                     "title": (man.get("metadata") or {}).get("title") or m.parent.name,
                     "profile": man.get("profile"), "pages": man.get("page_count")})
    return docs


def document_label(graph: nx.MultiDiGraph) -> str:
    """Human label of the document a graph was built from (its Document node)."""
    for _, d in graph.nodes(data=True):
        if d.get("type") == "Document":
            return d.get("title") or d.get("doc_id") or "document"
    return "document"


# ----------------------------------------------------------------------------
# Graph loading
# ----------------------------------------------------------------------------

def _iter_jsonl(path: Path):
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def load_graph(doc_id: str = DEFAULT_DOC, nodes_path: Optional[Path] = None,
               edges_path: Optional[Path] = None) -> nx.MultiDiGraph:
    """Rebuild one document's MultiDiGraph straight from its nodes.jsonl /
    edges.jsonl (output/<doc_id>/ unless explicit paths are given).

    Deliberately does NOT unpickle output/graph.pickle: jsonl is portable
    across networkx versions and doesn't execute arbitrary code on load,
    which matters more for a Streamlit app someone else might point at
    their own output/ directory.
    """
    nodes_path = Path(nodes_path or OUTPUT_DIR / doc_id / "nodes.jsonl")
    edges_path = Path(edges_path or OUTPUT_DIR / doc_id / "edges.jsonl")
    for p in (nodes_path, edges_path):
        if not p.exists():
            raise FileNotFoundError(f"{p} not found - run the pipeline first (python -m pipeline.run --all).")

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


# node type -> searchable text fields on that node's own data dict; every
# structural unit type (Clause, Article, Recital, ...) uses _UNIT_FIELDS
_UNIT_FIELDS = ("title", "body_text")
_SEARCH_FIELDS = {
    "Definition": ("quoted_term", "gloss"),
    "Abbreviation": ("surface_form", "expansion"),
    "Equation": ("linear", "context_before"),
    "Table": ("caption_id", "caption", "cell_text"),
}
# where a non-unit match is cited from
_CITATION_FIELD = {"Definition": "source_clause", "Abbreviation": "source_clause",
                   "Equation": "unit_id", "Table": "defining_unit"}


def search(
    graph: nx.MultiDiGraph,
    query: str,
    *,
    require_all_terms: bool = True,
    divisions: Optional[Iterable[str]] = None,
    max_results: int = 10,
) -> list[Match]:
    """Deterministic keyword search across structural units, definitions,
    abbreviations, equations and tables.

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
        if ntype in _SEARCH_FIELDS:
            citation_id = data.get(_CITATION_FIELD[ntype])
            field_names = _SEARCH_FIELDS[ntype]
        elif ntype not in NON_UNIT_TYPES:
            if not (data.get("has_body") or data.get("title")):
                continue
            citation_id = node_id
            field_names = _UNIT_FIELDS
        else:
            continue
        if not citation_id:
            continue
        if division_filter and graph.nodes.get(citation_id, {}).get("division") not in division_filter:
            continue

        fields = {k: data.get(k) or "" for k in field_names}
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
    local = data.get("local_number") or data.get("local_label")
    if data.get("type") and data.get("type") not in ("Clause",) and data.get("level") != "decimal":
        local = f"{data['type']} {local}" if local else data["type"]
    text = (data.get("title") or re.sub(r"\[(?:TABLE|FIGURE|EQ|FORM):[^\]]+\]", "", data.get("body_text") or "")).strip()
    if not text:
        return f"{local or clause_id} (heading, no body text)"
    return f"{local}. {textwrap.shorten(text, width=width, placeholder='…')}" if local \
        else textwrap.shorten(text, width=width, placeholder="…")


def area_of_requirement(graph: nx.MultiDiGraph, clause_id: str) -> dict:
    """Division + nearest depth==1 'Section' ancestor - the top-level area a clause sits under."""
    chain = ancestor_chain(graph, clause_id)
    section_id = next((n for n in chain if graph.nodes[n].get("type") == "Article"
                       or (graph.nodes[n].get("level") == "decimal" and graph.nodes[n].get("depth") == 1)), None)
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


def _json_list(v):
    """Graph properties may be lists (jsonl) or JSON strings (GraphML)."""
    if isinstance(v, str):
        try:
            return json.loads(v)
        except ValueError:
            return []
    return v or []


def equations_of(graph: nx.MultiDiGraph, clause_id: str) -> list[tuple[str, dict]]:
    """Equation nodes attached to this unit (HAS_EQUATION)."""
    if clause_id not in graph.nodes:
        return []
    return [(t, graph.nodes[t]) for _, t, d in graph.out_edges(clause_id, data=True) if d.get("type") == "HAS_EQUATION"]


def external_provisions(graph: nx.MultiDiGraph, clause_id: str) -> list[tuple[str, dict, dict]]:
    """External documents / provisions this unit CITES, with the edge data."""
    if clause_id not in graph.nodes:
        return []
    return [(t, graph.nodes[t], d) for _, t, d in graph.out_edges(clause_id, data=True) if d.get("type") == "CITES"]


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

    eqs = equations_of(graph, citation_id)
    if eqs:
        lines.append("### Equations in This Clause")
        for eid, e in eqs:
            lines.append(f"- [{eid}] ({e.get('kind')}, parse {e.get('parse_status')}): {e.get('linear') or '(image only - see crop)'}")
            if e.get("latex"):
                lines.append(f"  LaTeX: {e['latex']}")
            for g in _json_list(e.get("glossary")):
                unit = f" [{g.get('unit')}]" if g.get("unit") else ""
                lines.append(f"  where {g.get('symbol_text')} = {g.get('description') or '?'}{unit}")
        lines.append("")

    ext = external_provisions(graph, citation_id)
    if ext:
        lines.append("### External Provisions Referenced (text not in this graph)")
        for target, data, edge in ext:
            if data.get("type") == "ExternalProvision":
                prefix = target[: target.index("/EXT:")]          # node ids are "<doc_id>/EXT:..."
                doc = graph.nodes.get(f"{prefix}/{data.get('external_doc')}", {})
            else:
                doc = data
            name = doc.get("title") or (_json_list(doc.get("aliases")) or [doc.get("ext_id")])[0]
            where = data.get("label") if data.get("type") == "ExternalProvision" else "(whole document)"
            eli = f"  ELI: {doc['eli']}" if doc.get("eli") else ""
            lines.append(f"- {where} of {name}  [{data.get('ext_id')}]  role={edge.get('role')}  "
                         f'(as "{edge.get("raw_text")}"){eli}')
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
    example_id = matches[0].citation_id if matches else "<paragraph id>"

    lines = [
        f"# STRUCTURED REQUIREMENT CONTEXT — {document_label(graph)}",
        f'# Query keyword(s): "{query}"',
        "# Retrieval method: deterministic keyword search + graph traversal over the",
        "#   ontology knowledge graph (no LLM, embeddings, or NER used to build this prompt)",
        f"# Matched paragraphs: {len(matches)}",
        "",
        "## TASK",
        (f'You are a regulatory-compliance assistant. Using ONLY the context provided below '
         f'(do not use outside knowledge), answer the requirement described by the keyword(s) '
         f'"{query}". Every factual claim must cite the paragraph id(s) it is based on in square '
         f'brackets, e.g. [{example_id}]. External provisions are listed by reference only - their '
         f'text is not included; if the requirement depends on them, say which ones. If the context '
         f'below does not fully cover the requirement, say so explicitly instead of guessing.'),
        "",
    ]
    for i, m in enumerate(matches, 1):
        lines += _match_lines(graph, i, len(matches), m, abbr_index, include_glossary, include_references)

    return "\n".join(lines)
