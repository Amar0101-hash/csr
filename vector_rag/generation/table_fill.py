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

from ..knowledge.retriever import VectorRetriever
from ..models import SectionSpec, TableFill
from ..ingestion.template_forms import extract_form_fields, is_skip  # noqa: F401
from .llm import ClaudeClient
from .prompts import format_excerpts

SYSTEM_FORM = """\
You fill a field of a Clinical Investigation Report (CSR) table from source
excerpts. Rules: use ONLY facts supported by the excerpts; copy numbers verbatim;
be concise and formal (past tense); no invented values. If a field is not
supported by the excerpts, return an empty string for it. Do not include the
field label in the value.

FILL EXACTLY THE FIELD'S SCOPE — nothing more. Answer only what the field's
instruction asks; do NOT add related-but-unrequested information. In particular,
a "Test Product" / "Investigational Device" field contains ONLY the investigational
(test) product — never the comparator/control device. Keep each value to the
minimum that satisfies the instruction.

JSON SAFETY: Return ONLY a valid JSON object {"values": {"<label>": "<value>", ...}}.
Inside any value, use single quotes (') for quoted phrases such as study titles —
never put an unescaped double-quote (") inside a value. Use the field labels
exactly as given as the JSON keys.
"""


class FormFiller:
    def __init__(self, client: ClaudeClient, retriever: VectorRetriever, style_ref=None):
        self.client = client
        self.retriever = retriever
        self.style_ref = style_ref

    def fill_section(self, section: SectionSpec, doc_types: list[str] | None) -> list[TableFill]:
        # Use the template intelligence extracted at parse time (single source of
        # truth); fall back to on-the-fly extraction if a spec predates it.
        form_fields = section.form_fields or extract_form_fields(section.tables)
        by_table: dict[int, list] = {}
        for f in form_fields:
            by_table.setdefault(f.table_index, []).append(f)
        fills: list[TableFill] = []
        for ti, fields in by_table.items():
            fillable = [(f.label, f.instruction) for f in fields if f.fillable]
            if not fillable:
                continue
            mode = fields[0].mode
            values = self._fill_fields(section, fillable, doc_types)
            if values:
                fills.append(TableFill(table_index=ti, mode=mode, values=values))
        return fills

    def _fill_fields(self, section: SectionSpec, fields: list[tuple[str, str]],
                     doc_types: list[str] | None) -> dict[str, str]:
        labels = [l for l, _ in fields]
        # retrieve using the field labels AND their instructions so the right
        # sources surface (e.g. "study design, comparison, period, population").
        guide_terms = " ".join(g for _, g in fields if g)
        query = f"{section.title} {' '.join(labels)} {guide_terms}"[:600]
        retrieved = self.retriever.retrieve(query, doc_types=doc_types, k=12)
        if not retrieved:
            return {}
        excerpts, _ = format_excerpts(retrieved)
        # each field line carries its INSTRUCTION so the model fills the right thing
        field_list = "\n".join(
            f"- {l}: {g}" if g else f"- {l}" for l, g in fields
        )
        # few-shot: how a human medical writer filled these fields (masked values)
        fewshot = ""
        if self.style_ref is not None:
            ex = self.style_ref.form_exemplar_for(section.number)
            if ex:
                shown = "\n".join(f"- {k}: {v}" for k, v in list(ex.items())[:20])
                fewshot = (
                    "EXAMPLE — how a human medical writer filled these fields in a "
                    "prior report (values MASKED as «n»/«id»; match this STYLE, "
                    "phrasing and BREVITY, but take ZERO facts from it — all facts "
                    f"come from the SOURCE EXCERPTS):\n{shown}\n\n"
                )
        user = (
            f"CSR SECTION: {section.heading_text()}\n\n"
            f"{fewshot}"
            f"Fill each FIELD below. The text after each label is an INSTRUCTION for "
            f"what that field must contain — follow it, writing the actual value from "
            f"the SOURCE EXCERPTS (empty string if not supported). Do NOT copy the "
            f"instruction text or any example; write the real, grounded value.\n"
            f"{field_list}\n\n"
            f"SOURCE EXCERPTS:\n\n{excerpts}\n\n"
            f"Return JSON {{\"values\": {{label: value}}}} using the exact labels above."
        )
        try:  # persist the form prompt as a versioned artifact for the UI
            from ..prompt_store import save_prompt_version
            from ..config import Settings as _S
            save_prompt_version(_S(), section.number, section.title,
                                system=SYSTEM_FORM, user=user, kind="form")
        except Exception:
            pass
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
