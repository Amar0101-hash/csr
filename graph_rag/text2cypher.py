"""Text-to-Cypher: the LLM writes a read-only Cypher query for a natural-language
question, we guard + run it, then (optionally) generate an answer from the rows.

This deliberately exposes both the power (relational/aggregate questions) and the
risks (brittleness, non-determinism) of letting an LLM drive retrieval — the
trade-off to weigh for a *regulated* CSR.
"""
from __future__ import annotations

import re

from neo4j import GraphDatabase

from graph_rag.gr_config import L_DOC, L_SECTION, L_STUDY, SETTINGS, VECTOR_INDEX
from vector_rag.generation.llm import ClaudeClient

_client = ClaudeClient(SETTINGS)

SCHEMA = f"""
Graph schema (labels & properties):
  (:{L_STUDY} {{id}})
  (:{L_DOC} {{name, doc_type}})           doc_type in: protocol, sap, mop, tfl
  (:{L_SECTION} {{id, doc, path, kind, text}})   kind in: text, table
Relationships:
  (:{L_DOC})-[:PART_OF]->(:{L_STUDY})
  (:{L_SECTION})-[:IN]->(:{L_DOC})
  (:{L_SECTION})-[:OF_STUDY]->(:{L_STUDY})
There is also a vector index '{VECTOR_INDEX}' over {L_SECTION}.embedding for
semantic search: CALL db.index.vector.queryNodes('{VECTOR_INDEX}', k, $vec).
Do NOT select the `embedding` property in results (it is a huge vector).
"""

SYSTEM = (
    "You translate a question into a SINGLE read-only Neo4j Cypher query. "
    "Rules: read-only (no CREATE/MERGE/DELETE/SET/REMOVE/CALL{...write}); use only "
    "the labels/properties in the schema; never return the `embedding` property; "
    "always LIMIT to <= 25 rows. Return ONLY the Cypher, no prose, no code fences."
)

_WRITE = re.compile(r"\b(CREATE|MERGE|DELETE|SET|REMOVE|DROP|DETACH|LOAD\s+CSV)\b", re.I)


def generate_cypher(question: str) -> str:
    raw = _client.complete_text(SYSTEM, f"{SCHEMA}\n\nQuestion: {question}\n\nCypher:")
    m = re.search(r"```(?:cypher)?\s*(.*?)```", raw, re.DOTALL)
    cypher = (m.group(1) if m else raw).strip().rstrip(";")
    return cypher


def _driver():
    return GraphDatabase.driver(
        SETTINGS.neo4j_uri, auth=(SETTINGS.neo4j_user, SETTINGS.neo4j_password)
    )


def ask(question: str, verbose: bool = True) -> dict:
    cypher = generate_cypher(question)
    if verbose:
        print(f"\n[t2c] generated Cypher:\n{cypher}\n")
    if _WRITE.search(cypher):
        if verbose:
            print("[t2c] REJECTED: query contains a write clause")
        return {"error": "rejected: write clause", "cypher": cypher}
    if "$vec" in cypher or "$qvec" in cypher or "$embedding" in cypher:
        # classic failure: the LLM invoked the vector index but can't supply the
        # embedding vector parameter -> the query cannot run as written.
        if verbose:
            print("[t2c] FAILED: query needs an embedding parameter the LLM can't "
                  "provide (semantic retrieval isn't a pure Cypher pattern).")
        return {"error": "missing embedding parameter", "cypher": cypher}
    try:
        with _driver() as drv, drv.session(database=SETTINGS.neo4j_database) as s:
            rows = [r.data() for r in s.run(cypher)][:25]
    except Exception as e:
        if verbose:
            print(f"[t2c] FAILED at runtime: {type(e).__name__}: {str(e)[:120]}")
        return {"error": f"cypher failed: {type(e).__name__}", "cypher": cypher}

    if verbose:
        print(f"[t2c] rows returned: {len(rows)}")
        for r in rows[:10]:
            print("   ", {k: (str(v)[:60] if isinstance(v, str) else v) for k, v in r.items()})
    return {"cypher": cypher, "rows": rows}


if __name__ == "__main__":
    import sys
    ask(sys.argv[1] if len(sys.argv) > 1 else "How many sections does each document have?")
