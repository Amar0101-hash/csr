"""Post-generation verification: numeric grounding + citation validity.

This is the accuracy safety net. It does not trust the model's own claims — it
checks that every number in the authored prose actually appears in the source
excerpts that were provided, and that citations reference real sources.
"""
from __future__ import annotations

import re

from ..knowledge.retriever import RetrievedChunk

_NUM_RE = re.compile(r"(?<![\w.])[-+]?\d{1,3}(?:,\d{3})*(?:\.\d+)?%?|\b\d+\.\d+\b")


def _normalize_num(tok: str) -> str:
    return tok.replace(",", "").replace("%", "").strip()


def _numbers(text: str) -> list[str]:
    out = []
    for m in _NUM_RE.finditer(text):
        n = _normalize_num(m.group(0))
        if n and n not in {"", "-", "+"}:
            out.append(n)
    return out


# Small integers and years are too common to be meaningful hallucination signals.
def _is_material(num: str) -> bool:
    try:
        val = float(num)
    except ValueError:
        return False
    if "." in num or "%" in num:
        return True
    return abs(val) >= 10  # ignore trivially small counts like "2 arms"


def verify_section(
    paragraphs: list[str],
    citations: list[dict],
    retrieved: list[RetrievedChunk],
    label_map: dict[str, str],
) -> dict:
    source_blob = "\n".join(r.chunk.text for r in retrieved)
    source_nums = set(_numbers(source_blob))

    body = "\n".join(paragraphs)
    unsupported: list[str] = []
    for num in _numbers(body):
        if not _is_material(num):
            continue
        if num not in source_nums:
            unsupported.append(num)

    valid_labels = set(label_map.keys())
    bad_citations = [c.get("source_id") for c in citations if c.get("source_id") not in valid_labels]

    return {
        "num_numbers": len(_numbers(body)),
        "unsupported_numbers": sorted(set(unsupported)),
        "unsupported_count": len(set(unsupported)),
        "num_citations": len(citations),
        "invalid_citations": [c for c in bad_citations if c],
        "grounded": len(unsupported) == 0,
    }
