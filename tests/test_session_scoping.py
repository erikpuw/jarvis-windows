import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

import engine.core.memory as memory
from engine.core.session_context import get_session, set_session


@pytest.fixture(autouse=True)
def _fresh_db(monkeypatch):
    monkeypatch.setattr(memory, "DB_PATH", Path(tempfile.mkdtemp()) / "jarvis.db")
    memory.init_db()
    set_session("")
    yield
    set_session("")


def _say(session, role, text, **kw):
    set_session(session)
    memory.save_message(role, text, **kw)


def test_session_context_defaults_empty_and_is_settable():
    assert get_session() == ""
    set_session("web-aaaa1111")
    assert get_session() == "web-aaaa1111"


def test_same_text_in_two_sessions_is_not_a_duplicate():
    _say("web-a", "user", "ừ")
    _say("web-b", "user", "ừ")
    rows = memory.get_messages(limit=10)
    assert [r["session_id"] for r in rows] == ["web-a", "web-b"]


def test_repeat_inside_one_session_is_still_skipped():
    _say("web-a", "user", "ừ")
    _say("web-a", "user", "ừ")
    assert len(memory.get_messages(limit=10)) == 1


def test_pending_offer_ignores_rows_of_other_sessions():
    _say("web-a", "assistant", "Mở Notepad nhé?", ask_user="Mở Notepad nhé?", action_run="open_app")
    _say("web-b", "user", "ừ")  # phiên khác chen vào giữa
    _say("web-a", "user", "ừ")
    set_session("web-a")
    assert memory.get_pending_offer() == ("Mở Notepad nhé?", "open_app")
    set_session("web-b")
    assert memory.get_pending_offer() == ("", "")


def test_get_messages_filters_by_session_and_unfiltered_returns_all():
    _say("web-a", "user", "một")
    _say("tg-5", "user", "hai")
    assert [m["content"] for m in memory.get_messages(limit=10, session_id="tg-5")] == ["hai"]
    assert len(memory.get_messages(limit=10)) == 2


def test_routing_history_only_current_session():
    _say("web-a", "user", "chuyện của A")
    _say("web-b", "user", "chuyện của B")
    set_session("web-b")
    texts = [m["content"] for m in memory.build_unified_routing_history("xin chào")]
    assert "chuyện của B" in texts
    assert "chuyện của A" not in texts


def test_chat_history_only_current_session():
    from engine.prompts.chat import build_chat_history

    _say("web-a", "user", "chuyện của A")
    _say("web-b", "user", "chuyện của B")
    set_session("web-b")
    texts = [m["content"] for m in build_chat_history(user_text="xin chào")]
    assert texts == ["chuyện của B"]
