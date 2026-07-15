"""Parse the Device CSR Template into an ordered tree of SectionSpec.

The template encodes authoring rules through font color (see config.GUIDANCE_COLORS):
red/blue/green/orange/purple runs are *instructions to the author* and must not
appear verbatim in the final CSR, while black runs are boilerplate to retain.
This parser separates the two so the generator knows what to write and the
assembler knows what to keep.
"""
from __future__ import annotations

from collections import Counter

from docx.table import Table

from ..config import GUIDANCE_COLORS
from ..models import SectionSpec
from .docx_reader import Para, iter_block_items, open_document, read_paragraph, read_table

HEADING_STYLES = {
    "Title": 0,
    "Heading 1": 1,
    "Heading 2": 2,
    "Heading 3": 3,
    "Heading 4": 4,
}
SKIP_STYLES = {
    "TOC Title", "toc 1", "toc 2", "toc 3", "toc 4",
    "table of figures", "TOC Heading",
}
GUIDANCE_COLOR_SET = set(GUIDANCE_COLORS.keys())

# Sections that are administrative/structural: keep skeleton, do not author prose.
NO_GENERATE_KEYWORDS = (
    "TITLE PAGE", "SIGNATURE PAGE", "REFERENCES", "ANNEXES",
    "LIST OF ABBREVIATIONS", "COMPREHENSIVE CUMULATIVE HISTORY",
    "STUDY DOCUMENTS", "LIST OF PRINCIPAL INVESTIGATORS",
    "LIST OF EXTERNAL ORGANIZATIONS", "LIST OF MONITORS",
    "TABULATION OF RELEVANT DATA", "CONDUCT TABLES", "EFFECTIVENESS TABLES",
    "SAFETY TABLES", "SUBJECT LISTINGS", "SUBJECT NARRATIVES", "DEATHS",
    "ADVERSE EVENTS LEADING TO DISCONTINUATION", "ADES",
)


def _dominant_color(para: Para) -> str | None:
    counts: Counter = Counter()
    for r in para.runs:
        if r.text.strip():
            counts[r.color] += len(r.text)
    if not counts:
        return None
    return counts.most_common(1)[0][0]


def _clean_heading_title(text: str) -> str:
    return " ".join(text.split()).strip()


# Result subsections whose heading is a bare placeholder (no guidance of their
# own — the parent section holds it). These are the most important results
# sections, so we author them by inheriting the parent's guidance.
_ENDPOINT_MARKERS = ("effectiveness endpoint", "safety endpoint", "performance endpoint",
                     "primary endpoint", "secondary endpoint")


def _is_endpoint_placeholder(title: str) -> bool:
    low = title.lower()
    if any(m in low for m in _ENDPOINT_MARKERS):
        return True
    # bracketed results placeholder mentioning an endpoint or a safety result
    return title.strip().startswith("[") and ("endpoint" in low or "safety" in low)


def _endpoint_class(title: str) -> str:
    low = title.lower()
    if "primary" in low:
        return "primary"
    if "secondary" in low:
        return "secondary"
    if "supportive" in low or "exploratory" in low:
        return "supportive/exploratory"
    if "other" in low:
        return "other"
    return ""


def _should_generate(title: str, guidance: str) -> bool:
    up = title.upper()
    for kw in NO_GENERATE_KEYWORDS:
        if kw in up:
            return False
    if guidance.strip():
        return True
    # No guidance of its own, but an endpoint results placeholder -> still author.
    return _is_endpoint_placeholder(title)


def parse_template(path) -> list[SectionSpec]:
    doc = open_document(path)
    sections: list[SectionSpec] = []
    counters = [0, 0, 0, 0, 0]  # index by level 0..4

    current: SectionSpec | None = None
    guidance_parts: list[str] = []

    def flush():
        nonlocal current, guidance_parts
        if current is not None:
            current.guidance = "\n".join(g for g in guidance_parts if g.strip()).strip()
            current.generate = _should_generate(current.title, current.guidance)
            if _is_endpoint_placeholder(current.title):
                current.class_hint = _endpoint_class(current.title)
            sections.append(current)
        guidance_parts = []

    for block in iter_block_items(doc):
        if isinstance(block, Table):
            if current is not None:
                current.tables.append(read_table(block))
            continue

        para = read_paragraph(block)
        style = para.style
        text = para.text.strip()

        if style in HEADING_STYLES and (text or style == "Title"):
            level = HEADING_STYLES[style]
            flush()
            # compute hierarchical number
            number = ""
            if level >= 1:
                counters[level] += 1
                for i in range(level + 1, 5):
                    counters[i] = 0
                number = ".".join(str(counters[i]) for i in range(1, level + 1))
            title = _clean_heading_title(text)
            key = number if number else "title"
            current = SectionSpec(
                number=number, title=title, level=level, style=style,
                guidance="", key=key,
            )
            continue

        if style in SKIP_STYLES or current is None:
            continue
        if not text:
            continue

        color = _dominant_color(para)
        if color in GUIDANCE_COLOR_SET:
            if color == "0000FF":  # TOC field leftover — ignore
                continue
            gtype = GUIDANCE_COLORS[color]
            guidance_parts.append(text)
            if gtype == "iso_requirement":
                current.iso_requirements.append(text)
        else:
            # black / uncolored -> boilerplate to retain verbatim
            current.boilerplate.append(text)

    flush()
    # de-duplicate keys (some placeholder headings share numbers/titles)
    seen: dict[str, int] = {}
    for s in sections:
        base = s.key or "sec"
        if base in seen:
            seen[base] += 1
            s.key = f"{base}#{seen[base]}"
        else:
            seen[base] = 0
    return sections
