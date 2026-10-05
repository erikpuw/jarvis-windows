"""Settings → Nhật ký: đọc đuôi các file log cố định (jarvis.log, security_alerts.log, stream_tts.log).

GET /api/logs, /api/logs/security, /api/logs/tts (engine/UIUX/ui_engine.py). Tên file cố định trong code, giao diện không gửi đường dẫn;
chỉ đọc phần đuôi của file (file log có thể rất lớn); BOM (security_alerts.log ghi utf-8-sig) được bỏ.
Cả ba nằm sau mật khẩu như phần còn lại của Memory (tests/test_memory_lock.py).

Run: python -m pytest tests/test_log_files_api.py
"""
import asyncio
import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.UIUX import ui_engine


def _body(resp):
    return json.loads(resp.body) if hasattr(resp, "body") else resp


@pytest.fixture
def logdir(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        (d / "jarvis.log").write_text("\n".join(f"main {i}" for i in range(500)), encoding="utf-8")
        (d / "security_alerts.log").write_text("\n".join(f"sec {i}" for i in range(5)), encoding="utf-8-sig")
        (d / "stream_tts.log").write_text("tts một\ntts hai\n", encoding="utf-8")
        monkeypatch.setattr(ui_engine, "_log_dir", lambda: d)
        yield d


def test_main_log_keeps_working_and_returns_the_last_lines(logdir):
    data = _body(asyncio.run(ui_engine.api_logs(lines=3)))
    assert data["success"] is True and data["logs"].split("\n") == ["main 497", "main 498", "main 499"]


def test_security_log_is_read_and_its_bom_is_dropped(logdir):
    data = _body(asyncio.run(ui_engine.api_logs_security(lines=300)))
    assert data["success"] is True
    assert data["logs"].split("\n") == [f"sec {i}" for i in range(5)] and "﻿" not in data["logs"]


def test_tts_log_is_read(logdir):
    data = _body(asyncio.run(ui_engine.api_logs_tts(lines=300)))
    assert data["success"] is True and data["logs"].split("\n") == ["tts một", "tts hai"]


def test_missing_file_is_reported_not_raised(logdir):
    (logdir / "stream_tts.log").unlink()
    data = _body(asyncio.run(ui_engine.api_logs_tts(lines=10)))
    assert data["success"] is False and data["error"]


def test_lines_is_capped_and_never_negative(logdir):
    assert len(_body(asyncio.run(ui_engine.api_logs(lines=999999)))["logs"].split("\n")) == 500
    assert _body(asyncio.run(ui_engine.api_logs(lines=-5)))["logs"].split("\n") == ["main 499"]
    assert _body(asyncio.run(ui_engine.api_logs(lines=0)))["logs"].split("\n") == ["main 499"]


def test_only_the_tail_of_a_huge_file_is_read(logdir):
    big = logdir / "jarvis.log"
    big.write_text("DAU-FILE\n" + "x" * 80 + "\n" * 1 + ("y" * 80 + "\n") * 60000 + "CUOI-FILE\n", encoding="utf-8")  # ~4.8 MB
    data = _body(asyncio.run(ui_engine.api_logs(lines=2000)))
    assert data["success"] is True and "DAU-FILE" not in data["logs"] and data["logs"].endswith("CUOI-FILE")
    assert len(data["logs"]) < 700_000


def test_the_new_routes_are_locked_without_a_token(logdir, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    app = FastAPI()
    app.include_router(ui_engine.router)
    client = TestClient(app)
    for path in ("/api/logs", "/api/logs/security", "/api/logs/tts"):
        res = client.get(path)
        assert res.status_code == 401 and res.json() == {"detail": "locked"}, path
