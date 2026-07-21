"""Load study source documents (Protocol, SAP, MOP, TFLs) into Chunks."""
from __future__ import annotations

import json
from pathlib import Path

from docx.table import Table

from ..models import Chunk
from .docx_reader import (
    iter_block_items,
    looks_like_caption,
    open_document,
    parse_table_facts,
    read_paragraph,
    read_table,
    table_to_markdown,
)

# Map a source file to a logical (doc name, doc_type). Matched by substring on
# the lowercased filename, first match wins.
SOURCE_PATTERNS: list[tuple[str, str, str]] = [
    ("protocol", "protocol", "protocol"),
    ("sap", "sap", "sap"),
    ("mop", "mop", "mop"),
    ("11.4.1", "tfl_conduct", "tfl"),
    ("11.4.2", "tfl_effectiveness", "tfl"),
    ("11.4.3", "tfl_safety", "tfl"),
    ("11.4.4", "tfl_listings", "tfl"),
    ("conduct tables", "tfl_conduct", "tfl"),
    ("effectiveness tables", "tfl_effectiveness", "tfl"),
    ("safety tables", "tfl_safety", "tfl"),
    ("listings", "tfl_listings", "tfl"),
]

HEADING_STYLES = {f"Heading {i}" for i in range(1, 6)}


def classify_source(filename: str) -> tuple[str, str] | None:
    low = filename.lower()
    for pat, name, dtype in SOURCE_PATTERNS:
        if pat in low:
            return name, dtype
    return None


def _est_tokens(text: str) -> int:
    return max(1, int(len(text.split()) * 1.3))


def _flush_text_chunk(
    doc: str, dtype: str, path: str, buf: list[str], out: list[Chunk]
) -> None:
    text = "\n".join(buf).strip()
    if len(text) >= 40:
        out.append(Chunk.make(doc, dtype, path, text, kind="text"))


def load_source_file(path: Path, target_tokens: int, overlap_tokens: int) -> list[Chunk]:
    cls = classify_source(path.name)
    if cls is None:
        return []
    doc_name, dtype = cls
    document = open_document(path)
    chunks: list[Chunk] = []

    heading_stack: list[tuple[int, str]] = []
    buf: list[str] = []
    buf_tokens = 0
    last_para = ""  # nearest preceding paragraph — a table caption candidate

    def breadcrumb() -> str:
        return " > ".join(h for _, h in heading_stack) or doc_name

    for block in iter_block_items(document):
        if isinstance(block, Table):
            # Each table is one chunk. We store STRUCTURE-AWARE "facts" (row/group/
            # column context, n/% split) so numeric cells are unambiguous and
            # retrievable, followed by the raw markdown grid for completeness. If
            # the structure parse can't make sense of the table, we fall back to
            # markdown alone — so this never loses data or fails.
            rows = read_table(block)
            md = table_to_markdown(rows)
            if md.strip():
                caption = last_para if looks_like_caption(last_para) else ""
                try:
                    facts = parse_table_facts(rows, caption)
                except Exception:
                    facts = None
                text = f"{facts}\n\n{md}" if facts else md
                title = caption or (rows[0][0] if rows and rows[0] else "")
                path_str = breadcrumb()
                if title:
                    path_str = f"{path_str} > {title[:60]}"
                chunks.append(Chunk.make(doc_name, dtype, path_str, text, kind="table"))
            continue

        para = read_paragraph(block)
        text = para.text.strip()
        if not text:
            continue
        last_para = text

        if para.style in HEADING_STYLES:
            # close current text chunk at heading boundary
            _flush_text_chunk(doc_name, dtype, breadcrumb(), buf, chunks)
            buf, buf_tokens = [], 0
            level = int(para.style.split()[-1])
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, text))
            continue

        buf.append(text)
        buf_tokens += _est_tokens(text)
        if buf_tokens >= target_tokens:
            _flush_text_chunk(doc_name, dtype, breadcrumb(), buf, chunks)
            # keep a small overlap tail
            tail: list[str] = []
            tail_tokens = 0
            for seg in reversed(buf):
                tail_tokens += _est_tokens(seg)
                tail.insert(0, seg)
                if tail_tokens >= overlap_tokens:
                    break
            buf, buf_tokens = tail, tail_tokens

    _flush_text_chunk(doc_name, dtype, breadcrumb(), buf, chunks)
    return chunks


def load_all_sources(study_dir: Path, target_tokens: int, overlap_tokens: int) -> list[Chunk]:
    chunks: list[Chunk] = []
    for path in sorted(study_dir.glob("*.docx")):
        chunks.extend(load_source_file(path, target_tokens, overlap_tokens))
    return chunks


def save_chunks(chunks: list[Chunk], path: Path) -> None:
    data = [c.__dict__ for c in chunks]
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def load_chunks(path: Path) -> list[Chunk]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [Chunk(**d) for d in data]


def _est_tokens_public(text: str) -> int:
    return _est_tokens(text)


def write_chunk_preview(chunks: list[Chunk], path: Path) -> None:
    """Human-readable dump of every chunk exactly as it will be embedded/stored.

    Written before the vector build so the chunking can be inspected first."""
    from collections import Counter

    by_doc = Counter((c.doc, c.kind) for c in chunks)
    lines: list[str] = ["# Chunk preview (pre-vectorization)", ""]
    lines.append(f"Total chunks: **{len(chunks)}**")
    lines.append("")
    lines.append("| doc | kind | count |")
    lines.append("| --- | --- | --- |")
    for (doc, kind), n in sorted(by_doc.items()):
        lines.append(f"| {doc} | {kind} | {n} |")
    lines.append("")
    lines.append("---")
    lines.append("")
    for i, c in enumerate(chunks, 1):
        lines.append(
            f"## [{i}] {c.doc} · {c.kind} · ~{_est_tokens(c.text)} tok · id={c.id}"
        )
        lines.append(f"**path:** {c.section_path}")
        if c.entities:
            lines.append(f"**entities:** {', '.join(c.entities[:20])}")
        lines.append("")
        lines.append(c.text)
        lines.append("")
        lines.append("---")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
