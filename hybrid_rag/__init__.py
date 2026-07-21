"""Hybrid RAG: dense vector + sparse full-text + in-memory graph expansion, fused
with multi-signal RRF (consensus-boosted). Reuses shared code from vector_rag and
an in-memory NetworkX entity graph (no Neo4j)."""
from .retriever import HybridRetriever, build_hybrid_retriever

__all__ = ["HybridRetriever", "build_hybrid_retriever"]
