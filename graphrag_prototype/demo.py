"""GraphRAG prototype demo CLI.

Folders: dataingestion/ (build the graph)  ·  backend/ (API, retrieval,
generation)  ·  frontend/ (web UI).

    python graphrag_prototype/demo.py build         # dataingestion: study graph + vectors
    python graphrag_prototype/demo.py enrich        # dataingestion: readable captions
    python graphrag_prototype/demo.py template      # dataingestion: template + FILLED_BY
    python graphrag_prototype/demo.py search "<q>"   # backend: vector search in Neo4j
    python graphrag_prototype/demo.py ask "<q>"      # backend: LLM writes+runs Cypher
    python graphrag_prototype/demo.py fill 6.3.5     # backend: generate via traversal
    python graphrag_prototype/demo.py report [N]     # backend: full graph-driven .docx
    python graphrag_prototype/demo.py trace 6.3.5    # backend: section->sources JSON
    python graphrag_prototype/demo.py diff           # backend: compare vs main pipeline
    # web UI:  python graphrag_prototype/backend/server.py  -> http://localhost:8000
"""
from __future__ import annotations

import sys


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    cmd = sys.argv[1]
    arg = sys.argv[2] if len(sys.argv) > 2 else ""

    if cmd == "build":
        from dataingestion.build_graph import build
        build()

    elif cmd == "enrich":
        from dataingestion.enrich import enrich
        enrich()

    elif cmd == "template":
        from dataingestion.template_graph import build_template, coverage
        build_template()
        coverage()

    elif cmd == "coverage":
        from dataingestion.template_graph import coverage
        coverage()

    elif cmd == "search":
        from backend.retrieve import vector_search
        print(f"\n=== Neo4j vector search: {arg!r} ===")
        for r in vector_search(arg or "primary effectiveness endpoint", k=6):
            print(f"{r['score']:.3f}  [{r['doc']}/{r['kind']}] {r['path'][:45]}")
            print(f"        {r['preview']}")

    elif cmd == "ask":
        from backend.text2cypher import ask
        ask(arg or "How many sections does each document have?")

    elif cmd == "fill":
        from backend.fill_section import fill
        fill(arg or "6.2.1")

    elif cmd == "report":
        from backend.generate import generate_report
        limit = int(arg) if arg.isdigit() else None
        generate_report(limit=limit)

    elif cmd == "trace":
        import json
        from backend.trace_view import section_view
        print(json.dumps(section_view(arg or "6.3.5"), indent=2))

    elif cmd == "trace-export":
        from backend.trace_view import export_all
        d = export_all()
        print(f"wrote per-section trace views + coverage.json to {d}")

    elif cmd == "diff":
        from backend.compare_reports import compare
        compare()

    elif cmd == "compare":
        topic = arg or "device deficiencies"
        print(f"\n########## COMPARE: {topic!r} ##########")
        print("\n--- A) Deterministic vector search (reproducible, auditable) ---")
        from backend.retrieve import vector_search
        for r in vector_search(topic, k=5):
            print(f"  {r['score']:.3f} [{r['doc']}/{r['kind']}] {r['path'][:45]}")
        print("\n--- B) LLM-generated Cypher (flexible, non-deterministic) ---")
        from backend.text2cypher import ask
        ask(f"Find sections about {topic}. Return doc, path and a short text snippet.")

    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
