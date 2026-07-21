"""Semantic retrieval executed INSIDE Neo4j via the native vector index —
demonstrates that the graph store can also be the vector store (drop LanceDB)."""
from __future__ import annotations

from neo4j import GraphDatabase

from graph_rag.gr_config import L_SECTION, SETTINGS, VECTOR_INDEX
from vector_rag.knowledge.embeddings import TitanEmbedder

_embedder = TitanEmbedder(SETTINGS.embed_model, SETTINGS.aws_region, SETTINGS.embed_dim)


def _driver():
    return GraphDatabase.driver(
        SETTINGS.neo4j_uri, auth=(SETTINGS.neo4j_user, SETTINGS.neo4j_password)
    )


def vector_search(query: str, k: int = 8, doc_types: list[str] | None = None) -> list[dict]:
    qvec = _embedder.embed_one(query)
    cypher = f"""
    CALL db.index.vector.queryNodes('{VECTOR_INDEX}', $k, $qvec)
    YIELD node, score
    {"WHERE node.doc IN $docs" if doc_types else ""}
    RETURN node.doc AS doc, node.path AS path, node.kind AS kind,
           left(node.text, 160) AS preview, score
    ORDER BY score DESC
    """
    params = {"k": k * (3 if doc_types else 1), "qvec": qvec}
    if doc_types:
        params["docs"] = doc_types
    with _driver() as drv, drv.session(database=SETTINGS.neo4j_database) as s:
        return [r.data() for r in s.run(cypher, **params)][:k]


if __name__ == "__main__":
    import sys
    q = sys.argv[1] if len(sys.argv) > 1 else "primary effectiveness endpoint"
    for r in vector_search(q, k=6):
        print(f"{r['score']:.3f}  [{r['doc']}/{r['kind']}] {r['path'][:45]}")
        print(f"        {r['preview']}")
