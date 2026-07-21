"""Canonical per-section document model — the robust boundary between generation
and rendering.

Generation produces loose paragraph strings (some of which contain markdown
tables or bullet lists). Rendering to .docx (or PDF, HTML, eval) should NOT
re-guess structure ad hoc. This module parses those strings ONCE into a small set
of typed blocks, and defines the canonical JSON shape a section serializes to:

    {
      "number": "5.2", "key": "5.2", "title": "...",
      "method": "hybrid", "heading_override": null,
      "blocks": [
        {"type": "paragraph", "text": "..."},
        {"type": "table", "rows": [["h1","h2"], ["a","b"]]},   # rows[0] = header
        {"type": "list", "ordered": false, "items": ["...", "..."]}
      ],
      "table_fills": [...], "citations": [...], "verification": {...},
      "notes": null, "used_chunk_ids": [...]
    }

The block model has no docx dependency, so it is unit-testable without Word or
Bedrock. The docx renderer (assembly/docx_builder.render_blocks) consumes these
blocks deterministically — a switch on `type`, never a re-parse.
"""
from __future__ import annotations

import re
from typing import Any

# a markdown separator row like |---|:--:|
_SEP_RE = re.compile(r"^\|?[\s:|-]+\|?$")
# a list item: "- x", "* x", "• x", "1. x", "2) x"
_LIST_RE = re.compile(r"^\s*([-*•]\s+|\d+[.)]\s+)(.*)$")


def paragraph(text: str) -> dict:
    return {"type": "paragraph", "text": text}


def table(rows: list[list[str]]) -> dict:
    return {"type": "table", "rows": rows}


def bullet_list(items: list[str], ordered: bool = False) -> dict:
    return {"type": "list", "ordered": ordered, "items": items}


def _is_table_line(line: str) -> bool:
    s = line.strip()
    return s.startswith("|") and s.count("|") >= 2


def _split_table_row(line: str) -> list[str]:
    body = line.strip().strip("|")
    return [c.strip() for c in body.split("|")]


def _parse_one(text: str) -> list[dict]:
    """Parse a single generated string into an ordered list of blocks. Groups
    consecutive lines of the same kind (table / list / prose); a blank line flushes
    the current group. A lone '|' line is treated as prose (needs >= 2 rows to be a
    table), matching the previous heuristic but centralized and tested."""
    blocks: list[dict] = []
    tbl: list[list[str]] = []
    items: list[str] = []
    ordered = False
    prose: list[str] = []

    def flush_prose():
        nonlocal prose
        if prose:
            joined = "\n".join(prose).strip()
            if joined:
                blocks.append(paragraph(joined))
            prose = []

    def flush_table():
        nonlocal tbl
        # a real table needs at least a header + one data/separator row
        if len(tbl) >= 2:
            rows = [r for r in tbl if not _SEP_RE.match("|" + "|".join(r) + "|")]
            if rows:
                blocks.append(table(rows))
        elif tbl:  # a single pipe line — keep it as prose, don't drop it
            prose.append("|" + " | ".join(tbl[0]) + "|")
            flush_prose()
        tbl = []

    def flush_list():
        nonlocal items, ordered
        if items:
            blocks.append(bullet_list(items, ordered))
        items = []
        ordered = False

    for raw in (text or "").splitlines():
        line = raw.rstrip()
        if not line.strip():
            flush_prose(); flush_table(); flush_list()
            continue
        if _is_table_line(line):
            flush_prose(); flush_list()
            tbl.append(_split_table_row(line))
            continue
        m = _LIST_RE.match(line)
        if m:
            flush_prose(); flush_table()
            ordered = bool(re.match(r"^\s*\d", line))
            items.append(m.group(2).strip())
            continue
        # prose
        flush_table(); flush_list()
        prose.append(line)

    flush_prose(); flush_table(); flush_list()
    return blocks


def parse_blocks(paragraphs: list[str]) -> list[dict]:
    """Parse the generator's paragraph strings into typed content blocks.

    Robust to: standalone markdown tables, tables or lists mixed with prose in one
    string, bullet/numbered lists, and plain prose. Deterministic and lossless —
    every non-empty input becomes exactly one block sequence."""
    blocks: list[dict] = []
    for para in (paragraphs or []):
        blocks.extend(_parse_one(para))
    return blocks


def section_filename(number: str, title: str) -> str:
    """Stable, readable per-section filename stem: number + a slug of the title,
    e.g. "5.2.1_primary_effectiveness_endpoints". Caller appends the extension."""
    slug = re.sub(r"[^a-z0-9]+", "_", (title or "").lower()).strip("_")[:60]
    num = str(number or "").replace("/", "_").replace("\\", "_")
    return f"{num}_{slug}" if slug else (num or "section")


def section_to_dict(gen: Any, *, number: str | None = None,
                    method: str | None = None) -> dict:
    """Serialize a GeneratedSection to the canonical per-section JSON shape."""
    def _asdict(x):
        return x.__dict__ if hasattr(x, "__dict__") else dict(x)

    return {
        "number": number if number is not None else gen.key,
        "key": gen.key,
        "title": gen.title,
        "method": method,
        "heading_override": gen.heading_override,
        "blocks": parse_blocks(gen.paragraphs),
        "table_fills": [_asdict(tf) for tf in gen.table_fills],
        "citations": [_asdict(c) for c in gen.citations],
        "verification": gen.verification,
        "notes": gen.notes,
        "used_chunk_ids": list(gen.used_chunk_ids),
    }


def blocks_to_plain_text(blocks: list[dict]) -> str:
    """Flatten blocks back to a readable string (tables as markdown). Used for
    previews, eval, and round-trip checks."""
    out: list[str] = []
    for b in blocks:
        if b["type"] == "paragraph":
            out.append(b["text"])
        elif b["type"] == "table":
            for r in b["rows"]:
                out.append("| " + " | ".join(r) + " |")
        elif b["type"] == "list":
            mark = (lambda i: f"{i + 1}.") if b.get("ordered") else (lambda i: "-")
            out.extend(f"{mark(i)} {it}" for i, it in enumerate(b["items"]))
    return "\n\n".join(out)
