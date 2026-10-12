"""Streamlit app: requirement keyword -> knowledge graph -> structured LLM prompt.

Pure retrieval + text formatting - NO LLM is called anywhere in this app.
It reads one document's graph as built by `python -m pipeline.run`
(output/<doc_id>/nodes.jsonl + edges.jsonl), does a deterministic keyword
search over it, and assembles a citation-backed structured prompt
(Area of Requirement -> Requirement Hierarchy -> Citation Paragraphs)
that you can copy/download and feed into an LLM chain later. Wiring that
chain up is explicitly out of scope for this app.

Run with:
    streamlit run app/streamlit_app.py
"""

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.kg_retrieval import (  # noqa: E402
    NON_UNIT_TYPES,
    build_structured_prompt,
    document_label,
    list_documents,
    load_graph,
    search,
)

st.set_page_config(page_title="KG Requirement Prompt Builder", layout="wide")


@st.cache_resource(show_spinner="Loading knowledge graph…")
def get_graph(doc_id: str):
    return load_graph(doc_id)


def main() -> None:
    st.title("Requirement → Knowledge Graph → Structured Prompt")
    docs = list_documents()
    if not docs:
        st.error("No document graphs found under output/ - run `python -m pipeline.run --all` first.")
        st.stop()
        return

    with st.sidebar:
        st.header("Document")
        doc_id = st.selectbox("Knowledge graph", [d["doc_id"] for d in docs],
                              format_func=lambda d: next(f"{x['doc_id']} — {x['title'][:60]}" for x in docs if x["doc_id"] == d))

        st.header("Search options")
        require_all = st.checkbox("Require all keywords present (AND)", value=True,
                                   help="Off = match a clause if ANY keyword occurs (OR).")
        max_results = st.slider("Max matched paragraphs", 1, 30, 8)
        include_glossary = st.checkbox("Include defined / used terms & abbreviations", value=True)
        include_references = st.checkbox("Include cross-references", value=True)

    try:
        graph = get_graph(doc_id)
    except FileNotFoundError as e:
        st.error(f"Could not load graph: {e}")
        st.stop()
        return

    st.caption(
        f"Source: {document_label(graph)}. Retrieval is 100% deterministic keyword search + graph "
        "traversal over the ontology KG — no LLM, embeddings, or NER is used to build this "
        "prompt. The prompt is only assembled here; sending it to a model is a separate step."
    )

    divisions = sorted({
        d.get("division") for _, d in graph.nodes(data=True)
        if d.get("type") not in NON_UNIT_TYPES and d.get("division")
    })
    with st.sidebar:
        chosen_divisions = st.multiselect(
            "Limit to divisions (optional)", divisions,
            help="e.g. BODY, ANNEX-B1, ART-4, ANNEX-IV …",
        )

    st.caption(f"Loaded {graph.number_of_nodes():,} nodes / {graph.number_of_edges():,} edges.")

    query = st.text_input(
        "Requirement keyword / phrase",
        placeholder="e.g. battery durability, particle number, tyre pressure monitoring",
    )
    go = st.button("Search knowledge graph", type="primary")

    if not (go and query.strip()):
        st.info("Enter a requirement keyword above and click **Search knowledge graph**.")
        return

    matches = search(
        graph,
        query,
        require_all_terms=require_all,
        divisions=chosen_divisions or None,
        max_results=max_results,
    )

    if not matches:
        st.warning(
            "No matching paragraphs found. Try fewer/looser keywords, uncheck "
            "'Require all keywords present', or widen the division filter."
        )
        return

    st.success(f"Found {len(matches)} matching paragraph(s).")

    prompt_text = build_structured_prompt(
        graph, query, matches,
        include_glossary=include_glossary,
        include_references=include_references,
    )

    st.subheader("Structured LLM prompt")
    st.text_area("Generated prompt", prompt_text, height=500)
    st.download_button(
        "Download prompt (.txt)",
        prompt_text,
        file_name=f"kg_prompt_{doc_id}_{'_'.join(query.strip().split())}.txt",
        mime="text/plain",
    )

    st.subheader("Matches (preview)")
    for i, m in enumerate(matches, 1):
        with st.expander(f"Match {i}: {m.citation_id}  ·  score {m.score}  ·  {m.node_type}"):
            st.markdown(f"**Matched terms:** {', '.join(f'{t} ({c}x)' for t, c in m.hits.items())}")
            st.write(m.snippet)


if __name__ == "__main__":
    main()
