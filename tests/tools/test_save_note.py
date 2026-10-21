"""save_note (ngài 2026-10-18): chỉ ghi khi ngài bảo — nội dung ngài đọc, hoặc "lưu cái vừa tra" (kết quả gần nhất
trong outcomes, không tra lại). File mới trong data/wiki/Documents/Ghi_chu, watcher tự nạp cho search_documents."""
import asyncio
import json
import sqlite3
import time

import pytest

from engine.tools import registry as R
from engine.tools.catalog import files as F


@pytest.fixture
def notes(tmp_path, monkeypatch):
    monkeypatch.setattr(F, "NOTES_DIR", tmp_path / "Ghi_chu")
    return tmp_path / "Ghi_chu"


def run(**kw):
    return asyncio.run(F.save_note(**kw))


def test_writes_what_the_user_said(notes):
    out = run(content="Hạn thanh toán nợ thẻ là ngày 25/10.", title="Hạn trả nợ thẻ")
    files = list(notes.glob("*.md"))
    assert len(files) == 1 and files[0].name.endswith("-han-tra-no-the.md")
    text = files[0].read_text(encoding="utf-8")
    assert text.startswith("# Hạn trả nợ thẻ\n") and "Hạn thanh toán nợ thẻ là ngày 25/10." in text
    assert files[0].name in out


def test_same_title_never_overwrites(notes):
    run(content="một", title="Ghi chú")
    run(content="hai", title="Ghi chú")
    texts = sorted(p.read_text(encoding="utf-8") for p in notes.glob("*.md"))
    assert len(texts) == 2 and any("một" in t for t in texts) and any("hai" in t for t in texts)


def _db(tmp_path, rows):
    path = tmp_path / "jarvis.db"
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE outcomes (id INTEGER PRIMARY KEY, tools TEXT, query TEXT, status TEXT, result TEXT,"
              " traces TEXT, created_at REAL)")
    for tools, query, status, result, age in rows:
        c.execute("INSERT INTO outcomes (tools, query, status, result, traces, created_at) VALUES (?,?,?,?,?,?)",
                  (tools, query, status, "", json.dumps([{"tool": tools, "result": result}]), time.time() - age))
    c.commit(); c.close()
    return path


def test_from_last_result_saves_the_latest_successful_lookup(notes, tmp_path, monkeypatch):
    monkeypatch.setattr(F, "DB_PATH", _db(tmp_path, [
        ("search_news", "tin lãi suất", "success", "📰 Lãi suất giữ nguyên", 600),
        ("market_price", "giá xăng", "failed", "lỗi", 60),           # lỗi: bỏ qua
        ("save_note", "ghi lại", "success", "Đã ghi", 30),            # chính nó: bỏ qua
    ]))
    out = run(from_last_result=True)
    text = next(notes.glob("*.md")).read_text(encoding="utf-8")
    assert "📰 Lãi suất giữ nguyên" in text and "tin lãi suất" in text and "Đã ghi chú" in out


def test_from_last_result_ignores_old_lookups(notes, tmp_path, monkeypatch):
    monkeypatch.setattr(F, "DB_PATH", _db(tmp_path, [("search_news", "tin cũ", "success", "cũ", 3 * 3600)]))
    out = run(from_last_result=True)
    assert not notes.exists() or not list(notes.glob("*.md"))
    assert "Chưa có" in out


def test_nothing_to_save(notes):
    assert "Chưa có nội dung" in run()
    assert not notes.exists()


def test_registered_as_change_tool():
    assert R.kind("save_note") == "change" and "search_documents" in R.description("save_note")
