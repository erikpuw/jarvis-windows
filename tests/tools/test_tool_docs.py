# tests/tools/test_tool_docs.py
"""Mỗi tool thật có prompt/tools/<tên>.md, mô tả không rỗng, mọi tham số có mô tả, .md không nhắc tham số lạ."""
import inspect
from pathlib import Path

from engine.tools import registry as R

DOCS = Path(__file__).resolve().parents[2] / "prompt" / "tools"


def test_every_tool_has_complete_doc():
    R._reset_for_test()
    names = R.names()
    assert len(names) >= 21
    for n in names:
        path = DOCS / f"{n}.md"
        assert path.is_file(), f"thiếu {path}"
        desc, params, _ = R.parse_doc(path.read_text(encoding="utf-8"))
        assert desc, f"{n}: mô tả rỗng"
        real = [p for p in inspect.signature(R.get(n).fn).parameters if p != "ctx"]
        assert set(params) <= set(real), f"{n}: .md nhắc tham số lạ {set(params) - set(real)}"
        for p in real:
            assert params.get(p), f"{n}: tham số {p} chưa có mô tả"


def test_no_orphan_doc_files():
    R._reset_for_test()
    names = set(R.names())
    orphans = [f.stem for f in DOCS.glob("*.md") if f.stem not in names]
    assert not orphans, f".md không có tool: {orphans}"
