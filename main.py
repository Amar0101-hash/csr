"""Convenience entry point. Prefer the `csr` CLI (see README).

    python main.py ingest
    python main.py run
"""
from vector_rag.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
