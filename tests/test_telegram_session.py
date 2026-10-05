import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.core.session_context import get_session, set_session
from engine.server.telegram_bot import TelegramBot


def test_to_thread_keeps_session_id_in_worker_thread():
    async def scenario():
        bot = TelegramBot("token", {1}, SimpleNamespace())
        set_session("tg-1")
        return await bot._to_thread(get_session)

    assert asyncio.run(scenario()) == "tg-1"


def test_handle_text_scopes_the_turn_to_the_chat_session():
    seen = {}
    saved = []

    async def generate(text, client, session, **kw):
        seen["generate"] = get_session()
        return "xin chào"

    server = SimpleNamespace(
        openai_client=object(), generate_response_stream=generate, safe_ws_send_json=None
    )

    async def scenario():
        bot = TelegramBot("token", {7}, server)

        async def noop(*a, **k):
            return None

        async def save_user(text):
            saved.append(get_session())

        bot._save_user_message = save_user
        bot._send_text = noop
        bot._persist_conversation = noop
        bot._typing_loop = noop
        bot._start_reflection = lambda *a, **k: None
        await bot._handle_text(7, "chào")

    asyncio.run(scenario())
    assert seen["generate"] == "tg-7"
    assert saved == ["tg-7"]
