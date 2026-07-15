"""Convenience entry point. Prefer the `csr` CLI (see README).

    python main.py ingest
    python main.py run
"""
import sys

sys.path.insert(0, "src")

from csr.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
