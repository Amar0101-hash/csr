"""Patch readable captions onto the EXISTING graph in place (no re-embedding).

Sets `name` (section heading + doc) and `preview` on every RagSection so the
Neo4j Browser shows what each node actually is instead of 'sap sap protocol'.
"""
from __future__ import annotations

from neo4j import GraphDatabase

from graph_rag.gr_config import L_DOC, L_SECTION, L_STUDY, SETTINGS


def _driver():
    return GraphDatabase.driver(
        SETTINGS.neo4j_uri, auth=(SETTINGS.neo4j_user, SETTINGS.neo4j_password)
    )


# Compute the caption in Cypher from the existing path/doc/text properties.
_ENRICH_SECTIONS = f"""
MATCH (s:{L_SECTION})
WITH s, split(s.path, ' > ') AS parts
WITH s, trim(replace(parts[size(parts)-1], ':', '')) AS leaf
WITH s, CASE WHEN size(split(s.path,' > ')) > 1 AND leaf <> '' AND toLower(leaf) <> toLower(s.doc)
             THEN leaf
             ELSE left(s.text, 40) END AS heading
SET s.name = left(s.doc + ' · ' + CASE WHEN s.kind = 'table' THEN '[table] ' ELSE '' END + heading, 60),
    s.preview = left(s.text, 200)
RETURN count(s) AS updated
"""


def enrich(verbose: bool = True) -> None:
    with _driver() as drv, drv.session(database=SETTINGS.neo4j_database) as s:
        n = s.run(_ENRICH_SECTIONS).single()["updated"]
        # readable captions for docs and study too
        s.run(f"MATCH (d:{L_DOC}) SET d.name = d.doc_type + ': ' + d.name")
        s.run(f"MATCH (st:{L_STUDY}) SET st.name = 'Study ' + st.id")
    if verbose:
        print(f"[enrich] set readable name/preview on {n} sections "
              f"(+ docs, study). In Neo4j Browser, set the {L_SECTION} caption to 'name'.")


if __name__ == "__main__":
    enrich()
