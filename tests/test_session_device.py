"""Phiên chat web nhớ thiết bị đã mở nó (desktop / ios / android / mobile) để Settings → Bộ nhớ → Conversations và
danh sách phiên ghi rõ "web trên iPhone" thay vì chỉ có web-xxxxxxxx (user 2026-10-17).

Run: python -m pytest tests/test_session_device.py -q
"""
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
    for sid, text in (("", "tin cũ"), ("web-aaaa1111", "chào từ iPhone"), ("web-bbbb2222", "chào từ PC"), ("tg-5", "chào telegram")):
        set_session(sid)
        memory.save_message("user", text)
    set_session("")
    yield
    memory_lock._tokens.clear()


def _headers():
    token = client.post("/api/memory-lock/unlock", json={"password": PASSWORD}).json()["token"]
    return {"X-Memory-Token": token}


def test_conversation_records_carry_the_device_of_their_session():
    memory.record_session_device("web-aaaa1111", "ios")
    memory.record_session_device("web-bbbb2222", "desktop")
    items = {i["content"]: i for i in memory.list_conversation_records()["items"]}
    assert items["chào từ iPhone"]["device"] == "ios"
    assert items["chào từ PC"]["device"] == "desktop"
    assert items["chào telegram"]["device"] == "telegram"
    assert items["tin cũ"]["device"] == ""  # before devices were recorded: unknown


def test_sessions_api_lists_the_device():
    memory.record_session_device("web-aaaa1111", "android")
    data = client.get("/api/conversations/sessions", headers=_headers()).json()
    by_id = {s["session_id"]: s for s in data["sessions"]}
    assert by_id["web-aaaa1111"]["device"] == "android"
    assert by_id["web-bbbb2222"]["device"] == ""
    assert by_id["tg-5"]["device"] == "telegram"


def test_only_known_device_names_are_stored_and_the_first_one_stays():
    memory.record_session_device("web-aaaa1111", "<script>")
    memory.record_session_device("", "ios")
    items = {i["content"]: i for i in memory.list_conversation_records()["items"]}
    assert items["chào từ iPhone"]["device"] == ""
    memory.record_session_device("web-aaaa1111", "ios")
    memory.record_session_device("web-aaaa1111", "desktop")  # a reconnect of the same page cannot change it
    items = {i["content"]: i for i in memory.list_conversation_records()["items"]}
    assert items["chào từ iPhone"]["device"] == "ios"
