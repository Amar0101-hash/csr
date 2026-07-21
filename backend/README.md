# backend

The **FastAPI web layer** for the CSR RAG Explorer. It exposes the domain logic
of `vector_rag` / `graph_rag` / `hybrid_rag` as a JSON API, orchestrates section
generation (per-section and full-document), manages the version/approval
workflow, and serves the built React app.

This package is intentionally thin: it is the HTTP/orchestration seam. The actual
retrieval and generation live in the three RAG packages.

## Run

```bash
uv run python -m backend.server        # -> http://localhost:8000
```

- Serves the built frontend from `../frontend/dist` (falls back to
  `../frontend/legacy.html` until the React app is built).
- Requires a running **Neo4j** (section/template state, graph retrieval) and
  **Bedrock** access (embeddings + generation). See the RAG package READMEs.

For UI development, run the Vite dev server instead (`cd frontend && npm run dev`,
port 5173) — it proxies `/api` to this server on 8000.

## Layout

```
backend/
  __init__.py
  server.py     # the entire FastAPI app: routes, retriever singletons,
                #   author_section_method (method dispatch), version/approval,
                #   full-generation background job, report build/download
```

## Key pieces in `server.py`

- **Retriever singletons** (lazy): `_vector_retriever()`, `_hybrid_retriever()`,
  and the graph path via `graph_rag`. Built once per process on first use.
- **`author_section_method(number, method, custom_prompt, effort)`** — dispatches
  to `vector` / `graph` / `hybrid` retrieval, then the **shared** generation core
  (`graph_rag.generate.author_from_retrieved`). Only retrieval differs, so the
  three modes are directly comparable, and each section records `method_used`.
- **Version & approval workflow** — drafts bump `0.1 → 0.2 → …` on every content
  change; when every authorable, non-excluded section has content **and** is
  approved, the document can be promoted to the next major version (`1.0`, `2.0`).
- **Full-document generation** — a background thread pool with live progress
  (`/api/report/generate/status`), guarded against concurrent runs.
- **Audit trail** — every generate/edit/approve/exclude/release is appended to
  `output/graphrag_audit.jsonl` via `graph_rag.audit`.

## API reference

### Sections & content
| Method | Path | Purpose |
|---|---|---|
| GET  | `/api/sections` | list all template sections (number, title, level, sources, has_content, excluded, approved, method_used) |
| GET  | `/api/sections/{number}` | one section: content, citations, verification, FILLED_BY sources, flags |
| POST | `/api/sections/{number}/generate` | author a section (`method`, `custom_prompt`, `effort`, `preview`) |
| POST | `/api/sections/{number}/accept` | persist a previewed regeneration |
| POST | `/api/sections/{number}/save` | save manual edits |
| POST | `/api/sections/{number}/approve` | approve / un-approve (`approved`) |
| POST | `/api/sections/{number}/exclude` | remove / restore a section (`excluded`) |

### Document version / approval
| Method | Path | Purpose |
|---|---|---|
| GET  | `/api/version` | current version + approval counts + state (empty/draft/approved) |
| POST | `/api/version/approve` | promote to the next major version (409 unless all approved) |

### Full-document generation & reports
| Method | Path | Purpose |
|---|---|---|
| POST | `/api/report/generate` | start a full-document run (`method`, `effort`, `workers`) |
| GET  | `/api/report/generate/status` | live progress of the run |
| GET  | `/api/report/docx` | build + download the `.docx` from cached sections |
| GET  | `/api/report/pdf` | build the `.docx`, convert to PDF (docx2pdf → Word) |

### Explainability
| Method | Path | Purpose |
|---|---|---|
| GET  | `/api/coverage` | per-section source-count heatmap data |
| GET  | `/api/graph/{number}` | section → source-nodes lineage JSON (for the graph view) |
| GET  | `/api/numbers-audit` | every material number, supported vs unsupported by a source |
| GET  | `/api/audit/{number}` | audit events for one section (newest first) |
| GET  | `/api/audit` | recent audit events (all sections) |
| GET  | `/api/source/{doc}` | full source document, section by section (for the side-by-side viewer) |
| GET  | `/api/source/{doc}/file` | download the original source `.docx` |

### Retrieval comparison
| Method | Path | Purpose |
|---|---|---|
| POST | `/api/compare` | run one query through Vector, Graph, and Hybrid side by side (`query`, `graph_mode`, `k`) |

### Static
| Method | Path | Purpose |
|---|---|---|
| GET  | `/` | serve the React app (`frontend/dist`) or `legacy.html` |

## PDF note

`/api/report/pdf` uses `docx2pdf`, which drives **Microsoft Word** via COM in a
subprocess — Windows/Word only. On a headless/AWS deployment this endpoint would
be swapped for LibreOffice headless; the route is the seam, nothing else changes.
