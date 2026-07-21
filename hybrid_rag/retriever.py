"""Hybrid retriever: dense vector + sparse full-text (LanceDB) + Neo4j graph
expansion, fused with multi-signal Reciprocal Rank Fusion.

Why this is the "proper" hybrid and not just a concatenation of vector and graph
hits: it rewards CONSENSUS. Every signal contributes on the same rank-based scale,
so a source that is BOTH semantically retrieved AND linked in the graph is scored
above either signal alone. That cross-document agreement is exactly the
consistency a CSR needs, and it's what a pure vector or pure graph retriever each
miss on their own.

Graph signal — study **concept** bridging in Neo4j: source sections are related
when they touch the same clinical CONCEPT (an endpoint, analysis set or visit),
and the graph records *what each section does* for that concept via the edge role
— DEFINES (SAP), DESCRIBES (Protocol/MOP), MEASURES (a TFL table). Starting from
the top vector+FTS seeds we traverse
    (seed:RagSection)-[:MENTIONS_CONCEPT]->(c:RagConcept)<-[:MENTIONS_CONCEPT]-(other)
scoring each bridge by concept rarity (1/(1+freq)) so specific concepts count for
more than ubiquitous ones, and adding a bonus when `other` plays a role the seeds
don't (e.g. a seed defines the endpoint, `other` measures it) — that role
complementarity is precisely the cross-document consistency a CSR needs, and what
raw co-occurrence could not see. RagSection ids are content hashes shared by
LanceDB and Neo4j, so seeds map straight across. Requires the concept graph
(`python -m graph_rag.dataingestion.concept_graph`); absent it, the hybrid
degrades gracefully to vector+FTS.

The output type is vector_rag's RetrievedChunk, so the hybrid drops straight into
the existing grounded-generation writer.
"""
from __future__ import annotations

from neo4j import GraphDatabase

from vector_rag.config import Settings
from vector_rag.models import Chunk
from vector_rag.knowledge.embeddings import TitanEmbedder
from vector_rag.knowledge.vector_store import VectorStore
from vector_rag.knowledge.retriever import RetrievedChunk, demote_parent_overviews

from graph_rag.gr_config import SETTINGS as GR


# Cross-document neighbours via shared clinical CONCEPTS. Each bridge is weighted
# by concept rarity (rarer concept = stronger, more specific link) and gets a 1.5x
# bonus when the neighbour plays a document role the seeds don't already cover
# (definition <-> description <-> measurement) — surfacing the missing view of a
# concept the seeds only partially describe.
_EXPAND = """
MATCH (seed:RagSection)-[ms:MENTIONS_CONCEPT]->(c:RagConcept)<-[mo:MENTIONS_CONCEPT]-(o:RagSection)
WHERE seed.id IN $seeds AND NOT o.id IN $seeds
WITH o.id AS id, c, mo.role AS orole, collect(DISTINCT ms.role) AS sroles,
     coalesce(c.freq, count { (c)<-[:MENTIONS_CONCEPT]-(:RagSection) }) AS cfreq
WITH id, sum(
       (1.0 / (1.0 + cfreq)) *
       (CASE WHEN NOT orole IN sroles THEN 1.5 ELSE 1.0 END)
     ) AS score
RETURN id, score
ORDER BY score DESC
LIMIT $limit
"""


def _rrf(rank: int, k: int = 60) -> float:
    return 1.0 / (k + rank)


class HybridRetriever:
    """Fuses vector, FTS, and Neo4j graph-expansion signals. Weights let graph act
    as a softer, supporting signal (it *expands* the seed set rather than defining
    it), while vector and FTS carry equal primary weight."""

    def __init__(
        self,
        settings: Settings,
        store: VectorStore,
        driver,
        database: str,
        embedder: TitanEmbedder,
        chunks_by_id: dict[str, Chunk],
        w_vector: float = 1.0,
        w_fts: float = 1.0,
        w_graph: float = 0.5,
        graph_hops: int = 1,
        n_seeds: int = 10,
    ):
        self.s = settings
        self.store = store
        self.driver = driver
        self.database = database
        self.embedder = embedder
        self.by_id = chunks_by_id
        self.w_vector = w_vector
        self.w_fts = w_fts
        self.w_graph = w_graph
        self.graph_hops = graph_hops
        self.n_seeds = n_seeds

    def _graph_expand(self, seed_ids: list[str], limit: int) -> list[str]:
        """Concept-bridged neighbours of the seeds, ranked, from Neo4j. Returns []
        if the concept graph isn't built or Neo4j is unreachable — the hybrid then
        degrades gracefully to vector+FTS."""
        if not seed_ids:
            return []
        try:
            with self.driver.session(database=self.database) as sess:
                rows = sess.run(_EXPAND, seeds=seed_ids, limit=limit).data()
            return [r["id"] for r in rows]
        except Exception:
            return []

    def retrieve(
        self,
        query: str,
        doc_types: list[str] | None = None,
        k: int | None = None,
        guarantee_tables: tuple[str, int] | None = None,
    ) -> list[RetrievedChunk]:
        k = k or self.s.top_k_final
        qvec = self.embedder.embed_one(query)

        reserved, reserved_ids = self._reserve_tables(query, qvec, guarantee_tables)

        vhits = self.store.vector_search(qvec, self.s.top_k_vector, doc_types)
        fhits = self.store.fts_search(query, self.s.top_k_fts, doc_types)

        # Accumulate a rank-based score per chunk and remember which signals hit it.
        score: dict[str, float] = {}
        methods: dict[str, set[str]] = {}

        def add(cid: str, s: float, method: str) -> None:
            score[cid] = score.get(cid, 0.0) + s
            methods.setdefault(cid, set()).add(method)

        for rank, h in enumerate(vhits):
            add(h.chunk.id, self.w_vector * _rrf(rank), "vector")
        for rank, h in enumerate(fhits):
            add(h.chunk.id, self.w_fts * _rrf(rank), "fts")

        # Graph expansion from the strongest vector+FTS seeds, fused on the same
        # RRF scale by rank.
        seeds = [cid for cid, _ in sorted(score.items(), key=lambda kv: kv[1], reverse=True)]
        if self.graph_hops > 0 and seeds:
            expanded = self._graph_expand(seeds[: self.n_seeds], limit=k * 2)
            for rank, cid in enumerate(expanded):
                add(cid, self.w_graph * _rrf(rank), "graph")

        # Prefer the specific subsection over its parent-overview section.
        demote_parent_overviews(score, self.by_id)

        results: list[RetrievedChunk] = []
        for cid, sc in sorted(score.items(), key=lambda kv: kv[1], reverse=True):
            if cid in reserved_ids:
                continue
            ch = self.by_id.get(cid)
            if ch is None:
                continue
            if doc_types and ch.doc not in doc_types:
                continue
            # provenance like "graph+vector" or "fts+graph+vector" — the "+" count
            # is the consensus signal the comparison UI surfaces.
            prov = "+".join(sorted(methods[cid]))
            results.append(RetrievedChunk(ch, sc, prov))

        return reserved + results[:k]

    def _reserve_tables(self, query, qvec, guarantee_tables):
        """Reserve slots for the best-matching TFL result tables — grids of numbers
        embed weakly against a definitional query, so results sections would lose
        their data tables without this. Additive to the k budget."""
        reserved: list[RetrievedChunk] = []
        reserved_ids: set[str] = set()
        if not guarantee_tables:
            return reserved, reserved_ids
        gt_doc, gt_n = guarantee_tables
        tbl_hits = self.store.vector_search(qvec, gt_n * 3, [gt_doc], kinds=["table"])
        tbl_fts = self.store.fts_search(query, gt_n * 2, [gt_doc], kinds=["table"])
        fused: dict[str, float] = {}
        order: dict[str, Chunk] = {}
        for rank, h in enumerate(tbl_hits):
            fused[h.chunk.id] = fused.get(h.chunk.id, 0.0) + _rrf(rank)
            order[h.chunk.id] = h.chunk
        for rank, h in enumerate(tbl_fts):
            fused[h.chunk.id] = fused.get(h.chunk.id, 0.0) + _rrf(rank)
            order[h.chunk.id] = h.chunk
        for cid, _ in sorted(fused.items(), key=lambda kv: kv[1], reverse=True)[:gt_n]:
            reserved.append(RetrievedChunk(order[cid], 1.0, "guaranteed-table"))
            reserved_ids.add(cid)
        return reserved, reserved_ids

    def close(self) -> None:
        try:
            self.driver.close()
        except Exception:
            pass


def build_hybrid_retriever(settings: Settings) -> HybridRetriever:
    """Open the LanceDB index + a Neo4j driver for graph expansion, then assemble
    the retriever. Neo4j creds come from graph_rag.gr_config (attached to its
    SETTINGS), so this works regardless of which Settings the caller passes."""
    from vector_rag.ingestion.sources import load_chunks

    chunks = load_chunks(settings.sources_cache)
    by_id = {c.id: c for c in chunks}
    store = VectorStore(settings.lancedb_uri, settings.lancedb_table, settings.embed_dim)
    driver = GraphDatabase.driver(GR.neo4j_uri, auth=(GR.neo4j_user, GR.neo4j_password))
    embedder = TitanEmbedder(settings.embed_model, settings.aws_region, settings.embed_dim)
    return HybridRetriever(settings, store, driver, GR.neo4j_database, embedder, by_id)
