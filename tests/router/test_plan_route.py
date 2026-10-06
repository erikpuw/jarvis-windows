"""Cửa vào chế độ mục tiêu: CHỈ lệnh "@plans <mục tiêu>" (user 2026-09-27).
Trước đó chat được đề nghị <action_run>plan_goal</action_run> → prompt chat thêm luật đề nghị, model đề nghị lung tung.
Nay chat không biết plan_goal; router giữ nguyên, chỉ thêm lối tắt @plans trước resolve_mention."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import engine.router.decide  # noqa: F401 — nạp submodule trước khi lấy từ sys.modules (xem test_decide.py)
from engine.prompts import catalog
from engine.router import dispatch as DP
from engine.router.ask_user import extract_action
from engine.router.fast_paths import plan_mention
from engine.router.types import RouteDecision, TurnContext

D = sys.modules["engine.router.decide"]


def _decide(text, monkeypatch, ask="", tool=""):
    import engine.core.memory as memory
    monkeypatch.setattr(memory, "get_pending_offer", lambda: (ask, tool))
    calls = {"gate": 0}

    async def gate(clean, ctx):
        calls["gate"] += 1
        return "general"

    async def no_replay(clean, att):
        return None
    monkeypatch.setattr(D, "classify_bucket", gate)
    monkeypatch.setattr(D, "find_replay", no_replay)
    return asyncio.run(D.decide(text, TurnContext(ws=object(), send_json=None))), calls["gate"]


def test_plan_mention_parses_goal():
    assert plan_mention("@plans hôm nay không biết ăn gì") == "hôm nay không biết ăn gì"
    assert plan_mention("@plan, trưa nay ăn gì") == "trưa nay ăn gì"
    assert plan_mention("@PLANS: đi đâu chơi") == "đi đâu chơi"
    assert plan_mention("@plans") is None and plan_mention("@plans   ") is None
    assert plan_mention("@planner x") is None and plan_mention("hôm nay @plans x") is None
    assert plan_mention("@search thời tiết") is None


def test_plans_mention_routes_to_plan_without_gate(monkeypatch):
    d, gate = _decide("@plans hôm nay không biết ăn gì", monkeypatch)
    assert (d.kind, d.query, d.source, gate) == ("plan", "hôm nay không biết ăn gì", "mention", 0)


def test_empty_plans_mention_and_normal_text_keep_old_routing(monkeypatch):
    assert _decide("@plans", monkeypatch)[0].kind == "general"
    d, gate = _decide("hôm nay không biết ăn gì", monkeypatch)
    assert (d.kind, d.source, gate) == ("general", "gate", 1)


def test_chat_no_longer_knows_plan_goal(monkeypatch):
    assert "plan_goal" not in catalog.tool_list_text() and len(catalog.offerable_tools()) == 17
    assert not hasattr(catalog, "offer_choices")
    assert extract_action("x <ask_user>tìm hiểu</ask_user> không?<action_run>plan_goal</action_run>") == ""
    # lời đề nghị cũ còn trong DB (trước khi gỡ) không được mở chế độ mục tiêu
    d, _ = _decide("ừ", monkeypatch, "tìm hiểu và gợi ý món ăn hôm nay", "plan_goal")
    assert d.kind != "plan"


class _WS:
    pass


def _ctx():
    sent = []

    async def send(ws, data):
        sent.append(data)
        return True
    return TurnContext(ws=_WS(), send_json=send), sent


def test_dispatch_plan_runs_plan_and_falls_back_to_chat_when_empty(monkeypatch):
    calls = {"result": ""}

    async def fake_plan(goal, ctx):
        calls["plan"] = goal
        return calls["result"]

    async def fake_chat(kind, text, ctx):
        calls["chat"] = kind
        return f"CHAT:{kind}"
    monkeypatch.setattr(DP, "_run_plan", fake_plan)
    monkeypatch.setattr(DP, "_chat", fake_chat)

    ctx, sent = _ctx()
    out = asyncio.run(DP.dispatch(RouteDecision("plan", "gợi ý món ăn", "mention"), "@plans gợi ý món ăn", ctx))
    assert out == "CHAT:general" and calls["plan"] == "gợi ý món ăn" and ctx.action_declined is True
    assert {"type": "status", "state": "working"} in sent

    calls["result"] = "KẾT LUẬN"
    ctx2, _ = _ctx()
    assert asyncio.run(DP.dispatch(RouteDecision("plan", "gợi ý món ăn", "mention"), "@plans gợi ý món ăn", ctx2)) == "KẾT LUẬN"
    assert ctx2.action_declined is False
