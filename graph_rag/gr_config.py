"""Prototype config. Reuses the main app's Settings (read-only) for creds/paths,
but keeps its own Neo4j label namespace and vector-index name so nothing in the
production graph is touched."""
from __future__ import annotations

import os

from vector_rag.config import Settings  # read-only reuse

SETTINGS = Settings()

# Neo4j connection — lives here now that the main app is pure-vector (no graph).
# Attached to SETTINGS so existing `SETTINGS.neo4j_*` call sites keep working.

SETTINGS.neo4j_uri = os.environ.get("CSR_NEO4J_URI", "bolt://localhost:7687")
SETTINGS.neo4j_user = os.environ.get("CSR_NEO4J_USER", "neo4j")
SETTINGS.neo4j_password = os.environ.get("CSR_NEO4J_PASSWORD", "password123")
SETTINGS.neo4j_database = os.environ.get("CSR_NEO4J_DATABASE", "neo4j")

STUDY_ID = "CLA306-P002"

# Distinct labels so this prototype never collides with the app's
# :Chunk/:Entity/:Document graph in the same Neo4j database.
L_STUDY = "RagStudy"
L_DOC = "RagDoc"
L_SECTION = "RagSection"
VECTOR_INDEX = "rag_section_embeddings"
EMBED_DIM = SETTINGS.embed_dim  # 1024 (Titan v2)
