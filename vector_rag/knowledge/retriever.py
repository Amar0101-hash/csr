"""Vector retriever: vector + full-text search fused with RRF (no graph)."""
from __future__ import annotations

from dataclasses import dataclass

from ..config import Settings
from ..models import Chunk
from .embeddings import TitanEmbedder
from .vector_store import VectorStore


@dataclass
class RetrievedChunk:
    chunk: Chunk
    score: float
    provenance: str  # "vector+fts" | "guaranteed-table"


def _rrf(rank: int, k: int = 60) -> float:
    return 1.0 / (k + rank)


def demote_parent_overviews(score: dict[str, float], by_id: dict,
                            factor: float = 0.5) -> None:
    """With section-wise chunking, a parent section (its verbose overview) and its
    own specific subsections both get retrieved. The parent overview is usually
    keyword-dense, so pure RRF ranks it ABOVE the subsection that actually stores
    the answer. When a chunk is a strict ancestor (same doc, path prefix) of
    another retrieved chunk, its specifics are already covered by that descendant,
    so we demote it in place — the more specific section rises, the overview stays
    available lower down. Mutates `score`."""
    items = [(cid, by_id.get(cid)) for cid in list(score)]
    items = [(cid, ch) for cid, ch in items if ch is not None and ch.section_path]
    demote: list[str] = []
    for cid, ch in items:
        prefix = ch.section_path + " > "
        for oid, och in items:
            if oid == cid or och.doc != ch.doc:
                continue
            # och is a strict descendant AND a competitive match (not a noise chunk
            # that merely slipped into the candidate list) — only then is the parent
            # overview redundant enough to demote.
            if (och.section_path or "").startswith(prefix) and score[oid] >= 0.4 * score[cid]:
                demote.append(cid)
                break
    for cid in demote:  # applied after the scan so demotions don't affect the guard
        score[cid] *= factor


class VectorRetriever:
    def __init__(
        self,
        settings: Settings,
        store: VectorStore,
        embedder: TitanEmbedder,
        chunks_by_id: dict[str, Chunk],
    ):
        self.s = settings
        self.store = store
        self.embedder = embedder
        self.by_id = chunks_by_id

    def retrieve(
        self,
        query: str,
        doc_types: list[str] | None = None,
        k: int | None = None,
        guarantee_tables: tuple[str, int] | None = None,
    ) -> list[RetrievedChunk]:
        """`guarantee_tables=(doc_type, n)` reserves n slots for the best-matching
        *table* chunks from that document, so results sections always get their
        TFL data tables even though grids of numbers embed weakly against a
        definitional query."""
        k = k or self.s.top_k_final
        qvec = self.embedder.embed_one(query)

        reserved: list[RetrievedChunk] = []
        reserved_ids: set[str] = set()
        if guarantee_tables:
            gt_doc, gt_n = guarantee_tables
            tbl_hits = self.store.vector_search(qvec, gt_n * 3, [gt_doc], kinds=["table"])
            tbl_fts = self.store.fts_search(query, gt_n * 2, [gt_doc], kinds=["table"])
            fused_t: dict[str, float] = {}
            order: dict[str, Chunk] = {}
            for rank, h in enumerate(tbl_hits):
                fused_t[h.chunk.id] = fused_t.get(h.chunk.id, 0.0) + _rrf(rank)
                order[h.chunk.id] = h.chunk
            for rank, h in enumerate(tbl_fts):
                fused_t[h.chunk.id] = fused_t.get(h.chunk.id, 0.0) + _rrf(rank)
                order[h.chunk.id] = h.chunk
            for cid, _ in sorted(fused_t.items(), key=lambda kv: kv[1], reverse=True)[:gt_n]:
                reserved.append(RetrievedChunk(order[cid], 1.0, "guaranteed-table"))
                reserved_ids.add(cid)

        vhits = self.store.vector_search(qvec, self.s.top_k_vector, doc_types)
        fhits = self.store.fts_search(query, self.s.top_k_fts, doc_types)

        # Reciprocal-rank fusion across the two lists.
        fused: dict[str, float] = {}
        for rank, h in enumerate(vhits):
            fused[h.chunk.id] = fused.get(h.chunk.id, 0.0) + _rrf(rank)
        for rank, h in enumerate(fhits):
            fused[h.chunk.id] = fused.get(h.chunk.id, 0.0) + _rrf(rank)

        # Prefer the specific subsection over its parent-overview section.
        demote_parent_overviews(fused, self.by_id)

        seed_ids = [cid for cid, _ in sorted(fused.items(), key=lambda kv: kv[1], reverse=True)]
        results: list[RetrievedChunk] = []
        for cid in seed_ids:
            if cid in reserved_ids:
                continue
            ch = self.by_id.get(cid)
            if ch is not None:
                results.append(RetrievedChunk(ch, fused[cid], "vector+fts"))

        # Reserved TFL result tables always lead; then vector+fts by score.
        # Reserved tables are additive to the k budget so they never displace
        # the definitional context.
        results.sort(key=lambda r: r.score, reverse=True)
        return reserved + results[:k]
