# CSR / CIR Generator

Template-driven generation of a **Clinical Investigation Report** (a.k.a. Clinical
Study Report) for a medical device study, from the study's own source documents,
with **source traceability** and **template-structure preservation**.

- **Template-driven**: the `Device CSR Template - Single File.docx` defines the
  section skeleton and the ISO 14155:2020 / ICH E3 authoring rules (encoded as
  colored guidance text). The generator preserves that structure exactly and
  replaces the colored guidance with authored, grounded prose.
- **Three RAG strategies, compared**: the same grounded-generation core is fed by
  three interchangeable retrievers so they can be judged head-to-head —
  **Vector** (LanceDB dense + full-text, RRF), **Graph** (Neo4j knowledge graph +
  `FILLED_BY` links + text-to-Cypher), and **Hybrid** (vector + FTS + Neo4j
  entity-graph expansion, consensus-fused). The goal: an endpoint *defined* in the
  SAP, *described* in the Protocol, and *measured* in a TFL table is pulled
  together for one section.
- **Grounded + verified**: every section is authored only from retrieved source
  excerpts, with `[S#]` citations. A verifier checks that material numbers in
  the prose appear verbatim in the sources and flags any that don't.
- **Traceable output**: the final `.docx` carries Word comments citing the
  sources per generated paragraph, plus a `traceability.md` / `.json` report.
- **Review UI**: a React + FastAPI app to generate, review, compare retrieval
  strategies, audit every number, and drive a draft → approved-`1.0` workflow.

## Architecture

The repo is five top-level components, each with its own README:

```
vector_rag/    # Vector RAG + the shared foundation (models, ingestion, embeddings,
               #   generation, .docx assembly) + the `csr` CLI        -> vector_rag/README.md
graph_rag/     # Graph RAG: Neo4j knowledge graph, FILLED_BY linking,
               #   text-to-Cypher, the `graph_rag.demo` CLI           -> graph_rag/README.md
hybrid_rag/    # Hybrid RAG: vector + FTS + Neo4j entity-graph expansion, RRF fusion
               #                                                       -> hybrid_rag/README.md
backend/       # FastAPI web layer: API, generation orchestration, version/approval
               #                                                       -> backend/README.md
frontend/      # React (Vite) review UI                               -> frontend/README.md
```

All three retrievers emit the same `RetrievedChunk` type and feed **one** shared
generation core (`graph_rag.generate.author_from_retrieved`), so only *retrieval*
differs between strategies — which keeps the comparison fair.

## Prerequisites

- Python ≥ 3.10, [`uv`](https://docs.astral.sh/uv/) for env/deps.
- AWS credentials in the **default profile** with **Amazon Bedrock** access in
  `us-east-1` to:
  - `amazon.titan-embed-text-v2:0` (embeddings) — already enabled.
  - a Claude model. **This account must complete the Bedrock "Anthropic use case
    details" form** before Claude calls succeed (Sonnet 4.6 / 4.5 otherwise
    return `404 use case details not submitted`). Do this in the AWS console:
    **Bedrock → Model access → Anthropic → submit use-case details**, then wait
    ~15 min. Titan embeddings and the entire index build work without it.

Default generation model is `us.anthropic.claude-sonnet-4-6` (highest Claude tier
enabled on this account). Override with `--model` or `CSR_GEN_MODEL`.

## Usage

```bash
uv sync                       # install deps (+ the `csr` console script)

# 1. Build the hybrid index from study/*.docx (embeddings + graph + LanceDB)
uv run csr ingest

# 2. Author sections (grounded generation). Options:
uv run csr generate                          # all authorable sections (serial)
uv run csr generate --workers 8              # author 8 sections in parallel (much faster)
uv run csr generate --effort medium          # low|medium|high|max; lower = faster
uv run csr generate --limit 5                # first 5 (quick trial)
uv run csr generate --only 5.1 6.3.4.1       # specific sections

# Fast full run (recommended): parallel + medium effort, unbuffered progress
uv run python -u -m vector_rag.cli generate --workers 8 --effort medium

# 3. Assemble the .docx + traceability (also runs automatically after generate)
uv run csr assemble

# Everything at once:
uv run csr run

# See the parsed template skeleton and which sections get authored:
uv run csr inspect
```

Outputs land in `output/`:
- `Clinical_Investigation_Report.docx` — template structure preserved, authored
  content in place of guidance, Word comments citing sources.
- `traceability.md` / `traceability.json` — per-section citations + verification.

Intermediate index/cache lives in `.csr_work/` (LanceDB, graph, chunk cache).

## Review UI (generate · compare · approve)

A React + FastAPI app for reviewing and driving generation with all three RAG
strategies. Requires a running **Neo4j** (see `graph_rag/README.md`) plus the
LanceDB index (`uv run csr ingest`).

```bash
# one-time: build the graph + template links (Neo4j)
uv run python -m graph_rag.demo build
uv run python -m graph_rag.demo template

# start the web app  ->  http://localhost:8000
uv run python -m backend.server
```

For UI development with hot reload, run the Vite dev server alongside it
(`cd frontend && npm run dev`, port 5173, proxies `/api` to :8000). Full API and
component details are in `backend/README.md` and `frontend/README.md`.

The UI covers: per-section and full-document generation (pick Vector / Graph /
Hybrid), reviewable regeneration, source traceability with green-highlighted
quotes against the original documents, a document-wide numbers audit, an
interactive source-lineage graph, a three-way retrieval comparison, an
append-only audit trail, and a draft → approved-`1.0` version workflow.

## How template structure is preserved

The template encodes rules by font color (`config.GUIDANCE_COLORS`):
red `<…>` instructions, blue `[optional]`, green ISO-requirement lists, orange
`EU MDR 2017` labels, purple notes. Those runs are **guidance** — the parser
feeds them to the model as "what to write" and the assembler **deletes** them
from authored sections, replacing them with grounded prose. Black runs are
**boilerplate** and are kept verbatim. Headings, section order, and template
tables are never moved. Administrative sections (title page, signature page,
annex lists) are left untouched so their instructions stay visible to a reviewer.

## Results sections, endpoints, and the style reference

- **Endpoint placeholders** (6.2.1–6.2.3, 6.3.1–6.3.3) carry no guidance of their
  own in the template — the parent Results section holds it, and the author is
  meant to rename each per the actual endpoint. The pipeline authors them anyway:
  it inherits the parent's guidance, tags the endpoint class (primary/secondary/
  exploratory), and instructs the model to identify the real endpoint by name.
- **Guaranteed result tables**: results sections *reserve* slots for the matching
  TFL data tables (`generation/prompts.py::_GUARANTEE`) so the numeric tables are
  never crowded out by definitional prose. Tables are also embedded with their
  breadcrumb+headers so they're findable at all (a grid of numbers embeds weakly
  on its own).
- **Style reference (few-shot)**: if a prior human-authored CSR is present
  (`config.style_reference`), each section is shown the *same section* from it as
  a **masked exemplar** — every number, ID, and initial is replaced with `«…»`
  and subject-narrative sections are dropped — so the model mirrors register and
  structure while taking **zero facts or personal data** from it. Disable with
  `--no-style-ref`.

## Notes / next steps

- Retrieval is routed per section (`generation/prompts.py::doc_types_for`) — e.g.
  effectiveness results → TFL effectiveness + SAP + Protocol.
- The verifier flags numbers not found verbatim in sources; those sections are
  marked ⚠️ in `traceability.md` and in the Word comment for reviewer attention.
- Template tables (objective/endpoint tables, etc.) are currently preserved but
  not auto-filled — a good next increment is data-driven table population from
  the TFL chunks.
