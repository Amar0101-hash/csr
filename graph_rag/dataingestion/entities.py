"""Deterministic clinical-entity extraction (regex + curated vocab).

Moved here from the main app's knowledge graph when `src/csr` went pure-vector;
the prototype's template linking still uses it to relate template guidance to
source sections by shared clinical terms.
"""
from __future__ import annotations

import re

# Curated clinical/statistical vocabulary. Matched case-insensitively as whole
# phrases. Extend freely — recall improves, precision is bounded by phrase set.
VOCAB = [
    # analysis sets
    "full analysis set", "safety analysis set", "per protocol analysis set",
    "per protocol", "intent to treat", "analysis set",
    # design
    "randomization", "randomisation", "crossover", "masking", "masked",
    "double-masked", "single-masked", "interim analysis", "sample size",
    "control group", "comparator", "subject population",
    # endpoints / effectiveness
    "primary endpoint", "secondary endpoint", "exploratory endpoint",
    "effectiveness endpoint", "safety endpoint", "primary effectiveness",
    "primary objective", "secondary objective", "hypothesis",
    "logmar", "visual acuity", "bcva", "manifest refraction", "keratometry",
    "autorefractometry", "lens movement", "centration", "wettability",
    # safety
    "adverse event", "serious adverse event", "adverse device effect",
    "device deficiency", "biomicroscopy", "corneal staining", "hyperemia",
    "corneal edema", "slit lamp", "discontinuation",
    # conduct
    "inclusion criteria", "exclusion criteria", "screening", "enrollment",
    "disposition", "protocol deviation", "concomitant medication", "follow-up",
    "informed consent", "ethics committee", "monitoring",
    # visits
    "visit 1", "visit 2", "visit 3", "visit 4", "baseline", "dispense",
]

_STUDY_RE = re.compile(r"\b[A-Z]{2,5}\d{2,4}[- ]?P?\d{2,4}\b")
_ACRONYM_RE = re.compile(r"\b[A-Z]{2,6}\b")
_ACR_STOP = {"THE", "AND", "FOR", "WITH", "THIS", "THAT", "WILL", "SHALL", "FROM",
             "TABLE", "FIGURE", "NOTE", "ISO", "MDR", "GCP",
             # generic / geographic / legal noise that the acronym regex admits
             "BEFORE", "AFTER", "DURING", "NA", "TX", "RX", "UK", "US", "USA", "EU",
             "LLC", "INC", "LTD", "CO", "RL", "JCR", "WHO", "ALL", "ANY", "NOT",
             "MAY", "CAN", "PER", "VIA", "EACH", "SUCH", "THAN", "WHEN", "WERE"}


def extract_entities(text: str) -> list[str]:
    ents: set[str] = set()
    low = text.lower()
    for phrase in VOCAB:
        if phrase in low:
            ents.add(phrase)
    for m in _STUDY_RE.findall(text):
        ents.add(m.upper().replace(" ", "-"))
    for m in _ACRONYM_RE.findall(text):
        if m not in _ACR_STOP:
            ents.add(m)
    return sorted(ents)
