# tests/turn/test_entry.py
import asyncio
from types import SimpleNamespace

import pytest

from engine.tools import registry as R
from engine.turn import entry as E
from engine.turn.context import TurnContext


@pytest.fixture
def env(monkeypatch):
    R._reset_for_test()

    async def weather(location: str) -> str:
        return ""
    R._register_for_test(weather, doc="Thời tiết.\n\nlocation: nơi\n")
    calls = []

    async def fake_loop(text, ctx, only=None, replay=None, **kw):
        calls.append(("loop", text, only) if replay is None else ("replay", text, replay["id"]))
        return "LOOP"

    async def fake_rag(d, ctx):
        calls.append(("rag", d.query))
        return "RAG"

    async def no_archive(ctx):
        return None
    monkeypatch.setattr("engine.turn.loop.run_loop", fake_loop)
    monkeypatch.setattr("engine.rag.runner.handle", fake_rag)
    monkeypatch.setattr("engine.turn.archive.unpack_archive", no_archive)
    monkeypatch.setattr("engine.turn.entry._find_workflow", lambda text: None)
    yield calls
    R._reset_for_test()


def _ctx():
    async def send(ws, data):
        return True
    return TurnContext(ws=SimpleNamespace(forced_command=None, cancel_requested=False), send_json=send)


def test_order(env):
    ctx = _ctx()
    ctx.ws.forced_command = {"tool": "weather", "value": "huế"}
    assert asyncio.run(E.handle_turn("/weather huế", ctx)) == "LOOP" and ctx.ws.forced_command is None
    asyncio.run(E.handle_turn("@weather đà lạt", _ctx()))
    asyncio.run(E.handle_turn("@rag tài liệu nói gì", _ctx()))
    asyncio.run(E.handle_turn("@khongco xin chào", _ctx()))
    asyncio.run(E.handle_turn("thời tiết huế", _ctx()))
    assert env == [("loop", "huế", "weather"), ("loop", "đà lạt", "weather"), ("rag", "tài liệu nói gì"),
                   ("loop", "@khongco xin chào", None), ("loop", "thời tiết huế", None)]


def test_mention_list_from_registry(env):
    items = E.mention_list()
    assert items[0]["name"] == "rag" and {"name": "weather", "description": "Thời tiết."} in items
    assert not any(i["name"] in ("plans", "jobs") for i in items)


def test_rag_shortcut_still_ends_the_flow(env):
    """run_loop tự gửi 'Hoàn thành' trước khi chờ TTS (server.py thôi gửi); lối tắt @rag phải tự gửi."""
    done = []

    class _T:
        def step(self, label):
            raise AssertionError
        async def track(self, label, status="completed"):
            done.append(label)
    ctx = _ctx()
    ctx.flow_tracker = _T()
    asyncio.run(E.handle_turn("@rag tài liệu nói gì", ctx))
    assert done == ["Hoàn thành"]


def test_saved_workflow_is_replayed_except_with_attachment(env, monkeypatch):
    monkeypatch.setattr("engine.turn.entry._find_workflow",
                        lambda text: {"id": 3, "tools": "weather", "tool_chain": []} if text == "thời tiết huế" else None)
    asyncio.run(E.handle_turn("thời tiết huế", _ctx()))
    ctx = _ctx()
    ctx.attachment_context = SimpleNamespace(extension=".pdf")
    asyncio.run(E.handle_turn("thời tiết huế", ctx))
    asyncio.run(E.handle_turn("@weather thời tiết huế", _ctx()))
    assert env == [("replay", "thời tiết huế", 3), ("loop", "thời tiết huế", None),
                   ("loop", "thời tiết huế", "weather")]
