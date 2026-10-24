"""Ordinary turns use the model router; explicit commands and saved fast paths keep their priority."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from engine.turn import entry, schema
from engine.tools import registry


@pytest.fixture
def routing(monkeypatch):
    async def weather(location: str) -> str:
        return "Sunny"

    registry._register_for_test(weather, doc="Weather.\n\nlocation: city\n")
    loop = AsyncMock(return_value="ANSWER")
    monkeypatch.setattr("engine.turn.loop.run_loop", loop)
    monkeypatch.setattr("engine.turn.archive.unpack_archive", AsyncMock(return_value=None))
    monkeypatch.setattr(entry, "_find_workflow", lambda text: None)
    monkeypatch.setattr("engine.turn.skills.match", lambda *args: None)
    ctx = SimpleNamespace(ws=SimpleNamespace(forced_command=None), attachment_context=None)
    return loop, ctx


@pytest.mark.parametrize("text", ["Xin chào", "Mở máy tính giúp tôi", "Tôi đâu có yêu cầu dùng công cụ"])
def test_ordinary_turn_always_reaches_model_router(routing, text):
    loop, ctx = routing
    assert asyncio.run(entry.handle_turn(text, ctx)) == "ANSWER"
    loop.assert_awaited_once_with(text, ctx)


def test_workflow_and_skill_fast_paths_keep_priority(routing, monkeypatch):
    loop, ctx = routing
    workflow = {"id": 1, "tool_chain": []}
    skill = {"steps": [("weather", "Hue")]}
    monkeypatch.setattr(entry, "_find_workflow", lambda text: workflow)
    match = Mock(return_value=skill)
    monkeypatch.setattr("engine.turn.skills.match", match)
    asyncio.run(entry.handle_turn("Thời tiết Huế", ctx))
    loop.assert_awaited_once_with("Thời tiết Huế", ctx, replay=workflow)
    match.assert_not_called()
    loop.reset_mock()
    monkeypatch.setattr(entry, "_find_workflow", lambda text: None)
    asyncio.run(entry.handle_turn("Báo cáo sáng", ctx))
    loop.assert_awaited_once_with("Báo cáo sáng", ctx, skill=skill)


def test_explicit_command_and_attachment_keep_their_route(routing, monkeypatch):
    loop, ctx = routing
    ctx.ws.forced_command = {"tool": "weather", "value": "Hue"}
    asyncio.run(entry.handle_turn("/weather Hue", ctx))
    loop.assert_awaited_once_with("Hue", ctx, only="weather")
    assert ctx.ws.forced_command is None
    loop.reset_mock()
    find = Mock(side_effect=AssertionError("An attachment must not replay a saved workflow"))
    monkeypatch.setattr(entry, "_find_workflow", find)
    ctx.attachment_context = SimpleNamespace(extension=".pdf")
    asyncio.run(entry.handle_turn("Đọc tài liệu này", ctx))
    loop.assert_awaited_once_with("Đọc tài liệu này", ctx)
    find.assert_not_called()


def test_router_grammar_keeps_both_chat_and_tool_choices(routing):
    branches = schema.build(None)["anyOf"]
    tools = [branch["properties"]["tool"]["const"] for branch in branches]
    assert "none" in tools and "weather" in tools


def test_admin_only_tool_is_invisible_to_a_member(routing, monkeypatch):
    """Ngài 2026-10-24: user thường gõ @check_mail hay nói trúng skill có bước mail → như không có tool đó (không báo
    "chỉ Admin", lộ là tool tồn tại); skill khớp trên đúng danh sách tool của user. /check_mail: test_gmail_readonly."""
    loop, ctx = routing

    async def check_mail(query: str = "") -> str:
        return "mail"

    registry._register_for_test(check_mail, doc="Mail.\n\nquery: từ khoá\n", admin_only=True)
    ctx.user_id = "member"
    monkeypatch.setattr("engine.core.session_context.is_user_admin", lambda uid=None: uid != "member")
    assert entry.tool_mention("@check_mail hộp thư", "member") is None
    assert entry.tool_mention("@check_mail hộp thư", "admin") == ("check_mail", "hộp thư")
    match = Mock(return_value=None)
    monkeypatch.setattr("engine.turn.skills.match", match)
    asyncio.run(entry.handle_turn("@check_mail hộp thư", ctx))
    loop.assert_awaited_once_with("@check_mail hộp thư", ctx)
    assert "check_mail" not in match.call_args.args[1]
