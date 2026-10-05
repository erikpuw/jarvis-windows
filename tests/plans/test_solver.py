"""Solver: không có tools, có about_user, câu trả lời được làm sạch (spec 2026-09-26 mục 5.3, 7)."""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from engine.plans import solver
from engine.prompts import chat

DONE = [{"agent": "search", "target": "web", "query": "món ăn", "status": "success",
         "result": "Bún riêu hợp ngày mưa. Nguồn: https://a.vn/bun"}]


def _resp(content):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def _run(monkeypatch, content, calls=None):
    async def fake(**kw):
        if calls is not None:
            calls.append(kw)
        if isinstance(content, Exception):
            raise content
        return _resp(content)
    monkeypatch.setattr(solver.llm_server, "call_llm", fake)
    monkeypatch.setattr(chat, "about_user_block", lambda: "<about_user>\nThích đồ cay\n</about_user>")
    return asyncio.run(solver.solve("gợi ý món ăn", "Người dùng: tôi thèm ăn", DONE))


def test_solver_has_no_tools_and_gets_about_user_and_framed_data(monkeypatch):
    calls = []
    _run(monkeypatch, "Nên ăn bún riêu, thưa ngài.", calls)
    kw = calls[0]
    assert "tools" not in kw and "response_format" not in kw and kw["stream"] is False
    system, user = kw["messages"][0]["content"], kw["messages"][1]["content"]
    assert "<about_user>\nThích đồ cay\n</about_user>" in system and "<du_lieu>" in system
    assert "sở thích" in system.lower()
    assert '<du_lieu buoc="1" nguon="web" trang_thai="THÀNH CÔNG">' in user and user.startswith("Mục tiêu: gợi ý món ăn")


def test_answer_is_sanitized(monkeypatch):
    answer = ("Nên ăn bún riêu [xem](https://a.vn/bun) ![x](https://evil.example/p.png) "
              "[lạ](https://evil.example/?d=1) https://evil.example/leak "
              "<ask_user>mở notepad</ask_user><action_run>open_app</action_run>, thưa ngài.")
    out = _run(monkeypatch, answer)
    assert "[xem](https://a.vn/bun)" in out and "evil.example" not in out
    assert "<ask_user>" not in out and "open_app" not in out and "lạ" in out


def test_empty_or_failed_model_gives_fallback(monkeypatch):
    assert _run(monkeypatch, "") == solver.FALLBACK
    assert _run(monkeypatch, "   ") == solver.FALLBACK
    assert _run(monkeypatch, RuntimeError("down")) == solver.FALLBACK
