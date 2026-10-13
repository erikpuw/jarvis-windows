"""Ngữ cảnh một lượt, dùng chung WebUI và Telegram."""
from dataclasses import dataclass, field
from typing import Any


class _NoOpStep:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class NoOpTracker:
    """Thay FlowTracker khi caller không truyền (Telegram)."""

    def step(self, label):
        return _NoOpStep()

    async def track(self, label, status="completed"):
        pass


@dataclass
class TurnContext:
    ws: Any
    send_json: Any                       # async (ws, dict) -> bool  (server.safe_ws_send_json)
    client: Any = None
    conversation_history: list = field(default_factory=list)
    flow_tracker: Any = None
    attachment_context: Any = None
    background_tasks: set | None = None  # server._background_tasks

    def __post_init__(self):
        self.flow_tracker = self.flow_tracker or NoOpTracker()
        self.conversation_history = list(self.conversation_history or [])
