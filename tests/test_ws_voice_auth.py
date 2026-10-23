"""WebSocket /ws/voice qua TestClient: token sai bị đóng 1008; token thành viên nhận gói session đầu tiên.

Run: python -m pytest tests/test_ws_voice_auth.py -q -p no:cacheprovider --basetemp=.pytest-tmp
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from starlette.websockets import WebSocketDisconnect
from starlette.testclient import TestClient

import engine.core.memory as memory

MEMBER_TOKEN = "member_ws_auth_token"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(memory, "DB_PATH", Path(tempfile.mkdtemp()) / "jarvis.db")
    memory.init_db()
    with memory._get_db() as conn:
        conn.execute("INSERT INTO users (id, username, role, created_at) VALUES ('u1', 'u1', 'member', 0)")
        conn.execute("INSERT INTO user_tokens (token, user_id, role, created_at) VALUES (?, 'u1', 'member', 0)", (MEMBER_TOKEN,))
    import server
    return TestClient(server.app, client=("127.0.0.1", 50000))


def test_junk_token_closed_1008(client):
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws/voice?token=junk-token") as ws:
            ws.receive_json()
    assert exc.value.code == 1008


def test_member_token_gets_session_packet(client):
    with client.websocket_connect(f"/ws/voice?token={MEMBER_TOKEN}") as ws:
        packet = ws.receive_json()
    assert packet["type"] == "session"
    assert packet["id"].startswith("web-") and len(packet["id"]) == len("web-") + 8


def test_db_error_closes_1011_so_page_stays_logged_in(client, monkeypatch):
    def broken_db():
        raise RuntimeError("db down")

    monkeypatch.setattr(memory, "_get_db", broken_db)
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(f"/ws/voice?token={MEMBER_TOKEN}") as ws:
            ws.receive_json()
    assert exc.value.code == 1011
