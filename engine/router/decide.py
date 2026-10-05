"""Thứ tự ưu tiên định tuyến (spec §4). Đọc file này là hiểu toàn bộ luồng."""
import asyncio
import logging

from engine.router.fast_paths import (
    VOICE_CONTROL, ask_reply, command_mention, forced_command, is_routing_complaint, jobs_mention, plan_mention,
    rag_mention, resolve_mention, tool_name_command,
)
from engine.router.gate import classify_bucket
from engine.router.replay import find_replay
from engine.router.types import RouteDecision, TurnContext

log = logging.getLogger("jarvis.router.decide")


def _unlearn_last_route(text: str) -> bool:
    from engine.core.learning import get_learning_engine
    return get_learning_engine().unlearn_last_route(text)


async def decide(text: str, ctx: TurnContext) -> RouteDecision:
    clean = (text or "").strip()
    att = ctx.attachment_context

    slash = getattr(ctx.ws, "forced_command", None)  # đặt bởi handle_slash_message, dùng đúng một lượt
    if slash:
        ctx.ws.forced_command = None
    cmd = (slash["tool"], slash["value"]) if slash else command_mention(clean)
    if not cmd and att is None:
        named = tool_name_command(clean)  # "Dùng lệnh check_system coi": gọi đích danh công cụ, không qua gate
        cmd = (named, clean) if named else None
    d = forced_command(*cmd) if cmd else None
    if d:
        return d

    goal = plan_mention(clean)  # "@plans <mục tiêu>": cửa vào duy nhất của chế độ mục tiêu (2026-09-27)
    if goal:
        return RouteDecision("plan", goal, "mention")

    jobs_cmd = jobs_mention(clean)  # "@jobs <lệnh>": tìm việc (spec 2026-09-27-job-search mục 5)
    if jobs_cmd is not None:
        return RouteDecision("jobs", jobs_cmd, "mention")

    rag_cmd = rag_mention(clean)  # "@rag <câu hỏi|lệnh con>": kho tài liệu lâu dài
    if rag_cmd is not None:
        return RouteDecision("rag", rag_cmd, "mention")

    if att is None:  # đang phỏng vấn / lệnh duyệt thư: đọc file, không LLM
        from engine.jobs.gate import route_source
        jobs_source = await asyncio.to_thread(route_source, clean)
        if jobs_source:
            return RouteDecision("jobs", clean, jobs_source)

    agent, clean = resolve_mention(clean)
    if agent:
        return RouteDecision("agent", clean, "mention", agent=agent)

    d = await ask_reply(clean, att)
    if d:
        return d

    if VOICE_CONTROL.match(clean):
        return RouteDecision("agent", clean, "voice", agent="win_control")

    if att is None and is_routing_complaint(clean):
        try:
            if await asyncio.to_thread(_unlearn_last_route, clean):
                return RouteDecision("general", clean, "complaint")
        except Exception as exc:
            log.warning("[ROUTER] Complaint handling failed: %s", exc)

    wf = await find_replay(clean, att)
    if wf:
        return RouteDecision("replay", clean, "replay", agent=wf["agent"], workflow=wf)

    bucket = await classify_bucket(clean, ctx)
    return RouteDecision(bucket, clean, "gate")
