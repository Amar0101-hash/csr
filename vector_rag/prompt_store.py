"""Per-section prompt versioning.

Every section is generated from a prompt (system + user). The **default** prompt
(v0) is the one we build automatically from the template guidance + sources. When
the user regenerates with a custom instruction, that becomes a **new version**,
set active. The **active** version is the one used going forward — so a prompt the
user likes becomes "latest". Everything is saved as one JSON per section under
`output/prompts/` (a readable, inspectable artifact) and exposed in the UI.

Version identity is the custom instruction text: the same instruction updates the
same version (no spam); a new instruction adds a version.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .config import Settings
from .section_doc import section_filename


def _dir(settings: Settings) -> Path:
    d = settings.output_dir / "prompts"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path(settings: Settings, number: str, title: str) -> Path:
    return _dir(settings) / f"{section_filename(number, title)}.json"


def _load(path: Path) -> dict | None:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def save_prompt_version(settings: Settings, number: str, title: str, *,
                        system: str, user: str, custom_instruction: str = "",
                        kind: str = "prose", method: str | None = None) -> int:
    """Save the exact prompt sent. Same custom_instruction -> updates that version;
    a new instruction -> new version. The version just used becomes active."""
    path = _path(settings, number, title)
    data = _load(path) or {"number": number, "title": title,
                           "active": 0, "versions": []}
    custom = (custom_instruction or "").strip()
    match = next((v for v in data["versions"]
                  if v.get("custom_instruction", "").strip() == custom), None)
    if match:
        match.update(system=system, user=user, kind=kind, method=method,
                     updated_at=_now())
        vid = match["id"]
    else:
        vid = max([v["id"] for v in data["versions"]], default=-1) + 1
        data["versions"].append({
            "id": vid,
            "label": "default" if not custom else f"custom {vid}",
            "custom_instruction": custom,
            "system": system, "user": user, "kind": kind, "method": method,
            "created_at": _now(), "updated_at": _now(),
        })
    data["active"] = vid
    data["title"] = title
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return vid


def get_prompts(settings: Settings, number: str, title: str) -> dict:
    return _load(_path(settings, number, title)) or {
        "number": number, "title": title, "active": None, "versions": []}


def set_active(settings: Settings, number: str, title: str, version_id: int) -> dict | None:
    path = _path(settings, number, title)
    data = _load(path)
    if not data:
        return None
    if any(v["id"] == version_id for v in data["versions"]):
        data["active"] = version_id
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return data


def active_custom_instruction(settings: Settings, number: str, title: str) -> str:
    """The custom instruction of the active version — used as the default for the
    next regeneration so a liked prompt persists."""
    data = get_prompts(settings, number, title)
    aid = data.get("active")
    for v in data.get("versions", []):
        if v["id"] == aid:
            return v.get("custom_instruction", "")
    return ""
