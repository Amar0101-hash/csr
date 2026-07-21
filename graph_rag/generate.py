"""Generate a full CSR .docx driven ENTIRELY by graph traversal of FILLED_BY.

For each authorable template section we pull its linked source sections from the
graph, then reuse the main app's grounding prompt + assembly (read-only imports)
so the ONLY difference vs. the production pipeline is the retrieval mechanism:
graph FILLED_BY edges here vs. the hybrid retriever there. Output goes to a
separate file so you can diff the two head-to-head.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from neo4j import GraphDatabase

from graph_rag.gr_config import SETTINGS
from graph_rag.dataingestion.template_graph import L_TSECTION, _inherit_guidance

from vector_rag.ingestion.template_parser import parse_template
from vector_rag.models import Chunk, Citation, GeneratedSection
from vector_rag.knowledge.retriever import RetrievedChunk
from vector_rag.generation.llm import ClaudeClient
from vector_rag.generation.prompts import build_user_prompt, SYSTEM_WRITER
from vector_rag.generation.verify import verify_section
from vector_rag.assembly.docx_builder import build_report

_FETCH = f"""
MATCH (t:{L_TSECTION} {{number: $num}})-[f:FILLED_BY]->(s:RagSection)
RETURN s.id AS id, s.doc AS doc, s.path AS path, s.text AS text,
       s.kind AS kind, f.score AS score
ORDER BY f.score DESC LIMIT 14
"""


def _driver():
    return GraphDatabase.driver(
        SETTINGS.neo4j_uri, auth=(SETTINGS.neo4j_user, SETTINGS.neo4j_password)
    )


def _doc_type(doc: str) -> str:
    return "tfl" if doc.startswith("tfl") else doc


def _persist_content(driver, number: str, gs: GeneratedSection) -> None:
    """Cache a section's generated content on its template node so the web UI
    shows it instantly."""
    import json
    from graph_rag.dataingestion.template_graph import L_TSECTION
    cites = [{"doc": c.doc, "path": c.section_path, "quote": c.quote} for c in gs.citations]
    with driver.session(database=SETTINGS.neo4j_database) as s:
        s.run(f"MATCH (t:{L_TSECTION} {{number: $n}}) "
              f"SET t.content = $c, t.citations = $cit, t.verification = $v",
              n=number, c="\n\n".join(gs.paragraphs),
              cit=json.dumps(cites), v=json.dumps(gs.verification or {}))


def author_from_retrieved(spec, retrieved, client: ClaudeClient,
                          custom_prompt: str | None = None,
                          method: str = "graph",
                          style_exemplar: str | None = None) -> GeneratedSection:
    """Shared generation core for all three retrieval strategies. Given a section
    spec and a list of RetrievedChunk (from vector / graph / hybrid retrieval),
    build the grounded prompt, author, verify, and attach citations. `method` is
    recorded in the audit trail so runs are attributable to their retriever.
    `style_exemplar` is the masked human-CSR section (few-shot) to mirror register
    and brevity."""
    if not retrieved:
        return GeneratedSection(key=spec.key, title=spec.title, paragraphs=[],
                                notes=f"No sources retrieved ({method}).",
                                verification={"grounded": True})
    user, label_map = build_user_prompt(spec, retrieved, style_exemplar=style_exemplar)
    if custom_prompt and custom_prompt.strip():
        user += ("\n\nADDITIONAL AUTHOR INSTRUCTION (obey this while staying grounded "
                 f"in the sources above):\n{custom_prompt.strip()}\n")
    from graph_rag.audit import log_event
    # persist the exact prompt sent, as a versioned artifact the UI exposes
    try:
        from vector_rag.prompt_store import save_prompt_version
        save_prompt_version(SETTINGS, spec.number, spec.title,
                            system=SYSTEM_WRITER, user=user,
                            custom_instruction=(custom_prompt or ""),
                            kind="prose", method=method)
    except Exception:
        pass
    audit_sources = [{"id": r.chunk.id, "doc": r.chunk.doc,
                      "path": r.chunk.section_path, "score": r.score,
                      "provenance": getattr(r, "provenance", method)}
                     for r in retrieved]
    try:
        data = client.complete_json(SYSTEM_WRITER, user)
    except Exception as e:
        log_event("generate-error", spec.number, method=method,
                  model=SETTINGS.gen_model,
                  effort=SETTINGS.effort, error=f"{type(e).__name__}: {e}",
                  sources=audit_sources)
        return GeneratedSection(key=spec.key, title=spec.title, paragraphs=[],
                                notes=f"Generation error: {type(e).__name__}: {e}",
                                verification={"grounded": False})

    paras = [p.strip() for p in data.get("paragraphs", []) if str(p).strip()]
    raw_cites = data.get("citations", []) or []
    heading = (data.get("heading") or "").strip()
    gs = GeneratedSection(
        key=spec.key, title=spec.title, paragraphs=paras,
        notes=data.get("notes") or None,
        verification=verify_section(paras, raw_cites, retrieved, label_map),
        heading_override=heading if (heading and spec.class_hint) else None,
    )
    for c in raw_cites:
        cid = label_map.get(c.get("source_id"))
        if not cid:
            continue
        ch = next((x.chunk for x in retrieved if x.chunk.id == cid), None)
        gs.citations.append(Citation(chunk_id=cid, doc=ch.doc if ch else "?",
                                     section_path=ch.section_path if ch else "",
                                     quote=str(c.get("quote", ""))[:400]))
    log_event("generate", spec.number, method=method, model=SETTINGS.gen_model,
              effort=SETTINGS.effort,
              custom_prompt=(custom_prompt or None),
              sources=audit_sources, prompt=user,
              paragraphs=len(paras), citations=len(gs.citations),
              verification=gs.verification)
    return gs


def _author(spec, client: ClaudeClient, driver, custom_prompt: str | None = None) -> GeneratedSection:
    """Graph retrieval: pull the section's FILLED_BY sources from Neo4j, then author."""
    with driver.session(database=SETTINGS.neo4j_database) as sess:
        rows = sess.run(_FETCH, num=spec.number).data()
    if not rows:
        return GeneratedSection(key=spec.key, title=spec.title, paragraphs=[],
                                notes="No FILLED_BY sources linked.",
                                verification={"grounded": True})
    retrieved = [
        RetrievedChunk(
            Chunk(id=r["id"], doc=r["doc"], doc_type=_doc_type(r["doc"]),
                  section_path=r["path"], text=r["text"], kind=r["kind"]),
            r["score"] or 0.0, "graph",
        )
        for r in rows
    ]
    return author_from_retrieved(spec, retrieved, client, custom_prompt, method="graph")


def generate_report(effort: str = "medium", workers: int = 4, limit: int | None = None,
                    verbose: bool = True):
    SETTINGS.effort = effort
    sections = parse_template(SETTINGS.template_path)
    _inherit_guidance(sections)
    targets = [s for s in sections if s.generate]
    if limit:
        targets = targets[:limit]

    client = ClaudeClient(SETTINGS)
    generated: dict[str, GeneratedSection] = {}
    driver = _driver()
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = [(s, pool.submit(_author, s, client, driver)) for s in targets]
            for i, (spec, fut) in enumerate(futs, 1):
                gs = fut.result()
                generated[spec.key] = gs
                _persist_content(driver, spec.number, gs)  # populate the web UI
                if verbose:
                    print(f"[gr-gen] ({i}/{len(targets)}) §{spec.number} {spec.title[:34]} "
                          f"-> {len(gs.paragraphs)} paras, {len(gs.citations)} cites")
    finally:
        driver.close()

    out = SETTINGS.output_dir / "GraphRAG_Report.docx"
    stats = build_report(SETTINGS.template_path, sections, generated, out)
    if verbose:
        print(f"[gr-gen] {stats}")
        print(f"[gr-gen] wrote {stats.get('output_path', out)}")
    return out


# ---- single-section API for the web UI (lazy caches) ----
_SPECS: dict[str, object] | None = None
_CLIENT: ClaudeClient | None = None


def _spec_map() -> dict[str, object]:
    global _SPECS
    if _SPECS is None:
        secs = parse_template(SETTINGS.template_path)
        _inherit_guidance(secs)
        _SPECS = {s.number: s for s in secs if s.number}
    return _SPECS


def author_section(number: str, custom_prompt: str | None = None,
                   effort: str = "medium") -> GeneratedSection:
    global _CLIENT
    SETTINGS.effort = effort
    spec = _spec_map().get(number)
    if spec is None:
        return GeneratedSection(key=number, title=number, paragraphs=[],
                                notes="Unknown section.", verification={})
    if _CLIENT is None:
        _CLIENT = ClaudeClient(SETTINGS)
    drv = _driver()
    try:
        return _author(spec, _CLIENT, drv, custom_prompt=custom_prompt)
    finally:
        drv.close()


def build_docx_from_cache(out_name: str = "GraphRAG_Report.docx"):
    """Assemble the template-preserving .docx from whatever section content is
    cached on the template nodes (i.e. everything generated so far via the UI
    or a full run). Returns the written path."""
    import json
    from pathlib import Path

    secs = parse_template(SETTINGS.template_path)
    _inherit_guidance(secs)
    driver = _driver()
    try:
        with driver.session(database=SETTINGS.neo4j_database) as s:
            rows = s.run(
                f"MATCH (t:{L_TSECTION}) WHERE t.content IS NOT NULL "
                "RETURN t.number AS number, t.content AS content, "
                "t.citations AS citations, t.verification AS verification, "
                "t.heading_override AS heading_override, t.table_fills AS table_fills"
            ).data()
            excluded_nums = {r["n"] for r in s.run(
                f"MATCH (t:{L_TSECTION}) WHERE coalesce(t.excluded, false) "
                "RETURN t.number AS n"
            ).data()}
    finally:
        driver.close()

    def _loads(raw, default):
        try:
            return json.loads(raw) if raw else default
        except Exception:
            return default

    by_num = {s.number: s for s in secs if s.number}
    generated: dict[str, GeneratedSection] = {}
    for r in rows:
        spec = by_num.get(r["number"])
        if spec is None:
            continue
        cites = _loads(r["citations"], [])
        from vector_rag.models import TableFill
        tfs = _loads(r.get("table_fills"), [])
        generated[spec.key] = GeneratedSection(
            key=spec.key, title=spec.title,
            paragraphs=[p for p in (r["content"] or "").split("\n\n") if p.strip()],
            citations=[Citation(chunk_id="", doc=c.get("doc", ""),
                                section_path=c.get("path", ""), quote=c.get("quote", ""))
                       for c in cites],
            verification=_loads(r["verification"], {}),
            heading_override=r.get("heading_override"),
            table_fills=[TableFill(**tf) for tf in tfs] if tfs else [],
        )

    exclude_keys = {by_num[n].key for n in excluded_nums if n in by_num}
    SETTINGS.output_dir.mkdir(parents=True, exist_ok=True)
    out = SETTINGS.output_dir / out_name
    stats = build_report(SETTINGS.template_path, secs, generated, out,
                         exclude_keys=exclude_keys)
    return Path(stats.get("output_path", out))


if __name__ == "__main__":
    import sys
    lim = int(sys.argv[1]) if len(sys.argv) > 1 else None
    generate_report(limit=lim)
