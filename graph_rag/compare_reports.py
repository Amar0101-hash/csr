"""Head-to-head: main pipeline (hybrid retriever) vs GraphRAG prototype (FILLED_BY
traversal). Both use the same prompt + assembly, so differences isolate the
retrieval mechanism. Aligns the two .docx by heading order (same template)."""
from __future__ import annotations

import glob
import os

from graph_rag.gr_config import SETTINGS  # noqa: F401  (sets sys.path for the csr package)
from docx import Document
from docx.table import Table

from vector_rag.ingestion.docx_reader import iter_block_items
from vector_rag.ingestion.template_parser import HEADING_STYLES
from vector_rag.generation.verify import _numbers, _is_material

MAIN = "output/Clinical_Investigation_Report.docx"
GRAPH = "output/GraphRAG_Report.docx"

_PLACEHOLDER = ("data not available", "to be authored", "insufficient source")


def _latest(pattern: str, exact: str) -> str:
    if os.path.exists(exact):
        return exact
    files = sorted(glob.glob(pattern), key=os.path.getmtime)
    return files[-1] if files else exact


def extract(path: str) -> list[tuple[str, str]]:
    doc = Document(path)
    out, head, buf = [], None, []
    for block in iter_block_items(doc):
        if isinstance(block, Table):
            buf.append("[TABLE]")
            continue
        style = block.style.name if block.style else ""
        text = block.text.strip()
        if style in HEADING_STYLES and (text or style == "Title"):
            if head is not None:
                out.append((head, "\n".join(buf)))
            head, buf = text, []
        elif text:
            buf.append(text)
    if head is not None:
        out.append((head, "\n".join(buf)))
    return out


def _authored(body: str) -> bool:
    low = body.lower()
    if any(p in low for p in _PLACEHOLDER):
        return False
    return len(body.strip()) > 40


def _mnums(body: str) -> set[str]:
    return {n for n in _numbers(body) if _is_material(n)}


def compare() -> None:
    main = extract(_latest("output/Clinical_Investigation_Report*.docx", MAIN))
    graph = extract(_latest("output/GraphRAG_Report*.docx", GRAPH))
    n = min(len(main), len(graph))

    both = only_m = only_g = neither = 0
    tot_shared = tot_m_only = tot_g_only = 0
    divergent = []

    for i in range(n):
        (hm, bm), (hg, bg) = main[i], graph[i]
        am, ag = _authored(bm), _authored(bg)
        if am and ag:
            both += 1
        elif am:
            only_m += 1
        elif ag:
            only_g += 1
        else:
            neither += 1
        nm, ng = _mnums(bm), _mnums(bg)
        shared = nm & ng
        tot_shared += len(shared)
        tot_m_only += len(nm - ng)
        tot_g_only += len(ng - nm)
        # flag sections where the numeric facts differ a lot (both authored)
        if am and ag and (nm or ng):
            jac = len(shared) / max(1, len(nm | ng))
            if jac < 0.5 and (len(nm) >= 3 or len(ng) >= 3):
                divergent.append((hm[:46], len(nm), len(ng), len(shared), jac))

    print(f"Aligned sections: {n}  (main headings={len(main)}, graph headings={len(graph)})")
    print("\n--- authoring coverage ---")
    print(f"  authored in BOTH : {both}")
    print(f"  only MAIN        : {only_m}")
    print(f"  only GRAPH       : {only_g}")
    print(f"  neither          : {neither}")
    print("\n--- numeric grounding overlap (material numbers) ---")
    print(f"  shared by both   : {tot_shared}")
    print(f"  main-only numbers: {tot_m_only}")
    print(f"  graph-only numbers:{tot_g_only}")
    denom = tot_shared + tot_m_only + tot_g_only
    if denom:
        print(f"  number agreement : {100*tot_shared/denom:.0f}% of all material numbers "
              f"appear in BOTH reports")
    print("\n--- sections whose numeric content diverges most (both authored) ---")
    if not divergent:
        print("  (none — numeric content largely agrees)")
    for h, a, b, s, j in sorted(divergent, key=lambda x: x[4])[:12]:
        print(f"  {h:48} main#={a:2} graph#={b:2} shared={s:2} overlap={j:.0%}")


if __name__ == "__main__":
    compare()
