import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

import engine.core.memory as memory
import engine.core.memory_tree as memory_tree
from engine.core.session_context import set_session


def _run_threads(target, count):
    errors = []

    def wrapped(i):
        try:
            target(i)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=wrapped, args=(i,)) for i in range(count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors


def test_concurrent_save_message_from_many_sessions(monkeypatch):
    monkeypatch.setattr(memory, "DB_PATH", Path(tempfile.mkdtemp()) / "jarvis.db")
    memory.init_db()

    def worker(i):
        set_session(f"web-{i:08d}")
        for n in range(5):
            memory.save_message("user", f"tin {i}-{n}")

    _run_threads(worker, 8)
    assert len(memory.get_messages(limit=100)) == 40


def test_concurrent_daily_digest_writes_header_once(monkeypatch):
    wiki = Path(tempfile.mkdtemp())
    monkeypatch.setattr(memory_tree, "WIKI_DIR", wiki)
    monkeypatch.setattr("engine.core.wiki_sync.sync_wiki_to_semantic_memory", lambda *a, **k: None)

    _run_threads(lambda i: memory_tree.save_daily_digest(f"hỏi {i}", f"đáp {i}"), 8)

    daily = [p for p in (wiki / "daily").rglob("*.md") if not p.name.startswith("Tháng")]
    assert len(daily) == 1
    text = daily[0].read_text(encoding="utf-8")
    assert text.count("# Nhật ký hoạt động ngày") == 1
    assert text.count("### [") == 8
    month = next((wiki / "daily").rglob("Tháng *.md")).read_text(encoding="utf-8")
    assert month.count(f"|{daily[0].stem}]]") == 1
