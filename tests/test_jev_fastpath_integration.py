import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch
import pytest

WORKSPACE = Path(r"E:\workspace\jarvis")
sys.path.insert(0, str(WORKSPACE))

from engine.turn import entry, jev_gate


class FakeContext:
    def __init__(self):
        self.ws = AsyncMock()
        self.ws.forced_command = None
        self.send_json = AsyncMock()
        self.attachment_context = None
        self.flow_tracker = AsyncMock()
        self.conversation_history = []


@pytest.mark.asyncio
async def test_integration():
    ctx = FakeContext()

    # 1. Test Chat query
    with patch("engine.turn.loop.run_loop", new_callable=AsyncMock) as mock_loop:
        mock_loop.return_value = "Xin chào ngài!"
        chat_text = "Xin chào bạn, hôm nay bạn thế nào?"
        res = await entry.handle_turn(chat_text, ctx)
        assert res == "Xin chào ngài!"
        mock_loop.assert_awaited_once()
        _, kwargs = mock_loop.call_args
        assert kwargs.get("skip_tool_round") is True, f"Chat query phải có skip_tool_round=True, nhận: {kwargs}"

    # 2. Test Tool query
    with patch("engine.turn.loop.run_loop", new_callable=AsyncMock) as mock_loop:
        mock_loop.return_value = "Đang tra thời tiết..."
        tool_text = "Thời tiết Hà Nội hôm nay có mưa không?"
        res = await entry.handle_turn(tool_text, ctx)
        assert res == "Đang tra thời tiết..."
        mock_loop.assert_awaited_once()
        _, kwargs = mock_loop.call_args
        assert kwargs.get("skip_tool_round") is not True, f"Tool query không được skip_tool_round, nhận: {kwargs}"

    jev_gate.close()


if __name__ == "__main__":
    asyncio.run(test_integration())
