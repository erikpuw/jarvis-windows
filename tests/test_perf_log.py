"""POST /api/perf-log: bảng ?debug=1 (frontend/src/perf-debug.ts) gửi số liệu mỗi giây, ghi nối vào logs/perf.jsonl để đọc lại sau
một phiên dùng điện thoại (Safari iPhone không mở được DevTools). Không khóa bằng mật khẩu (chỉ ghi, không đọc).

Run: python -m pytest tests/test_perf_log.py
"""
import json
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.UIUX import ui_engine

app = FastAPI()
app.include_router(ui_engine.router)
client = TestClient(app)


def test_samples_are_appended_one_json_per_line(tmp_path, monkeypatch):
    monkeypatch.setattr(ui_engine, "_log_dir", lambda: tmp_path)
    r = client.post("/api/perf-log", json={"samples": [{"t": 1, "fps": 60}, {"t": 2, "fps": 58}]})
    assert r.status_code == 200 and r.json()["success"]
    client.post("/api/perf-log", json={"samples": [{"t": 3, "fps": 30}]})
    lines = (tmp_path / "perf.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(x)["fps"] for x in lines] == [60, 58, 30]


def test_new_session_starts_a_fresh_file(tmp_path, monkeypatch):
    monkeypatch.setattr(ui_engine, "_log_dir", lambda: tmp_path)
    client.post("/api/perf-log", json={"samples": [{"t": 1}]})
    client.post("/api/perf-log", json={"samples": [{"t": 2}], "reset": True})
    lines = (tmp_path / "perf.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(x)["t"] for x in lines] == [2]


def test_oversized_batch_is_refused_and_file_is_capped(tmp_path, monkeypatch):
    monkeypatch.setattr(ui_engine, "_log_dir", lambda: tmp_path)
    assert client.post("/api/perf-log", json={"samples": [{"x": "a" * 70_000}]}).status_code == 413
    monkeypatch.setattr(ui_engine, "PERF_LOG_MAX_BYTES", 200)
    for i in range(20):
        client.post("/api/perf-log", json={"samples": [{"t": i, "pad": "b" * 40}]})
    assert (tmp_path / "perf.jsonl").stat().st_size <= 200 + 100


def test_not_behind_the_memory_lock():
    from engine.UIUX.memory_lock import PROTECTED_PREFIXES
    assert not "/api/perf-log".startswith(PROTECTED_PREFIXES)
