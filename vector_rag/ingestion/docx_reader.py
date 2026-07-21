"""Low-level .docx reading helpers: iterate body blocks in document order,
carrying paragraph style, run colors, and tables."""
from __future__ import annotations

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
