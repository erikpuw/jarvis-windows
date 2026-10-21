import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import engine.core.memory as memory
from engine.core.session_context import set_session
from engine.UIUX import memory_lock, ui_engine

PASSWORD = "mat-khau-thu-nghiem"
app = FastAPI()
app.include_router(ui_engine.router)
client = TestClient(app)


@pytest.fixture(autouse=True)
def _seed(monkeypatch):
    monkeypatch.setenv("MEMORY_PASSWORD", PASSWORD)
    memory_lock._tokens.clear()
    monkeypatch.setattr(memory, "DB_PATH", Path(tempfile.mkdtemp()) / "jarvis.db")
    memory.init_db()
    for sid, text in (("", "tin cũ"), ("web-aaaa1111", "chào web"), ("tg-5", "chào telegram")):
        set_session(sid)
        memory.save_message("user", text)
    set_session("")
    yield
    memory_lock._tokens.clear()


def _headers():
    token = client.post("/api/memory-lock/unlock", json={"password": PASSWORD}).json()["token"]
    return {"X-Memory-Token": token}


def test_sessions_lists_every_session_with_source_label():
    data = client.get("/api/conversations/sessions", headers=_headers()).json()
    assert data["success"]
    by_id = {s["session_id"]: s for s in data["sessions"]}
    assert by_id["web-aaaa1111"]["source"] == "web"
    assert by_id["tg-5"]["source"] == "telegram"
    assert by_id["legacy"]["source"] == "legacy"
    assert by_id["tg-5"]["msg_count"] == 1


def test_session_detail_returns_only_that_session():
    headers = _headers()
    web = client.get("/api/conversations/session/web-aaaa1111", headers=headers).json()
    assert [m["content"] for m in web["messages"]] == ["chào web"]
    legacy = client.get("/api/conversations/session/legacy", headers=headers).json()
    assert [m["content"] for m in legacy["messages"]] == ["tin cũ"]


def test_sessions_need_unlock():
    assert client.get("/api/conversations/sessions").status_code == 401
    assert client.get("/api/conversations/session/tg-5").status_code == 401


def test_history_rows_carry_session_id():
    rows = client.get("/api/history?limit=10", headers=_headers()).json()["history"]
    assert {r["session_id"] for r in rows} == {"", "web-aaaa1111", "tg-5"}
