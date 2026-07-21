"""Build the study **concept graph** on top of the existing RagSection nodes.

    (:RagConcept {key, name, kind, freq})
    (:RagSection)-[:MENTIONS_CONCEPT {role, count}]->(:RagConcept)

`role` is what the *mentioning document* does for the concept:
    sap        -> DEFINES     (the statistical/endpoint definition)
    protocol   -> DESCRIBES   (design & methods)
    mop        -> DESCRIBES   (operational procedure)
    tfl_*      -> MEASURES    (the reported result / actual numbers)

So one concept — say the primary effectiveness endpoint — is reachable as
DEFINES(SAP) + DESCRIBES(Protocol) + MEASURES(TFL table). That is the precise
cross-document bridge the hybrid retriever traverses, replacing the old coarse
entity co-mention. Ids are the RagSection content hashes, identical to LanceDB's
chunk ids, so hybrid seeds map straight onto these nodes.

Idempotent: re-running wipes only :RagConcept (and its edges) and rebuilds.
"""
from __future__ import annotations

from collections import Counter

from neo4j import GraphDatabase

from graph_rag.gr_config import L_SECTION, SETTINGS
from graph_rag.dataingestion.concepts import CONCEPT_BY_KEY, detect_concepts

L_CONCEPT = "RagConcept"

# doc name -> role the section plays for a concept it mentions.
_ROLE = {
    "sap": "DEFINES",
    "protocol": "DESCRIBES",
    "mop": "DESCRIBES",
    "tfl_effectiveness": "MEASURES",
    "tfl_safety": "MEASURES",
    "tfl_conduct": "MEASURES",
    "tfl_listings": "MEASURES",
}


def _driver():
    return GraphDatabase.driver(
        SETTINGS.neo4j_uri, auth=(SETTINGS.neo4j_user, SETTINGS.neo4j_password)
    )


def build_concepts(verbose: bool = True) -> None:
    with _driver() as drv, drv.session(database=SETTINGS.neo4j_database) as s:
        sections = s.run(
            f"MATCH (n:{L_SECTION}) RETURN n.id AS id, n.doc AS doc, n.text AS text"
        ).data()
        if verbose:
            print(f"[concept] scanning {len(sections)} sections for concepts ...")

        edges: list[dict] = []
        freq: Counter[str] = Counter()
        for row in sections:
            role = _ROLE.get(row["doc"], "RELATES_TO")
            for key, count in detect_concepts(row["text"] or "").items():
                edges.append({"sid": row["id"], "key": key, "role": role, "count": count})
                freq[key] += 1

        # Only materialize concepts that actually occur, plus their per-concept
        # section frequency (drives the rarity weighting in retrieval).
        concept_rows = [
            {"key": k, "name": CONCEPT_BY_KEY[k].name,
             "kind": CONCEPT_BY_KEY[k].kind, "freq": n}
            for k, n in freq.items()
        ]

        s.run(f"MATCH (c:{L_CONCEPT}) DETACH DELETE c")
        s.run(f"CREATE CONSTRAINT rag_concept_key IF NOT EXISTS "
              f"FOR (c:{L_CONCEPT}) REQUIRE c.key IS UNIQUE")
        for i in range(0, len(concept_rows), 200):
            s.run(_INSERT_CONCEPTS, rows=concept_rows[i : i + 200])
        for i in range(0, len(edges), 500):
            s.run(_INSERT_EDGES, rows=edges[i : i + 500])

    if verbose:
        # a concept only bridges documents if it is mentioned with >1 distinct role
        multi = _multi_role_count()
        print(f"[concept] built {len(concept_rows)} concepts, {len(edges)} "
              f"MENTIONS_CONCEPT edges; {multi} concepts bridge >1 document role "
              f"(these are the cross-document links the hybrid uses).")


_INSERT_CONCEPTS = f"""
UNWIND $rows AS row
MERGE (c:{L_CONCEPT} {{key: row.key}})
  SET c.name = row.name, c.kind = row.kind, c.freq = row.freq
"""

_INSERT_EDGES = f"""
UNWIND $rows AS row
MATCH (s:{L_SECTION} {{id: row.sid}}), (c:{L_CONCEPT} {{key: row.key}})
MERGE (s)-[m:MENTIONS_CONCEPT]->(c)
  SET m.role = row.role, m.count = row.count
"""


def _multi_role_count() -> int:
    with _driver() as drv, drv.session(database=SETTINGS.neo4j_database) as s:
        return s.run(
            f"MATCH (c:{L_CONCEPT})<-[m:MENTIONS_CONCEPT]-(:{L_SECTION}) "
            "WITH c, count(DISTINCT m.role) AS roles WHERE roles > 1 "
            "RETURN count(c) AS n"
        ).single()["n"]


def concept_report() -> None:
    """Human-readable summary: which concepts bridge which document roles."""
    with _driver() as drv, drv.session(database=SETTINGS.neo4j_database) as s:
        rows = s.run(
            f"MATCH (c:{L_CONCEPT})<-[m:MENTIONS_CONCEPT]-(sec:{L_SECTION}) "
            "WITH c, collect(DISTINCT m.role) AS roles, count(DISTINCT sec) AS secs "
            "RETURN c.key AS key, c.name AS name, c.kind AS kind, "
            "c.freq AS freq, roles, secs ORDER BY size(roles) DESC, secs DESC"
        ).data()
    bridging = [r for r in rows if len(r["roles"]) > 1]
    print(f"\n=== Concept graph: {len(rows)} concepts, "
          f"{len(bridging)} bridge >1 document role ===")
    print("  (concept · roles it connects · #sections)")
    for r in bridging[:20]:
        roles = "+".join(sorted(r["roles"]))
        print(f"   {r['name'][:34]:34s} {roles:26s} {r['secs']:2d} sections")
    lonely = [r for r in rows if len(r["roles"]) == 1]
    if lonely:
        print(f"  single-role (no cross-doc bridge): "
              f"{', '.join(r['key'] for r in lonely[:12])}")


if __name__ == "__main__":
    build_concepts()
    concept_report()
