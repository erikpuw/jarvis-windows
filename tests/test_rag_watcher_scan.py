"""scan_existing của RAGFolderWatcher chỉ được dọn chunk mồ côi TRONG thư mục thả file, không đụng tài liệu lưu qua @rag."""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.core import rag_watcher


class _FakeRag:
    def __init__(self, chunks):
        self.chunks = chunks
        self.embed_client = object()
        self.active_seen = None

    async def sync_lifecycle(self, active):
        self.active_seen = {str(Path(p).resolve()) for p in active}
        return 0

    async def process_document(self, file_path):
        return {"success": True, "chunks": 1}


def test_scan_keeps_chunks_from_outside_the_watch_folder(monkeypatch, tmp_path):
    watch, other = tmp_path / "documents", tmp_path / "uploads"
    watch.mkdir(); other.mkdir()
    saved = other / "saved_by_rag.pdf"                # lưu qua '@rag lưu': nằm ngoài thư mục thả file
    gone = watch / "deleted_meanwhile.txt"            # từng thả vào thư mục nhưng đã bị xoá khi server tắt
    fake = _FakeRag([{"file_path": str(saved), "filename": saved.name},
                     {"file_path": str(gone), "filename": gone.name}])
    import engine.core.rag_engine as rag_engine
    monkeypatch.setattr(rag_engine, "get_rag_engine", lambda: fake)
    monkeypatch.setattr(rag_watcher, "WATCH_DB_PATH", tmp_path / "watch.db")

    asyncio.run(rag_watcher.RAGFolderWatcher(str(watch)).scan_existing())

    assert str(saved.resolve()) in fake.active_seen          # tài liệu @rag được giữ
    assert str(gone.resolve()) not in fake.active_seen       # chunk mồ côi trong thư mục thả file vẫn bị dọn


def test_already_indexed_file_is_not_indexed_again(monkeypatch, tmp_path):
    watch = tmp_path / "documents"; watch.mkdir()
    f = watch / "a.txt"; f.write_text("nội dung", encoding="utf-8")
    fake = _FakeRag([])
    calls = []

    async def counting(file_path):
        calls.append(file_path)
        return {"success": True, "chunks": 1}
    fake.process_document = counting
    import engine.core.rag_engine as rag_engine
    monkeypatch.setattr(rag_engine, "get_rag_engine", lambda: fake)
    monkeypatch.setattr(rag_watcher, "WATCH_DB_PATH", tmp_path / "watch.db")

    async def twice():
        w = rag_watcher.RAGFolderWatcher(str(watch))
        await w.scan_existing()
        await w.scan_existing()
    asyncio.run(twice())
    assert len(calls) == 1


def _edit_setup(monkeypatch, tmp_path):
    watch = tmp_path / "documents"; watch.mkdir()
    fake = _FakeRag([])
    log = []

    async def process(file_path):
        log.append(("index", Path(file_path).read_text(encoding="utf-8")))
        return {"success": True, "chunks": 1}

    async def remove(file_path):
        log.append(("remove", Path(file_path).name))
        return 1
    fake.process_document, fake.remove_document = process, remove
    import engine.core.rag_engine as rag_engine
    monkeypatch.setattr(rag_engine, "get_rag_engine", lambda: fake)
    monkeypatch.setattr(rag_watcher, "WATCH_DB_PATH", tmp_path / "watch.db")
    monkeypatch.setattr(rag_watcher, "_SETTLE_SECONDS", 0)
    return watch, log


def test_edited_file_is_reindexed_after_its_old_chunks_are_removed(monkeypatch, tmp_path):
    """jarvis.log 2026-10-17 13:10: ghi chú tạo rỗng rồi mới gõ nội dung → watcher chỉ thấy bản rỗng, hỏi không ra."""
    import os, time
    watch, log = _edit_setup(monkeypatch, tmp_path)
    f = watch / "ghi_chu.md"; f.write_text("cũ", encoding="utf-8")

    async def run():
        w = rag_watcher.RAGFolderWatcher(str(watch))
        await w._index_file(str(f.resolve()))
        f.write_text("nội dung mới dài hơn", encoding="utf-8")
        later = time.time() + 5
        os.utime(f, (later, later))
        await w._index_file(str(f.resolve()))
        await w._index_file(str(f.resolve()))          # không đổi nữa → bỏ qua
    asyncio.run(run())
    assert log == [("index", "cũ"), ("remove", "ghi_chu.md"), ("index", "nội dung mới dài hơn")]


def test_empty_file_filled_later_gets_indexed(monkeypatch, tmp_path):
    watch, log = _edit_setup(monkeypatch, tmp_path)
    f = watch / "trong.md"; f.write_text("", encoding="utf-8")
    fake_fail = {"n": 0}
    import engine.core.rag_engine as rag_engine
    rag = rag_engine.get_rag_engine()
    orig = rag.process_document

    async def process(file_path):
        if not Path(file_path).read_text(encoding="utf-8"):
            fake_fail["n"] += 1
            return {"success": False, "error": "Document content is empty."}
        return await orig(file_path)
    rag.process_document = process

    async def run():
        w = rag_watcher.RAGFolderWatcher(str(watch))
        await w._index_file(str(f.resolve()))
        f.write_text("có chữ", encoding="utf-8")
        await w._index_file(str(f.resolve()))
    asyncio.run(run())
    assert fake_fail["n"] == 1 and log == [("index", "có chữ")]


def test_watcher_queues_a_file_again_when_it_is_modified(monkeypatch, tmp_path):
    watch = tmp_path / "documents"; watch.mkdir()
    f = watch / "note.md"; f.write_text("a", encoding="utf-8")

    async def run():
        w = rag_watcher.RAGFolderWatcher(str(watch))
        w.start(asyncio.get_running_loop())
        try:
            await asyncio.sleep(0.3)
            f.write_text("ab", encoding="utf-8")
            for _ in range(30):
                await asyncio.sleep(0.1)
                if not w._indexing_queue.empty():
                    break
            return [w._indexing_queue.get_nowait() for _ in range(w._indexing_queue.qsize())]
        finally:
            w.stop()
    queued = asyncio.run(run())
    assert str(f.resolve()) in queued
