"""Emit a source-traceability report (JSON + Markdown) for the generated CSR."""
from __future__ import annotations

import json
from pathlib import Path

from ..models import GeneratedSection, SectionSpec


def write_generated_preview(
    sections: list[SectionSpec],
    generated: dict[str, GeneratedSection],
    path: Path,
) -> None:
    """Human-readable dump of every generated section: the authored text plus
    its metadata, citations, and verification — the generation analogue of the
    pre-vectorization chunk preview."""
    def _has_content(g: GeneratedSection) -> bool:
        return bool(g.paragraphs) or bool(g.table_fills)

    ok = sum(1 for g in generated.values() if _has_content(g))
    err = sum(1 for g in generated.values() if not _has_content(g))
    lines = ["# Generated sections preview", ""]
    lines.append(f"Authored: **{ok}**  ·  Empty/failed: **{err}**  ·  Total: **{len(generated)}**")
    lines.append("")
    lines.append("---")
    lines.append("")
    # keep template order
    for section in sections:
        gen = generated.get(section.key)
        if gen is None:
            continue
        v = gen.verification or {}
        status = "AUTHORED" if (gen.paragraphs or gen.table_fills) else "EMPTY/FAILED"
        if gen.heading_override:
            status += " · renamed"
        grounded = v.get("grounded", True)
        lines.append(f"## {section.heading_text()}  ·  [{status}]")
        if gen.heading_override:
            lines.append(f"_heading → {gen.heading_override}_")
        meta = [
            f"key={section.key}",
            f"paras={len(gen.paragraphs)}",
            f"table_fills={sum(len(tf.values) for tf in gen.table_fills)}",
            f"citations={len(gen.citations)}",
            f"numbers={v.get('num_numbers', 0)}",
            f"unsupported={v.get('unsupported_count', 0)}",
            f"grounded={grounded}",
        ]
        lines.append("`" + "  ".join(meta) + "`")
        if v.get("unsupported_numbers"):
            lines.append(f"> ⚠️ numbers not found verbatim in sources: {', '.join(v['unsupported_numbers'])}")
        if gen.notes:
            lines.append(f"> note: {gen.notes}")
        lines.append("")
        if gen.table_fills:
            for tf in gen.table_fills:
                lines.append(f"### Filled table (mode={tf.mode})")
                for label, value in tf.values.items():
                    lines.append(f"- **{label}:** {value}")
                lines.append("")
        if gen.paragraphs:
            lines.append("### Authored text")
            for p in gen.paragraphs:
                lines.append(p)
                lines.append("")
        if gen.citations:
            lines.append("### Citations")
            for c in gen.citations:
                q = (c.quote or "").replace("\n", " ").strip()
                lines.append(f"- **{c.doc}** — {c.section_path}" + (f"  · “{q[:160]}”" if q else ""))
            lines.append("")
        if gen.used_chunk_ids:
            lines.append(f"_source chunk ids:_ {', '.join(gen.used_chunk_ids)}")
            lines.append("")
        lines.append("---")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_traceability(
    sections: list[SectionSpec],
    generated: dict[str, GeneratedSection],
    json_path: Path,
    md_path: Path,
) -> dict:
    records = []
    total = 0
    grounded = 0
    flagged = []
    for section in sections:
        gen = generated.get(section.key)
        if gen is None:
            continue
        total += 1
        v = gen.verification or {}
        if v.get("grounded", True):
            grounded += 1
        else:
            flagged.append(section.heading_text())
        records.append(
            {
                "section": section.heading_text(),
                "key": section.key,
                "authored": bool(gen.paragraphs),
                "paragraphs": len(gen.paragraphs),
                "citations": [
                    {"doc": c.doc, "section_path": c.section_path, "quote": c.quote}
                    for c in gen.citations
                ],
                "used_chunk_ids": gen.used_chunk_ids,
                "verification": v,
                "notes": gen.notes,
            }
        )

    summary = {
        "sections_generated": total,
        "sections_grounded": grounded,
        "sections_flagged": flagged,
    }
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps({"summary": summary, "sections": records}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    lines = ["# CSR Source Traceability Report", ""]
    lines.append(f"- Sections authored: **{total}**")
    lines.append(f"- Numerically grounded: **{grounded}/{total}**")
    if flagged:
        lines.append(f"- ⚠️ Flagged for review: {', '.join(flagged)}")
    lines.append("")
    for rec in records:
        lines.append(f"## {rec['section']}")
        if not rec["authored"]:
            lines.append(f"_Not authored — {rec['notes'] or 'insufficient data'}_\n")
            continue
        v = rec["verification"]
        flag = "" if v.get("grounded", True) else "  ⚠️ **REVIEW**"
        lines.append(
            f"- Paragraphs: {rec['paragraphs']} | Citations: {len(rec['citations'])} | "
            f"Numbers checked: {v.get('num_numbers', 0)} | "
            f"Unsupported: {v.get('unsupported_count', 0)}{flag}"
        )
        if v.get("unsupported_numbers"):
            lines.append(f"  - Numbers not found verbatim in sources: {', '.join(v['unsupported_numbers'])}")
        if rec["citations"]:
            lines.append("  - Sources cited:")
            seen = set()
            for c in rec["citations"]:
                tag = f"{c['doc']} — {c['section_path']}"
                if tag in seen:
                    continue
                seen.add(tag)
                lines.append(f"    - {tag}")
        lines.append("")
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return summary
