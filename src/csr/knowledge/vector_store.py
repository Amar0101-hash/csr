"""LanceDB-backed vector + full-text store over source chunks."""
from __future__ import annotations

from dataclasses import dataclass

import lancedb
import pyarrow as pa

from ..models import Chunk


@dataclass
class Hit:
    chunk: Chunk
    score: float
    source: str  # "vector" | "fts"


def _schema(dim: int) -> pa.Schema:
    return pa.schema(
        [
            pa.field("id", pa.string()),
            pa.field("doc", pa.string()),
            pa.field("doc_type", pa.string()),
            pa.field("section_path", pa.string()),
            pa.field("text", pa.string()),
            pa.field("kind", pa.string()),
            pa.field("vector", pa.list_(pa.float32(), dim)),
        ]
    )


class VectorStore:
    def __init__(self, uri: str, table_name: str, dim: int):
        self.uri = uri
        self.table_name = table_name
        self.dim = dim
        self._db = lancedb.connect(uri)
        self._table = None

    def build(self, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        rows = []
        for c, v in zip(chunks, vectors):
            rows.append(
                {
                    "id": c.id,
                    "doc": c.doc,
                    "doc_type": c.doc_type,
                    "section_path": c.section_path,
                    "text": c.text,
                    "kind": c.kind,
                    "vector": v,
                }
            )
        if self.table_name in self._db.table_names():
            self._db.drop_table(self.table_name)
        self._table = self._db.create_table(
            self.table_name, data=rows, schema=_schema(self.dim)
        )
        # full-text index over text (lance native FTS)
        self._table.create_fts_index("text", replace=True)

    def open(self):
        if self._table is None:
            self._table = self._db.open_table(self.table_name)
        return self._table

    def exists(self) -> bool:
        return self.table_name in self._db.table_names()

    @staticmethod
    def _row_to_chunk(row: dict) -> Chunk:
        return Chunk(
            id=row["id"],
            doc=row["doc"],
            doc_type=row["doc_type"],
            section_path=row["section_path"],
            text=row["text"],
            kind=row["kind"],
        )

    @staticmethod
    def _where(doc_types: list[str] | None, kinds: list[str] | None) -> str | None:
        # Filter on the fine-grained `doc` name (protocol, sap, mop,
        # tfl_effectiveness, ...) — routing distinguishes TFL subtypes, whereas
        # `doc_type` collapses all TFLs to "tfl".
        clauses = []
        if doc_types:
            clauses.append("(" + " OR ".join(f"doc = '{d}'" for d in doc_types) + ")")
        if kinds:
            clauses.append("(" + " OR ".join(f"kind = '{k}'" for k in kinds) + ")")
        return " AND ".join(clauses) if clauses else None

    def vector_search(self, query_vec: list[float], k: int,
                      doc_types: list[str] | None = None,
                      kinds: list[str] | None = None) -> list[Hit]:
        tbl = self.open()
        q = tbl.search(query_vec, vector_column_name="vector").limit(k)
        where = self._where(doc_types, kinds)
        if where:
            q = q.where(where, prefilter=True)
        hits: list[Hit] = []
        for row in q.to_list():
            dist = row.get("_distance", 1.0)
            hits.append(Hit(self._row_to_chunk(row), 1.0 / (1.0 + dist), "vector"))
        return hits

    def fts_search(self, query: str, k: int,
                   doc_types: list[str] | None = None,
                   kinds: list[str] | None = None) -> list[Hit]:
        tbl = self.open()
        clean = _sanitize_fts(query)
        if not clean:
            return []
        try:
            q = tbl.search(clean, query_type="fts").limit(k)
            where = self._where(doc_types, kinds)
            if where:
                q = q.where(where)
            rows = q.to_list()
        except Exception:
            return []
        hits: list[Hit] = []
        for row in rows:
            score = row.get("_score", row.get("score", 0.0)) or 0.0
            hits.append(Hit(self._row_to_chunk(row), float(score), "fts"))
        return hits


def _sanitize_fts(query: str) -> str:
    # keep alphanumerics/spaces; FTS choke on punctuation/operators
    import re

    tokens = re.findall(r"[A-Za-z0-9]+", query.lower())
    stop = {"the", "a", "an", "of", "and", "or", "for", "to", "in", "on", "with", "is", "are"}
    tokens = [t for t in tokens if t not in stop and len(t) > 1]
    return " ".join(tokens[:40])
