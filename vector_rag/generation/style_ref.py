"""Few-shot STYLE exemplars from a prior human-authored CSR.

Purpose: teach the writer the *register and structure* a human uses for each
section type — NOT its facts. To keep the later original-vs-generated comparison
fair and to avoid leaking personal data, every study-specific value is masked:

  - all numbers, percentages, decimals, CIs, p-values          -> «n»
  - subject/site identifiers and initials                      -> «id»
  - subject-narrative content (where names/DOB/medical history -> dropped entirely
    concentrate) is not used as an exemplar at all

The masked exemplar is injected only as a structural template; the model is told
explicitly to take zero facts from it.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

from ..ingestion.docx_reader import iter_block_items

_HEADING_LEVEL = {"Heading 1": 1, "Heading 2": 2, "Heading 3": 3,
                  "Heading 4": 4, "Heading 5": 5}

# Sections whose bodies concentrate personal data — never use as exemplars.
_PII_HEAVY = ("narrative", "death", "listing", "signature", "investigator",
              "ethics committee", "principal investigator")

_NUM = re.compile(r"[-+]?\b\d[\d,]*\.?\d*\s?%?")
_ID = re.compile(r"\b\d{3,}[-/]?\d*\b")
_INITIALS = re.compile(r"\b(?:[A-Z]\.){2,}")
_PAREN_ID = re.compile(r"\b(?:subject|site|patient|inv(?:estigator)?)\s+\w+", re.I)


def _mask(text: str) -> str:
    text = _INITIALS.sub("«id»", text)
    text = _PAREN_ID.sub(lambda m: m.group(0).split()[0] + " «id»", text)
    text = _ID.sub("«id»", text)
    text = _NUM.sub("«n»", text)
    return text


class StyleReference:
    def __init__(self, path: Path):
        self.path = path
        self.by_number: dict[str, str] = {}
        self.by_title: dict[str, str] = {}
        if path and path.exists():
            self._parse()

    def _parse(self) -> None:
        doc = Document(str(self.path))
        counters = [0, 0, 0, 0, 0, 0]
        cur_number = ""
        cur_title = ""
        buf: list[str] = []

        def flush():
            if cur_number and buf:
                body = "\n".join(buf).strip()
                if body and not any(k in cur_title.lower() for k in _PII_HEAVY):
                    self.by_number[cur_number] = _mask(body)[:1600]
                    self.by_title[_norm(cur_title)] = self.by_number[cur_number]

        for block in iter_block_items(doc):
            if isinstance(block, Table):
                continue
            p: Paragraph = block
            style = p.style.name if p.style else ""
            text = p.text.strip()
            if style in _HEADING_LEVEL and text:
                flush()
                lvl = _HEADING_LEVEL[style]
                counters[lvl] += 1
                for i in range(lvl + 1, 6):
                    counters[i] = 0
                cur_number = ".".join(str(counters[i]) for i in range(1, lvl + 1))
                cur_title = text
                buf = []
            elif text and style in ("Document Text", "List Bulleted", "List Numbered", "Normal"):
                buf.append(text)
        flush()

    def exemplar_for(self, number: str, title: str) -> Optional[str]:
        if number and number in self.by_number:
            return self.by_number[number]
        return self.by_title.get(_norm(title))


def _norm(title: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", title.lower()).strip()
