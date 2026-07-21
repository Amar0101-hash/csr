"""Clinical **concept** catalog for the study-concept graph.

Where `entities.py` extracts a flat bag of terms (every acronym, every study id),
this groups the clinically meaningful terms into CONCEPTS — an endpoint, an
analysis set, a visit — each with its synonyms folded together. That grouping is
the whole point: "primary endpoint" and "primary effectiveness endpoint" are the
SAME concept, and a concept is what gets *defined* (SAP), *described* (Protocol/
MOP) and *measured* (a TFL table) across documents. The concept graph then lets
the hybrid retriever bridge those three views of one concept instead of relying on
coarse word co-occurrence.

Deliberately device-CSR-**generic**: these are the concept families a device
Clinical Investigation Report template asks about (endpoints, analysis sets,
visits, design, safety, conduct) — nothing here is specific to one study id, so
the same catalog drives any study built on the device template. Surface terms are
matched case-insensitively on word boundaries; extend `CONCEPTS` freely.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Concept:
    key: str          # stable slug (node key)
    name: str         # human-readable label
    kind: str         # endpoint | analysis_set | visit | design | safety | conduct | measure
    terms: tuple[str, ...]  # surface synonyms; any match => the concept is mentioned


# One entry per clinical concept; the first term doubles as the canonical phrase.
CONCEPTS: tuple[Concept, ...] = (
    # --- endpoints (the spine of the effectiveness/safety story) ---
    Concept("endpoint_primary_eff", "Primary effectiveness endpoint", "endpoint",
            ("primary effectiveness endpoint", "primary effectiveness",
             "primary endpoint", "primary objective")),
    Concept("endpoint_secondary", "Secondary endpoint", "endpoint",
            ("secondary endpoint", "secondary objective")),
    Concept("endpoint_exploratory", "Exploratory endpoint", "endpoint",
            ("exploratory endpoint",)),
    Concept("endpoint_safety", "Safety endpoint", "endpoint",
            ("safety endpoint",)),
    Concept("hypothesis_noninferiority", "Non-inferiority hypothesis", "design",
            ("non-inferiority", "noninferiority", "hypothesis")),

    # --- measures (what the endpoints are measured with) ---
    Concept("visual_acuity", "Visual acuity", "measure",
            ("visual acuity", "bcva", "logmar")),
    Concept("refraction", "Refraction / keratometry", "measure",
            ("manifest refraction", "autorefractometry", "keratometry")),
    Concept("lens_fit", "Lens fit / centration", "measure",
            ("lens movement", "centration", "wettability")),

    # --- analysis sets ---
    Concept("analysis_full", "Full analysis set", "analysis_set",
            ("full analysis set",)),
    Concept("analysis_safety", "Safety analysis set", "analysis_set",
            ("safety analysis set",)),
    Concept("analysis_pp", "Per-protocol analysis set", "analysis_set",
            ("per protocol analysis set", "per protocol", "per-protocol")),
    Concept("analysis_itt", "Intent-to-treat", "analysis_set",
            ("intent to treat", "intention to treat", "itt")),

    # --- design ---
    Concept("design_randomization", "Randomization", "design",
            ("randomization", "randomisation")),
    Concept("design_masking", "Masking", "design",
            ("double-masked", "single-masked", "masking", "masked")),
    Concept("design_sample_size", "Sample size justification", "design",
            ("sample size",)),
    Concept("design_interim", "Interim analysis", "design",
            ("interim analysis",)),
    Concept("design_comparator", "Comparator / control", "design",
            ("comparator", "control group", "control lens")),
    Concept("design_crossover", "Crossover", "design",
            ("crossover",)),

    # --- safety ---
    Concept("ae", "Adverse event", "safety", ("adverse event",)),
    Concept("sae", "Serious adverse event", "safety", ("serious adverse event",)),
    Concept("ade", "Adverse device effect", "safety",
            ("adverse device effect", "sade")),
    Concept("device_deficiency", "Device deficiency", "safety",
            ("device deficiency",)),
    Concept("ocular_findings", "Ocular findings", "safety",
            ("biomicroscopy", "corneal staining", "hyperemia", "corneal edema",
             "slit lamp")),

    # --- conduct / disposition ---
    Concept("disposition", "Subject disposition", "conduct", ("disposition",)),
    Concept("deviation", "Protocol deviation", "conduct", ("protocol deviation",)),
    Concept("conmed", "Concomitant medication", "conduct",
            ("concomitant medication",)),
    Concept("consent", "Informed consent", "conduct", ("informed consent",)),
    Concept("eligibility", "Eligibility criteria", "conduct",
            ("inclusion criteria", "exclusion criteria")),
    Concept("discontinuation", "Discontinuation", "conduct", ("discontinuation",)),

    # --- visits ---
    Concept("visit_baseline", "Baseline visit", "visit", ("baseline",)),
    Concept("visit_dispense", "Dispensing visit", "visit", ("dispense", "dispensing")),
    Concept("visit_1", "Visit 1", "visit", ("visit 1",)),
    Concept("visit_2", "Visit 2", "visit", ("visit 2",)),
    Concept("visit_3", "Visit 3", "visit", ("visit 3",)),
    Concept("visit_4", "Visit 4", "visit", ("visit 4",)),
    Concept("followup", "Follow-up", "visit", ("follow-up", "follow up")),
)

CONCEPT_BY_KEY = {c.key: c for c in CONCEPTS}

# Pre-compile one word-boundary regex per surface term, longest-first so a longer
# phrase wins its span before a shorter one that is contained in it.
_COMPILED: list[tuple[str, re.Pattern]] = []
for _c in CONCEPTS:
    for _t in _c.terms:
        _COMPILED.append((_c.key, re.compile(r"(?<!\w)" + re.escape(_t) + r"(?!\w)")))
_COMPILED.sort(key=lambda kt: -len(kt[1].pattern))


def detect_concepts(text: str) -> dict[str, int]:
    """Concepts mentioned in `text`, mapped to the number of surface-term hits.
    Deterministic and reproducible — the same text always yields the same
    concepts, which is exactly what the old entity co-mention graph lacked."""
    low = " ".join(text.lower().split())
    hits: dict[str, int] = {}
    for key, rx in _COMPILED:
        n = len(rx.findall(low))
        if n:
            hits[key] = hits.get(key, 0) + n
    return hits
