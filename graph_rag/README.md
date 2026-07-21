# GraphRAG prototype (isolated — does not touch `src/csr`)

A standalone spike of the "colleague's design": a **study-rooted knowledge graph
in Neo4j with embeddings on the nodes** (native Neo4j vector index) plus a
**text-to-Cypher** path where the LLM writes the query. Built to compare, side by
side, against the deterministic retrieval in the main app.

Isolation guarantees:
- Lives entirely in this folder; the main pipeline is untouched.
- Uses **distinct node labels** (`:RagStudy`, `:RagDoc`, `:RagSection`) so it
  shares the same Neo4j instance without colliding with the app's
  `:Chunk/:Entity/:Document` graph.
- Reuses the app's chunking / Titan embeddings / Bedrock client **by import only**
  (read-only) to avoid duplicating stable code.

## Graph model

```
(:RagStudy {id})
(:RagDoc {name, doc_type})-[:PART_OF]->(:RagStudy)
(:RagSection {id, doc, path, kind, text, embedding})-[:IN]->(:RagDoc)
(:RagSection)-[:OF_STUDY]->(:RagStudy)
```
`RagSection.embedding` is a 1024-dim Titan v2 vector; a native vector index
`rag_section_embeddings` (cosine) powers semantic search inside Cypher.

## Run

```bash
# 1. build the study-rooted graph + embeddings + vector index
uv run python graphrag_prototype/demo.py build

# 2. semantic (vector) search executed INSIDE Neo4j
uv run python graphrag_prototype/demo.py search "primary effectiveness endpoint results"

# 3. text-to-Cypher: the LLM writes + runs the query (guarded, read-only)
uv run python graphrag_prototype/demo.py ask "How many source documents are in the study and how many sections does each have?"
uv run python graphrag_prototype/demo.py ask "Which sections mention adverse events?"

# 4. side-by-side: deterministic vector vs LLM-Cypher for the same question
uv run python graphrag_prototype/demo.py compare "device deficiencies"

# 5. readable node captions in Neo4j Browser (patch existing graph, no re-embed)
uv run python graphrag_prototype/demo.py enrich

# --- template-driven linking (the second design) ---
# 6. put the TEMPLATE in the graph + compute FILLED_BY edges to source sections
uv run python graphrag_prototype/demo.py template
# 7. coverage: which template sections have no linked source (data gaps)
uv run python graphrag_prototype/demo.py coverage
# 8. generate a section by TRAVERSING its FILLED_BY edges (traceable chain)
uv run python graphrag_prototype/demo.py fill 6.3.5
# 9. generate the FULL report from graph traversal -> output/GraphRAG_Report.docx
uv run python graphrag_prototype/demo.py report        # all sections
uv run python graphrag_prototype/demo.py report 5      # first 5 (quick)
```

## Web UI — CSR GraphRAG Explorer

A local FastAPI app + self-contained single-page frontend (`webapp/`) on top of
the graph. `src/csr` untouched; backend reuses the prototype modules read-only.

**Backend** (FastAPI, always needed):
```bash
uv run python graphrag_prototype/backend/server.py     # API on http://localhost:8000
```

**Frontend** is a **Vite + React** app in `frontend/` (requires Node.js LTS):
```bash
cd graphrag_prototype/frontend
npm install
npm run dev        # dev UI on http://localhost:5173 (proxies /api -> :8000)
# or, for production:
npm run build      # -> frontend/dist ; the FastAPI server then serves it at :8000
```
Until React is built, the backend serves the zero-build `frontend/legacy.html`
fallback at `http://localhost:8000`, so the UI works with no Node.

Structure: `frontend/src/App.jsx` (shell + tabs) · `components/SectionList`,
`SectionDetail`, `SourcePanel`, `LineageGraph` (SVG star), `CoverageHeatmap` ·
`api.js` (backend client).

Features:
- **Section list** (left) with a coverage dot per section (color = # linked sources).
- **Section content** (center), editable, with **Save edits** and **Regenerate**
  — including a **custom prompt** box to steer regeneration (grounded in the
  section's linked sources). Generated content is cached on the graph nodes.
- **Source traceability** panel: every `FILLED_BY` source with its doc, **role**
  (DEFINES / REPORTS / SPECIFIES / DESCRIBES), score, path and expandable preview.
- **Source lineage** as an inline SVG star: the template section in the centre,
  its source nodes around it, colored by document, edges weighted by score — the
  readable "section → its sources" view (not a hairball).
- **Coverage heatmap** tab: every section as a cell colored by source count
  (red = gap), click to jump to the section.

Run `demo.py report` first to pre-populate every section's content (it now caches
to the nodes); otherwise click **Regenerate** per section in the UI.

## Head-to-head comparison

`report` reuses the main app's grounding prompt + template-preserving assembly
(read-only), so the produced `output/GraphRAG_Report.docx` differs from the main
pipeline's `Clinical_Investigation_Report.docx` **only in the retrieval
mechanism** — graph `FILLED_BY` edges here vs. the hybrid retriever there. Diff
the two to judge whether the graph-driven links retrieve better, worse, or the
same. (`FILLED_BY` is tuned with doc-type routing + entity overlap + guaranteed
result tables; §8.2 External Organizations correctly shows a coverage gap.)

## Node readability

Section nodes carry a `name` (e.g. `protocol · Effectiveness Analyses`) and a
`preview`. In Neo4j Browser, click the `RagSection` / `RagTemplateSection` label
chip and set the **caption** to `name`. Useful visual queries:

```cypher
// a template section and the source nodes that fill it
MATCH p = (:RagTemplateSection {number:'6.3.5'})-[:FILLED_BY]->(:RagSection)
RETURN p

// the template tree
MATCH p = (:RagTemplateSection)-[:PARENT_OF*]->(:RagTemplateSection) RETURN p LIMIT 50
```

## Template-driven model

```
(:RagTemplateSection {number, title, guidance, embedding, name})
(:RagTemplateSection)-[:PARENT_OF]->(:RagTemplateSection)
(:RagTemplateSection)-[:FILLED_BY {score, method}]->(:RagSection)
```
`FILLED_BY` is computed by semantic similarity (section requirement ↔ source
embeddings, via the vector index) and **materialized as edges**, so generation
and traceability are graph traversals and coverage gaps are one query.

## What to look for

- **Vector-in-Neo4j** works and could replace LanceDB (one store).
- **text-to-Cypher** is great for *structured/relational* questions (counts,
  "which docs", "how many sections") and brittle/non-deterministic for *semantic*
  ones — exactly the trade-off to show the director.
