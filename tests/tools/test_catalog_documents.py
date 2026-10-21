"""search_documents (2026-10-14): tra kho tài liệu mà không cần gõ @rag ("Thực đơn cho gym dùng rag" → gym, nói đại)."""
import asyncio

from engine.tools import registry as R


def test_search_documents_asks_library_and_is_displayed(monkeypatch):
    R._reset_for_test()
    seen = []

    async def fake_ask(query, ctx=None):
        seen.append((query, ctx))
        return "Ngày 2: cá hồi.\n\nNguồn: Food Drinks.pdf"
    monkeypatch.setattr("engine.rag.runner._ask", fake_ask)
    monkeypatch.setattr("engine.core.trace_logger.TraceLogger.log_trace", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr("engine.core.guardrails.verify_output", lambda n, a: (True, ""))
    res = asyncio.run(R.run("search_documents", {"query": "thực đơn ngày 2"}, None))
    assert seen == [("thực đơn ngày 2", None)] and "Nguồn: Food Drinks.pdf" in res.text
    assert R.display("search_documents") is True and "search_documents" in R.chat_names(None)
