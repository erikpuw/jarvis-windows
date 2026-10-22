import sqlite3
from types import SimpleNamespace

import pytest

from engine.server.tts_manager import _resolve_user_voice, _vieneu_payload


@pytest.fixture
def voice_db(tmp_path, monkeypatch):
    from engine.core import memory

    db = tmp_path / "voices.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE users (id TEXT PRIMARY KEY, tts_voice_id TEXT)")
        conn.executemany("INSERT INTO users VALUES (?, ?)", [
            ("member", "vi-VN-HoaiMyNeural"), ("admin", "Adam bựa"),
        ])
    monkeypatch.setattr(memory, "DB_PATH", db)
    monkeypatch.setenv("VIENEU_VOICE_ID", "Adam bựa")
    monkeypatch.setenv("TTS_LOCAL_MODEL", "vi-VN-NamMinhNeural")
    return db


def test_vieneu_ignores_saved_edge_voice(voice_db):
    ws = SimpleNamespace(user_id="member", tts_voice_id="vi-VN-HoaiMyNeural")
    assert _vieneu_payload("Xin chào.", ws=ws) == {"text": "Xin chào.", "voice": "Adam bựa"}


def test_open_socket_uses_newly_selected_voice(voice_db):
    ws = SimpleNamespace(user_id="member", tts_voice_id="vi-VN-HoaiMyNeural")
    with sqlite3.connect(voice_db) as conn:
        conn.execute("UPDATE users SET tts_voice_id = 'Mạnh Dũng' WHERE id = 'member'")
    assert _vieneu_payload("Xin chào.", ws=ws)["voice"] == "Mạnh Dũng"
    assert _resolve_user_voice(ws=SimpleNamespace(user_id="admin"), engine="vieneu") == "Adam bựa"


def test_edge_ignores_saved_vieneu_voice(voice_db):
    ws = SimpleNamespace(user_id="admin", tts_voice_id="Adam bựa")
    assert _resolve_user_voice(ws=ws, engine="edge") == "vi-VN-NamMinhNeural"


def test_explicit_voice_keeps_priority(voice_db):
    ws = SimpleNamespace(user_id="member", tts_voice_id="vi-VN-HoaiMyNeural")
    assert _resolve_user_voice(ws=ws, explicit_voice="Trúc Ly", engine="vieneu") == "Trúc Ly"


def test_voice_only_socket_keeps_its_voice(voice_db, monkeypatch):
    from engine.core import session_context

    monkeypatch.setattr(session_context, "get_current_user_id", lambda: "admin")
    assert _resolve_user_voice(ws=SimpleNamespace(tts_voice_id="Trúc Ly"), engine="vieneu") == "Trúc Ly"


def test_edge_keeps_saved_edge_voice(voice_db):
    assert _resolve_user_voice(ws=SimpleNamespace(user_id="member"), engine="edge") == "vi-VN-HoaiMyNeural"
