# graph_rag

The **Graph RAG** package: a study-rooted **knowledge graph in Neo4j** with
embeddings on the section nodes (native Neo4j vector index), a **text-to-Cypher**
path where the LLM writes the query, and **template-driven `FILLED_BY` linking**
that turns generation and traceability into graph traversals.

> Naming: this package was formerly `graphrag_prototype`. It reuses `vector_rag`'s
> chunker, Titan embedder, prompts, verifier, and `.docx` assembler by import
> (read-only) — only the *retrieval mechanism* differs.

## Graph model

```
(:RagStudy {id})
(:RagDoc {name, doc_type})-[:PART_OF]->(:RagStudy)
(:RagSection {id, doc, path, kind, text, embedding, name, preview})-[:IN]->(:RagDoc)
(:RagSection)-[:OF_STUDY]->(:RagStudy)

(:RagTemplateSection {number, title, guidance, generate, embedding, name, content, ...})
(:RagTemplateSection)-[:PARENT_OF]->(:RagTemplateSection)         # template tree
(:RagTemplateSection)-[:OF_STUDY]->(:RagStudy)
(:RagTemplateSection)-[:FILLED_BY {score, method, role}]->(:RagSection)   # computed link
```

- `RagSection.embedding` is a 1024-dim Titan v2 vector; the native vector index
  `rag_section_embeddings` (cosine) powers semantic search **inside Cypher**, and
  `rag_section_fts` is a full-text index over the section text.
- `FILLED_BY` is computed per authorable template section by fusing vector + FTS
  candidates (RRF) with a doc-type routing bonus, an entity-overlap bonus, and
  reserved slots for the section's TFL result tables. Materializing it as edges
  makes generation, traceability, and coverage one-line traversals.

There is also a **legacy entity graph** in the same database —
`(:Chunk)-[:MENTIONS]->(:Entity)` — over the same content-hash ids. `hybrid_rag`
uses it for cross-document entity expansion (see `hybrid_rag/README.md`).

## Layout

```
graph_rag/
  gr_config.py         # reuses vector_rag Settings, attaches Neo4j creds, label namespace
                       #   L_STUDY/L_DOC/L_SECTION, VECTOR_INDEX, STUDY_ID
  dataingestion/
    build_graph.py     # RagStudy/RagDoc/RagSection + Titan embeddings + native vector index
    template_graph.py  # RagTemplateSection + FILLED_BY edges (L_TSECTION), coverage()
    entities.py        # extract_entities — deterministic clinical-entity extraction
    enrich.py          # readable node captions for Neo4j Browser
  generate.py          # author_from_retrieved (SHARED generation core), _author (FILLED_BY),
                       #   author_section, generate_report, build_docx_from_cache
  retrieve.py          # vector_search — semantic search executed inside Neo4j
  text2cypher.py       # LLM writes + runs a guarded, read-only Cypher query
  trace_view.py        # section_view, coverage_view, section_sort_key (UI graph JSON)
  audit.py             # log_event, events_for — append-only JSONL audit trail
  compare_reports.py   # head-to-head diff: main app .docx vs graph .docx
  fill_section.py      # single-section fill helper
  demo.py              # CLI for the whole prototype (see below)
```

## Prerequisites

- A running **Neo4j 5.x** at `bolt://localhost:7687` (override via `CSR_NEO4J_URI`,
  `CSR_NEO4J_USER`, `CSR_NEO4J_PASSWORD`, `CSR_NEO4J_DATABASE`).
- Same Bedrock access as `vector_rag` (Titan v2 + Claude).

## CLI (`demo.py`)

Run as a module from the repo root:

```bash
# 1. build the study-rooted graph + embeddings + native vector index
uv run python -m graph_rag.demo build

# 2. semantic (vector) search executed INSIDE Neo4j
uv run python -m graph_rag.demo search "primary effectiveness endpoint results"

# 3. text-to-Cypher: the LLM writes + runs a read-only query
uv run python -m graph_rag.demo ask "Which sections mention adverse events?"

# 4. readable node captions in Neo4j Browser (no re-embed)
uv run python -m graph_rag.demo enrich

# --- template-driven linking ---
uv run python -m graph_rag.demo template     # add the template + compute FILLED_BY edges
uv run python -m graph_rag.demo coverage     # which template sections have no source (gaps)

# --- generation / comparison ---
uv run python -m graph_rag.demo fill 6.3.5   # author one section from its FILLED_BY sources
uv run python -m graph_rag.demo report       # author the whole doc (graph retrieval) -> output/GraphRAG_Report.docx
uv run python -m graph_rag.demo report 5     # first 5 sections (quick)
uv run python -m graph_rag.demo compare "device deficiencies"   # deterministic vector vs LLM-Cypher
uv run python -m graph_rag.demo trace 6.3.5  # per-section source lineage JSON
uv run python -m graph_rag.demo diff         # numeric agreement: main vs graph reports
```

## The shared generation core

`generate.author_from_retrieved(spec, retrieved, client, custom_prompt, method)`
is the **single generation path used by all three RAG strategies**. It takes any
`list[RetrievedChunk]`, builds the grounded prompt (`vector_rag` prompts), calls
Claude, verifies numbers, attaches citations, and writes an audit event tagged
with `method`. The `_author` function here fetches a section's `FILLED_BY` sources
from Neo4j and feeds them to it; `backend` feeds it vector/hybrid retrievals the
same way. Because only retrieval differs, the three modes are directly comparable.

## Notes

- Distinct label namespace (`RagStudy` / `RagDoc` / `RagSection` /
  `RagTemplateSection`) keeps this graph isolated within a shared Neo4j instance.
- `text2cypher` is deliberately guarded (read-only clauses only, `LIMIT` enforced)
  and is meant to expose both the power and the risks of letting an LLM drive
  retrieval in a *regulated* setting.
