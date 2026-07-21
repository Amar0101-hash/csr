"""Low-level .docx reading helpers: iterate body blocks in document order,
carrying paragraph style, run colors, and tables."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterator, Optional

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph


@dataclass
class Run:
    text: str
    color: Optional[str]   # uppercase hex like "FF0000" or None
    bold: bool = False


@dataclass
class Para:
    style: str
    runs: list[Run]

    @property
    def text(self) -> str:
        return "".join(r.text for r in self.runs)


def iter_block_items(parent) -> Iterator[object]:
    """Yield Paragraph and Table objects in document order."""
    body = parent.element.body
    for child in body.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, parent)
        elif child.tag == qn("w:tbl"):
            yield Table(child, parent)


def _run_color(run) -> Optional[str]:
    try:
        col = run.font.color
        if col is not None and col.rgb is not None:
            return str(col.rgb).upper()
    except Exception:
        pass
    return None


def read_paragraph(p: Paragraph) -> Para:
    style = p.style.name if p.style else "Normal"
    runs = [Run(text=r.text, color=_run_color(r), bold=bool(r.bold)) for r in p.runs]
    if not runs and p.text:
        runs = [Run(text=p.text, color=None)]
    return Para(style=style, runs=runs)


def read_table(t: Table) -> list[list[str]]:
    rows: list[list[str]] = []
    for row in t.rows:
        rows.append([cell.text.strip() for cell in row.cells])
    return rows


# ---- structure-aware TFL table parsing (generic, shape-based, never fails) ----

_DIGIT = re.compile(r"\d")
# a value cell like "151 ( 99.3)" / "151 (99.3%)" / "1 ( 0.7 )" -> (n, pct)
_NPCT = re.compile(r"^([\d,]+(?:\.\d+)?)\s*\(\s*([\d.]+)\s*%?\s*\)\s*$")
# header-ish tokens that carry digits but describe a column, not a datum
_HEADER_WORDS = {"n", "%", "n (%)", "n(%)", "mean (sd)", "mean", "sd", "median",
                 "min", "max", "n (%)*", "95% ci", "ci", "p-value", "p value",
                 "estimate", "difference", "lsmean", "ls mean", "se"}
_CAPTION_RE = re.compile(r"^\s*(table|listing|figure|tbl|appendix)\b", re.I)


def looks_like_caption(text: str) -> bool:
    t = (text or "").strip()
    return bool(t) and bool(_CAPTION_RE.match(t)) and len(t) < 200


def _is_value_cell(c: str) -> bool:
    """True if the cell holds a data value (has a digit and isn't a header token)."""
    c = (c or "").strip()
    if not c or c.lower() in _HEADER_WORDS:
        return False
    return bool(_DIGIT.search(c))


def _split_npct(v: str):
    m = _NPCT.match((v or "").strip())
    if m:
        return m.group(1).replace(",", ""), m.group(2)
    return (v or "").strip(), None


def parse_table_facts(rows: list[list[str]], caption: str = "",
                      max_facts: int = 260) -> Optional[str]:
    """Melt a table into self-describing "facts" — one line per data cell carrying
    its group + row + column context, with n/% split. Generic and shape-based (no
    study-specific labels). Returns None when the table doesn't look tabular enough,
    so the caller falls back to plain markdown. Designed to never raise."""
    try:
        grid = [[(c or "").replace("\n", " ").strip() for c in r]
                for r in rows if any((c or "").strip() for c in r)]
        if len(grid) < 2:
            return None
        ncols = max(len(r) for r in grid)
        if ncols < 2:
            return None
        grid = [r + [""] * (ncols - len(r)) for r in grid]

        # header rows = leading rows whose non-first cells carry NO data value
        def is_header(r):
            body = [c for c in r[1:] if c]
            return bool(body) and not any(_is_value_cell(c) for c in body)

        h = 0
        while h < len(grid) and h < 3 and is_header(grid[h]):
            h += 1
        if h == 0:
            h = 1  # assume first row is the header even if it held numbers

        cols = []
        for j in range(ncols):
            parts = []
            for hr in grid[:h]:
                v = hr[j].strip()
                if v and v not in parts:
                    parts.append(v)
            cols.append(" ".join(parts).strip())

        facts: list[str] = []
        group = ""
        for r in grid[h:]:
            label = r[0].strip()
            body = [c for c in r[1:] if c.strip()]
            if label and not body:            # group / section header row
                group = label
                continue
            if not label and not body:
                continue
            for j in range(1, ncols):
                v = r[j].strip()
                if not v:
                    continue
                n, pct = _split_npct(v)
                val = f"n={n} ({pct}%)" if pct is not None else v
                ctx = " · ".join(x for x in (group, label, cols[j]) if x)
                facts.append(f"{ctx}: {val}" if ctx else val)
            if len(facts) >= max_facts:
                break

        if len(facts) < 2:
            return None
        head = caption.strip()
        return (head + "\n" if head else "") + "\n".join(facts[:max_facts])
    except Exception:
        return None


def table_to_markdown(rows: list[list[str]], max_rows: int = 60) -> str:
    """Render a table as compact markdown so an LLM can read it."""
    if not rows:
        return ""
    out: list[str] = []
    header = rows[0]
    ncols = max(len(r) for r in rows)
    header = header + [""] * (ncols - len(header))
    out.append("| " + " | ".join(c.replace("\n", " ").strip() for c in header) + " |")
    out.append("| " + " | ".join(["---"] * ncols) + " |")
    for r in rows[1:max_rows]:
        r = r + [""] * (ncols - len(r))
        out.append("| " + " | ".join(c.replace("\n", " ").strip() for c in r) + " |")
    if len(rows) - 1 > max_rows:
        out.append(f"| ...({len(rows) - 1 - max_rows} more rows) |")
    return "\n".join(out)


def open_document(path) -> Document:
    return Document(str(path))
