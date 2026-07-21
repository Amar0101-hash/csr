"""Author a single CSR section: retrieve -> prompt -> generate -> verify.

Two modes may apply to one section:
  - prose  : grounded paragraphs (the default for narrative sections)
  - form   : fill the section's structured template table (Title Page, Summary
             synopsis, objectives) via FormFiller

Some sections (Title Page, Summary) are table-only — no loose prose.
"""
from __future__ import annotations

from ..knowledge.retriever import VectorRetriever, RetrievedChunk
from ..models import Citation, GeneratedSection, SectionSpec
from .llm import ClaudeClient
from .prompts import (
    build_query,
    build_user_prompt,
    doc_types_for,
    FORM_FILL_KEYS,
    guaranteed_tables_for,
    SYSTEM_WRITER,
    TABLE_ONLY_KEYS,
)
from .style_ref import StyleReference
from .table_fill import FormFiller
from .verify import verify_section


class SectionWriter:
    def __init__(self, client: ClaudeClient, retriever: VectorRetriever,
                 style_ref: StyleReference | None = None):
        self.client = client
        self.retriever = retriever
        self.style_ref = style_ref
        self.filler = FormFiller(client, retriever, style_ref=style_ref)

    def write(self, section: SectionSpec) -> GeneratedSection:
        doc_types = doc_types_for(section)
        do_prose = section.generate and section.key not in TABLE_ONLY_KEYS
        do_forms = section.key in FORM_FILL_KEYS

        gen = GeneratedSection(key=section.key, title=section.title, paragraphs=[],
                               verification={"grounded": True, "unsupported_count": 0})

        if do_prose:
            self._write_prose(section, doc_types, gen)

        if do_forms:
            try:
                gen.table_fills = self.filler.fill_section(section, doc_types)
            except Exception as e:
                gen.notes = (gen.notes or "") + f" [table-fill error: {e}]"

        if not gen.paragraphs and not gen.table_fills and not gen.notes:
            gen.notes = "No content generated."
        return gen

    def _write_prose(self, section: SectionSpec, doc_types, gen: GeneratedSection) -> None:
        query = build_query(section)
        guarantee = guaranteed_tables_for(section)
        retrieved: list[RetrievedChunk] = self.retriever.retrieve(
            query, doc_types=doc_types, guarantee_tables=guarantee
        )
        if not retrieved:
            gen.notes = "No source excerpts retrieved for this section."
            return

        exemplar = None
        if self.style_ref is not None:
            exemplar = self.style_ref.exemplar_for(section.number, section.title)
        user, label_map = build_user_prompt(section, retrieved, style_exemplar=exemplar)
        try:
            data = self.client.complete_json(SYSTEM_WRITER, user)
        except Exception as e:
            gen.notes = f"Generation error: {type(e).__name__}: {e}"
            gen.verification = {"grounded": False, "error": str(e)}
            return

        paragraphs = [p.strip() for p in data.get("paragraphs", []) if str(p).strip()]
        raw_citations = data.get("citations", []) or []
        insufficient = bool(data.get("insufficient_data", False))
        notes = data.get("notes") or None
        heading = (data.get("heading") or "").strip()
        if heading and section.class_hint:
            gen.heading_override = heading

        gen.verification = verify_section(paragraphs, raw_citations, retrieved, label_map)

        citations: list[Citation] = []
        used_ids: set[str] = set()
        for c in raw_citations:
            sid = c.get("source_id")
            cid = label_map.get(sid)
            if not cid:
                continue
            used_ids.add(cid)
            ch = next((r.chunk for r in retrieved if r.chunk.id == cid), None)
            citations.append(
                Citation(
                    chunk_id=cid,
                    doc=ch.doc if ch else "?",
                    section_path=ch.section_path if ch else "",
                    quote=str(c.get("quote", ""))[:400],
                )
            )

        if insufficient and not paragraphs:
            notes = notes or "Model reported insufficient source data for this section."

        gen.paragraphs = paragraphs
        gen.citations = citations
        gen.used_chunk_ids = sorted(used_ids)
        gen.notes = notes
