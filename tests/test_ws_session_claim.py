"""WebSocket /ws/voice: bắt buộc token, phiên chỉ dùng lại khi thuộc về người gọi, gửi gói session về trang.

Run: python -m pytest tests/test_ws_session_claim.py -q -p no:cacheprovider --basetemp=.pytest-tmp
"""
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

import engine.core.memory as memory
from engine.core import session_context as sc
from engine.core.session_context import claim_ws_session, set_current_user_id, ws_user_for_token

ADMIN_TOKEN = "admin_ws_token"
MEMBER_TOKEN = "member_ws_token"
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _seed(monkeypatch):
    monkeypatch.setattr(memory, "DB_PATH", Path(tempfile.mkdtemp()) / "jarvis.db")
    memory.init_db()
    with memory._get_db() as conn:
        conn.execute("INSERT INTO users (id, username, role, created_at) VALUES ('u1', 'u1', 'member', 0)")
        conn.execute("INSERT INTO users (id, username, role, created_at) VALUES ('u2', 'u2', 'member', 0)")
        conn.execute("INSERT INTO user_tokens (token, user_id, role, created_at) VALUES (?, 'admin', 'admin', 0)", (ADMIN_TOKEN,))
        conn.execute("INSERT INTO user_tokens (token, user_id, role, created_at) VALUES (?, 'u1', 'member', 0)", (MEMBER_TOKEN,))
    yield
    set_current_user_id("admin")


def _save(uid, sid, text):
    set_current_user_id(uid)
    memory.save_message("user", text, sid)
    set_current_user_id("admin")


def test_ws_user_for_token():
    assert ws_user_for_token("") is None
    assert ws_user_for_token("junk-token") is None
    assert ws_user_for_token(MEMBER_TOKEN) == "u1"
    assert ws_user_for_token(ADMIN_TOKEN) == "admin"


def test_ws_user_for_token_db_error_propagates(monkeypatch):
    # Lỗi DB phải nổi lên để voice_handler đóng 1011 (lỗi máy chủ), không coi là token sai (1008 → đăng xuất)
    def broken_db():
        raise RuntimeError("db down")

    monkeypatch.setattr(memory, "_get_db", broken_db)
    with pytest.raises(RuntimeError):
        ws_user_for_token(MEMBER_TOKEN)


def test_claim_keeps_own_session():
    _save("u1", "web-aaaa1111", "xin chào")
    assert claim_ws_session("web-aaaa1111", "u1") == "web-aaaa1111"


def test_claim_refuses_session_with_other_users_messages():
    _save("u1", "web-bbbb2222", "tin của u1")
    sid = claim_ws_session("web-bbbb2222", "u2")
    assert sid != "web-bbbb2222" and sc.WS_SESSION_RE.fullmatch(sid)


def test_claim_refuses_session_owned_by_other_user_in_devices_table():
    with memory._get_db() as conn:
        conn.execute(
            "INSERT INTO session_devices (session_id, device, created_at, user_id) VALUES ('web-cccc3333', 'desktop', 0, 'u1')"
        )
    assert claim_ws_session("web-cccc3333", "admin") != "web-cccc3333"


def test_claim_admin_owns_null_or_empty_user_messages():
    with memory._get_db() as conn:
        conn.execute(
            "INSERT INTO messages (role, content, session_id, created_at, user_id) VALUES ('user', 'cũ', 'web-dddd4444', 0, '')"
        )
    assert claim_ws_session("web-dddd4444", "admin") == "web-dddd4444"
    assert claim_ws_session("web-dddd4444", "u1") != "web-dddd4444"


def test_claim_refuses_bad_format():
    for bad in ("", None, "web-XYZ", "web-1a2b3c4d5", "tg-1a2b3c4d", "web-1a2b3c4d;drop", "../web-1a2b3c4d"):
        sid = claim_ws_session(bad, "u1")
        assert sid != bad and sc.WS_SESSION_RE.fullmatch(sid), (bad, sid)


def test_claim_accepts_unused_id():
    assert claim_ws_session("web-eeee5555", "u1") == "web-eeee5555"


def test_voice_handler_rejects_missing_token():
    src = (ROOT / "server.py").read_text(encoding="utf-8")
    body = re.search(r"async def voice_handler.*?(?=\n@|\nasync def |\ndef |\nclass |\Z)", src, re.S).group(0)
    assert "ws_user_for_token(token)" in body
    assert re.search(r"if ws_user_id is None:\s*\n\s*await ws\.close\(code=1008\)\s*\n\s*return", body)
    assert re.search(r"except Exception[^\n]*\n(?:[^\n]*\n){0,3}?\s*await ws\.close\(code=1011\)", body)
    assert 'ws_user_id = "admin"' not in body
    assert 'safe_ws_send_json(ws, {"type": "session", "id": ws.session_id})' in body
