"""Build the study-rooted graph with embeddings on Section nodes + a native
Neo4j vector index. Reuses the app's chunker and Titan embedder (read-only)."""
from __future__ import annotations

from neo4j import GraphDatabase

from graph_rag.gr_config import (
    EMBED_DIM,
    L_DOC,
    L_SECTION,
    L_STUDY,
    SETTINGS,
    STUDY_ID,
    VECTOR_INDEX,
)

from vector_rag.ingestion.sources import load_all_sources
from vector_rag.knowledge.embeddings import TitanEmbedder


def _driver():
    return GraphDatabase.driver(
        SETTINGS.neo4j_uri, auth=(SETTINGS.neo4j_user, SETTINGS.neo4j_password)
    )


def _caption(doc: str, path: str, text: str, kind: str) -> str:
    """A short, human-readable node caption: the actual section heading (leaf of
    the breadcrumb) + doc, so the graph shows WHAT each node is, not just 'sap'."""
    leaf = ""
    if " > " in path:
        leaf = path.split(" > ")[-1].strip().rstrip(":")
    if not leaf or leaf.lower() == doc.lower():
        leaf = " ".join(text.split()[:6])
    tag = f"[{kind}] " if kind == "table" else ""
    return f"{doc} · {tag}{leaf}"[:60]


def build(verbose: bool = True) -> None:
    chunks = load_all_sources(
        SETTINGS.study_dir, SETTINGS.chunk_target_tokens, SETTINGS.chunk_overlap_tokens
    )
    if verbose:
        print(f"[gr] loaded {len(chunks)} sections from {SETTINGS.study_dir}")

    embedder = TitanEmbedder(SETTINGS.embed_model, SETTINGS.aws_region, EMBED_DIM)
    if verbose:
        print(f"[gr] embedding {len(chunks)} sections with {SETTINGS.embed_model} ...")
    vectors = embedder.embed_batch(
        [f"{c.doc} | {c.section_path}\n{c.text}" for c in chunks], progress=verbose
    )

    rows = [
        {
            "id": c.id, "doc": c.doc, "doc_type": c.doc_type,
            "path": c.section_path, "kind": c.kind, "text": c.text, "embedding": v,
            "name": _caption(c.doc, c.section_path, c.text, c.kind),
            "preview": c.text[:200],
        }
        for c, v in zip(chunks, vectors)
    ]

    db = SETTINGS.neo4j_database
    with _driver() as drv, drv.session(database=db) as s:
        # wipe only THIS prototype's labels
        s.run(f"MATCH (n) WHERE n:{L_STUDY} OR n:{L_DOC} OR n:{L_SECTION} DETACH DELETE n")
        s.run(f"CREATE CONSTRAINT rag_section_id IF NOT EXISTS "
              f"FOR (x:{L_SECTION}) REQUIRE x.id IS UNIQUE")
        s.run(f"MERGE (:{L_STUDY} {{id: $sid}})", sid=STUDY_ID)

        for i in range(0, len(rows), 100):
            s.run(_INSERT, rows=rows[i : i + 100], sid=STUDY_ID)

        # native vector index (cosine) over the section embeddings
        s.run(
            f"CREATE VECTOR INDEX {VECTOR_INDEX} IF NOT EXISTS "
            f"FOR (x:{L_SECTION}) ON (x.embedding) "
            f"OPTIONS {{ indexConfig: {{ `vector.dimensions`: $dim, "
            f"`vector.similarity_function`: 'cosine' }} }}",
            dim=EMBED_DIM,
        )

        counts = s.run(
            f"MATCH (st:{L_STUDY}) OPTIONAL MATCH (d:{L_DOC})-[:PART_OF]->(st) "
            f"OPTIONAL MATCH (sec:{L_SECTION})-[:IN]->(d) "
            f"RETURN st.id AS study, count(DISTINCT d) AS docs, count(sec) AS sections"
        ).single()
    if verbose:
        print(f"[gr] built study={counts['study']} docs={counts['docs']} "
              f"sections={counts['sections']}; vector index '{VECTOR_INDEX}' ready")


_INSERT = f"""
MATCH (st:{L_STUDY} {{id: $sid}})
UNWIND $rows AS row
MERGE (d:{L_DOC} {{name: row.doc}})
  SET d.doc_type = row.doc_type
MERGE (d)-[:PART_OF]->(st)
MERGE (sec:{L_SECTION} {{id: row.id}})
  SET sec.doc = row.doc, sec.path = row.path, sec.kind = row.kind,
      sec.text = row.text, sec.embedding = row.embedding,
      sec.name = row.name, sec.preview = row.preview
MERGE (sec)-[:IN]->(d)
MERGE (sec)-[:OF_STUDY]->(st)
"""


if __name__ == "__main__":
    build()
