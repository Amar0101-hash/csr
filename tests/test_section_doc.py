"""Fixture tests for the canonical section-document block parser.

Pure — no LLM, no Word, no Neo4j. Run:
    uv run python tests/test_section_doc.py     (self-contained, prints PASS/FAIL)
    uv run python -m pytest tests/test_section_doc.py   (if pytest is installed)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vector_rag.section_doc import parse_blocks, blocks_to_plain_text, section_to_dict


def test_prose_only():
    blocks = parse_blocks(["First paragraph.", "Second paragraph."])
    assert [b["type"] for b in blocks] == ["paragraph", "paragraph"]
    assert blocks[0]["text"] == "First paragraph."


def test_standalone_markdown_table():
    md = "| Arm | N |\n| --- | --- |\n| P1fA | 141 |\n| MDT | 61 |"
    blocks = parse_blocks([md])
    assert len(blocks) == 1 and blocks[0]["type"] == "table"
    rows = blocks[0]["rows"]
    assert rows[0] == ["Arm", "N"]            # header kept
    assert ["P1fA", "141"] in rows            # data kept
    assert all("---" not in "".join(r) for r in rows)  # separator dropped


def test_table_mixed_with_prose_in_one_string():
    # the fragile case the old inline detector mishandled
    s = "The results are summarised below:\n| Endpoint | Value |\n| --- | --- |\n| BCVA | 0.02 |"
    blocks = parse_blocks([s])
    assert [b["type"] for b in blocks] == ["paragraph", "table"]
    assert blocks[0]["text"].startswith("The results")
    assert blocks[1]["rows"][0] == ["Endpoint", "Value"]


def test_bullet_and_numbered_lists():
    b = parse_blocks(["- alpha\n- beta\n- gamma"])
    assert b[0]["type"] == "list" and b[0]["ordered"] is False
    assert b[0]["items"] == ["alpha", "beta", "gamma"]
    n = parse_blocks(["1. first\n2. second"])
    assert n[0]["type"] == "list" and n[0]["ordered"] is True
    assert n[0]["items"] == ["first", "second"]


def test_single_pipe_line_is_prose_not_dropped():
    blocks = parse_blocks(["Value | for reference only"])
    # not a real table (needs >= 2 rows); content must survive as prose
    assert len(blocks) == 1 and blocks[0]["type"] == "paragraph"
    assert "reference only" in blocks[0]["text"]


def test_mixed_document_order_preserved():
    paras = [
        "Intro paragraph.",
        "| A | B |\n| - | - |\n| 1 | 2 |",
        "- point one\n- point two",
        "Closing paragraph.",
    ]
    kinds = [b["type"] for b in parse_blocks(paras)]
    assert kinds == ["paragraph", "table", "list", "paragraph"]


def test_roundtrip_nonempty():
    paras = ["Prose.", "| A | B |\n| - | - |\n| 1 | 2 |"]
    text = blocks_to_plain_text(parse_blocks(paras))
    assert "Prose." in text and "| A | B |" in text


def test_section_to_dict_shape():
    class _Gen:
        key = "5.2"; title = "Clinical Investigation Plan"
        paragraphs = ["Para.", "| A | B |\n| - | - |\n| 1 | 2 |"]
        citations = []; used_chunk_ids = []; notes = None
        verification = {"grounded": True}; heading_override = None; table_fills = []
    d = section_to_dict(_Gen(), number="5.2", method="hybrid")
    assert d["number"] == "5.2" and d["method"] == "hybrid"
    assert [b["type"] for b in d["blocks"]] == ["paragraph", "table"]
    assert d["heading_override"] is None and d["table_fills"] == []


def _run():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"FAIL  {t.__name__}: {e}")
        except Exception as e:
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(tests)} passed")
    return passed == len(tests)


if __name__ == "__main__":
    sys.exit(0 if _run() else 1)
