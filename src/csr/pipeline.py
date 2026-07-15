"""End-to-end orchestration: ingest -> index -> generate -> assemble."""
from __future__ import annotations

import json
from pathlib import Path

from .assembly.docx_builder import build_report
from .assembly.traceability import write_traceability
from .config import Settings
from .generation.llm import ClaudeClient
from .generation.writer import SectionWriter
from .ingestion.sources import (
    load_all_sources,
    load_chunks,
    save_chunks,
    write_chunk_preview,
)
from .ingestion.template_parser import parse_template
from .knowledge.embeddings import TitanEmbedder
from .knowledge.graph_store import GraphStore
from .knowledge.retriever import HybridRetriever
from .knowledge.vector_store import VectorStore


def _make_graph(settings: Settings):
    """Pick the knowledge-graph backend: persistent Neo4j or in-memory networkx."""
    if settings.graph_backend.lower() == "neo4j":
        from .knowledge.neo4j_store import Neo4jGraphStore

        return Neo4jGraphStore(settings)
    return GraphStore()
from .models import Chunk, GeneratedSection, SectionSpec


def ingest(settings: Settings, verbose: bool = True) -> list[Chunk]:
    """Read sources, embed, build vector store + knowledge graph."""
    settings.ensure_dirs()
    chunks = load_all_sources(
        settings.study_dir, settings.chunk_target_tokens, settings.chunk_overlap_tokens
    )
    if verbose:
        print(f"[ingest] loaded {len(chunks)} chunks from {settings.study_dir}")

    graph = _make_graph(settings)
    graph.build(chunks)  # also backfills chunk.entities
    graph.save(settings.graph_path)
    if verbose:
        nodes, edges = graph.stats()
        print(f"[ingest] graph ({settings.graph_backend}): {nodes} nodes, {edges} edges")
    graph.close()

    # Persist chunks (JSON + readable preview) BEFORE vectorization so the
    # chunking can be inspected before anything is embedded/indexed.
    save_chunks(chunks, settings.sources_cache)
    write_chunk_preview(chunks, settings.chunk_preview)
    if verbose:
        print(f"[ingest] wrote {len(chunks)} chunks -> {settings.sources_cache.name}, "
              f"{settings.chunk_preview.name} (pre-vectorization)")

    embedder = TitanEmbedder(settings.embed_model, settings.aws_region, settings.embed_dim)
    if verbose:
        print(f"[ingest] embedding {len(chunks)} chunks with {settings.embed_model} ...")
    # Embed breadcrumb + text so numeric tables carry semantic context (their raw
    # grids embed weakly on their own). Stored chunk.text stays raw for the LLM.
    embed_texts = [f"{c.doc} | {c.section_path}\n{c.text}" for c in chunks]
    vectors = embedder.embed_batch(embed_texts, progress=verbose)

    store = VectorStore(settings.lancedb_uri, settings.lancedb_table, settings.embed_dim)
    store.build(chunks, vectors)
    if verbose:
        print(f"[ingest] indexed into LanceDB at {settings.lancedb_uri}")
    return chunks


def _load_retriever(settings: Settings) -> HybridRetriever:
    chunks = load_chunks(settings.sources_cache)
    by_id = {c.id: c for c in chunks}
    store = VectorStore(settings.lancedb_uri, settings.lancedb_table, settings.embed_dim)
    graph = _make_graph(settings)
    graph.load(settings.graph_path)  # no-op for Neo4j (already connected)
    embedder = TitanEmbedder(settings.embed_model, settings.aws_region, settings.embed_dim)
    return HybridRetriever(settings, store, graph, embedder, by_id)


def generate(
    settings: Settings,
    only: list[str] | None = None,
    limit: int | None = None,
    workers: int = 1,
    verbose: bool = True,
) -> tuple[list[SectionSpec], dict[str, GeneratedSection]]:
    """Author sections. `only` filters by section key/number; `limit` caps count.

    `workers` > 1 authors sections concurrently (each section is one independent
    Claude call, so a thread pool cuts wall-clock roughly linearly until Bedrock
    rate limits bite)."""
    settings.ensure_dirs()
    if not settings.sources_cache.exists():
        raise FileNotFoundError("No index found. Run `ingest` first.")

    sections = parse_template(settings.template_path)
    (settings.work_dir / "template.json").write_text(
        json.dumps([_section_dict(s) for s in sections], ensure_ascii=False, indent=1),
        encoding="utf-8",
    )

    retriever = _load_retriever(settings)
    client = ClaudeClient(settings)
    style_ref = None
    if settings.use_style_reference and settings.style_reference.exists():
        from .generation.style_ref import StyleReference

        style_ref = StyleReference(settings.style_reference)
        if verbose:
            print(f"[generate] style reference loaded: {len(style_ref.by_number)} masked exemplars")
    writer = SectionWriter(client, retriever, style_ref=style_ref)

    _inherit_guidance(sections)
    from .generation.prompts import FORM_FILL_KEYS

    targets = [s for s in sections if s.generate or s.key in FORM_FILL_KEYS]
    if only:
        wanted = set(only)
        targets = [s for s in targets if s.key in wanted or s.number in wanted]
    if limit:
        targets = targets[:limit]

    generated: dict[str, GeneratedSection] = {}
    total = len(targets)

    def _report(i: int, section: SectionSpec, gen: GeneratedSection) -> None:
        if not verbose:
            return
        v = gen.verification or {}
        flag = "" if v.get("grounded", True) else "  <-- REVIEW numbers"
        note = f" [{gen.notes}]" if gen.notes else ""
        print(
            f"[generate] ({i}/{total}) {section.heading_text()}\n"
            f"    -> {len(gen.paragraphs)} paras, {len(gen.citations)} citations{flag}{note}",
            flush=True,
        )

    if workers <= 1:
        for i, section in enumerate(targets, 1):
            gen = writer.write(section)
            generated[section.key] = gen
            _report(i, section, gen)
    else:
        import os
        from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutTimeout

        if verbose:
            print(f"[generate] authoring {total} sections with {workers} workers "
                  f"(template order; Ctrl+C to stop & save partial)", flush=True)
        pool = ThreadPoolExecutor(max_workers=workers)
        # Submit in template order (workers pick up 1, 2, 3, ... as they free up);
        # collect in that same order so progress reads 1 -> 11. A heartbeat prints
        # while waiting on a slow section so it never looks frozen.
        futures = [(s, pool.submit(writer.write, s)) for s in targets]
        try:
            for i, (section, fut) in enumerate(futures, 1):
                waited = 0
                while True:
                    try:
                        gen = fut.result(timeout=20)
                        break
                    except FutTimeout:
                        waited += 20
                        if verbose:
                            print(f"[generate]   …still authoring {section.number} "
                                  f"{section.title[:34]} ({len(generated)}/{total} done, "
                                  f"{waited}s elapsed)", flush=True)
                generated[section.key] = gen
                _report(i, section, gen)
            pool.shutdown(wait=True)
        except KeyboardInterrupt:
            print("\n[generate] interrupt — cancelling pending sections and saving "
                  "partial results...", flush=True)
            for _, f in futures:
                f.cancel()
            pool.shutdown(wait=False, cancel_futures=True)
            _save_generated(settings, generated)
            os._exit(130)

    _save_generated(settings, generated)
    from .assembly.traceability import write_generated_preview

    write_generated_preview(sections, generated, settings.generated_preview)
    if verbose:
        ok = sum(1 for g in generated.values() if g.paragraphs or g.table_fills)
        print(f"[generate] authored {ok}/{len(generated)}; "
              f"wrote {settings.generated_preview.name} (+ generated.json)")
    return sections, generated


def assemble(
    settings: Settings,
    sections: list[SectionSpec] | None = None,
    generated: dict[str, GeneratedSection] | None = None,
    verbose: bool = True,
) -> Path:
    settings.ensure_dirs()
    if sections is None:
        sections = parse_template(settings.template_path)
    if generated is None:
        generated = _load_generated(settings)

    out_docx = settings.output_dir / "Clinical_Investigation_Report.docx"
    stats = build_report(settings.template_path, sections, generated, out_docx)
    written = Path(stats.get("output_path", out_docx))
    if verbose:
        print(f"[assemble] {stats}")

    summary = write_traceability(
        sections,
        generated,
        settings.output_dir / "traceability.json",
        settings.output_dir / "traceability.md",
    )
    if verbose:
        print(f"[assemble] traceability: {summary['sections_grounded']}/{summary['sections_generated']} grounded")
        print(f"[assemble] wrote {written}")
    return written


def run_all(
    settings: Settings, limit: int | None = None, workers: int = 1, verbose: bool = True
) -> Path:
    ingest(settings, verbose=verbose)
    sections, generated = generate(settings, limit=limit, workers=workers, verbose=verbose)
    return assemble(settings, sections, generated, verbose=verbose)


def _inherit_guidance(sections: list[SectionSpec]) -> None:
    """Endpoint result placeholders (6.2.1, 6.3.1, ...) carry no guidance of
    their own — the parent section holds it. Give each such section its nearest
    numbered ancestor's guidance so the writer has instructions to work from."""
    by_number = {s.number: s for s in sections if s.number}
    for s in sections:
        if not s.generate or s.guidance.strip() or not s.number:
            continue
        parts = s.number.split(".")
        while len(parts) > 1:
            parts = parts[:-1]
            anc = by_number.get(".".join(parts))
            if anc and anc.guidance.strip():
                s.guidance = anc.guidance
                s.guidance_inherited = True
                break


# ---- persistence helpers ----

def _section_dict(s: SectionSpec) -> dict:
    return {
        "key": s.key, "number": s.number, "title": s.title, "level": s.level,
        "generate": s.generate, "guidance_len": len(s.guidance),
        "iso_requirements": s.iso_requirements,
    }


def _save_generated(settings: Settings, generated: dict[str, GeneratedSection]) -> None:
    data = {}
    for k, g in generated.items():
        data[k] = {
            "key": g.key, "title": g.title, "paragraphs": g.paragraphs,
            "citations": [c.__dict__ for c in g.citations],
            "used_chunk_ids": g.used_chunk_ids, "notes": g.notes,
            "verification": g.verification,
            "heading_override": g.heading_override,
            "table_fills": [tf.__dict__ for tf in g.table_fills],
        }
    (settings.work_dir / "generated.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8"
    )


def _load_generated(settings: Settings) -> dict[str, GeneratedSection]:
    from .models import Citation, TableFill

    path = settings.work_dir / "generated.json"
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, GeneratedSection] = {}
    for k, d in raw.items():
        out[k] = GeneratedSection(
            key=d["key"], title=d["title"], paragraphs=d["paragraphs"],
            citations=[Citation(**c) for c in d.get("citations", [])],
            used_chunk_ids=d.get("used_chunk_ids", []),
            notes=d.get("notes"), verification=d.get("verification", {}),
            heading_override=d.get("heading_override"),
            table_fills=[TableFill(**tf) for tf in d.get("table_fills", [])],
        )
    return out
