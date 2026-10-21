"""RAG gom về một nơi: thư mục watcher là nguồn duy nhất; `@rag lưu` chỉ copy tệp vào đó."""
import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

import engine.core.rag_engine as rag_engine_mod
import engine.core.rag_watcher as watcher_mod
import engine.rag.runner as runner
from types import SimpleNamespace

from engine.turn.context import TurnContext

PROJECT_ROOT = Path(watcher_mod.__file__).resolve().parents[2]


def test_watch_folder_default_is_inside_the_obsidian_vault(monkeypatch):
    monkeypatch.delenv("RAG_WATCH_FOLDER", raising=False)
    assert watcher_mod.watch_folder() == PROJECT_ROOT / "data" / "wiki" / "Documents"


def test_watch_folder_env_override_absolute_and_relative(monkeypatch, tmp_path):
    monkeypatch.setenv("RAG_WATCH_FOLDER", str(tmp_path))
    assert watcher_mod.watch_folder() == tmp_path
    monkeypatch.setenv("RAG_WATCH_FOLDER", "data/other")
    assert watcher_mod.watch_folder() == PROJECT_ROOT / "data" / "other"


class FakeRAG:
    def __init__(self):
        self.chunks = []
        self.embed_client = object()

    async def try_self_heal(self, embed_client=None):
        pass


@pytest.fixture
def env(monkeypatch, tmp_path):
    watch = tmp_path / "Documents"
    monkeypatch.setenv("RAG_WATCH_FOLDER", str(watch))
    monkeypatch.setattr(runner, "SAVE_WAIT_SECONDS", 0.05)
    rag = FakeRAG()
    monkeypatch.setattr(rag_engine_mod, "get_rag_engine", lambda: rag)
    monkeypatch.setattr(watcher_mod, "get_rag_watcher", lambda *a, **k: None)
    return SimpleNamespace(watch=watch, upload=tmp_path / "uploads", rag=rag, mp=monkeypatch)


def _att(env, name, data=b"%PDF-1.4 demo"):
    env.upload.mkdir(exist_ok=True)
    path = env.upload / f"abc123{Path(name).suffix}"
    path.write_bytes(data)
    return SimpleNamespace(filename=name, extension=Path(name).suffix.lower(), resolved_path=path)


def _save(att):
    async def send(ws, data):
        return True
    ctx = TurnContext(ws=SimpleNamespace(), send_json=send, attachment_context=att)
    return asyncio.run(runner.handle(SimpleNamespace(query="lưu"), ctx))


def test_save_copies_into_watch_folder_atomically(env):
    out = _save(_att(env, "hợp đồng.pdf", b"AAA"))
    assert (env.watch / "hợp đồng.pdf").read_bytes() == b"AAA"
    assert [p.name for p in env.watch.iterdir()] == ["hợp đồng.pdf"], "tệp tạm .part không được để lại"
    assert "hợp đồng.pdf" in out


def test_save_reports_chunks_once_watcher_has_indexed_it(env):
    env.mp.setattr(watcher_mod, "get_rag_watcher", lambda *a, **k: object())
    att = _att(env, "a.pdf")
    dest = str((env.watch / "a.pdf").resolve())
    env.mp.setattr(watcher_mod, "get_watch_stats", lambda: {"files": [{"file_path": dest, "chunks": 2}]})
    assert "2 đoạn" in _save(att)


def test_save_tells_user_when_watcher_is_not_done_yet(env):
    env.mp.setattr(watcher_mod, "get_rag_watcher", lambda *a, **k: object())
    env.mp.setattr(watcher_mod, "get_watch_stats", lambda: {"files": []})
    out = _save(_att(env, "a.pdf"))
    assert "đang nạp" in out


def test_save_same_content_twice_does_not_duplicate(env):
    _save(_att(env, "a.pdf", b"AAA"))
    out = _save(_att(env, "a.pdf", b"AAA"))
    assert "đã có" in out and len(list(env.watch.iterdir())) == 1


def test_save_same_name_different_content_gets_new_name(env):
    _save(_att(env, "a.pdf", b"AAA"))
    _save(_att(env, "a.pdf", b"BBB"))
    assert sorted(p.name for p in env.watch.iterdir()) == ["a (2).pdf", "a.pdf"]
    assert (env.watch / "a.pdf").read_bytes() == b"AAA"


def test_save_rejects_types_the_watcher_cannot_index(env):
    out = _save(_att(env, "ảnh.png"))
    assert "không hỗ trợ" in out and not env.watch.exists()


def test_save_strips_directories_from_filename(env):
    _save(_att(env, "../../evil.pdf"))
    assert [p.name for p in env.watch.iterdir()] == ["evil.pdf"]


def test_save_returns_document_summary_after_indexing(env):
    """2026-10-14: lưu xong chỉ nói "Đã lưu X: N đoạn" → kèm tài liệu nói về gì (đọc đoạn của đúng tệp đó)."""
    import engine.rag.summary as summary_mod
    env.mp.setattr(watcher_mod, "get_rag_watcher", lambda *a, **k: object())
    att = _att(env, "Food.pdf")
    dest = str((env.watch / "Food.pdf").resolve())
    env.mp.setattr(watcher_mod, "get_watch_stats", lambda: {"files": [{"file_path": dest, "chunks": 2}]})
    env.rag.chunks = [{"file_path": dest.lower(), "content": "thực đơn"}, {"file_path": "khac.pdf", "content": "khác"},
                      {"file_path": dest, "content": "ngày 2"}]
    seen = {}

    async def fake_summarize(name, chunks):
        seen["args"] = (name, [c["content"] for c in chunks])
        return "**Food.pdf**: Thực đơn"
    env.mp.setattr(summary_mod, "summarize", fake_summarize)
    out = _save(att)
    assert "2 đoạn" in out and "**Food.pdf**: Thực đơn" in out
    assert seen["args"] == ("Food.pdf", ["thực đơn", "ngày 2"])
