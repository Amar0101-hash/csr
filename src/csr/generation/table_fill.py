"""Fill the template's structured form-tables (Title Page identification,
Summary synopsis, etc.) with grounded values, preserving the table structure.

Two form shapes are handled:
  - "synopsis"     : an Nx1 table whose cells read "Label: <guidance>" (the CSR
                     Summary). We fill the value after each label.
  - "label_value"  : col-0 is a label, col-1 holds the value/guidance (Title
                     Page). We fill col-1 for fillable labels.

Personal / administrative fields (author names, investigator names, signatures)
are never auto-filled — they're left as template guidance for a human.
"""
from __future__ import annotations

import re

from ..knowledge.retriever import HybridRetriever
from ..models import SectionSpec, TableFill
from .llm import ClaudeClient
from .prompts import format_excerpts

# Labels we never auto-fill (PII / admin / sign-off).
_SKIP = (
    "signature", "author", "sponsor’s representative", "sponsor's representative",
    "principal or coordinating", "other relevant parties", "report status",
    "name and affiliation",
)

SYSTEM_FORM = """\
You fill a field of a Clinical Investigation Report (CSR) table from source
excerpts. Rules: use ONLY facts supported by the excerpts; copy numbers verbatim;
be concise and formal (past tense); no invented values. If a field is not
supported by the excerpts, return an empty string for it. Do not include the
field label in the value.

JSON SAFETY: Return ONLY a valid JSON object {"values": {"<label>": "<value>", ...}}.
Inside any value, use single quotes (') for quoted phrases such as study titles —
never put an unescaped double-quote (") inside a value. Use the field labels
exactly as given as the JSON keys.
"""


def _clean_label(text: str) -> str:
    lbl = text.split(":")[0].strip()
    return re.sub(r"\s+", " ", lbl)


def _is_skip(label: str) -> bool:
    low = label.lower()
    return any(s in low for s in _SKIP)


def classify_form(table: list[list[str]]) -> tuple[str, list[str]] | None:
    """Return (mode, field_labels) if the table is a fillable form, else None."""
    if not table or len(table) < 2:
        return None
    ncols = max(len(r) for r in table)
    rows = [r for r in table if any(c.strip() for c in r)]
    if ncols == 1:
        labels = []
        colon_rows = 0
        for r in rows:
            cell = r[0].strip()
            if ":" in cell:
                colon_rows += 1
                labels.append(_clean_label(cell))
        if colon_rows >= max(2, int(0.5 * len(rows))):
            return "synopsis", labels
        return None
    # label_value: col0 short labels
    labels = []
    for r in rows:
        lab = _clean_label(r[0])
        if lab and len(lab) < 80:
            labels.append(lab)
    if len(labels) >= 2:
        return "label_value", labels
    return None


class FormFiller:
    def __init__(self, client: ClaudeClient, retriever: HybridRetriever):
        self.client = client
        self.retriever = retriever

    def fill_section(self, section: SectionSpec, doc_types: list[str] | None) -> list[TableFill]:
        fills: list[TableFill] = []
        for ti, table in enumerate(section.tables):
            form = classify_form(table)
            if not form:
                continue
            mode, labels = form
            fillable = [l for l in labels if not _is_skip(l)]
            if not fillable:
                continue
            values = self._fill_fields(section, fillable, doc_types)
            if values:
                fills.append(TableFill(table_index=ti, mode=mode, values=values))
        return fills

    def _fill_fields(self, section: SectionSpec, labels: list[str],
                     doc_types: list[str] | None) -> dict[str, str]:
        query = section.title + " " + " ".join(labels)
        retrieved = self.retriever.retrieve(query, doc_types=doc_types, k=12)
        if not retrieved:
            return {}
        excerpts, _ = format_excerpts(retrieved)
        field_list = "\n".join(f"- {l}" for l in labels)
        user = (
            f"CSR SECTION: {section.heading_text()}\n\n"
            f"Fill each of these FIELDS from the source excerpts (empty string if "
            f"not supported):\n{field_list}\n\n"
            f"SOURCE EXCERPTS:\n\n{excerpts}\n\n"
            f"Return JSON {{\"values\": {{label: value}}}} for the fields above."
        )
        try:
            data = self.client.complete_json(SYSTEM_FORM, user, max_tokens=8000)
        except Exception:
            return {}
        raw = data.get("values", {}) if isinstance(data, dict) else {}
        # keep only non-empty, map back to the closest requested label
        out: dict[str, str] = {}
        for lab in labels:
            v = raw.get(lab)
            if v is None:
                # tolerant match (case/spacing)
                for k, vv in raw.items():
                    if _clean_label(k).lower() == lab.lower():
                        v = vv
                        break
            if v and str(v).strip():
                out[lab] = str(v).strip()
        return out
