"""Knowledge graph over source chunks and clinical entities (networkx).

The graph is the "graph" half of hybrid RAG. Nodes are chunks and entities;
edges connect a chunk to every entity it mentions. Retrieval uses it to expand
a vector/FTS hit set with other chunks that share the same clinical entities —
crucial for CSR consistency, where an endpoint is *defined* in the SAP,
*described* in the Protocol, and *measured* in a TFL table.

Entity extraction is deterministic (regex + curated vocab), so the graph is
reproducible and cheap — no LLM calls to build the index.
"""
from __future__ import annotations

import pickle
import re
from pathlib import Path

import networkx as nx

from ..models import Chunk

# Curated clinical/statistical vocabulary. Matched case-insensitively as whole
# phrases. Extend freely — recall improves, precision is bounded by phrase set.
VOCAB = [
    # analysis sets
    "full analysis set", "safety analysis set", "per protocol analysis set",
    "per protocol", "intent to treat", "analysis set",
    # design
    "randomization", "randomisation", "crossover", "masking", "masked",
    "double-masked", "single-masked", "interim analysis", "sample size",
    "control group", "comparator", "subject population",
    # endpoints / effectiveness
    "primary endpoint", "secondary endpoint", "exploratory endpoint",
    "effectiveness endpoint", "safety endpoint", "primary effectiveness",
    "primary objective", "secondary objective", "hypothesis",
    "logmar", "visual acuity", "bcva", "manifest refraction", "keratometry",
    "autorefractometry", "lens movement", "centration", "wettability",
    # safety
    "adverse event", "serious adverse event", "adverse device effect",
    "device deficiency", "biomicroscopy", "corneal staining", "hyperemia",
    "corneal edema", "slit lamp", "discontinuation",
    # conduct
    "inclusion criteria", "exclusion criteria", "screening", "enrollment",
    "disposition", "protocol deviation", "concomitant medication", "follow-up",
    "informed consent", "ethics committee", "monitoring",
    # visits
    "visit 1", "visit 2", "visit 3", "visit 4", "baseline", "dispense",
]

_STUDY_RE = re.compile(r"\b[A-Z]{2,5}\d{2,4}[- ]?P?\d{2,4}\b")
_ACRONYM_RE = re.compile(r"\b[A-Z]{2,6}\b")
_ACR_STOP = {"THE", "AND", "FOR", "WITH", "THIS", "THAT", "WILL", "SHALL", "FROM",
             "TABLE", "FIGURE", "NOTE", "ISO", "MDR", "GCP",
             # generic / geographic / legal noise that the acronym regex admits
             "BEFORE", "AFTER", "DURING", "NA", "TX", "RX", "UK", "US", "USA", "EU",
             "LLC", "INC", "LTD", "CO", "RL", "JCR", "WHO", "ALL", "ANY", "NOT",
             "MAY", "CAN", "PER", "VIA", "EACH", "SUCH", "THAN", "WHEN", "WERE"}


def extract_entities(text: str) -> list[str]:
    ents: set[str] = set()
    low = text.lower()
    for phrase in VOCAB:
        if phrase in low:
            ents.add(phrase)
    for m in _STUDY_RE.findall(text):
        ents.add(m.upper().replace(" ", "-"))
    for m in _ACRONYM_RE.findall(text):
        if m not in _ACR_STOP:
            ents.add(m)
    return sorted(ents)


class GraphStore:
    def __init__(self):
        self.g = nx.Graph()

    def build(self, chunks: list[Chunk]) -> None:
        self.g = nx.Graph()
        for c in chunks:
            self.g.add_node(("chunk", c.id), doc=c.doc, doc_type=c.doc_type,
                            section_path=c.section_path)
            ents = extract_entities(c.section_path + "\n" + c.text)
            c.entities = ents  # backfill onto chunk
            for e in ents:
                enode = ("entity", e)
                if enode not in self.g:
                    self.g.add_node(enode, count=0)
                self.g.nodes[enode]["count"] += 1
                self.g.add_edge(("chunk", c.id), enode)

    def neighbors_of_chunks(self, chunk_ids: list[str], max_entities_per_chunk: int = 6,
                            max_expand: int = 40) -> list[str]:
        """Return chunk ids sharing entities with the seed chunks (1 hop),
        excluding the seeds themselves. Rarer entities are prioritized."""
        seed = set(chunk_ids)
        scored: dict[str, float] = {}
        for cid in chunk_ids:
            cn = ("chunk", cid)
            if cn not in self.g:
                continue
            ents = list(self.g.neighbors(cn))
            # prefer rarer (more specific) entities
            ents.sort(key=lambda e: self.g.nodes[e].get("count", 999))
            for enode in ents[:max_entities_per_chunk]:
                weight = 1.0 / (1.0 + self.g.nodes[enode].get("count", 1))
                for other in self.g.neighbors(enode):
                    if other[0] != "chunk":
                        continue
                    ocid = other[1]
                    if ocid in seed:
                        continue
                    scored[ocid] = scored.get(ocid, 0.0) + weight
        ranked = sorted(scored.items(), key=lambda kv: kv[1], reverse=True)
        return [cid for cid, _ in ranked[:max_expand]]

    def stats(self) -> tuple[int, int]:
        return self.g.number_of_nodes(), self.g.number_of_edges()

    def close(self) -> None:
        pass

    def save(self, path: Path) -> None:
        with open(path, "wb") as f:
            pickle.dump(self.g, f)

    def load(self, path: Path) -> None:
        with open(path, "rb") as f:
            self.g = pickle.load(f)
