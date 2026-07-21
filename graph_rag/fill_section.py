"""Graph-driven generation: author a template section using ONLY the source
sections reachable via its FILLED_BY edges. Shows the full traceable chain
    template section -> linked source nodes -> generated text
purely as a graph traversal.
"""
from __future__ import annotations

from neo4j import GraphDatabase

from graph_rag.gr_config import SETTINGS
from graph_rag.dataingestion.template_graph import L_TSECTION
from vector_rag.generation.llm import ClaudeClient

_client = ClaudeClient(SETTINGS)

SYSTEM = (
    "You are a medical writer authoring one section of a Clinical Investigation "
    "Report. Write ONLY facts supported by the provided source passages; copy "
    "numbers verbatim; formal, past tense; refer to participants as 'subjects'. "
    "If the sources are insufficient, say so briefly. Output the section body only."
)


def _driver():
    return GraphDatabase.driver(
        SETTINGS.neo4j_uri, auth=(SETTINGS.neo4j_user, SETTINGS.neo4j_password)
    )


def fill(number: str, verbose: bool = True) -> str:
    q = f"""
    MATCH (t:{L_TSECTION} {{number: $num}})-[f:FILLED_BY]->(s:RagSection)
    RETURN t.title AS title, t.guidance AS guidance,
           collect({{doc: s.doc, path: s.path, text: s.text, score: f.score}}) AS sources
    """
    with _driver() as drv, drv.session(database=SETTINGS.neo4j_database) as sess:
        rec = sess.run(q, num=number).single()
    if not rec or not rec["sources"]:
        print(f"§{number}: no FILLED_BY sources linked.")
        return ""

    title, guidance, sources = rec["title"], rec["guidance"], rec["sources"]
    sources = sorted(sources, key=lambda x: -(x["score"] or 0))[:12]

    if verbose:
        print(f"\n=== §{number} {title} ===")
        print("linked source nodes (via FILLED_BY):")
        for s in sources:
            print(f"   {s['score']:.3f}  [{s['doc']}] {s['path'][:55]}")

    blocks = "\n\n".join(
        f"[{i+1}] {s['doc']} | {s['path']}\n{s['text']}" for i, s in enumerate(sources)
    )
    user = (
        f"SECTION: {title}\n\nWHAT IT MUST COVER:\n{guidance[:1500]}\n\n"
        f"SOURCE PASSAGES (your only permitted facts):\n\n{blocks}\n\n"
        f"Write the section body now."
    )
    text = _client.complete_text(SYSTEM, user, max_tokens=4000)
    if verbose:
        print("\n--- generated from those nodes ---")
        print(text)
    return text


if __name__ == "__main__":
    import sys
    fill(sys.argv[1] if len(sys.argv) > 1 else "6.2.1")
