"""Nhật ký (Settings → Nhật ký): API phiên chỉ admin, danh sách phiên của mọi user kèm chủ phiên và tiêu đề.

Run: python -m pytest tests/test_sessions_admin_logs.py -q
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import engine.core.memory as memory
from engine.core.session_context import set_current_user_id
from engine.UIUX import memory_lock, ui_engine

app = FastAPI()
app.include_router(ui_engine.router)
client = TestClient(app)

ADMIN_TOKEN = "admin_test_token"
MEMBER_TOKEN = "usr_test_token"


@pytest.fixture(autouse=True)
def _seed(monkeypatch):
    memory_lock._tokens.clear()
    monkeypatch.setattr(memory, "DB_PATH", Path(tempfile.mkdtemp()) / "jarvis.db")
    memory.init_db()
    with memory._get_db() as conn:
        conn.execute("INSERT INTO users (id, username, role, created_at) VALUES ('u1', 'u1', 'member', 0)")
        conn.execute("INSERT INTO user_tokens (token, user_id, role, created_at) VALUES (?, 'admin', 'admin', 0)", (ADMIN_TOKEN,))
        conn.execute("INSERT INTO user_tokens (token, user_id, role, created_at) VALUES (?, 'u1', 'member', 0)", (MEMBER_TOKEN,))
    for uid, sid, role, text in (
        ("admin", "web-aaaa1111", "user", "chào admin"),
        ("u1", "web-bbbb2222", "user", "Giá vàng hôm nay?"),
        ("u1", "web-bbbb2222", "assistant", "Vàng SJC hôm nay khoảng 85 triệu."),
        ("admin", "tg-5", "user", "chào telegram"),
        ("admin", "", "user", "tin cũ"),
    ):
        set_current_user_id(uid)
        memory.save_message(role, text, sid)
    set_current_user_id("admin")
    yield
    memory_lock._tokens.clear()
    set_current_user_id("admin")


def _auth(token):
    return {"X-Memory-Token": token}


def test_admin_sees_sessions_of_every_user_with_owner_and_title():
    data = client.get("/api/conversations/sessions", headers=_auth(ADMIN_TOKEN)).json()
    assert data["success"] is True
    by_id = {s["session_id"]: s for s in data["sessions"]}
    assert set(by_id) == {"web-aaaa1111", "web-bbbb2222", "tg-5", "legacy"}

    member_session = by_id["web-bbbb2222"]
    assert member_session["user_id"] == "u1"
    assert member_session["user_name"] == "u1"
    assert member_session["title"] == "Giá vàng hôm nay?"
    assert member_session["msg_count"] == 2

    admin_session = by_id["web-aaaa1111"]
    assert admin_session["user_id"] == "admin"
    assert admin_session["user_name"] == "admin"
    assert admin_session["title"] == "chào admin"

    assert by_id["tg-5"]["user_id"] == "admin"
    assert by_id["legacy"]["user_id"] == "admin"

    owners = {u["id"]: u["name"] for u in data["users"]}
    assert owners == {"admin": "admin", "u1": "u1"}


def test_admin_filters_by_user():
    only_u1 = client.get("/api/conversations/sessions?user=u1", headers=_auth(ADMIN_TOKEN)).json()
    assert [s["session_id"] for s in only_u1["sessions"]] == ["web-bbbb2222"]
    assert {u["id"] for u in only_u1["users"]} == {"admin", "u1"}  # dropdown keeps every owner

    only_admin = client.get("/api/conversations/sessions?user=admin", headers=_auth(ADMIN_TOKEN)).json()
    assert {s["session_id"] for s in only_admin["sessions"]} == {"web-aaaa1111", "tg-5", "legacy"}

    everyone = client.get("/api/conversations/sessions?user=", headers=_auth(ADMIN_TOKEN)).json()
    assert len(everyone["sessions"]) == 4


def test_member_gets_403_on_log_session_apis():
    assert client.get("/api/conversations/sessions", headers=_auth(MEMBER_TOKEN)).status_code == 403
    assert client.get("/api/conversations/session/web-bbbb2222", headers=_auth(MEMBER_TOKEN)).status_code == 403
    assert client.delete("/api/conversations/session/web-bbbb2222", headers=_auth(MEMBER_TOKEN)).status_code == 403
    with memory._get_db() as conn:
        left = conn.execute("SELECT COUNT(*) FROM messages WHERE session_id = 'web-bbbb2222'").fetchone()[0]
    assert left == 2


def test_unguarded_edit_and_delete_routes_are_gone():
    # Trước đây ai cũng sửa/xóa được tin bất kỳ qua hai route này; nay không còn route nào
    assert client.post("/api/conversations/update", json={"id": 1, "content": "x"}).status_code in (404, 405)
    assert client.delete("/api/conversations/delete?id=1").status_code in (404, 405)
