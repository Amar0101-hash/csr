# CSR / CIR Generator

Template-driven generation of a **Clinical Investigation Report** (a.k.a. Clinical
Study Report) for a medical device study, from the study's own source documents,
with **source traceability** and **template-structure preservation**.

- **Template-driven**: the `Device CSR Template - Single File.docx` defines the
  section skeleton and the ISO 14155:2020 / ICH E3 authoring rules (encoded as
  colored guidance text). The generator preserves that structure exactly and
  replaces the colored guidance with authored, grounded prose.
- **Hybrid RAG**: LanceDB vector search + full-text search (RRF fusion) plus a
  `networkx` knowledge graph over clinical entities (analysis sets, endpoints,
  visits, AE terms…) that expands retrieval across documents — so an endpoint
  *defined* in the SAP, *described* in the Protocol, and *measured* in a TFL
  table is pulled together for one section.
- **Grounded + verified**: every section is authored only from retrieved source
  excerpts, with `[S#]` citations. A verifier checks that material numbers in
  the prose appear verbatim in the sources and flags any that don't.
- **Traceable output**: the final `.docx` carries Word comments citing the
  sources per generated paragraph, plus a `traceability.md` / `.json` report.

## Architecture

```
src/csr/
  config.py                 # paths, Bedrock model ids, retrieval knobs, color map
  models.py                 # Chunk, SectionSpec, GeneratedSection, Citation
  ingestion/
    docx_reader.py          # ordered block iteration, run colors, tables->markdown
    template_parser.py      # color-aware template -> SectionSpec tree
    sources.py              # Protocol/SAP/MOP/TFL -> heading-aware Chunks
  knowledge/
    embeddings.py           # Amazon Titan v2 text embeddings (Bedrock)
    vector_store.py         # LanceDB vector + FTS
    graph_store.py          # networkx entity graph (deterministic extraction)
    retriever.py            # vector + FTS (RRF) + graph expansion
  generation/
    llm.py                  # Claude on Bedrock (Anthropic SDK) + JSON parsing
    prompts.py              # grounding system prompt, per-section routing
    writer.py               # retrieve -> prompt -> generate -> verify
    verify.py               # numeric-grounding + citation checks
  assembly/
    docx_builder.py         # fill template in place, keep structure, add comments
    traceability.py         # traceability.json + traceability.md
  pipeline.py               # ingest / generate / assemble / run
  cli.py                    # `csr` command
```

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
uv run python -u -m csr.cli generate --workers 8 --effort medium

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
