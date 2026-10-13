"""@rag runner: lệnh con cố định, "lưu" chỉ là lệnh khi có tệp đính kèm."""
import asyncio
from types import SimpleNamespace

import engine.core.rag_engine as rag_engine_mod
import engine.rag.runner as runner
from engine.rag.runner import parse
from types import SimpleNamespace

from engine.turn.context import TurnContext


def test_parse_subcommands():
    assert parse("", False) == ("help", "")
    assert parse("danh sách", False) == ("list", "")
    assert parse("xóa abc123", False) == ("delete", "abc123")
    assert parse("xoá abc123", False) == ("delete", "abc123")
    assert parse("lưu", True) == ("save", "")


def test_luu_without_attachment_is_a_question():
    assert parse("lưu trữ hồ sơ thế nào", False) == ("ask", "lưu trữ hồ sơ thế nào")
    assert parse("lưu", False) == ("ask", "lưu")


def test_xoa_with_multi_word_argument_is_a_question():
    assert parse("xóa nợ là gì", False) == ("ask", "xóa nợ là gì")


def test_other_text_is_a_question():
    assert parse("điều khoản phạt hợp đồng", False) == ("ask", "điều khoản phạt hợp đồng")


class FakeRAG:
    def __init__(self, chunks=None, results=None):
        self.chunks = chunks or []
        self.results = results or []
        self.embed_client = object()
        self.retrieve_kwargs = None
        self.removed_paths = []

    async def try_self_heal(self, embed_client=None):
        pass

    async def retrieve(self, query, **kwargs):
        self.retrieve_kwargs = kwargs
        return self.results

    async def remove_document(self, file_path):
        self.removed_paths.append(file_path)
        gone = [c for c in self.chunks if c.get("file_path") == file_path]
        self.chunks = [c for c in self.chunks if c.get("file_path") != file_path]
        return len(gone)


def _run(query, rag, monkeypatch, attachment=None):
    monkeypatch.setattr(rag_engine_mod, "get_rag_engine", lambda: rag)
    sent = []

    async def send(ws, data):
        sent.append(data)
        return True
    ctx = TurnContext(ws=SimpleNamespace(), send_json=send, attachment_context=attachment)
    return asyncio.run(runner.handle(SimpleNamespace(query=query), ctx))


def test_ask_on_empty_store_says_so_without_llm(monkeypatch):
    out = _run("điều khoản phạt", FakeRAG(), monkeypatch)
    assert out == runner.EMPTY


def test_ask_with_no_relevant_chunks_does_not_call_llm(monkeypatch):
    rag = FakeRAG(chunks=[{"id": 0}], results=[])
    out = _run("điều khoản phạt", rag, monkeypatch)
    assert out == runner.NO_MATCH
    assert rag.retrieve_kwargs["min_score"] == runner.MIN_SCORE


def test_ask_answers_from_evidence_with_sources(monkeypatch):
    chunk = {"id": 7, "content": "Phạt 10% giá trị hợp đồng.", "filename": "hd.pdf", "page_number": 3}
    rag = FakeRAG(chunks=[chunk], results=[chunk])
    seen = {}

    async def fake_llm(messages, **kwargs):
        seen["user"] = messages[-1]["content"]
        msg = SimpleNamespace(content="Phạt 10%.")
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])
    import engine.server.llm_server as llm_server
    monkeypatch.setattr(llm_server, "call_llm", fake_llm)

    out = _run("điều khoản phạt", rag, monkeypatch)
    assert "Phạt 10% giá trị hợp đồng." in seen["user"]
    assert out.startswith("Phạt 10%.") and "hd.pdf (trang 3)" in out


def _two_docs(tmp_path):
    a, b = tmp_path / "Food Drinks.pdf", tmp_path / "note.txt"
    a.write_bytes(b"A")
    b.write_bytes(b"B")
    return FakeRAG(chunks=[
        {"id": 0, "file_path": str(a), "filename": "Food Drinks.pdf"},
        {"id": 1, "file_path": str(a), "filename": "Food Drinks.pdf"},
        {"id": 2, "file_path": str(b), "filename": "note.txt"},
    ]), a, b


def test_list_numbers_documents_and_counts_chunks(monkeypatch, tmp_path):
    rag, _, _ = _two_docs(tmp_path)
    out = _run("danh sách", rag, monkeypatch)
    assert "1. Food Drinks.pdf (2 đoạn)" in out and "2. note.txt (1 đoạn)" in out


def test_parse_delete_accepts_file_names_with_spaces_but_not_questions():
    assert parse("xóa 2", False) == ("delete", "2")
    assert parse("xóa Food Drinks.pdf", False) == ("delete", "Food Drinks.pdf")
    assert parse("xóa nợ là gì", False) == ("ask", "xóa nợ là gì")


def test_delete_by_number_removes_chunks_and_moves_file_to_vault_trash(monkeypatch, tmp_path):
    watch = tmp_path / "Documents"
    watch.mkdir()
    monkeypatch.setenv("RAG_WATCH_FOLDER", str(watch))
    marked = []
    monkeypatch.setattr(runner.rag_watcher, "mark_removed", marked.append)
    doc = watch / "Food Drinks.pdf"
    doc.write_bytes(b"A")
    rag = FakeRAG(chunks=[{"id": 0, "file_path": str(doc), "filename": "Food Drinks.pdf"}])

    out = _run("xóa 1", rag, monkeypatch)

    assert rag.removed_paths == [str(doc)] and marked == [str(doc)]
    assert not doc.exists(), "tệp phải rời thư mục watcher, nếu không khởi động lại sẽ nạp lại"
    assert (tmp_path / ".trash" / "Documents" / "Food Drinks.pdf").read_bytes() == b"A"
    assert "Food Drinks.pdf" in out and "1 đoạn" in out


def test_delete_by_name_is_case_insensitive_and_leaves_files_outside_watch_folder(monkeypatch, tmp_path):
    monkeypatch.setenv("RAG_WATCH_FOLDER", str(tmp_path / "Documents"))
    marked = []
    monkeypatch.setattr(runner.rag_watcher, "mark_removed", marked.append)
    rag, a, _ = _two_docs(tmp_path)

    out = _run("xóa food drinks.PDF", rag, monkeypatch)

    assert rag.removed_paths == [str(a)] and a.exists(), "tệp ngoài thư mục watcher không được đụng tới"
    assert "2 đoạn" in out


def test_delete_unknown_reports_not_found_and_touches_nothing(monkeypatch, tmp_path):
    rag, a, b = _two_docs(tmp_path)
    for arg in ("9", "khongco.pdf"):
        assert "Không tìm thấy" in _run(f"xóa {arg}", rag, monkeypatch)
    assert rag.removed_paths == [] and a.exists() and b.exists()


def test_ask_streams_chunks_and_sources(monkeypatch):
    chunk = {"id": 8, "content": "Tài liệu mẫu.", "filename": "sample.pdf", "page_number": 1}
    rag = FakeRAG(chunks=[chunk], results=[chunk])
    monkeypatch.setattr(rag_engine_mod, "get_rag_engine", lambda: rag)

    async def fake_streaming_llm(messages, stream=False, **kwargs):
        async def gen():
            yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="Đoạn 1 "))])
            yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="Đoạn 2"))])
        return gen()

    import engine.server.llm_server as llm_server
    monkeypatch.setattr(llm_server, "call_llm", fake_streaming_llm)

    sent = []
    async def send(ws, data):
        sent.append(data)
        return True
    ctx = TurnContext(ws=SimpleNamespace(), send_json=send)
    out = asyncio.run(runner.handle(SimpleNamespace(query="câu hỏi"), ctx))
    assert "Đoạn 1 Đoạn 2" in out
    assert "sample.pdf (trang 1)" in out
    text_chunks = [d["text"] for d in sent if d.get("type") == "text_chunk"]
    assert "Đoạn 1 " in text_chunks
    assert "Đoạn 2" in text_chunks
    assert any("sample.pdf (trang 1)" in t for t in text_chunks)
    assert any(d.get("type") == "stream_end" for d in sent)
