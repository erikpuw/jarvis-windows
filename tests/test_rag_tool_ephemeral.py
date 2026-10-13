"""Đính kèm + hỏi một lần là tạm thời: handle_rag_query không bao giờ ghi vào kho lâu dài.
Lưu lâu dài chỉ qua `@rag lưu` (copy vào thư mục watcher) - không để LLM đoán ý "lưu"."""
import asyncio
from pathlib import Path
from types import SimpleNamespace

import engine.core.rag_document_store as store_mod
import engine.core.rag_engine as rag_engine_mod
import engine.core.rag_pdf_ingest as ingest_mod
import engine.server.llm_server as llm_server
import engine.tools.rag_tool as rag_tool


def test_attachment_question_never_builds_a_persistent_engine(monkeypatch):
    engines, promoted = [], []

    class RecordingEngine:
        def __init__(self, dim=768, persistent=True):
            self.persistent = persistent
            self.chunks, self.vector_index, self.bm25_index = [], None, None
            engines.append(self)

        def set_client(self, c): pass
        def set_embed_client(self, c): pass

        async def index_prepared_pages(self, **kw):
            return {"success": True, "chunks": 1}

    class FakeStore:
        def find_persistent(self, p): return None
        def promote(self, prepared):
            promoted.append(prepared)
            return prepared
        def discard_staging(self, prepared): pass

    prepared = SimpleNamespace(document_id="d1", source_filename="a.pdf", manifest_path=None)

    async def fake_prepare(att, ingestor): return prepared

    async def fake_retrieve(rag, prep, query, **kw):
        return [{"id": 1, "content": "nội dung", "page_number": 1}], {"success": True}

    async def fake_llm(messages, **kw):
        msg = SimpleNamespace(content="trả lời")
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

    async def always_persist(query, **kw): return True

    monkeypatch.setattr(rag_engine_mod, "RAGEngine", RecordingEngine)
    monkeypatch.setattr(store_mod, "RAGDocumentStore", FakeStore)
    monkeypatch.setattr(ingest_mod, "RAGPDFIngestor", lambda store: object())
    monkeypatch.setattr(llm_server, "get_embed_client", lambda: object())
    monkeypatch.setattr(llm_server, "get_llm_client", lambda: object())
    monkeypatch.setattr(llm_server, "call_llm", fake_llm)
    monkeypatch.setattr(rag_tool, "prepare_attachment", fake_prepare)
    monkeypatch.setattr(rag_tool, "index_and_retrieve_prepared", fake_retrieve)
    monkeypatch.setattr(rag_tool, "classify_persistence_intent", always_persist, raising=False)

    att = SimpleNamespace(extension=".pdf", filename="a.pdf", resolved_path=Path(__file__))
    result = asyncio.run(rag_tool.handle_rag_query(query="tóm tắt rồi lưu lại tài liệu này", attachment_context=att))

    assert result["status"] == "success"
    assert [e.persistent for e in engines] == [False], "chỉ được có engine tạm thời"
    assert promoted == [], "không được chuyển tệp vào kho lâu dài"
    assert not result.get("persisted")
