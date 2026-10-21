import os
import time
import pytest
from unittest.mock import MagicMock, patch
from starlette.requests import Request
import server
from engine.server.tts_manager import _resolve_user_voice
from engine.core.memory import _get_db
from engine.core.session_context import set_current_user_id
from engine.UIUX.ui_engine import api_tts_voices, api_tts_select_voice, VoiceSelect


@pytest.fixture(autouse=True)
def setup_teardown_users():
    orig_env_voice = os.environ.get("VIENEU_VOICE_ID", "")
    with _get_db() as conn:
        # Lưu admin ban đầu nếu có
        admin_row = conn.execute("SELECT tts_voice_id FROM users WHERE id = 'admin'").fetchone()
        orig_admin_voice = admin_row["tts_voice_id"] if admin_row else ""

        # Tạo / reset user test
        conn.execute(
            "INSERT OR REPLACE INTO users (id, username, display_name, role, tts_voice_id, created_at) "
            "VALUES ('user-test-tts-member', 'test_tts_member', 'Test Member', 'member', 'voice_member_init', ?)",
            (time.time(),)
        )
        conn.execute(
            "INSERT OR REPLACE INTO users (id, username, display_name, role, tts_voice_id, created_at) "
            "VALUES ('admin', 'admin', 'Admin', 'admin', 'voice_admin_master', ?)",
            (time.time(),)
        )
        
        # Tạo token test
        conn.execute("INSERT OR REPLACE INTO user_tokens (token, user_id, role, created_at) VALUES ('tok_test_member', 'user-test-tts-member', 'member', ?)", (time.time(),))
        conn.execute("INSERT OR REPLACE INTO user_tokens (token, user_id, role, created_at) VALUES ('tok_test_admin', 'admin', 'admin', ?)", (time.time(),))
        conn.commit()

    os.environ["VIENEU_VOICE_ID"] = "voice_admin_master"

    yield

    with _get_db() as conn:
        conn.execute("DELETE FROM user_tokens WHERE token IN ('tok_test_member', 'tok_test_admin')")
        conn.execute("DELETE FROM users WHERE id = 'user-test-tts-member'")
        if orig_admin_voice:
            conn.execute("UPDATE users SET tts_voice_id = ? WHERE id = 'admin'", (orig_admin_voice,))
        conn.commit()

    if orig_env_voice:
        os.environ["VIENEU_VOICE_ID"] = orig_env_voice
    elif "VIENEU_VOICE_ID" in os.environ:
        del os.environ["VIENEU_VOICE_ID"]


def test_resolve_user_voice_priority():
    # 1. Explicit voice
    assert _resolve_user_voice(explicit_voice="explicit_v") == "explicit_v"

    # 2. WebSocket with tts_voice_id
    ws_mock = MagicMock()
    ws_mock.tts_voice_id = "ws_voice_123"
    assert _resolve_user_voice(ws=ws_mock) == "ws_voice_123"

    # 3. WebSocket with user_id
    ws_mock2 = MagicMock(spec=["user_id"])
    ws_mock2.user_id = "user-test-tts-member"
    assert _resolve_user_voice(ws=ws_mock2) == "voice_member_init"

    # 4. Session context current user
    set_current_user_id("user-test-tts-member")
    try:
        assert _resolve_user_voice() == "voice_member_init"
    finally:
        set_current_user_id("admin")

    # 5. Fallback to env
    set_current_user_id("non-existent-user")
    try:
        assert _resolve_user_voice() == "voice_admin_master"
    finally:
        set_current_user_id("admin")


@pytest.mark.asyncio
async def test_api_tts_voices_multiuser_isolation():
    def make_request(token):
        scope = {
            "type": "http",
            "headers": [(b"authorization", f"Bearer {token}".encode("latin-1"))],
        }
        return Request(scope)

    req_member = make_request("tok_test_member")
    req_admin = make_request("tok_test_admin")

    with patch("engine.UIUX.ui_engine._tts_voices_call") as mock_voices_call, \
         patch("server._write_env_key") as mock_write_env:

        mock_voices_call.return_value = {"voices": ["voice_a", "voice_b"], "default": "voice_a"}

        # 1. Member GET /api/tts/voices -> current phải là voice của member
        res_member = await api_tts_voices(request=req_member)
        assert res_member["current"] == "voice_member_init"

        # 2. Admin GET /api/tts/voices -> current phải là voice của admin
        res_admin = await api_tts_voices(request=req_admin)
        assert res_admin["current"] == "voice_admin_master"

        # 3. Member đổi giọng thành "voice_member_custom"
        select_body_member = VoiceSelect(voice="voice_member_custom")
        res_update_member = await api_tts_select_voice(body=select_body_member, request=req_member)
        assert res_update_member["success"] is True

        # Kiểm tra:
        # - DB của member được cập nhật
        with _get_db() as conn:
            m_voice = conn.execute("SELECT tts_voice_id FROM users WHERE id = 'user-test-tts-member'").fetchone()["tts_voice_id"]
            a_voice = conn.execute("SELECT tts_voice_id FROM users WHERE id = 'admin'").fetchone()["tts_voice_id"]
        assert m_voice == "voice_member_custom"
        # - DB của admin và os.environ KHÔNG bị thay đổi
        assert a_voice == "voice_admin_master"
        assert os.environ.get("VIENEU_VOICE_ID") == "voice_admin_master"
        mock_write_env.assert_not_called()

        # 4. Admin đổi giọng thành "voice_admin_new"
        select_body_admin = VoiceSelect(voice="voice_admin_new")
        res_update_admin = await api_tts_select_voice(body=select_body_admin, request=req_admin)
        assert res_update_admin["success"] is True

        # Kiểm tra:
        # - DB của admin được cập nhật
        # - os.environ và .env được cập nhật
        # - DB của member KHÔNG bị ảnh hưởng
        with _get_db() as conn:
            m_voice = conn.execute("SELECT tts_voice_id FROM users WHERE id = 'user-test-tts-member'").fetchone()["tts_voice_id"]
            a_voice = conn.execute("SELECT tts_voice_id FROM users WHERE id = 'admin'").fetchone()["tts_voice_id"]
        assert a_voice == "voice_admin_new"
        assert os.environ.get("VIENEU_VOICE_ID") == "voice_admin_new"
        assert m_voice == "voice_member_custom"
        mock_write_env.assert_called_with("VIENEU_VOICE_ID", "voice_admin_new")
