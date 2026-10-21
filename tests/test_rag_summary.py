"""Tổng hợp tài liệu (2026-10-14): lưu vào kho xong / hỏi "tóm tắt" tệp đính kèm thì trả lại tài liệu nói về gì,
không chỉ "Đã lưu X". Đọc rải đều cả tài liệu (không chỉ 5 đoạn khớp câu hỏi); grammar JSON + think 128."""
import asyncio
import json
from types import SimpleNamespace

import engine.server.llm_server as llm_server
from engine.rag import summary
from engine.tools import rag_tool


def _chunks(n, size=200):
    return [{"content": f"đoạn {i} " + "x" * size} for i in range(n)]


def test_excerpt_spreads_over_whole_document_within_budget():
    text = summary.excerpt(_chunks(100), budget=2000)
    assert "đoạn 0 " in text and "đoạn 99 " in text and len(text) <= 2000
    picked = [int(p.split()[1]) for p in text.split("\n\n---\n\n")]
    assert picked == sorted(picked) and len(picked) >= 5


def test_excerpt_short_document_kept_whole():
    assert summary.excerpt(_chunks(3, 10), budget=6000).count("đoạn") == 3


def test_summarize_uses_grammar_and_formats(monkeypatch):
    calls = []

    async def fake_llm(**kw):
        calls.append(kw)
        out = {"chu_de": "Thực đơn tăng cơ 7 ngày", "tom_tat": "Thực đơn theo ngày, có kcal và protein.",
               "muc_chinh": ["Ngày 1: gà + bò", "Ngày 2: cá"]}
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(out, ensure_ascii=False)))])
    monkeypatch.setattr(llm_server, "call_llm", fake_llm)
    text = asyncio.run(summary.summarize("Food Drinks.pdf", _chunks(4, 20)))
    assert text.startswith("**Food Drinks.pdf**: Thực đơn tăng cơ 7 ngày")
    assert "Thực đơn theo ngày" in text and "- Ngày 1: gà + bò" in text and "- Ngày 2: cá" in text
    kw = calls[0]
    assert kw["thinking"] is True and kw["thinking_budget"] == 128
    assert kw["response_format"]["json_schema"]["schema"]["required"] == ["chu_de", "tom_tat", "muc_chinh"]
    assert "<tai_lieu>" in kw["messages"][0]["content"] and "đoạn 3" in kw["messages"][0]["content"]


def test_summarize_bad_json_or_no_chunks_gives_none(monkeypatch):
    async def fake_llm(**kw):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="không phải json"))])
    monkeypatch.setattr(llm_server, "call_llm", fake_llm)
    assert asyncio.run(summary.summarize("a.pdf", _chunks(2))) is None
    assert asyncio.run(summary.summarize("a.pdf", [])) is None


def test_attachment_summary_intent():
    for q in ("", "  ", "tóm tắt giúp tôi", "tổng hợp tài liệu này", "file này nói về gì", "nội dung chính là gì"):
        assert rag_tool.wants_summary(q), q
    for q in ("giá ức gà bao nhiêu", "ngày 3 ăn gì"):
        assert not rag_tool.wants_summary(q), q


def _grab_llm(monkeypatch, reply="Ngày 2 ăn cá hồi."):
    calls = []

    async def fake_llm(**kw):
        calls.append(kw)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=reply))])
    monkeypatch.setattr(llm_server, "call_llm", fake_llm)
    return calls


def _assert_answer_call(kw, question, source):
    """Câu trả lời RAG (chữ thường, không grammar): think 128 + prompt thẻ XML, bằng chứng tách khỏi câu hỏi."""
    assert kw["thinking"] is True and kw["thinking_budget"] == 128 and "response_format" not in kw
    system, user = kw["messages"][0]["content"], kw["messages"][1]["content"]
    assert "<nhiem_vu>" in system
    assert f"<cau_hoi>\n{question}\n</cau_hoi>" in user and "<bang_chung>" in user and source in user


def test_library_answer_uses_think_budget_and_xml(monkeypatch):
    import engine.rag.runner as runner

    class Rag:
        chunks, embed_client = [{"content": "x"}], object()
        async def try_self_heal(self, c): pass
        async def retrieve(self, **kw): return [{"content": "Ngày 2: cá hồi", "filename": "Food.pdf", "page_number": 3, "score": 0.8}]
    monkeypatch.setattr("engine.core.rag_engine.get_rag_engine", lambda: Rag())
    monkeypatch.setattr(llm_server, "get_embed_client", lambda: object())
    calls = _grab_llm(monkeypatch)
    out = asyncio.run(runner._ask("thực đơn ngày 2"))
    assert out == "Ngày 2 ăn cá hồi.\n\nNguồn: Food.pdf (trang 3)"
    _assert_answer_call(calls[0], "thực đơn ngày 2", "kho tài liệu")


def test_attachment_answer_uses_think_budget_and_xml(monkeypatch):
    calls = _grab_llm(monkeypatch)
    msgs = summary.answer_messages("giá ức gà", "[Đoạn 1]\nỨc gà 200g", "tệp a.pdf")
    asyncio.run(llm_server.call_llm(messages=msgs, **summary.ANSWER_KW))
    _assert_answer_call(calls[0], "giá ức gà", "tệp a.pdf")


def test_library_stream_sends_answering_status_before_first_text(monkeypatch):
    """Ngài chốt B 2026-10-15: đường @rag stream cũng báo "Đang trả lời…" một lần trước chữ đầu tiên."""
    import engine.rag.runner as runner

    class Rag:
        chunks, embed_client = [{"content": "x"}], object()
        async def try_self_heal(self, c): pass
        async def retrieve(self, **kw): return [{"content": "Ngày 2: cá hồi", "filename": "Food.pdf", "score": 0.8}]

    async def fake_llm(**kw):
        async def gen():
            for t in ("Ngày 2 ", "ăn cá hồi."):
                yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=t))])
        return gen()

    class VS:
        def __init__(self, ws): pass
        def start(self): return None
        async def put(self, s): pass
        async def stop(self, clear_queue=False): pass
    sent = []

    async def send(ws, data):
        sent.append(data)
    monkeypatch.setattr("engine.core.rag_engine.get_rag_engine", lambda: Rag())
    monkeypatch.setattr(llm_server, "get_embed_client", lambda: object())
    monkeypatch.setattr(llm_server, "call_llm", fake_llm)
    monkeypatch.setattr("engine.server.voice_streamer.VoiceStreamer", VS)
    ctx = SimpleNamespace(ws=SimpleNamespace(cancel_requested=False), send_json=send, background_tasks=None)
    asyncio.run(runner._ask("thực đơn ngày 2", ctx=ctx))
    kinds = [(e["type"], e.get("message")) for e in sent if e["type"] in ("status", "text_chunk")]
    assert kinds[0] == ("status", "Đang trả lời…") and kinds[1][0] == "text_chunk"
    assert sum(e.get("message") == "Đang trả lời…" for e in sent) == 1
