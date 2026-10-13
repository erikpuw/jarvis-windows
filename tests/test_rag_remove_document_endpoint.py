"""DELETE /api/rag/document dùng chung logic với "@rag xóa": bỏ chỉ mục, đồng bộ rag_watch.db và chuyển tệp
gốc vào thùng rác của vault (không thì lần khởi động sau tệp được nạp lại).

Lỗi cũ: endpoint gọi coroutine qua asyncio.to_thread nên thân hàm không bao giờ chạy."""
import asyncio

import engine.core.rag_engine as rag_engine_mod
import engine.core.rag_watcher as rag_watcher_mod
from engine.UIUX.ui_engine import api_rag_remove_document


class FakeRAGEngine:
    def __init__(self):
        self.calls = []

    async def remove_document(self, file_path: str) -> int:
        self.calls.append(file_path)
        return 3


def test_endpoint_removes_syncs_watch_db_and_trashes_the_file(monkeypatch, tmp_path):
    watch = tmp_path / "Documents"
    watch.mkdir()
    monkeypatch.setenv("RAG_WATCH_FOLDER", str(watch))
    doc = watch / "a.pdf"
    doc.write_bytes(b"A")
    fake, marked = FakeRAGEngine(), []
    monkeypatch.setattr(rag_engine_mod, "get_rag_engine", lambda: fake)
    monkeypatch.setattr(rag_watcher_mod, "mark_removed", marked.append)

    result = asyncio.run(api_rag_remove_document(str(doc)))

    resolved = str(doc.resolve())
    assert fake.calls == [resolved], "thân remove_document phải chạy"
    assert marked == [resolved]
    assert result["success"] is True and result["chunks_removed"] == 3
    assert not doc.exists() and (tmp_path / ".trash" / "Documents" / "a.pdf").exists()


def test_endpoint_leaves_files_outside_the_watch_folder(monkeypatch, tmp_path):
    monkeypatch.setenv("RAG_WATCH_FOLDER", str(tmp_path / "Documents"))
    doc = tmp_path / "elsewhere.pdf"
    doc.write_bytes(b"A")
    monkeypatch.setattr(rag_engine_mod, "get_rag_engine", FakeRAGEngine)
    monkeypatch.setattr(rag_watcher_mod, "mark_removed", lambda p: None)

    result = asyncio.run(api_rag_remove_document(str(doc)))

    assert result["chunks_removed"] == 3 and result["trashed_to"] is None and doc.exists()
