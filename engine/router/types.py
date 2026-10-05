"""Kiểu dữ liệu dùng chung của router. Thay chuỗi route đa nghĩa của route_agents.py cũ."""
from dataclasses import dataclass, field
from typing import Any, Literal

RouteKind = Literal["general", "general_knowledge", "orchestrator", "agent", "replay", "attachment_clarify", "plan", "jobs", "rag"]
BUCKETS = ("general", "general_knowledge", "orchestrator", "attachment_clarify")


@dataclass
class RouteDecision:
    kind: RouteKind
    query: str                    # câu sẽ xử lý
    source: str                   # mention | ask_reply | voice | complaint | replay | gate | fallback | short
    agent: str | None = None      # kind="agent"/"replay"
    workflow: dict | None = None  # kind="replay": {id, agent, tool_chain}


class _NoOpStep:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class NoOpTracker:
    """Thay FlowTracker/FlowAgents khi caller không truyền (trước đây lặp ở server.py và route_agents.py)."""

    def step(self, label, *args, **kwargs):
        return _NoOpStep()

    async def track(self, *args, **kwargs):
        pass

    async def fail_all_active(self):
        pass

    async def complete_all_active(self):
        pass


@dataclass
class TurnContext:
    ws: Any
    send_json: Any                       # async (ws, dict) -> bool  (server.safe_ws_send_json)
    client: Any = None
    conversation_history: list = field(default_factory=list)
    flow_tracker: Any = None
    flow_agents: Any = None
    attachment_context: Any = None
    background_tasks: set | None = None  # server._background_tasks
    action_declined: bool = False        # Task 18: agent path fell back to chat

    def __post_init__(self):
        self.flow_tracker = self.flow_tracker or NoOpTracker()
        self.flow_agents = self.flow_agents or NoOpTracker()
        self.conversation_history = list(self.conversation_history or [])
