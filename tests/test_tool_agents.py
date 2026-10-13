"""Kiểm tra tool registry và forced tool router mới."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.tools import registry


def test_slash_marks_forced_command():
    from types import SimpleNamespace
    from engine.server.slash_commands import handle_slash_message

    async def send(payload):
        pass

    ws = SimpleNamespace(pending_slash_command=None)
    asyncio.run(handle_slash_message(ws, "/weather Hà Nội", send))
    assert ws.forced_command == {"tool": "weather", "value": "Hà Nội"}
    ws = SimpleNamespace(pending_slash_command=None)
    asyncio.run(handle_slash_message(ws, "/open_app notepad", send))
    assert ws.forced_command == {"tool": "open_app", "value": "notepad"}
