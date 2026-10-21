import asyncio
import os
import shutil
import sys
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.UIUX import ui_engine, memory_lock
from engine.core.memory import (
    init_db,
    _get_db,
    get_user_by_telegram_chat_id,
    link_telegram_chat_id,
)
from engine.core.session_context import get_current_user_id, set_current_user_id
from engine.server.telegram_bot import TelegramBot

app = FastAPI()
app.include_router(ui_engine.router)
app.include_router(memory_lock.lock_router)
client = TestClient(app)


@pytest.fixture(autouse=True)
def _setup(monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "admin-pass-123")
    init_db()
    memory_lock._tokens.clear()
    set_current_user_id("admin")
    yield
    memory_lock._tokens.clear()
    set_current_user_id("admin")
    with _get_db() as conn:
        junk_users = conn.execute(
            "SELECT id FROM users WHERE username LIKE 'tg_%' OR id LIKE 'tg_%'"
        ).fetchall()
        for u in junk_users:
            uid = u[0]
            conn.execute("DELETE FROM users WHERE id = ?", (uid,))
            conn.execute("DELETE FROM user_tokens WHERE user_id = ?", (uid,))
            conn.execute("DELETE FROM learnings WHERE user_id = ?", (uid,))
            conn.execute("DELETE FROM messages WHERE user_id = ?", (uid,))
            shutil.rmtree(Path("data/users") / uid, ignore_errors=True)
        conn.commit()


def test_telegram_resolve_and_link():
    bot = TelegramBot("dummy_token", {12345}, SimpleNamespace(openai_client=None))

    # 1. Chat in allowed_chat_ids defaults to admin
    admin_user = bot._resolve_user_for_chat(12345)
    assert admin_user is not None
    assert admin_user["id"] == "admin"
    assert admin_user["role"] == "admin"

    # 2. Unknown chat returns None
    assert bot._resolve_user_for_chat(999999) is None

    # 3. Create a member user and token in DB
    mem_id = f"tg_{uuid.uuid4().hex[:6]}"
    mem_uname = f"tg_member_{uuid.uuid4().hex[:4]}"
    token = f"mem_token_{uuid.uuid4().hex[:8]}"

    with _get_db() as conn:
        conn.execute(
            "INSERT INTO users (id, username, display_name, role, created_at) VALUES (?, ?, ?, 'member', ?)",
            (mem_id, mem_uname, "Telegram Member", time.time()),
        )
        conn.execute(
            "INSERT INTO user_tokens (token, user_id, role, created_at) VALUES (?, ?, 'member', ?)",
            (token, mem_id, time.time()),
        )
        conn.commit()

    try:
        # Link via helper
        assert link_telegram_chat_id(mem_id, 999999) is True

        # Now _resolve_user_for_chat finds member
        resolved = bot._resolve_user_for_chat(999999)
        assert resolved is not None
        assert resolved["id"] == mem_id
        assert resolved["role"] == "member"
        assert resolved["username"] == mem_uname

        # Test link command via bot
        sent_messages = []

        async def fake_send_text(chat_id, text, **kw):
            sent_messages.append((chat_id, text))

        bot._send_text = fake_send_text

        # Invalid token
        res_fail = asyncio.run(bot._handle_link_command(888888, "/link invalid_token"))
        assert res_fail is True
        assert "không hợp lệ" in sent_messages[-1][1]

        # Valid token for new chat 888888
        res_ok = asyncio.run(bot._handle_link_command(888888, f"/link {token}"))
        assert res_ok is True
        assert "Liên kết thành công" in sent_messages[-1][1]

        # Check in DB
        user_888 = get_user_by_telegram_chat_id(888888)
        assert user_888 is not None
        assert user_888["id"] == mem_id

    finally:
        with _get_db() as conn:
            conn.execute("DELETE FROM users WHERE id = ?", (mem_id,))
            conn.execute("DELETE FROM user_tokens WHERE user_id = ?", (mem_id,))
            conn.commit()


def test_telegram_member_execution_and_isolation():
    mem_id = f"tg_{uuid.uuid4().hex[:6]}"
    mem_uname = f"tg_user_{uuid.uuid4().hex[:4]}"
    mem_chat_id = 777777

    with _get_db() as conn:
        conn.execute(
            "INSERT INTO users (id, username, display_name, role, telegram_chat_id, created_at) VALUES (?, ?, ?, 'member', ?, ?)",
            (mem_id, mem_uname, "Member User", str(mem_chat_id), time.time()),
        )
        conn.commit()

    seen_user_ids = []

    async def fake_generate_stream(text, client, session, **kw):
        seen_user_ids.append(getattr(session, "user_id", None))
        seen_user_ids.append(get_current_user_id())
        return "Xin chào thành viên"

    server = SimpleNamespace(
        openai_client=object(),
        generate_response_stream=fake_generate_stream,
        safe_ws_send_json=None,
    )

    bot = TelegramBot("dummy_token", {12345}, server)

    sent = []

    async def fake_send(chat_id, text, **kw):
        sent.append((chat_id, text))

    bot._send_text = fake_send

    reflection_user_ids = []

    def fake_reflection(u_text, r_text, user_id=None):
        reflection_user_ids.append(user_id)

    bot._start_reflection = fake_reflection

    try:
        # 1. Member sends normal message
        asyncio.run(bot._handle_text(mem_chat_id, "Tôi muốn đặt lịch"))
        assert mem_id in seen_user_ids
        assert reflection_user_ids == [mem_id]

        # Check DB messages saved with member user_id
        with _get_db() as conn:
            row = conn.execute(
                "SELECT user_id, session_id FROM messages WHERE content = 'Tôi muốn đặt lịch'"
            ).fetchone()
            assert row is not None
            assert row["user_id"] == mem_id
            assert row["session_id"] == f"tg-{mem_chat_id}"

        # 2. Member tries /restart -> blocked
        update_msg = {
            "message": {
                "chat": {"id": mem_chat_id, "type": "private"},
                "from": {"id": mem_chat_id, "username": mem_uname},
                "text": "/restart",
            }
        }
        asyncio.run(bot._handle_update(update_msg))
        assert any("chỉ dành cho Quản trị viên" in s[1] for s in sent)

        # 3. Unlinked user tries to send message -> rejected with polite guide
        unlinked_chat_id = 555555
        update_unlinked = {
            "message": {
                "chat": {"id": unlinked_chat_id, "type": "private"},
                "from": {"id": unlinked_chat_id, "username": "stranger"},
                "text": "Hello bot",
            }
        }
        asyncio.run(bot._handle_update(update_unlinked))
        assert any("chưa được liên kết" in s[1] for s in sent)

    finally:
        with _get_db() as conn:
            conn.execute("DELETE FROM messages WHERE session_id = ?", (f"tg-{mem_chat_id}",))
            conn.execute("DELETE FROM users WHERE id = ?", (mem_id,))
            conn.commit()


def test_telegram_chat_id_api_integration():
    res_adm = client.post(
        "/api/auth/login", json={"username": "admin", "password": "admin-pass-123"}
    )
    token_admin = res_adm.json()["token"]

    mem_id = f"tg_{uuid.uuid4().hex[:6]}"
    mem_uname = f"tg_api_{uuid.uuid4().hex[:4]}"

    with _get_db() as conn:
        conn.execute(
            "INSERT INTO users (id, username, display_name, role, created_at) VALUES (?, ?, ?, 'member', ?)",
            (mem_id, mem_uname, "API User", time.time()),
        )
        conn.commit()

    try:
        # 1. Admin lists users -> sees telegram_chat_id field
        res_list = client.get(
            "/api/users/list", headers={"Authorization": f"Bearer {token_admin}"}
        )
        assert res_list.status_code == 200
        items = res_list.json()["users"]
        target = next((u for u in items if u["id"] == mem_id), None)
        assert target is not None
        assert "telegram_chat_id" in target

        # 2. Admin updates telegram_chat_id
        res_update = client.post(
            "/api/users/update",
            json={"id": mem_id, "values": {"telegram_chat_id": "99887766"}},
            headers={"Authorization": f"Bearer {token_admin}"},
        )
        assert res_update.status_code == 200
        assert res_update.json()["success"] is True

        # Verify DB updated
        user_row = get_user_by_telegram_chat_id("99887766")
        assert user_row is not None
        assert user_row["id"] == mem_id

    finally:
        with _get_db() as conn:
            conn.execute("DELETE FROM users WHERE id = ?", (mem_id,))
            conn.commit()
