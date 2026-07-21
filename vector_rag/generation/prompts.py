"""Prompt construction and retrieval-routing for section generation."""
from __future__ import annotations

from ..knowledge.retriever import RetrievedChunk
from ..models import SectionSpec

SYSTEM_WRITER = """\
You are a senior medical writer authoring a Clinical Investigation Report (CIR),
also called a Clinical Study Report (CSR), for a medical device study. You write
to ISO 14155:2020 and ICH E3 conventions.

ABSOLUTE RULES — follow every one:
1. GROUNDING: Write ONLY facts that are explicitly supported by the provided
   SOURCE EXCERPTS. Never invent numbers, endpoints, dates, populations,
   statistics, device names, or conclusions. If the excerpts do not support a
   statement, do not make it.
2. NO GUESSING: If the excerpts are insufficient to author the section, set
   "insufficient_data": true and briefly say what is missing. Do not pad.
3. CITATIONS: For every material factual statement, cite the source excerpt(s)
   it came from using their [S#] labels. Quote the minimal exact substring you
   relied on in the citation "quote" field.
4. NUMBERS: Copy numeric values (sample sizes, percentages, p-values, CIs)
   verbatim from the excerpts. Do not round, recompute, or translate units.
5. STYLE: Formal, objective, past tense. Refer to participants as "subjects".
   Do not include the template's bracketed guidance, ISO clause labels, or
   instructions in your output. Do not include the section heading. Write the
   section body only, as clean prose paragraphs (and short lists where natural).
6. SCOPE: Write only this section. Do not write other sections or a summary of
   the whole report unless this IS the summary section.
7. BREVITY — this is critical: write like a professional medical writer, who is
   terse. Use the FEWEST sentences that fully cover the required facts. Most
   sections are 1–3 short paragraphs; many are a few sentences. State each fact
   once and stop. Do NOT: restate or paraphrase the guidance, add background or
   rationale not asked for, add caveats/transitions/filler, or explain what the
   section is about. If the sources contain little, write little — do not pad to
   look complete. A precise 3-sentence section beats an over-written page.

JSON SAFETY: Inside any string value, use single quotes (') for quoted phrases
(e.g. study titles, verbatim terms); never place an unescaped double-quote (")
inside a value. The output must be a single valid JSON object.

Return ONLY a JSON object with this exact shape:
{
  "heading": "<optional: for a placeholder endpoint section, the real endpoint's
              section title, e.g. 'Visual Acuity at Week 1 (Primary Effectiveness
              Endpoint)'; omit or empty otherwise>",
  "paragraphs": ["<paragraph 1>", "<paragraph 2>", ...],
  "citations": [{"source_id": "S3", "quote": "<exact substring from that source>"}, ...],
  "insufficient_data": false,
  "notes": "<optional short note, e.g. what data was missing>"
}
"""

# Which source document types are most relevant per top-level section number.
# Falls back to all sources when unmatched.
_ROUTING: list[tuple[tuple[str, ...], list[str]]] = [
    (("2",), ["protocol", "sap", "tfl_conduct", "tfl_effectiveness", "tfl_safety"]),  # Summary
    (("4",), ["protocol"]),                       # Introduction
    (("5.1",), ["protocol", "mop"]),              # Device description
    (("5.2",), ["protocol", "mop"]),              # CIP design/ethics/pop/treatment
    (("5.3",), ["sap", "protocol"]),              # Statistical analysis
    (("6.1",), ["tfl_conduct", "protocol", "tfl_listings"]),  # Study conduct
    (("6.2",), ["tfl_effectiveness", "sap", "protocol"]),     # Effectiveness results
    (("6.3",), ["tfl_safety", "protocol", "mop"]),           # Safety results
    (("6.4",), ["tfl_effectiveness", "sap"]),
    (("7",), ["sap", "protocol", "tfl_effectiveness", "tfl_safety"]),  # Discussion/conclusions
    (("8",), ["protocol"]),
]


# Sections whose template table is a form to FILL (identification / synopsis /
# objectives) rather than prose. Title page has no prose guidance (generate=False)
# but still needs its identification table filled.
FORM_FILL_KEYS = {"1", "2", "5.2.1"}
# Sections rendered as the filled table ONLY (no loose prose paragraphs).
TABLE_ONLY_KEYS = {"1", "2"}


# Results sections must include their TFL result tables. (doc_type, n_tables)
_GUARANTEE: list[tuple[str, tuple[str, int]]] = [
    ("6.1", ("tfl_conduct", 6)),
    ("6.2", ("tfl_effectiveness", 8)),
    ("6.3", ("tfl_safety", 8)),
    ("6.4", ("tfl_effectiveness", 6)),
]


def guaranteed_tables_for(section: SectionSpec) -> tuple[str, int] | None:
    key = section.number or ""
    for prefix, spec in _GUARANTEE:
        if key == prefix or key.startswith(prefix + ".") or key == prefix.split(".")[0]:
            return spec
    return None


def doc_types_for(section: SectionSpec) -> list[str] | None:
    key = section.number or ""
    for prefixes, types in _ROUTING:
        for p in prefixes:
            if key == p or key.startswith(p + "."):
                return types
    return None  # no filter -> search all


def build_query(section: SectionSpec) -> str:
    parts = [section.title]
    if section.iso_requirements:
        parts.append(" ".join(section.iso_requirements[:6]))
    # take a lead slice of guidance (it describes what to cover)
    if section.guidance:
        parts.append(section.guidance[:600])
    return " ".join(parts)


def format_excerpts(retrieved: list[RetrievedChunk]) -> tuple[str, dict[str, str]]:
    """Return (excerpt_block, label->chunk_id map)."""
    lines: list[str] = []
    label_map: dict[str, str] = {}
    for i, r in enumerate(retrieved, start=1):
        label = f"S{i}"
        label_map[label] = r.chunk.id
        header = f"[{label}] source={r.chunk.doc} ({r.chunk.doc_type}) | {r.chunk.section_path}"
        lines.append(header)
        lines.append(r.chunk.text.strip())
        lines.append("")
    return "\n".join(lines), label_map


def build_user_prompt(
    section: SectionSpec,
    retrieved: list[RetrievedChunk],
    style_exemplar: str | None = None,
) -> tuple[str, dict[str, str]]:
    excerpts, label_map = format_excerpts(retrieved)
    style_block = ""
    if style_exemplar:
        style_block = (
            "STYLE EXEMPLAR — a section of the SAME type from a prior human-authored "
            "report, with every study-specific value masked as «…». Mirror its STRUCTURE, "
            "tense, register, ordering, and how it references tables — but take ZERO facts "
            "from it (all facts must come from the SOURCE EXCERPTS below). Do not reproduce "
            "the «…» tokens.\n"
            f"----- begin style exemplar -----\n{style_exemplar}\n"
            "----- end style exemplar -----\n\n"
        )
    guidance = section.guidance.strip() or "(no specific guidance; cover the section per ISO 14155.)"
    focus = ""
    if section.class_hint:
        focus = (
            f"THIS SUBSECTION REPORTS THE **{section.class_hint.upper()}** ENDPOINT(S). "
            f"From the sources, identify the {section.class_hint} effectiveness/safety "
            f"endpoint(s) for this study by their actual clinical name (e.g. the specific "
            f"visual-acuity or safety measure), and report their results — analysis set, "
            f"sample size, point estimates, variability, confidence intervals, p-values, and "
            f"whether the pass/fail or hypothesis criterion was met — strictly from the "
            f"excerpts. If the named endpoint's numeric results are not in the excerpts, say so.\n\n"
        )
    # Section-specific structured-table directives. Some sections the human writer
    # renders as a figure/table (e.g. the subject-disposition CONSORT flow) — since
    # we cannot fill an embedded image, we emit the same content as a real table
    # (markdown -> rendered Word table via the block renderer).
    table_directive = _TABLE_DIRECTIVES.get(section.number or "", "")

    if section.guidance_inherited:
        guidance = "(guidance inherited from the parent Results section:)\n" + guidance
    iso = ""
    if section.iso_requirements:
        iso = "REQUIRED CONTENT (ISO 14155 — ensure each point is covered if data exists):\n" + \
            "\n".join(f"- {r}" for r in section.iso_requirements[:20]) + "\n\n"
    return (
        f"SECTION TO AUTHOR: {section.heading_text()}\n\n"
        f"{focus}"
        f"TEMPLATE GUIDANCE (what this section must contain — do NOT copy this text "
        f"verbatim; use it to decide what to write):\n{guidance}\n\n"
        f"{table_directive}"
        f"{iso}"
        f"{style_block}"
        f"SOURCE EXCERPTS (your ONLY permitted facts; cite by [S#]):\n\n{excerpts}\n"
        f"Now author the section body as grounded JSON.",
        label_map,
    )


# Sections that must include a specific structured table, emitted as a markdown
# table inside "paragraphs" (rendered to a real Word table). Grounded numbers only.
_TABLE_DIRECTIVES: dict[str, str] = {
    "6.1.1": (
        "REQUIRED TABLE — subject disposition. In addition to a brief prose "
        "sentence, include a markdown table (pipe syntax) summarising subject flow, "
        "with columns: Category | Subjects (N) | Eyes (n). Include a row for each of: "
        "Enrolled (signed consent), Screen failures / excluded, Treated (received "
        "investigational device), Discontinued (give the primary reason), Completed. "
        "Use ONLY counts found verbatim in the source excerpts; leave a cell blank if "
        "a value is not supported. Do not invent totals.\n\n"
    ),
}
