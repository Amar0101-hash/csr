





























































































































































































































































































































































































































































# vector_rag

The **Vector RAG** package and the **shared foundation** for the whole project.
It owns the end-to-end CSR/CIR pipeline (ingest → index → generate → assemble)
using **LanceDB dense-vector + full-text retrieval**, and it exports the models,
ingestion, embeddings, generation, and document-assembly code that `graph_rag`,
`hybrid_rag`, and `backend` all reuse.

> Naming: this package was formerly `src/csr`. The installed console script is
> still `csr` (see `pyproject.toml → [project.scripts]`).

## What it does

1. **Ingest** the study's source `.docx` files (Protocol, SAP, MOP, TFL tables)
   into heading-aware `Chunk`s, embed them with **Amazon Titan v2** (Bedrock),
   and index into **LanceDB** (vector + native full-text index).
2. **Generate** each template section with grounded, cited prose from retrieved
   source excerpts, authored by **Claude on Bedrock**.
3. **Assemble** the final `.docx` — template structure preserved, colored guidance
   replaced by authored content, Word comments citing sources — plus a
   `traceability.md` / `.json` report.

## Layout

```
vector_rag/
  config.py            # Settings: paths, Bedrock model ids, retrieval knobs, GUIDANCE_COLORS
  models.py            # Chunk (content-hash id), SectionSpec, GeneratedSection, Citation, TableFill
  pipeline.py          # ingest / generate / assemble / run_all orchestration
  cli.py               # the `csr` command
  ingestion/
    docx_reader.py     # ordered block iteration, run colors, tables -> markdown
    template_parser.py # color-aware template .docx -> SectionSpec tree (parse_template)
    sources.py         # Protocol/SAP/MOP/TFL -> heading-aware Chunks (load_all_sources, classify_source)
  knowledge/
    embeddings.py      # TitanEmbedder — Amazon Titan v2 text embeddings (Bedrock)
    vector_store.py    # VectorStore — LanceDB vector_search + fts_search (Hit)
    retriever.py       # VectorRetriever + RetrievedChunk — vector + FTS fused with RRF
    graph_store.py     # GraphStore + extract_entities — in-memory NetworkX entity graph
                       #   (SET ASIDE: not used by the pipeline; kept for the future AWS
                       #    NetworkX plan. hybrid_rag currently uses Neo4j instead.)
  generation/
    llm.py             # ClaudeClient — Claude on Bedrock (Anthropic SDK) + JSON parsing
    prompts.py         # build_query, build_user_prompt, doc_types_for, guaranteed_tables_for,
                       #   SYSTEM_WRITER, FORM_FILL_KEYS, TABLE_ONLY_KEYS, format_excerpts
    writer.py          # SectionWriter — retrieve -> prompt -> generate -> verify
    table_fill.py      # FormFiller — fill structured template tables (Title Page, Summary)
    verify.py          # verify_section, _numbers, _is_material — numeric-grounding checks
    style_ref.py       # StyleReference — masked human-CSR few-shot exemplar
  assembly/
    docx_builder.py    # build_report — fill template in place, keep structure, add comments,
                       #   exclude_keys to drop non-applicable sections
    traceability.py    # write_traceability, write_generated_preview
```

## Retrieval (VectorRetriever)

`knowledge/retriever.py` fuses two signals with **Reciprocal Rank Fusion (RRF)**:

- **dense vector** search over Titan embeddings (`top_k_vector`, default 12)
- **full-text** search (LanceDB native FTS) (`top_k_fts`, default 8)

Plus **guaranteed tables**: results sections reserve slots for the best-matching
TFL data tables so grids of numbers (which embed weakly) are never crowded out by
definitional prose. Output is `list[RetrievedChunk]` (`chunk`, `score`,
`provenance`) — the same type `graph_rag` and `hybrid_rag` produce, so all three
feed the identical generation core.

## The `csr` CLI

```bash
uv sync                       # install deps + the `csr` console script

uv run csr ingest             # read study/*.docx, embed, build the LanceDB index
uv run csr generate           # author all sections (serial)
uv run csr generate --workers 8 --effort medium   # parallel, faster
uv run csr generate --limit 5                      # first 5 (quick trial)
uv run csr generate --only 5.1 6.3.4.1             # specific sections
uv run csr assemble           # build .docx + traceability from cached generation
uv run csr run                # ingest + generate + assemble
uv run csr inspect            # print the parsed template skeleton

# common flags (all subcommands): --study-dir --template --model --region --effort
# generate/run also take: --workers, --limit; generate: --only, --no-style-ref
```

Outputs land in `output/` (`Clinical_Investigation_Report.docx`,
`traceability.md` / `.json`); the index and chunk cache live in `.csr_work/`
(LanceDB at `.csr_work/lancedb`, chunks at `.csr_work/sources.json`).

## Configuration (`config.py`)

All tunables live on `Settings` and can be overridden via `CSR_*` env vars:

| Setting | Default | Env |
|---|---|---|
| `aws_region` | `us-east-1` | `CSR_AWS_REGION` |
| `gen_model` | `us.anthropic.claude-sonnet-4-6` | `CSR_GEN_MODEL` |
| `embed_model` | `amazon.titan-embed-text-v2:0` | `CSR_EMBED_MODEL` |
| `embed_dim` | `1024` | — |
| `effort` | `high` | `CSR_EFFORT` |
| `top_k_vector` / `top_k_fts` / `top_k_final` | `12 / 8 / 10` | — |
| `chunk_target_tokens` / `chunk_overlap_tokens` | `550 / 80` | — |
| `lancedb_table` | `csr_chunks` | — |

> Bedrock note: this account can invoke **Sonnet 4.6/4.5 + Titan v2** only, and
> Claude calls require the Bedrock "Anthropic use-case details" form to be
> submitted once. Titan embeddings and the full index build work without it.

## Template-structure preservation

The template encodes authoring rules by **font color** (`config.GUIDANCE_COLORS`):
red `<…>` instructions, blue `[optional]`, green ISO-requirement lists, orange
`EU MDR 2017` labels, purple notes. Those runs are **guidance** — fed to the model
as "what to write" and **deleted** from authored sections. Black runs are
**boilerplate**, kept verbatim. Headings, section order, and template tables never
move. See the repo-root `README.md` for the full explanation.

## Chunk ids are content hashes

`models.Chunk` ids are `sha1(doc || section_path || text[:200] || kind)[:16]` —
deterministic. This is why the same chunk has the **same id** in LanceDB and in
the Neo4j graph, which lets `hybrid_rag` map vector seeds straight into the graph.
