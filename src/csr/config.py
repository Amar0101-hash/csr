"""Central configuration for the CSR generator.

All tunables live here. Paths default to the repo layout but can be overridden
via environment variables (CSR_*) or by constructing Settings directly.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass
class Settings:
    # --- Filesystem ---
    repo_root: Path = REPO_ROOT
    study_dir: Path = field(default_factory=lambda: REPO_ROOT / "study")
    template_path: Path = field(
        default_factory=lambda: REPO_ROOT / "Device CSR Template - Single File.docx"
    )
    work_dir: Path = field(default_factory=lambda: REPO_ROOT / ".csr_work")
    output_dir: Path = field(default_factory=lambda: REPO_ROOT / "output")
    # Optional prior human-authored CSR used ONLY as a masked style exemplar
    # (few-shot for register/structure; no facts or PII are taken from it).
    style_reference: Path = field(
        default_factory=lambda: REPO_ROOT / "CLA306-P002 CSR Sections 1-11.docx"
    )
    use_style_reference: bool = True

    # --- AWS / Bedrock ---
    aws_region: str = field(default_factory=lambda: _env("CSR_AWS_REGION", "us-east-1"))
    # Generation model. This account only has Sonnet 4.6/4.5 enabled on Bedrock
    # (see memory/bedrock-model-access). Change once Opus/Sonnet-5 is enabled.
    gen_model: str = field(
        default_factory=lambda: _env("CSR_GEN_MODEL", "us.anthropic.claude-sonnet-4-6")
    )
    embed_model: str = field(
        default_factory=lambda: _env("CSR_EMBED_MODEL", "amazon.titan-embed-text-v2:0")
    )
    embed_dim: int = 1024
    # Room for adaptive thinking + a long grounded JSON. Too small a budget lets
    # high-effort thinking consume everything before any JSON is emitted.
    max_gen_tokens: int = 16000
    # effort for Sonnet 4.6: low|medium|high|max. Use high for accuracy.
    effort: str = field(default_factory=lambda: _env("CSR_EFFORT", "high"))
    # Hard per-request timeout (seconds) so a stalled Bedrock call fails fast and
    # the section is marked failed instead of hanging the whole run.
    request_timeout: float = field(
        default_factory=lambda: float(_env("CSR_REQUEST_TIMEOUT", "180"))
    )

    # --- Retrieval ---
    top_k_vector: int = 12
    top_k_fts: int = 8
    top_k_final: int = 10
    graph_hops: int = 1

    # --- Chunking ---
    chunk_target_tokens: int = 550
    chunk_overlap_tokens: int = 80

    # --- LanceDB ---
    lancedb_table: str = "csr_chunks"

    def ensure_dirs(self) -> None:
        for d in (self.work_dir, self.output_dir):
            d.mkdir(parents=True, exist_ok=True)

    @property
    def lancedb_uri(self) -> str:
        return str(self.work_dir / "lancedb")

    @property
    def graph_path(self) -> Path:
        return self.work_dir / "knowledge_graph.gpickle"

    @property
    def sources_cache(self) -> Path:
        return self.work_dir / "sources.json"

    @property
    def chunk_preview(self) -> Path:
        return self.work_dir / "chunks_preview.md"

    @property
    def generated_preview(self) -> Path:
        return self.work_dir / "generated_preview.md"

    @property
    def template_cache(self) -> Path:
        return self.work_dir / "template.json"


# Template run-level font colors and their authoring meaning.
# Runs in these colors are *guidance* (instructional) and are NOT retained
# verbatim in the authored CSR — they tell the model what to write.
GUIDANCE_COLORS = {
    "FF0000": "instruction",   # red: <placeholder> / instructional prose
    "0070C0": "optional",      # blue: [optional bracketed headers/content]
    "00B050": "iso_requirement",  # green: ISO 14155 enumerated requirements
    "E36C0A": "regulatory",    # orange: "EU MDR 2017" labels
    "7030A0": "note",          # purple: NOTE: ...
    "0000FF": "toc",           # blue2: TOC field numbers (ignore)
}
