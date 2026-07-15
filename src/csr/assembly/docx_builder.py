"""Render generated sections into the template while preserving its structure.

Strategy: load the template, walk it in document order, and for each section
that we authored, replace the colored *guidance* paragraphs in place with the
generated prose — keeping every heading, boilerplate paragraph, and template
table exactly where the template put them. Sections we did not author (title
page, signature page, annex lists) are left untouched so the template's
authoring instructions remain visible to a human reviewer.

Traceability is attached as Word comments anchored to each generated paragraph.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Optional

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

from ..config import GUIDANCE_COLORS
from ..ingestion.docx_reader import iter_block_items
from ..ingestion.template_parser import HEADING_STYLES, SKIP_STYLES
from ..models import GeneratedSection, SectionSpec

GUIDANCE_COLOR_SET = set(GUIDANCE_COLORS.keys())
BODY_STYLE = "Document Text"


def _dominant_color(p: Paragraph) -> Optional[str]:
    counts: Counter = Counter()
    for r in p.runs:
        if r.text.strip():
            col = None
            try:
                if r.font.color is not None and r.font.color.rgb is not None:
                    col = str(r.font.color.rgb).upper()
            except Exception:
                col = None
            counts[col] += len(r.text)
    if not counts:
        return None
    return counts.most_common(1)[0][0]


def _delete_paragraph(p: Paragraph) -> None:
    el = p._element
    parent = el.getparent()
    if parent is not None:
        parent.remove(el)


def _safe_style(doc: Document, name: str) -> Optional[str]:
    try:
        _ = doc.styles[name]
        return name
    except KeyError:
        return None


def build_report(
    template_path: Path,
    sections: list[SectionSpec],
    generated: dict[str, GeneratedSection],
    output_path: Path,
    add_comments: bool = True,
) -> dict:
    doc = Document(str(template_path))
    body_style = _safe_style(doc, BODY_STYLE)

    # First pass: assign each block to a section index (aligned by heading order
    # with the parsed `sections`). Collect guidance paragraphs, the heading
    # paragraph, and the template tables per section.
    sec_idx = -1
    guidance_by_section: dict[int, list[Paragraph]] = {}
    heading_by_section: dict[int, Paragraph] = {}
    tables_by_section: dict[int, list[Table]] = {}

    for block in iter_block_items(doc):
        if isinstance(block, Table):
            if sec_idx >= 0:
                tables_by_section.setdefault(sec_idx, []).append(block)
            continue
        p = block
        style = p.style.name if p.style else "Normal"
        text = p.text.strip()

        is_heading = style in HEADING_STYLES and (text or style == "Title")
        if is_heading:
            sec_idx += 1
            heading_by_section[sec_idx] = p
            continue
        if sec_idx < 0 or style in SKIP_STYLES or not text:
            continue

        color = _dominant_color(p)
        if color in GUIDANCE_COLOR_SET and color != "0000FF":
            guidance_by_section.setdefault(sec_idx, []).append(p)

    # Second pass: fill tables, rename placeholder headings, insert prose, remove
    # guidance. Iterate a stable snapshot so edits don't disturb traversal.
    stats = {"authored": 0, "placeholder": 0, "skipped": 0, "comments": 0, "tables_filled": 0}

    for idx, section in enumerate(sections):
        gen = generated.get(section.key)
        g_paras = guidance_by_section.get(idx, [])
        sec_tables = tables_by_section.get(idx, [])

        if gen is None:
            if not section.generate:
                stats["skipped"] += 1
                continue
            # generate=True but nothing produced -> placeholder
            anchor = g_paras[0] if g_paras else None
            _insert_note(doc, anchor, _placeholder_text(None), body_style)
            stats["placeholder"] += 1
            for gp in g_paras:
                _delete_paragraph(gp)
            continue

        # (a) rename placeholder endpoint heading, if the model gave a real name
        if gen.heading_override and idx in heading_by_section:
            _set_heading_text(heading_by_section[idx], gen.heading_override)

        # (b) fill the section's template form-tables
        for tf in gen.table_fills:
            if 0 <= tf.table_index < len(sec_tables):
                if _fill_form_table(sec_tables[tf.table_index], tf):
                    stats["tables_filled"] += 1

        # (c) insert prose (rendering any markdown tables as real Word tables)
        anchor = g_paras[0] if g_paras else None
        first_para: Optional[Paragraph] = None
        if gen.paragraphs:
            for para_text in gen.paragraphs:
                if _looks_like_md_table(para_text):
                    _render_table_before(doc, anchor, _parse_md_table(para_text))
                else:
                    np = _insert_note(doc, anchor, para_text, body_style)
                    if first_para is None:
                        first_para = np
            if add_comments and first_para is not None:
                _attach_comment(doc, first_para, gen, stats)
            stats["authored"] += 1
        elif not gen.table_fills:
            _insert_note(doc, anchor, _placeholder_text(gen), body_style)
            stats["placeholder"] += 1
        else:
            stats["authored"] += 1  # table-only section (Title Page / Summary)

        for gp in g_paras:
            _delete_paragraph(gp)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    written = _save_resilient(doc, output_path)
    stats["output_path"] = str(written)
    return stats


def _insert_note(doc: Document, anchor: Optional[Paragraph], text: str, style) -> Paragraph:
    if anchor is not None:
        return anchor.insert_paragraph_before(text, style=style)
    return doc.add_paragraph(text, style=style)


def _set_heading_text(heading: Paragraph, text: str) -> None:
    """Replace a placeholder heading's text, keeping its Heading style (size/bold)
    and clearing the blue guidance color so it reads as a real heading."""
    runs = heading.runs
    if not runs:
        heading.add_run(text)
        return
    runs[0].text = text
    try:
        runs[0].font.color.rgb = None  # inherit style default (black)
    except Exception:
        pass
    for r in runs[1:]:
        r.text = ""


# ---- markdown table rendering ----

def _looks_like_md_table(text: str) -> bool:
    lines = [l for l in text.splitlines() if l.strip()]
    piped = [l for l in lines if l.strip().startswith("|")]
    return len(piped) >= 2


def _parse_md_table(text: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in text.splitlines():
        s = line.strip()
        if not s.startswith("|"):
            continue
        body = s.strip("|")
        if set(body.replace("|", "").strip()) <= set("-: "):
            continue  # separator row
        rows.append([c.strip() for c in body.split("|")])
    return rows


def _render_table_before(doc: Document, anchor: Optional[Paragraph], rows: list[list[str]]) -> None:
    if not rows:
        return
    ncols = max(len(r) for r in rows)
    table = doc.add_table(rows=len(rows), cols=ncols)
    try:
        table.style = "Table Grid"
    except Exception:
        pass
    for i, r in enumerate(rows):
        for j in range(ncols):
            cell = table.cell(i, j)
            cell.text = r[j] if j < len(r) else ""
            if i == 0:
                for cp in cell.paragraphs:
                    for run in cp.runs:
                        run.bold = True
    if anchor is not None:
        anchor._p.addprevious(table._tbl)


# ---- template form-table filling ----

def _copy_font(dst_run, src_run) -> None:
    try:
        if src_run is not None:
            dst_run.font.size = src_run.font.size
            dst_run.font.name = src_run.font.name
    except Exception:
        pass


def _first_run(cell) -> object:
    for p in cell.paragraphs:
        if p.runs:
            return p.runs[0]
    return None


def _write_cell(cell, label: Optional[str], value: str) -> None:
    """Rewrite a cell as an optional bold label + value, preserving cell font."""
    ref = _first_run(cell)
    # clear all paragraphs but the first
    for p in cell.paragraphs[1:]:
        _delete_paragraph(p)
    para = cell.paragraphs[0]
    for r in list(para.runs):
        r.text = ""
    # remove extra empty runs
    first = para.runs[0] if para.runs else para.add_run("")
    if label:
        first.text = f"{label}: "
        first.bold = True
        _copy_font(first, ref)
        val_run = para.add_run(value)
        val_run.bold = False
        _copy_font(val_run, ref)
    else:
        first.text = value
        first.bold = False
        _copy_font(first, ref)


def _fill_form_table(table: Table, tf) -> bool:
    from ..generation.table_fill import _clean_label

    filled = False
    if tf.mode == "synopsis":
        for row in table.rows:
            cell = row.cells[0]
            cell_text = cell.text.strip()
            if ":" not in cell_text:
                continue
            label = _clean_label(cell_text)
            val = tf.values.get(label)
            if val:
                _write_cell(cell, label, val)
                filled = True
    else:  # label_value
        for row in table.rows:
            cells = row.cells
            if len(cells) < 2:
                continue
            label = _clean_label(cells[0].text)
            val = tf.values.get(label)
            if val:
                _write_cell(cells[1], None, val)
                filled = True
    return filled


def _save_resilient(doc: Document, output_path: Path) -> Path:
    """Save the docx. If the target is locked (open in Word/IDE), fall back to a
    timestamped filename instead of losing the whole run."""
    try:
        doc.save(str(output_path))
        return output_path
    except PermissionError:
        import time

        stamp = time.strftime("%Y%m%d_%H%M%S")
        alt = output_path.with_name(f"{output_path.stem}_{stamp}{output_path.suffix}")
        doc.save(str(alt))
        print(
            f"[assemble] '{output_path.name}' is open/locked — wrote '{alt.name}' instead. "
            f"Close it and re-run to update the primary file.",
            flush=True,
        )
        return alt


def _placeholder_text(gen: Optional[GeneratedSection]) -> str:
    reason = (gen.notes if gen and gen.notes else "insufficient source data").strip()
    return f"[To be authored — {reason}]"


def _attach_comment(doc: Document, para: Paragraph, gen: GeneratedSection, stats: dict) -> None:
    lines = ["Generated from study sources."]
    if gen.citations:
        srcs = []
        for c in gen.citations[:8]:
            srcs.append(f"{c.doc}: {c.section_path}")
        # de-dup preserving order
        seen = set()
        uniq = [s for s in srcs if not (s in seen or seen.add(s))]
        lines.append("Sources: " + "; ".join(uniq))
    v = gen.verification or {}
    if v.get("unsupported_numbers"):
        lines.append("REVIEW numbers not found verbatim in sources: " + ", ".join(v["unsupported_numbers"][:10]))
    if gen.notes:
        lines.append("Note: " + gen.notes)
    try:
        runs = [r for r in para.runs if r.text.strip()] or para.runs
        if runs:
            doc.add_comment(runs=runs, text="\n".join(lines), author="CSR-GenAI", initials="AI")
            stats["comments"] += 1
    except Exception:
        pass
