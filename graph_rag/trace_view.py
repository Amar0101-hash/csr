"""Traceability views: emit the SMALL, readable subgraph for one section
(the section node + its FILLED_BY source nodes) as JSON a UI can render with
react-force-graph / Cytoscape / Neo4j NVL — instead of the raw hairball.

Also emits a coverage view (heatmap data) — section -> source count / gap.
"""
from __future__ import annotations

import json
from pathlib import Path

from neo4j import GraphDatabase

from gr_config import SETTINGS
from dataingestion.template_graph import L_TSECTION

_DOC_COLORS = {
    "protocol": "#2563eb", "sap": "#7c3aed", "mop": "#0891b2",
    "tfl_effectiveness": "#059669", "tfl_safety": "#dc2626",
    "tfl_conduct": "#d97706", "tfl_listings": "#65a30d",
}


def _driver():
    return GraphDatabase.driver(
        SETTINGS.neo4j_uri, auth=(SETTINGS.neo4j_user, SETTINGS.neo4j_password)
    )


def section_sort_key(number: str) -> list[int]:
    """Natural order for dotted section numbers: 1 < 1.1 < 2 < 10 < 11.5.5.1
    (plain string ORDER BY sorts '10' before '2')."""
    parts = []
    for p in (number or "").split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    return parts


def section_view(number: str) -> dict:
    q = f"""
    MATCH (t:{L_TSECTION} {{number: $num}})
    OPTIONAL MATCH (t)-[f:FILLED_BY]->(s:RagSection)
    RETURN t.number AS number, t.title AS title,
           collect(CASE WHEN s IS NULL THEN NULL ELSE {{
             id: s.id, doc: s.doc, path: s.path, name: s.name, kind: s.kind,
             preview: s.preview, score: f.score, method: f.method }} END) AS sources
    """
    with _driver() as drv, drv.session(database=SETTINGS.neo4j_database) as sess:
        rec = sess.run(q, num=number).single()
    if not rec:
        return {"error": f"section {number} not found"}

    tkey = f"§{rec['number']}"
    nodes = [{"id": tkey, "label": f"§{rec['number']} {rec['title']}",
              "type": "section", "color": "#111827"}]
    edges = []
    for s in [x for x in rec["sources"] if x]:
        nodes.append({
            "id": s["id"], "label": s["name"], "type": "source",
            "doc": s["doc"], "kind": s["kind"], "preview": s["preview"],
            "path": s["path"],
            "color": _DOC_COLORS.get(s["doc"], "#6b7280"),
        })
        edges.append({"source": tkey, "target": s["id"],
                      "score": s["score"], "method": s["method"]})
    edges.sort(key=lambda e: -(e["score"] or 0))
    return {"section": {"number": rec["number"], "title": rec["title"]},
            "nodes": nodes, "edges": edges}


def coverage_view() -> list[dict]:
    q = f"""
    MATCH (t:{L_TSECTION}) WHERE t.generate
    OPTIONAL MATCH (t)-[f:FILLED_BY]->()
    WITH t, count(f) AS n
    RETURN t.number AS number, t.title AS title, n AS sources
    """
    with _driver() as drv, drv.session(database=SETTINGS.neo4j_database) as sess:
        rows = [dict(r) for r in sess.run(q).data()]
    rows.sort(key=lambda r: section_sort_key(r["number"]))
    return rows


def export_all(out_dir: Path | None = None) -> Path:
    out_dir = out_dir or (SETTINGS.output_dir / "trace_views")
    out_dir.mkdir(parents=True, exist_ok=True)
    cov = coverage_view()
    (out_dir / "coverage.json").write_text(json.dumps(cov, indent=2), encoding="utf-8")
    for row in cov:
        view = section_view(row["number"])
        safe = row["number"].replace(".", "_")
        (out_dir / f"section_{safe}.json").write_text(
            json.dumps(view, indent=2), encoding="utf-8")
    return out_dir


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "export":
        d = export_all()
        print(f"wrote per-section trace views + coverage.json to {d}")
    else:
        num = sys.argv[1] if len(sys.argv) > 1 else "6.3.5"
        print(json.dumps(section_view(num), indent=2))
