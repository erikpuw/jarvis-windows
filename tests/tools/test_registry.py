# tests/tools/test_registry.py
import asyncio
from typing import Literal

import pytest

from engine.tools import registry as R

DOC = """Mở một thứ.

app_name: tên thứ cần mở
days: số ngày

## answer
Nói ngắn gọn.
"""


@pytest.fixture(autouse=True)
def clean_registry():
    R._reset_for_test()
    yield
    R._reset_for_test()


def _demo():
    async def open_thing(app_name: str, mode: Literal["a", "b"] = "a", days: int = 7, ctx=None) -> str:
        return f"opened {app_name} {mode} {days} {ctx.user_text if ctx else ''}"
    R._register_for_test(open_thing, doc=DOC.replace("days: số ngày", "days: số ngày\nmode: chế độ"),
                         kind="change", display=True)
    return open_thing


def test_parse_doc_splits_description_params_answer():
    assert R.parse_doc(DOC) == ("Mở một thứ.", {"app_name": "tên thứ cần mở", "days": "số ngày"}, "Nói ngắn gọn.")


def test_parameters_from_signature_and_doc():
    _demo()
    p = R.parameters("open_thing")
    assert p["required"] == ["app_name"]
    assert p["properties"]["app_name"] == {"type": "string", "description": "tên thứ cần mở"}
    assert p["properties"]["mode"]["enum"] == ["a", "b"]
    assert p["properties"]["days"]["type"] == "integer"
    assert "ctx" not in p["properties"]
    assert R.description("open_thing") == "Mở một thứ." and R.answer_rules("open_thing") == "Nói ngắn gọn."
    assert R.display("open_thing") is True and R.kind("open_thing") == "change"
    assert R.usage("open_thing") == "/open_thing <app_name, mode, days>"


def test_catalog_text_format():
    _demo()
    assert R.catalog_text(["open_thing"]) == (
        "- open_thing: Mở một thứ. (app_name: tên thứ cần mở, mode: chế độ, days: số ngày)")


def test_chat_names_and_attachment():
    async def read_doc(question: str, ctx=None) -> str:
        return ""

    async def plain() -> str:
        return ""

    async def hidden() -> str:
        return ""
    R._register_for_test(read_doc, doc="Đọc tài liệu.\n\nquestion: câu hỏi\n", needs_attachment=True,
                         extensions=lambda: {".pdf"})
    R._register_for_test(plain, doc="Thường.")
    R._register_for_test(hidden, doc="Ẩn.", chat=False)
    pdf = type("A", (), {"extension": ".pdf"})()
    assert R.chat_names(None) == ["plain"]
    assert R.chat_names(pdf) == ["read_doc", "plain"]
    assert R.file_tools_for(pdf) == ["read_doc"]


def test_validate_coerces_and_rejects():
    _demo()
    allowed = {"open_thing"}
    assert R.validate("open_thing", {"app_name": "word", "days": "3", "junk": 1}, allowed) == (
        {"app_name": "word", "days": 3}, None)
    assert R.validate("open_thing", {"app_name": ""}, allowed)[1]
    assert R.validate("open_thing", {"app_name": "x", "mode": "z"}, allowed)[1]
    assert R.validate("ghost", {}, allowed)[1]
    assert R.validate("open_thing", "x", allowed)[1]


def test_run_passes_ctx(monkeypatch):
    _demo()
    monkeypatch.setattr("engine.core.trace_logger.TraceLogger.log_trace", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr("engine.core.guardrails.verify_output", lambda n, a: (True, ""))
    res = asyncio.run(R.run("open_thing", {"app_name": "word"}, R.ToolContext(user_text="hi")))
    assert res == R.ToolResult("opened word a 7 hi", "success")


def test_every_real_tool_has_a_human_label():
    """Ngài 2026-10-13: status/island hiện tên phần đang dùng, không hiện lệnh thô (check_mail, read_screen…)."""
    R._reset_for_test()
    for name in R.names():
        label = R.label(name)
        assert label and label != name and "_" not in label, name
    R._reset_for_test()
