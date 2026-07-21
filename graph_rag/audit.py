"""Append-only audit trail (JSONL) for the GraphRAG explorer.

Every generation run, manual edit, approval, exclusion, and release is recorded
with enough detail to reconstruct HOW each section's content was authored:
timestamp, model, effort, the exact prompt, the retrieved sources with scores,
and the verification result. The file is append-only — events are never
rewritten — so it can serve as the regulatory audit story.
"""
from __future__ import annotations

import json
import time

from graph_rag.gr_config import SETTINGS

AUDIT_PATH = SETTINGS.output_dir / "graphrag_audit.jsonl"
_MAX_PROMPT_CHARS = 20000


def log_event(event: str, number: str | None = None, **details) -> None:
    rec: dict = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "event": event}
    if number:
        rec["number"] = number
    if isinstance(details.get("prompt"), str):
        details["prompt"] = details["prompt"][:_MAX_PROMPT_CHARS]
    rec.update(details)
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(AUDIT_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def events_for(number: str | None = None, limit: int = 50) -> list[dict]:
    """Events for one section (or all if number is None), newest first."""
    if not AUDIT_PATH.exists():
        return []
    out: list[dict] = []
    with open(AUDIT_PATH, encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if number is None or rec.get("number") == number:
                out.append(rec)
    return out[-limit:][::-1]
