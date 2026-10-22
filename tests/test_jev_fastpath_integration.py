"""Integration test cho Fast-path Jev Gate trong engine.turn.entry."""
import threading
from unittest.mock import AsyncMock, patch

import pytest

from engine.turn import entry


class FakeContext:
    def __init__(self):
        self.ws = AsyncMock()
        self.ws.forced_command = None
        self.send_json = AsyncMock()
        self.attachment_context = None
        self.flow_tracker = AsyncMock()
        self.conversation_history = []


@pytest.mark.asyncio
async def test_jev_fastpath_chat_query():
    """Khi Jev phân loại là Chat với độ tin cậy cao, entry bỏ qua vòng chọn tool."""
    ctx = FakeContext()
    chat_text = "Xin chào bạn, hôm nay bạn thế nào?"

    with patch("engine.turn.jev_gate.is_available", return_value=True), \
         patch("engine.turn.jev_gate.classify_chat", return_value=(True, 0.96)), \
         patch("engine.turn.loop.run_loop", new_callable=AsyncMock) as mock_loop:
        mock_loop.return_value = "Xin chào ngài!"
        res = await entry.handle_turn(chat_text, ctx)
        assert res == "Xin chào ngài!"
        mock_loop.assert_awaited_once()
        _, kwargs = mock_loop.call_args
        assert kwargs.get("skip_tool_round") is True, f"Chat query phải có skip_tool_round=True, nhận: {kwargs}"


@pytest.mark.asyncio
async def test_jev_fastpath_tool_query():
    """Khi Jev phân loại là Tool, entry vẫn chạy đủ vòng chọn tool bình thường."""
    ctx = FakeContext()
    tool_text = "Thời tiết Hà Nội hôm nay có mưa không?"

    with patch("engine.turn.jev_gate.is_available", return_value=True), \
         patch("engine.turn.jev_gate.classify_chat", return_value=(False, 0.92)), \
         patch("engine.turn.loop.run_loop", new_callable=AsyncMock) as mock_loop:
        mock_loop.return_value = "Đang tra thời tiết..."
        res = await entry.handle_turn(tool_text, ctx)
        assert res == "Đang tra thời tiết..."
        mock_loop.assert_awaited_once()
        _, kwargs = mock_loop.call_args
        assert kwargs.get("skip_tool_round") is not True, f"Tool query không được skip_tool_round, nhận: {kwargs}"


@pytest.mark.asyncio
async def test_jev_unavailable_fallback():
    """Khi Jev không khả dụng, entry vẫn hoạt động bình thường qua vòng lặp chọn tool."""
    ctx = FakeContext()
    text = "Xin chào bạn"

    with patch("engine.turn.jev_gate.is_available", return_value=False), \
         patch("engine.turn.loop.run_loop", new_callable=AsyncMock) as mock_loop:
        mock_loop.return_value = "Chào ngài!"
        res = await entry.handle_turn(text, ctx)
        assert res == "Chào ngài!"
        mock_loop.assert_awaited_once()
        _, kwargs = mock_loop.call_args
        assert kwargs.get("skip_tool_round") is not True


@pytest.mark.asyncio
async def test_health_check_runs_outside_event_loop():
    loop_thread = threading.get_ident()
    checked = []

    def available():
        checked.append(threading.get_ident())
        return False

    with patch("engine.turn.jev_gate.is_available", side_effect=available), \
         patch("engine.turn.loop.run_loop", new_callable=AsyncMock):
        await entry.handle_turn("Xin chào bạn", FakeContext())
    assert checked and checked[0] != loop_thread
