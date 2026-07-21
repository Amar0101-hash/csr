"""Add the TEMPLATE into the graph and link each template section to the source
sections that should fill it (the "FILLED_BY" edges) — combining both designs:
study-rooted source graph + template-driven linking.

    (:RagTemplateSection {number, title, guidance, generate, embedding, name})
    (:RagTemplateSection)-[:PARENT_OF]->(:RagTemplateSection)     # template tree
    (:RagTemplateSection)-[:OF_STUDY]->(:RagStudy)
    (:RagTemplateSection)-[:FILLED_BY {score, method}]->(:RagSection)   # computed

FILLED_BY is computed by semantic similarity between each section's *requirement*
(title + guidance) and the source section embeddings, via the Neo4j vector index.
It's materialized as edges so generation and traceability become traversals, and
coverage gaps ("sections with no source") become a one-line query.
"""
from __future__ import annotations

from neo4j import GraphDatabase

from graph_rag.gr_config import L_SECTION, L_STUDY, SETTINGS, STUDY_ID, VECTOR_INDEX
from vector_rag.ingestion.template_parser import parse_template
from vector_rag.knowledge.embeddings import TitanEmbedder
from graph_rag.dataingestion.entities import extract_entities
from vector_rag.generation.prompts import doc_types_for, guaranteed_tables_for

L_TSECTION = "RagTemplateSection"


def _driver():
    return GraphDatabase.driver(
        SETTINGS.neo4j_uri, auth=(SETTINGS.neo4j_user, SETTINGS.neo4j_password)
    )


def _inherit_guidance(sections) -> None:
    """Endpoint placeholders (6.2.1 …) inherit the parent Results section's
    guidance (copied locally so the prototype doesn't depend on app internals)."""
    by_number = {s.number: s for s in sections if s.number}
    for s in sections:
        if not s.generate or s.guidance.strip() or not s.number:
            continue
        parts = s.number.split(".")
        while len(parts) > 1:
            parts = parts[:-1]
            anc = by_number.get(".".join(parts))
            if anc and anc.guidance.strip():
                s.guidance = anc.guidance
                break


def build_template(threshold: float = 0.62, top_k: int = 8, verbose: bool = True) -> None:
    sections = parse_template(SETTINGS.template_path)
    _inherit_guidance(sections)
    targets = [s for s in sections if s.number]  # skip the doc-title node

    embedder = TitanEmbedder(SETTINGS.embed_model, SETTINGS.aws_region, SETTINGS.embed_dim)
    req_texts = [f"{s.title}\n{s.guidance}".strip() for s in targets]
    if verbose:
        print(f"[tmpl] embedding {len(targets)} template sections ...")
    vecs = embedder.embed_batch(req_texts, progress=False)
    vec_by_key = {s.key: v for s, v in zip(targets, vecs)}

    rows = [
        {
            "key": s.key, "number": s.number, "title": s.title, "level": s.level,
            "generate": s.generate, "guidance": s.guidance[:4000],
            "embedding": v, "name": f"§{s.number} {s.title}"[:60],
        }
        for s, v in zip(targets, vecs)
    ]

    db = SETTINGS.neo4j_database
    with _driver() as drv, drv.session(database=db) as sess:
        sess.run(f"MATCH (n:{L_TSECTION}) DETACH DELETE n")
        sess.run(f"CREATE CONSTRAINT rag_tsection_key IF NOT EXISTS "
                 f"FOR (t:{L_TSECTION}) REQUIRE t.key IS UNIQUE")
        for i in range(0, len(rows), 100):
            sess.run(_INSERT_TS, rows=rows[i : i + 100], sid=STUDY_ID)
        sess.run(_PARENTS)  # 6.2.1 -> parent 6.2 -> 6
        # full-text index over source text (lexical half of the hybrid link signal)
        sess.run(f"CREATE FULLTEXT INDEX rag_section_fts IF NOT EXISTS "
                 f"FOR (s:{L_SECTION}) ON EACH [s.text]")

        # Precise FILLED_BY: for each authorable section, rank candidates by
        # vector score + doc-type routing bonus + entity overlap, then reserve
        # slots for the section's TFL result tables (as the main app does).
        total = 0
        for s in targets:
            if not s.generate:
                continue
            total += _link_section(sess, s, vec_by_key[s.key], top_k, threshold)

    if verbose:
        print(f"[tmpl] created {len(rows)} template sections, {total} FILLED_BY edges "
              f"(vector + routing + entity-overlap + guaranteed tables)")


_ROLE = {"sap": "DEFINES", "protocol": "SPECIFIES", "mop": "DESCRIBES",
         "tfl_effectiveness": "REPORTS", "tfl_safety": "REPORTS",
         "tfl_conduct": "REPORTS", "tfl_listings": "REPORTS"}


def _fts_query(title: str, entities: set[str]) -> str:
    """Lucene query from the section's title + its clinical entities (the terms a
    source must lexically contain to satisfy this section)."""
    import re
    terms = re.findall(r"[A-Za-z0-9]+", (title + " " + " ".join(entities)).lower())
    stop = {"the", "a", "an", "of", "and", "or", "for", "to", "in", "on", "with",
            "endpoint", "endpoints", "section", "study", "analysis"}
    terms = [t for t in terms if t not in stop and len(t) > 2]
    return " ".join(dict.fromkeys(terms))[:300]


def _link_section(sess, spec, emb, top_k: int, threshold: float) -> int:
    routed = set(doc_types_for(spec) or [])
    req_ents = set(extract_entities(f"{spec.title} {spec.guidance}"))

    # --- hybrid candidate generation: vector + FTS, fused by reciprocal rank ---
    vec = sess.run(_CANDIDATES, emb=emb, k=top_k * 3).data()
    fq = _fts_query(spec.title, req_ents)
    fts = sess.run(_FTS_CANDIDATES, q=fq, k=top_k * 3).data() if fq else []

    meta = {c["id"]: c for c in vec}
    for c in fts:
        meta.setdefault(c["id"], c)
    vscore = {c["id"]: c["score"] for c in vec}

    # a candidate qualifies if it clears the vector floor OR the FTS caught it
    qualified = {c["id"] for c in vec if c["score"] >= threshold} | {c["id"] for c in fts}

    rrf: dict[str, float] = {}
    for rank, c in enumerate(vec):
        if c["id"] in qualified:
            rrf[c["id"]] = rrf.get(c["id"], 0.0) + 1.0 / (60 + rank)
    for rank, c in enumerate(fts):
        if c["id"] in qualified:
            rrf[c["id"]] = rrf.get(c["id"], 0.0) + 1.0 / (60 + rank)

    scored = []
    for cid in qualified:
        c = meta[cid]
        s = rrf.get(cid, 0.0)
        if routed and c["doc"] in routed:
            s += 0.010                                       # routing bonus
        overlap = len(req_ents & set(extract_entities(c["text"])))
        s += 0.003 * min(overlap, 4)                         # entity-anchor bonus
        method = "hybrid" if cid in vscore and cid in {x["id"] for x in fts} else \
                 ("vector" if cid in vscore else "fts")
        scored.append((cid, round(s, 4), method))
    scored.sort(key=lambda x: x[1], reverse=True)
    selected = {cid: (sc, m) for cid, sc, m in scored[:top_k]}

    # reserve slots for the section's result tables (effectiveness/safety/conduct)
    gt = guaranteed_tables_for(spec)
    if gt:
        doc_t, n = gt
        for c in sess.run(_TABLE_CANDIDATES, emb=emb, doc=doc_t, k=n * 3).data()[:n]:
            selected.setdefault(c["id"], (round(c["score"], 3), "guaranteed-table"))

    for cid, (sc, m) in selected.items():
        role = _ROLE.get(meta[cid]["doc"], "RELATES_TO")
        sess.run(_MERGE_EDGE, key=spec.key, cid=cid, sc=sc, m=m, role=role)
    return len(selected)


_INSERT_TS = f"""
MATCH (st:{L_STUDY} {{id: $sid}})
UNWIND $rows AS row
MERGE (t:{L_TSECTION} {{key: row.key}})
  SET t.number = row.number, t.title = row.title, t.level = row.level,
      t.generate = row.generate, t.guidance = row.guidance,
      t.embedding = row.embedding, t.name = row.name
MERGE (t)-[:OF_STUDY]->(st)
"""

_PARENTS = f"""
MATCH (c:{L_TSECTION}), (p:{L_TSECTION})
WHERE c.number CONTAINS '.'
  AND p.number = left(c.number, size(c.number) - size(split(c.number,'.')[-1]) - 1)
MERGE (p)-[:PARENT_OF]->(c)
"""

_CANDIDATES = f"""
CALL db.index.vector.queryNodes('{VECTOR_INDEX}', $k, $emb) YIELD node, score
RETURN node.id AS id, node.doc AS doc, node.kind AS kind, node.text AS text, score
"""

_FTS_CANDIDATES = f"""
CALL db.index.fulltext.queryNodes('rag_section_fts', $q, {{limit: $k}})
  YIELD node, score
RETURN node.id AS id, node.doc AS doc, node.kind AS kind, node.text AS text, score
"""

_TABLE_CANDIDATES = f"""
CALL db.index.vector.queryNodes('{VECTOR_INDEX}', $k, $emb) YIELD node, score
WITH node, score WHERE node.doc = $doc AND node.kind = 'table'
RETURN node.id AS id, score
ORDER BY score DESC
"""

_MERGE_EDGE = f"""
MATCH (t:{L_TSECTION} {{key: $key}}), (s:{L_SECTION} {{id: $cid}})
MERGE (t)-[f:FILLED_BY]->(s)
  SET f.score = $sc, f.method = $m, f.role = $role
"""


def coverage() -> None:
    with _driver() as drv, drv.session(database=SETTINGS.neo4j_database) as s:
        rows = s.run(
            f"MATCH (t:{L_TSECTION}) WHERE t.generate "
            f"OPTIONAL MATCH (t)-[f:FILLED_BY]->() "
            f"WITH t, count(f) AS n RETURN t.number AS number, t.title AS title, n "
            f"ORDER BY n ASC, t.number"
        ).data()
    gaps = [r for r in rows if r["n"] == 0]
    print(f"\n=== FILLED_BY coverage: {len(rows)} authorable sections, "
          f"{len(gaps)} with NO source link ===")
    for r in gaps:
        print(f"   GAP  §{r['number']}  {r['title'][:50]}")
    print("   (sections with most links:)")
    for r in sorted(rows, key=lambda x: -x["n"])[:6]:
        print(f"   {r['n']:2d}   §{r['number']}  {r['title'][:50]}")


if __name__ == "__main__":
    build_template()
    coverage()
