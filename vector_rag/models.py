"""Core data models shared across ingestion, retrieval, generation, assembly."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Optional


def _hash(*parts: str) -> str:
    return hashlib.sha1("||".join(parts).encode("utf-8")).hexdigest()[:16]


@dataclass
class Chunk:
    """A retrievable unit of source content."""

    id: str
    doc: str            # logical source name: protocol | sap | mop | tfl_conduct ...
    doc_type: str       # protocol | sap | mop | tfl
    section_path: str   # heading breadcrumb, e.g. "ANALYSIS PLAN > Analysis Sets"
    text: str
    kind: str = "text"  # text | table
    page_hint: Optional[int] = None
    entities: list[str] = field(default_factory=list)

    @staticmethod
    def make(doc: str, doc_type: str, section_path: str, text: str, kind: str = "text") -> "Chunk":
        return Chunk(
            id=_hash(doc, section_path, text[:200], kind),
            doc=doc,
            doc_type=doc_type,
            section_path=section_path,
            text=text,
            kind=kind,
        )


@dataclass
class TemplateBlock:
    """One block (paragraph or table) inside a template section."""

    kind: str           # heading | boilerplate | guidance | table
    style: str
    text: str
    guidance_type: Optional[str] = None   # instruction|optional|iso_requirement|...
    table: Optional[list[list[str]]] = None


@dataclass
class FormField:
    """One fillable field inside a template form-table, with the template's own
    per-field instruction (extracted from the value cell). The 'template
    intelligence' the generator uses to fill each field correctly and the docx
    assembler uses to place it."""
    table_index: int
    mode: str            # synopsis | label_value
    label: str
    instruction: str     # what this field must contain (template guidance)
    fillable: bool = True  # False for PII / sign-off fields left to a human


@dataclass
class SectionSpec:
    """A section of the CSR template: a heading plus everything under it up to
    the next heading of equal-or-higher level."""

    number: str          # e.g. "5.2.1" ("" for unnumbered)
    title: str           # clean title text
    level: int           # 1-4
    style: str           # Heading 1..4 / Title
    guidance: str        # concatenated instructional text (what to write)
    boilerplate: list[str] = field(default_factory=list)  # black text to retain
    iso_requirements: list[str] = field(default_factory=list)
    tables: list[list[list[str]]] = field(default_factory=list)
    generate: bool = True    # whether the model should author this section
    key: str = ""            # stable key: number or slug
    class_hint: str = ""     # for endpoint placeholders: "primary"/"secondary"/...
    guidance_inherited: bool = False  # guidance was inherited from an ancestor
    form_fields: list[FormField] = field(default_factory=list)  # extracted form fields
    has_figure: bool = False  # section contains an image/figure placeholder

    def heading_text(self) -> str:
        return f"{self.number} {self.title}".strip()


@dataclass
class Citation:
    chunk_id: str
    doc: str
    section_path: str
    quote: str


@dataclass
class TableFill:
    """Values to write into a template table, preserving its structure/format.

    `mode` = "synopsis" (Nx1 'Label: value' cells) or "label_value" (col0 label,
    fill col1). `values` maps the row label -> grounded value string.
    """
    table_index: int
    mode: str
    values: dict[str, str] = field(default_factory=dict)


@dataclass
class GeneratedSection:
    key: str
    title: str
    paragraphs: list[str]
    citations: list[Citation] = field(default_factory=list)
    used_chunk_ids: list[str] = field(default_factory=list)
    notes: Optional[str] = None            # e.g. "no source data found"
    verification: dict[str, Any] = field(default_factory=dict)
    heading_override: Optional[str] = None   # e.g. real endpoint name for placeholder
    table_fills: list[TableFill] = field(default_factory=list)
