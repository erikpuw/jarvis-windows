"""Tên phiên và API thanh bên /api/sessions/mine: chỉ phiên web của chính người gọi.

Run: python -m pytest tests/test_sessions_sidebar_api.py -q
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import engine.core.memory as memory
from engine.core.session_context import session_title, set_current_user_id
from engine.UIUX import memory_lock
from engine.UIUX.sessions_api import router

app = FastAPI()
app.include_router(router)
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
    ):
        set_current_user_id(uid)
        memory.save_message(role, text, sid)
    set_current_user_id("admin")
    yield
    memory_lock._tokens.clear()
    set_current_user_id("admin")


def _auth(token):
    return {"X-Memory-Token": token}


def test_title_cuts_first_line_at_word_boundary():
    full = "Giá vàng SJC hôm nay bao nhiêu vậy, so với tuần trước thì tăng hay giảm nhiều không"
    title = session_title(full)
    assert title.endswith("…")
    assert len(title) <= 49
    body = title[:-1]
    assert full.startswith(body + " ")  # cut right before a space: no half word


def test_title_strips_markdown_and_command_prefix():
    assert session_title("**Giá vàng** hôm nay?") == "Giá vàng hôm nay?"
    assert session_title("@weather Đà Lạt") == "Đà Lạt"
    assert session_title("/gym tạ") == "tạ"
    assert session_title("   ") == "Phiên trống"


def test_title_keeps_code_and_snake_case_text():
    assert session_title("C# là gì") == "C# là gì"
    assert session_title("my_var lỗi") == "my_var lỗi"


def test_title_strips_leading_markers_emphasis_backticks_and_links():
    assert session_title("## Tiêu đề") == "Tiêu đề"
    assert session_title("- mục một") == "mục một"
    assert session_title("[Báo](https://x)") == "Báo"
    assert session_title("`code` và __đậm__ *nghiêng* _nghiêng_") == "code và đậm nghiêng nghiêng"


def test_title_keeps_48_chars_when_char_48_is_space():
    line = "a" * 48 + " xyz"
    assert session_title(line) == "a" * 48 + "…"


def test_mine_lists_only_callers_web_sessions_with_title():
    member = client.get("/api/sessions/mine", headers=_auth(MEMBER_TOKEN)).json()
    assert member["success"] is True
    assert [s["session_id"] for s in member["sessions"]] == ["web-bbbb2222"]
    assert member["sessions"][0]["title"] == "Giá vàng hôm nay?"
    assert member["sessions"][0]["msg_count"] == 2

    admin = client.get("/api/sessions/mine", headers=_auth(ADMIN_TOKEN)).json()
    assert [s["session_id"] for s in admin["sessions"]] == ["web-aaaa1111"]


def test_mine_read_refuses_other_users_session():
    resp = client.get("/api/sessions/mine/web-aaaa1111", headers=_auth(MEMBER_TOKEN))
    assert resp.status_code == 404
    assert "chào admin" not in resp.text


def test_mine_read_returns_own_messages_oldest_first():
    data = client.get("/api/sessions/mine/web-bbbb2222", headers=_auth(MEMBER_TOKEN)).json()
    assert [m["role"] for m in data["messages"]] == ["user", "assistant"]
    assert data["messages"][0]["content"] == "Giá vàng hôm nay?"


def test_mine_requires_token():
    assert client.get("/api/sessions/mine").status_code == 401
