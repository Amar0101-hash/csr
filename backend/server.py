"""FastAPI backend for the CSR GraphRAG Explorer.

Serves the section list, each section's generated content, its FILLED_BY source
traceability/lineage, the coverage heatmap, and lets a user edit a section or
regenerate it (optionally with a custom prompt). Generated content is cached on
the RagTemplateSection nodes so the UI is instant after first generation.

Run:  uv run python graphrag_prototype/webapp/server.py   ->  http://localhost:8000
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time

# repo root = parent of this backend/ package (used to locate the frontend build)
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from neo4j import GraphDatabase  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from graph_rag.gr_config import SETTINGS  # noqa: E402
from graph_rag.dataingestion.template_graph import L_TSECTION  # noqa: E402
from graph_rag.trace_view import section_view, coverage_view, section_sort_key  # noqa: E402
from graph_rag.generate import author_section  # noqa: E402
from graph_rag.audit import log_event, events_for  # noqa: E402

app = FastAPI(title="CSR GraphRAG Explorer")
_driver = GraphDatabase.driver(
    SETTINGS.neo4j_uri, auth=(SETTINGS.neo4j_user, SETTINGS.neo4j_password)
)
_DB = SETTINGS.neo4j_database


def _run(cypher: str, **params):
    with _driver.session(database=_DB) as s:
        return [r.data() for r in s.run(cypher, **params)]


# ---------- read APIs ----------

@app.get("/api/sections")
def list_sections():
    rows = _run(f"""
        MATCH (t:{L_TSECTION})
        OPTIONAL MATCH (t)-[f:FILLED_BY]->()
        WITH t, count(f) AS sources
        RETURN t.number AS number, t.title AS title, t.level AS level,
               t.generate AS generate, sources,
               (t.content IS NOT NULL) AS has_content,
               coalesce(t.excluded, false) AS excluded,
               coalesce(t.approved, false) AS approved,
               t.method_used AS method_used
    """)
    rows.sort(key=lambda r: section_sort_key(r["number"]))
    return rows


@app.get("/api/sections/{number}")
def section_detail(number: str):
    rec = _run(f"""
        MATCH (t:{L_TSECTION} {{number: $n}})
        OPTIONAL MATCH (t)-[f:FILLED_BY]->(s:RagSection)
        RETURN t.number AS number, t.title AS title, t.guidance AS guidance,
               t.content AS content, t.citations AS citations,
               t.verification AS verification,
               coalesce(t.excluded, false) AS excluded,
               coalesce(t.approved, false) AS approved,
               t.method_used AS method_used,
               collect(CASE WHEN s IS NULL THEN NULL ELSE {{
                 id: s.id, doc: s.doc, path: s.path, name: s.name, kind: s.kind,
                 preview: s.preview, score: f.score, role: f.role,
                 method: f.method }} END) AS sources
    """, n=number)
    if not rec:
        return JSONResponse({"error": "not found"}, status_code=404)
    d = rec[0]
    d["sources"] = sorted([x for x in d["sources"] if x],
                          key=lambda x: -(x["score"] or 0))
    for key in ("citations", "verification"):
        if isinstance(d.get(key), str):
            try:
                d[key] = json.loads(d[key])
            except Exception:
                pass
    return d


class ExcludeReq(BaseModel):
    excluded: bool


@app.post("/api/sections/{number}/exclude")
def set_excluded(number: str, req: ExcludeReq):
    """Mark a template section as not applicable to this study (or restore it).
    Excluded sections are skipped by full generation and removed from the
    assembled .docx/PDF; they stay in the UI so they can be added back."""
    _run(f"MATCH (t:{L_TSECTION} {{number: $n}}) SET t.excluded = $e",
         n=number, e=req.excluded)
    log_event("exclude" if req.excluded else "restore", number)
    return {"ok": True, "number": number, "excluded": req.excluded}


@app.get("/api/coverage")
def coverage():
    return coverage_view()


@app.get("/api/graph/{number}")
def graph(number: str):
    return section_view(number)


# ---------- full-document generation (background job with progress) ----------

_GEN_JOB = {"running": False, "done": 0, "total": 0, "current": [],
            "errors": [], "finished_at": None}
_GEN_LOCK = threading.Lock()


class FullGenReq(BaseModel):
    effort: str = "medium"
    workers: int = 4
    method: str = "hybrid"  # vector | graph | hybrid


def _run_full_generation(effort: str, workers: int, method: str = "hybrid") -> None:
    from concurrent.futures import ThreadPoolExecutor
    from graph_rag.generate import _spec_map

    try:
        excluded = {r["n"] for r in _run(
            f"MATCH (t:{L_TSECTION}) WHERE coalesce(t.excluded, false) "
            "RETURN t.number AS n")}
        specs = [s for s in _spec_map().values()
                 if getattr(s, "generate", False) and s.number not in excluded]
        specs.sort(key=lambda s: section_sort_key(s.number))
        with _GEN_LOCK:
            _GEN_JOB["total"] = len(specs)

        def one(spec):
            with _GEN_LOCK:
                _GEN_JOB["current"].append(spec.number)
            try:
                gs = author_section_method(spec.number, method=method, effort=effort)
                if gs.paragraphs:
                    cites = [{"doc": c.doc, "path": c.section_path, "quote": c.quote}
                             for c in gs.citations]
                    _persist(spec.number, "\n\n".join(gs.paragraphs), cites,
                             gs.verification, bump=False, method=method)
                else:
                    with _GEN_LOCK:
                        _GEN_JOB["errors"].append(f"§{spec.number}: {gs.notes or 'no content'}")
            except Exception as e:
                with _GEN_LOCK:
                    _GEN_JOB["errors"].append(f"§{spec.number}: {type(e).__name__}: {e}")
            finally:
                with _GEN_LOCK:
                    _GEN_JOB["current"].remove(spec.number)
                    _GEN_JOB["done"] += 1

        log_event("full-generation-started", sections=len(specs),
                  effort=effort, workers=workers, method=method)
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            list(pool.map(one, specs))
        if specs:
            _bump_minor()  # one version bump for the whole run
        log_event("full-generation-finished", sections=len(specs),
                  failed=len(_GEN_JOB["errors"]))
    finally:
        with _GEN_LOCK:
            _GEN_JOB["running"] = False
            _GEN_JOB["finished_at"] = time.time()


@app.post("/api/report/generate")
def generate_full(req: FullGenReq):
    """Author every generate-marked section (overwrites cached content/edits).
    Returns immediately; poll /api/report/generate/status for progress."""
    with _GEN_LOCK:
        if _GEN_JOB["running"]:
            return JSONResponse({"error": "A full generation is already running."},
                                status_code=409)
        _GEN_JOB.update(running=True, done=0, total=0, current=[],
                        errors=[], finished_at=None)
    threading.Thread(target=_run_full_generation,
                     args=(req.effort, req.workers, req.method), daemon=True).start()
    return {"started": True, "method": req.method}


@app.get("/api/report/generate/status")
def generate_full_status():
    with _GEN_LOCK:
        return dict(_GEN_JOB)


# ---------- report download (.docx built from cached sections; PDF via Word) ----------

@app.get("/api/report/docx")
def report_docx():
    from graph_rag.generate import build_docx_from_cache
    try:
        path = build_docx_from_cache()
    except Exception as e:
        return JSONResponse({"error": f"{type(e).__name__}: {e}"}, status_code=500)
    return FileResponse(
        path, filename="GraphRAG_Report.docx",
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


@app.get("/api/report/pdf")
def report_pdf():
    """Build the .docx, then convert with docx2pdf (drives Microsoft Word via COM;
    run in a subprocess so COM never touches the server's threads)."""
    import subprocess
    from graph_rag.generate import build_docx_from_cache
    try:
        docx_path = build_docx_from_cache()
    except Exception as e:
        return JSONResponse({"error": f"{type(e).__name__}: {e}"}, status_code=500)

    pdf_path = docx_path.with_suffix(".pdf")
    try:
        conv = subprocess.run(
            [sys.executable, "-c",
             "import sys; from docx2pdf import convert; convert(sys.argv[1], sys.argv[2])",
             str(docx_path), str(pdf_path)],
            capture_output=True, text=True, timeout=180,
        )
    except subprocess.TimeoutExpired:
        return JSONResponse({"error": "PDF conversion timed out"}, status_code=504)
    if conv.returncode != 0 or not pdf_path.exists():
        return JSONResponse(
            {"error": "PDF conversion failed — docx2pdf needs Microsoft Word installed.",
             "detail": (conv.stderr or conv.stdout or "")[-400:]},
            status_code=501,
        )
    return FileResponse(pdf_path, filename="GraphRAG_Report.pdf", media_type="application/pdf")


# ---------- retrieval comparison (Vector RAG vs Graph RAG; hybrid TBD) ----------

class CompareReq(BaseModel):
    query: str
    k: int = 8
    graph_mode: str = "vector"  # "vector" = Neo4j native vector index; "cypher" = LLM text-to-Cypher


_VECTOR_RETRIEVER = None  # lazy: needs the LanceDB index built by `csr ingest`
_HYBRID_RETRIEVER = None


def _vector_retriever():
    global _VECTOR_RETRIEVER
    if _VECTOR_RETRIEVER is None:
        from vector_rag.pipeline import _load_retriever
        _VECTOR_RETRIEVER = _load_retriever(SETTINGS)
    return _VECTOR_RETRIEVER


def _hybrid_retriever():
    global _HYBRID_RETRIEVER
    if _HYBRID_RETRIEVER is None:
        from hybrid_rag import build_hybrid_retriever
        _HYBRID_RETRIEVER = build_hybrid_retriever(SETTINGS)
    return _HYBRID_RETRIEVER


_AUTHOR_CLIENT = None


def _author_client():
    global _AUTHOR_CLIENT
    if _AUTHOR_CLIENT is None:
        from vector_rag.generation.llm import ClaudeClient
        _AUTHOR_CLIENT = ClaudeClient(SETTINGS)
    return _AUTHOR_CLIENT


def author_section_method(number: str, method: str = "hybrid",
                          custom_prompt: str | None = None, effort: str = "medium"):
    """Author a section with the chosen retrieval strategy. The generation core
    (prompt, LLM call, verification) is shared across all three — only retrieval
    differs — so the three modes are directly comparable.

      vector: LanceDB dense + FTS (RRF fusion)
      graph:  Neo4j FILLED_BY sources for this template section
      hybrid: vector + FTS + Neo4j entity-graph expansion, consensus-fused
    """
    from graph_rag.generate import (author_section as graph_author,
                                     author_from_retrieved, _spec_map)
    SETTINGS.effort = effort
    if method == "graph":
        return graph_author(number, custom_prompt=custom_prompt, effort=effort)

    spec = _spec_map().get(number)
    if spec is None:
        from vector_rag.models import GeneratedSection
        return GeneratedSection(key=number, title=number, paragraphs=[],
                                notes="Unknown section.", verification={})
    from vector_rag.generation.prompts import (build_query, doc_types_for,
                                               guaranteed_tables_for)
    retriever = _hybrid_retriever() if method == "hybrid" else _vector_retriever()
    query = build_query(spec)
    retrieved = retriever.retrieve(query, doc_types=doc_types_for(spec),
                                   guarantee_tables=guaranteed_tables_for(spec))
    return author_from_retrieved(spec, retrieved, _author_client(),
                                 custom_prompt=custom_prompt, method=method)


@app.post("/api/compare")
def compare(req: CompareReq):
    """Run the same query through both retrieval systems, side by side.

    vector: the main app (LanceDB vector + full-text search, RRF fusion).
    graph:  the prototype (Neo4j) — native vector index, or LLM text-to-Cypher.
    hybrid: vector + FTS + in-memory graph expansion, consensus-fused (RRF).
    """
    import time
    out = {"query": req.query}

    try:
        r = _vector_retriever()
        t0 = time.perf_counter()
        hits = r.retrieve(req.query, k=req.k)
        out["vector"] = {
            "latency_ms": round((time.perf_counter() - t0) * 1000),
            "results": [
                {"id": h.chunk.id, "doc": h.chunk.doc, "kind": h.chunk.kind,
                 "path": h.chunk.section_path, "preview": h.chunk.text[:280],
                 "score": round(h.score, 4), "provenance": h.provenance}
                for h in hits
            ],
        }
    except Exception as e:
        out["vector"] = {"error": f"{type(e).__name__}: {e}"}

    try:
        t0 = time.perf_counter()
        if req.graph_mode == "cypher":
            from graph_rag.text2cypher import ask
            res = ask(req.query, verbose=False)
            out["graph"] = {
                "latency_ms": round((time.perf_counter() - t0) * 1000),
                "cypher": res.get("cypher"), "rows": res.get("rows"),
                "error": res.get("error"),
            }
        else:
            from graph_rag.retrieve import vector_search
            rows = vector_search(req.query, k=req.k)
            out["graph"] = {
                "latency_ms": round((time.perf_counter() - t0) * 1000),
                "results": [
                    {"doc": g["doc"], "kind": g["kind"], "path": g["path"],
                     "preview": g["preview"], "score": round(g["score"], 4),
                     "provenance": "neo4j-vector"}
                    for g in rows
                ],
            }
    except Exception as e:
        out["graph"] = {"error": f"{type(e).__name__}: {e}"}

    try:
        hr = _hybrid_retriever()
        t0 = time.perf_counter()
        hits = hr.retrieve(req.query, k=req.k)
        results = [
            {"id": h.chunk.id, "doc": h.chunk.doc, "kind": h.chunk.kind,
             "path": h.chunk.section_path, "preview": h.chunk.text[:280],
             "score": round(h.score, 4), "provenance": h.provenance}
            for h in hits
        ]
        # consensus = surfaced by more than one signal (the hybrid's advantage);
        # graph_only = chunks a pure vector retriever would have missed.
        out["hybrid"] = {
            "latency_ms": round((time.perf_counter() - t0) * 1000),
            "results": results,
            "consensus": sum(1 for r in results if "+" in r["provenance"]),
            "graph_only": sum(1 for r in results if r["provenance"] == "graph"),
        }
    except Exception as e:
        out["hybrid"] = {"error": f"{type(e).__name__}: {e}"}

    return out


# ---------- write APIs ----------

class GenReq(BaseModel):
    custom_prompt: str | None = None
    effort: str = "medium"
    preview: bool = False  # true: return the proposal WITHOUT persisting
    method: str = "hybrid"  # vector | graph | hybrid


class SaveReq(BaseModel):
    content: str


class AcceptReq(BaseModel):
    content: str
    citations: list = []
    verification: dict = {}


def _persist(number: str, content: str, citations=None, verification=None,
             bump: bool = True, method: str | None = None):
    # Any content change un-approves the section and (by default) bumps the
    # document's minor version. The full-generation job bumps once at the end.
    # `method` (when given) records which retrieval strategy produced the content.
    _run(f"""
        MATCH (t:{L_TSECTION} {{number: $n}})
        SET t.content = $c, t.citations = $cit, t.verification = $ver,
            t.approved = false, t.method_used = coalesce($method, t.method_used)
    """, n=number, c=content, cit=json.dumps(citations or []),
        ver=json.dumps(verification or {}), method=method)
    if bump:
        _bump_minor()


# ---------- document version & approval workflow ----------
# Drafts move 0.1 -> 0.2 -> ... on every content change. When every authorable,
# non-excluded section has content AND is approved, the document can be promoted
# to the next MAJOR version (1.0, 2.0, ...). Any later change makes it a draft
# again (1.1, 1.2, ...).

def _version() -> dict:
    rows = _run(
        "MERGE (m:RagMeta {id:'doc'}) "
        "ON CREATE SET m.major = 0, m.minor = 0 "
        "RETURN coalesce(m.major, 0) AS major, coalesce(m.minor, 0) AS minor"
    )
    return rows[0]


def _bump_minor() -> None:
    _run("MERGE (m:RagMeta {id:'doc'}) "
         "SET m.minor = coalesce(m.minor, 0) + 1, m.major = coalesce(m.major, 0)")


@app.get("/api/version")
def version():
    v = _version()
    d = _run(f"""
        MATCH (t:{L_TSECTION}) WHERE t.generate AND NOT coalesce(t.excluded, false)
        RETURN count(t) AS total,
               sum(CASE WHEN t.content IS NOT NULL THEN 1 ELSE 0 END) AS with_content,
               sum(CASE WHEN coalesce(t.approved, false) AND t.content IS NOT NULL
                   THEN 1 ELSE 0 END) AS approved
    """)[0]
    all_approved = d["total"] > 0 and d["approved"] == d["total"]
    is_approved_release = v["major"] > 0 and v["minor"] == 0
    return {**v, **d, "all_approved": all_approved,
            "can_approve": all_approved and not is_approved_release,
            "state": ("approved" if is_approved_release
                      else "draft" if d["with_content"] else "empty")}


class ApproveReq(BaseModel):
    approved: bool = True


@app.post("/api/sections/{number}/approve")
def approve_section(number: str, req: ApproveReq):
    _run(f"MATCH (t:{L_TSECTION} {{number: $n}}) SET t.approved = $a",
         n=number, a=req.approved)
    log_event("approve" if req.approved else "unapprove", number)
    return {"ok": True, "number": number, "approved": req.approved}


@app.post("/api/version/approve")
def approve_document():
    """Promote to the next major version — only when every authorable,
    non-excluded section has content and has been approved."""
    st = version()
    if not st["all_approved"]:
        return JSONResponse(
            {"error": f"Not all sections approved yet "
                      f"({st['approved']}/{st['total']} approved, "
                      f"{st['with_content']}/{st['total']} have content)."},
            status_code=409)
    _run("MERGE (m:RagMeta {id:'doc'}) "
         "SET m.major = coalesce(m.major, 0) + 1, m.minor = 0")
    v = version()
    log_event("release", version=f"v{v['major']}.{v['minor']}",
              sections_approved=v["approved"])
    return v


@app.post("/api/sections/{number}/generate")
def generate(number: str, req: GenReq):
    gs = author_section_method(number, method=req.method,
                               custom_prompt=req.custom_prompt, effort=req.effort)
    content = "\n\n".join(gs.paragraphs)
    cites = [{"doc": c.doc, "path": c.section_path, "quote": c.quote} for c in gs.citations]
    if not req.preview:
        _persist(number, content, cites, gs.verification, method=req.method)
    return {"content": content, "citations": cites,
            "verification": gs.verification, "notes": gs.notes,
            "preview": req.preview, "method": req.method}


@app.post("/api/sections/{number}/accept")
def accept_regeneration(number: str, req: AcceptReq):
    """Persist a previewed regeneration the user reviewed and accepted."""
    _persist(number, req.content, req.citations, req.verification)
    log_event("accept-regeneration", number, chars=len(req.content),
              citations=len(req.citations))
    return {"ok": True}


@app.post("/api/sections/{number}/save")
def save(number: str, req: SaveReq):
    _persist(number, req.content)
    log_event("manual-edit", number, chars=len(req.content))
    return {"ok": True}


# ---------- explainability APIs: audit trail, numbers audit, source viewer ----------

@app.get("/api/audit/{number}")
def audit_for_section(number: str):
    return events_for(number)


@app.get("/api/audit")
def audit_all():
    return events_for(None, limit=100)


@app.get("/api/numbers-audit")
def numbers_audit():
    """Every material number in every generated section, with the source that
    supports it (or flagged unsupported). The document-wide fact check."""
    from vector_rag.generation.verify import _numbers, _is_material
    rows = _run(f"""
        MATCH (t:{L_TSECTION})
        WHERE t.content IS NOT NULL AND t.generate AND NOT coalesce(t.excluded, false)
        OPTIONAL MATCH (t)-[:FILLED_BY]->(s:RagSection)
        RETURN t.number AS number, t.title AS title, t.content AS content,
               collect(CASE WHEN s IS NULL THEN NULL ELSE
                       {{doc: s.doc, path: s.path, text: s.text}} END) AS sources
    """)
    rows.sort(key=lambda r: section_sort_key(r["number"]))
    sections, total, supported_total = [], 0, 0
    for r in rows:
        sources = [s for s in r["sources"] if s]
        seen, nums = set(), []
        for n in _numbers(r["content"]):
            if not _is_material(n) or n in seen:
                continue
            seen.add(n)
            src = next((s for s in sources if n in s["text"]), None)
            nums.append({"value": n, "supported": src is not None,
                         "doc": src["doc"] if src else None,
                         "path": src["path"] if src else None})
        if not nums:
            continue
        ok = sum(1 for x in nums if x["supported"])
        total += len(nums)
        supported_total += ok
        sections.append({"number": r["number"], "title": r["title"],
                         "numbers": nums, "supported": ok, "total": len(nums)})
    # sections with problems first, template order within each group
    sections.sort(key=lambda s: (s["supported"] == s["total"],
                                 section_sort_key(s["number"])))
    return {"total": total, "supported": supported_total, "sections": sections}


_SOURCE_CACHE = None  # ordered chunks from the main app's sources.json


def _source_chunks():
    global _SOURCE_CACHE
    if _SOURCE_CACHE is None:
        from vector_rag.ingestion.sources import load_chunks, load_all_sources
        if SETTINGS.sources_cache.exists():
            _SOURCE_CACHE = load_chunks(SETTINGS.sources_cache)
        else:  # no cache yet: chunk the study docs directly (one-time)
            _SOURCE_CACHE = load_all_sources(
                SETTINGS.study_dir, SETTINGS.chunk_target_tokens,
                SETTINGS.chunk_overlap_tokens)
    return _SOURCE_CACHE


@app.get("/api/source/{doc}/file")
def source_original_file(doc: str):
    """Download the original .docx this logical source doc came from."""
    from vector_rag.ingestion.sources import classify_source
    for path in sorted(SETTINGS.study_dir.glob("*.docx")):
        cls = classify_source(path.name)
        if cls and cls[0] == doc:
            return FileResponse(
                str(path), filename=path.name,
                media_type="application/vnd.openxmlformats-officedocument"
                           ".wordprocessingml.document")
    return JSONResponse({"error": f"no source file found for '{doc}'"},
                        status_code=404)


@app.get("/api/source/{doc}")
def source_document(doc: str):
    """The full source document, section by section in document order — the
    right-hand pane of the side-by-side source comparison."""
    secs = [{"id": c.id, "path": c.section_path, "kind": c.kind, "text": c.text}
            for c in _source_chunks() if c.doc == doc]
    if not secs:
        return JSONResponse({"error": f"unknown source document '{doc}'"},
                            status_code=404)
    return {"doc": doc, "sections": secs}


# ---------- static frontend ----------
# In production serve the built React app (frontend/dist). Until it's built,
# fall back to the vanilla legacy.html so the UI still works. For React dev,
# run `npm run dev` (Vite on :5173, which proxies /api to this server).
_FRONTEND = os.path.join(_ROOT, "frontend")
_DIST = os.path.join(_FRONTEND, "dist")

if os.path.isdir(os.path.join(_DIST, "assets")):
    app.mount("/assets", StaticFiles(directory=os.path.join(_DIST, "assets")), name="assets")
    _INDEX = os.path.join(_DIST, "index.html")
else:
    _INDEX = os.path.join(_FRONTEND, "legacy.html")


@app.get("/")
def index():
    return FileResponse(_INDEX)


if __name__ == "__main__":
    import uvicorn
    print("CSR GraphRAG Explorer -> http://localhost:8000")
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")
