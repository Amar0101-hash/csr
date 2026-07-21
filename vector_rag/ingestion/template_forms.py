"""Template form-table intelligence — shared by the parser (to populate
SectionSpec.form_fields), the form-filler (to fill each field), and traceability.

A template table is a "form" when it is a set of labelled fields to fill:
  - "label_value" : col-0 label, col-1 value/guidance (Title Page identification)
  - "synopsis"    : an Nx1 table whose cells read "Label: <guidance>" (Summary)

For each field we capture the LABEL and the template's per-field INSTRUCTION (the
red <...> guidance in the value cell) — extracting only the <instruction>, never
the blue [example] (whose nested brackets otherwise leak the wrong study's text).
Personal / sign-off fields are marked not fillable (left for a human).
"""
from __future__ import annotations

import re

from ..models import FormField

# Labels never auto-filled (PII / admin / sign-off).
_SKIP = (
    "signature", "author", "sponsor’s representative", "sponsor's representative",
    "principal or coordinating", "other relevant parties", "report status",
    "name and affiliation",
)


def clean_label(text: str) -> str:
    return re.sub(r"\s+", " ", text.split(":")[0].strip())


def is_skip(label: str) -> bool:
    low = label.lower()
    return any(s in low for s in _SKIP)


def field_instruction(guidance: str) -> str:
    """Extract the field's INSTRUCTION: the red <instruction> markers only; drop
    the blue [examples] (their nested brackets leak the wrong study's text)."""
    instrs = re.findall(r"<([^<>]*)>", guidance or "")
    text = " ".join(i.strip() for i in instrs if i.strip())
    if not text:  # no <> markers: fall back to removing [examples]
        text = re.sub(r"\[[^\[\]]*\]", "", guidance or "")
    return re.sub(r"\s+", " ", text).strip()[:400]


def _classify(table: list[list[str]]) -> tuple[str, list[tuple[str, str]]] | None:
    """Return (mode, [(label, raw_guidance)]) if the table is a fillable form."""
    if not table or len(table) < 2:
        return None
    ncols = max(len(r) for r in table)
    rows = [r for r in table if any(c.strip() for c in r)]
    if ncols == 1:
        fields, colon_rows = [], 0
        for r in rows:
            cell = r[0].strip()
            if ":" in cell:
                colon_rows += 1
                fields.append((clean_label(cell), cell.split(":", 1)[1]))
        if colon_rows >= max(2, int(0.5 * len(rows))):
            return "synopsis", fields
        return None
    fields = []
    for r in rows:
        lab = clean_label(r[0])
        if lab and len(lab) < 80:
            fields.append((lab, r[1] if len(r) > 1 else ""))
    if len(fields) >= 2:
        return "label_value", fields
    return None


def extract_form_fields(tables: list[list[list[str]]]) -> list[FormField]:
    """Flat list of FormField across all of a section's tables (with table_index
    and mode on each), ready to persist and to drive filling."""
    out: list[FormField] = []
    for ti, table in enumerate(tables or []):
        form = _classify(table)
        if not form:
            continue
        mode, fields = form
        for label, raw in fields:
            out.append(FormField(
                table_index=ti, mode=mode, label=label,
                instruction=field_instruction(raw), fillable=not is_skip(label),
            ))
    return out
