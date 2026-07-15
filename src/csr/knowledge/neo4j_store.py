"""Neo4j-backed knowledge graph — a persistent alternative to the in-memory
networkx GraphStore, with the same interface used by the retriever.

Graph model:
    (:Document {name, doc_type})
    (:Chunk {id, doc, section_path, kind, text})
    (:Entity {name, count})            count = # chunks that mention it
    (Chunk)-[:IN]->(Document)
    (Chunk)-[:MENTIONS]->(Entity)

Retrieval expansion walks Chunk-MENTIONS-Entity-MENTIONS-Chunk, scoring shared
entities by rarity (1/(1+count)) so specific clinical terms weigh more than
common ones — the same idea as the networkx version, expressed in Cypher.
"""
from __future__ import annotations

from pathlib import Path

from neo4j import GraphDatabase

from ..config import Settings
from ..models import Chunk
from .graph_store import extract_entities


class Neo4jGraphStore:
    def __init__(self, settings: Settings):
        self.s = settings
        self.database = settings.neo4j_database
        self._driver = GraphDatabase.driver(
            settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password)
        )

    # ---- lifecycle ----
    def close(self) -> None:
        try:
            self._driver.close()
        except Exception:
            pass

    def save(self, path: Path) -> None:  # persisted in the DB; nothing to write
        pass

    def load(self, path: Path) -> None:  # already connected; nothing to load
        pass

    def stats(self) -> tuple[int, int]:
        q = ("MATCH (n) WHERE n:Chunk OR n:Entity OR n:Document "
             "WITH count(n) AS nodes "
             "MATCH (:Chunk)-[r]->() RETURN nodes, count(r) AS rels")
        rec = self._driver.execute_query(q, database_=self.database).records
        if rec:
            return rec[0]["nodes"], rec[0]["rels"]
        return (0, 0)

    # ---- build ----
    def build(self, chunks: list[Chunk], batch_size: int = 100) -> None:
        # backfill entities onto the chunk objects (so sources.json carries them)
        for c in chunks:
            c.entities = extract_entities(c.section_path + "\n" + c.text)

        with self._driver.session(database=self.database) as session:
            session.run("MATCH (n) WHERE n:Chunk OR n:Entity OR n:Document DETACH DELETE n")
            session.run("CREATE CONSTRAINT chunk_id IF NOT EXISTS "
                        "FOR (c:Chunk) REQUIRE c.id IS UNIQUE")
            session.run("CREATE CONSTRAINT entity_name IF NOT EXISTS "
                        "FOR (e:Entity) REQUIRE e.name IS UNIQUE")
            session.run("CREATE CONSTRAINT doc_name IF NOT EXISTS "
                        "FOR (d:Document) REQUIRE d.name IS UNIQUE")

            rows = [
                {
                    "id": c.id, "doc": c.doc, "doc_type": c.doc_type,
                    "section_path": c.section_path, "kind": c.kind,
                    "text": c.text, "entities": c.entities,
                }
                for c in chunks
            ]
            for i in range(0, len(rows), batch_size):
                session.run(_INSERT, rows=rows[i : i + batch_size])
            session.run("MATCH (e:Entity) "
                        "SET e.count = count { (e)<-[:MENTIONS]-(:Chunk) }")

    # ---- retrieval expansion ----
    def neighbors_of_chunks(self, chunk_ids: list[str], max_entities_per_chunk: int = 6,
                            max_expand: int = 40) -> list[str]:
        if not chunk_ids:
            return []
        recs = self._driver.execute_query(
            _EXPAND, ids=chunk_ids, limit=max_expand, database_=self.database
        ).records
        return [r["id"] for r in recs]


_INSERT = """
UNWIND $rows AS row
MERGE (d:Document {name: row.doc})
  SET d.doc_type = row.doc_type
MERGE (c:Chunk {id: row.id})
  SET c.doc = row.doc, c.section_path = row.section_path,
      c.kind = row.kind, c.text = row.text
MERGE (c)-[:IN]->(d)
WITH c, row
UNWIND row.entities AS ent
  MERGE (e:Entity {name: ent})
  MERGE (c)-[:MENTIONS]->(e)
"""

_EXPAND = """
MATCH (seed:Chunk)-[:MENTIONS]->(e:Entity)<-[:MENTIONS]-(other:Chunk)
WHERE seed.id IN $ids AND NOT other.id IN $ids
WITH other, sum(1.0 / (1.0 + coalesce(e.count, 1))) AS score
RETURN other.id AS id
ORDER BY score DESC
LIMIT $limit
"""
