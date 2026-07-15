"""Command-line interface for the CSR generator.

    csr ingest                 # read sources, embed, build hybrid index
    csr generate [--limit N] [--only 5.1 6.3 ...]
    csr assemble               # build the .docx + traceability from cached generation
    csr run [--limit N]        # ingest + generate + assemble
    csr inspect                # show parsed template sections
"""
from __future__ import annotations

import argparse
import sys

from .config import Settings
from . import pipeline


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--study-dir", help="Override study source directory")
    p.add_argument("--template", help="Override template .docx path")
    p.add_argument("--model", help="Override Bedrock generation model id")
    p.add_argument("--region", help="Override AWS region")
    p.add_argument("--effort", choices=["low", "medium", "high", "max"],
                   help="Generation effort (default high). Lower = faster.")
    p.add_argument("--graph", choices=["neo4j", "networkx"],
                   help="Knowledge-graph backend (default neo4j)")


def _settings(args) -> Settings:
    s = Settings()
    if getattr(args, "study_dir", None):
        s.study_dir = __import__("pathlib").Path(args.study_dir)
    if getattr(args, "template", None):
        s.template_path = __import__("pathlib").Path(args.template)
    if getattr(args, "model", None):
        s.gen_model = args.model
    if getattr(args, "region", None):
        s.aws_region = args.region
    if getattr(args, "effort", None):
        s.effort = args.effort
    if getattr(args, "graph", None):
        s.graph_backend = args.graph
    return s


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="csr", description="Template-driven CSR/CIR generator")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_ing = sub.add_parser("ingest", help="Read sources, embed, build hybrid index")
    _add_common(p_ing)

    p_gen = sub.add_parser("generate", help="Author sections with grounded generation")
    _add_common(p_gen)
    p_gen.add_argument("--limit", type=int, help="Only author the first N sections")
    p_gen.add_argument("--only", nargs="*", help="Author only these section keys/numbers")
    p_gen.add_argument("--workers", type=int, default=1,
                       help="Author sections concurrently (e.g. 8). Default 1 (serial).")
    p_gen.add_argument("--no-style-ref", action="store_true",
                       help="Disable the masked human-CSR style exemplar (few-shot)")

    p_asm = sub.add_parser("assemble", help="Assemble .docx + traceability from cache")
    _add_common(p_asm)

    p_run = sub.add_parser("run", help="ingest + generate + assemble")
    _add_common(p_run)
    p_run.add_argument("--limit", type=int, help="Only author the first N sections")
    p_run.add_argument("--workers", type=int, default=1,
                       help="Author sections concurrently (e.g. 8). Default 1 (serial).")

    p_ins = sub.add_parser("inspect", help="Print parsed template sections")
    _add_common(p_ins)

    args = parser.parse_args(argv)
    s = _settings(args)

    if args.cmd == "ingest":
        pipeline.ingest(s)
    elif args.cmd == "generate":
        if getattr(args, "no_style_ref", False):
            s.use_style_reference = False
        pipeline.generate(s, only=args.only, limit=args.limit, workers=args.workers)
        pipeline.assemble(s)
    elif args.cmd == "assemble":
        pipeline.assemble(s)
    elif args.cmd == "run":
        out = pipeline.run_all(s, limit=args.limit, workers=args.workers)
        print(f"\nDone. Output: {out}")
    elif args.cmd == "inspect":
        from .ingestion.template_parser import parse_template

        for sec in parse_template(s.template_path):
            mark = "GEN" if sec.generate else "   "
            print(f"[{mark}] {sec.key:9} L{sec.level} {sec.title[:60]}  (guid={len(sec.guidance)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
