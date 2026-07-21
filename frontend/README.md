# frontend

The **React (Vite) single-page app** for the CSR RAG Explorer — review, generate,
compare, and approve CSR sections with full source traceability. It talks to the
`backend` FastAPI server over `/api`.

## Run

```bash
# Development (hot reload) — Vite on :5173, proxies /api to the backend on :8000
cd frontend
npm install        # first time only
npm run dev

# Production build — emits dist/, which `backend` serves directly
npm run build
```

The backend serves `frontend/dist` at `http://localhost:8000/`, so after
`npm run build` the whole app is available from the single backend process. Use
`npm run dev` only while editing the UI.

Stack: **React 18 + Vite 5**, no component library — all styling is in
`src/styles.css` (a light blue/white theme, theme variables at `:root`).

## Layout

```
frontend/
  index.html
  vite.config.js         # dev server :5173, proxies /api -> http://localhost:8000
  src/
    main.jsx             # React entry
    App.jsx              # header (version badge, method selector, generate/download,
                         #   approve), tab switching, full-generation polling
    api.js               # thin fetch client for every backend endpoint; DOC_COLORS
    styles.css           # the entire theme + component styles
    components/
      SectionList.jsx    # left rail: sections in natural order, content/approval marks,
                         #   remove (✕) / add-back (↩) for non-applicable sections
      SectionDetail.jsx  # a section: rendered content + Edit toggle, per-section method
                         #   selector, Regenerate (previewed), Approve, citations,
                         #   lineage graph, FILLED_BY sources, audit trail
      RenderedContent.jsx# clean paragraph + markdown-table rendering of generated content
      SourceViewer.jsx   # side-by-side modal: generated section vs full source doc,
                         #   cited quotes highlighted green; "Original file" download
      SourcePanel.jsx    # FILLED_BY source list with previews
      LineageGraph.jsx   # interactive SVG: section <- source nodes, click to open source
      CoverageHeatmap.jsx# section coverage grid (source counts / gaps)
      NumbersAudit.jsx   # document-wide numeric fact check (green = supported, red = not)
      Compare.jsx        # three-column Vector / Graph / Hybrid retrieval comparison
```

## Tabs & features

- **Sections** — the main review surface. Pick a section on the left; on the right
  see rendered content, regenerate it (as a reviewable proposal, per RAG method),
  edit, approve, and inspect citations, source lineage, and the audit trail.
- **Coverage heatmap** — which sections have source links vs coverage gaps.
- **Numbers audit** — every material number checked against its sources; problem
  sections float to the top.
- **Compare RAG** — run one query through Vector, Graph, and Hybrid side by side,
  with colour-coded provenance chips and a consensus count for the hybrid.

Header controls: document **version badge** (empty/draft/approved), **RAG method
selector** (Hybrid / Vector / Graph — governs generation), **⚡ Generate full
document** (background run with a progress bar), **⬇ Report .docx / PDF**, and
**✓ Approve document → vN.0** (appears once every section is approved).

### Generation & versioning flow

Generate (full doc or a single section) → review each section's content,
citations, unsupported-number flags, and source lineage → fix individually
(reviewable regeneration or manual edit) → **Approve** each → once all are
approved, **Approve document** promotes it from a `0.x` draft to an approved
`1.0`. Any later change drops it back to a draft (`1.1`, `1.2`, …).

## API client

`src/api.js` wraps every backend route (see `backend/README.md`). Notable calls:
`sections`, `section`, `generate(n, prompt, preview, method)`,
`generateFull(effort, method)`, `approveSection`, `approveDoc`, `setExcluded`,
`numbersAudit`, `source`, `audit`, `compare`. `DOC_COLORS` maps each source doc
(protocol, sap, mop, tfl_*) to a consistent colour used across the UI.
