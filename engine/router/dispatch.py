"""RouteDecision → nhánh xử lý. Luôn trả câu trả lời cuối; không còn chuỗi "" giữa các module (spec §5)."""
import asyncio
import logging

from engine.router.replay import run_replay
from engine.router.types import RouteDecision, TurnContext

log = logging.getLogger("jarvis.router.dispatch")

_RAG_NEEDS_FILE = "Agent RAG chỉ hoạt động khi request hiện tại có tệp đính kèm hợp lệ."
_CANCELLED = "Đã hủy xử lý tệp vì chưa có lựa chọn phù hợp."
_ATTACHMENT_LABELS = {"rag": "Đọc hoặc phân tích bằng RAG", "office": "Chỉnh sửa bằng OfficeCLI",
                      "image": "Tăng độ phân giải bằng Upscayl"}


def _unsupported(att) -> str:
    return f"Tôi chưa xử lý được tệp {att.extension} ({att.filename}), thưa ngài."


def _cancel_message(att) -> str:
    """Câu đã nói khi _clarify_attachment trả None — dispatch trả đúng câu đó."""
    from engine.orchestrator import attachment_agents_for
    return _CANCELLED if attachment_agents_for(getattr(att, "extension", None)) else _unsupported(att)


async def _chat(kind: str, text: str, ctx: TurnContext) -> str:
    from engine.router.chat import build_chat_messages
    from engine.router.chat_stream import stream_chat
    messages, text = await build_chat_messages(kind, text, ctx)
    return await stream_chat(messages, text, ctx)


async def _run_orchestrator(**kwargs) -> str:
    from engine.orchestrator import run_orchestrator
    return await run_orchestrator(**kwargs)


async def _run_plan(goal: str, ctx: TurnContext) -> str:
    from engine.plans.runner import run_plan
    return await run_plan(goal, ctx)


async def _run_jobs(d: RouteDecision, ctx: TurnContext) -> str:
    from engine.jobs.runner import handle
    return await handle(d, ctx)


async def _say(ctx: TurnContext, message: str) -> str:
    await ctx.send_json(ctx.ws, {"type": "text_chunk", "text": message})
    await ctx.send_json(ctx.ws, {"type": "stream_end"})
    return message


async def _clarify_attachment(ctx: TurnContext) -> str | None:
    """Nguyên văn route_agents.py:448-483. Trả route đã chọn hoặc None (đã báo huỷ)."""
    att = ctx.attachment_context
    from engine.orchestrator import attachment_agents_for
    agents = attachment_agents_for(att.extension)
    if not agents:  # .zip, .rar, .tif… : bảng chỉ có "Không xử lý" là vô ích (2026-09-28)
        await _say(ctx, _unsupported(att))
        return None
    options = [{"id": a, "label": _ATTACHMENT_LABELS[a]} for a in agents]
    if len(options) == 1:
        options.append({"id": "cancel", "label": "Không xử lý ảnh" if agents == ["image"] else "Không xử lý tệp"})
    from engine.main.ask_verifi import ask_user_selection
    selected = await ask_user_selection(ctx.ws, ctx.send_json, "attachment_route",
                                        f"Bạn muốn xử lý tệp {att.filename} theo cách nào?", options)
    if not selected or selected == "cancel":
        await _say(ctx, _cancel_message(att))
        return None
    return selected


async def dispatch(d: RouteDecision, text: str, ctx: TurnContext) -> str:
    setattr(ctx.ws, "pending_ask_user", "")  # chỉ nhánh chat đặt lại (Pha 3)
    setattr(ctx.ws, "pending_action_run", "")

    if d.kind == "attachment_clarify":
        if ctx.attachment_context is None:
            return "Không có tệp đính kèm hợp lệ để lựa chọn cách xử lý."
        selected = await _clarify_attachment(ctx)
        if selected is None:
            return _cancel_message(ctx.attachment_context)
        d = RouteDecision("agent", d.query, "attachment", agent=selected)

    if d.kind in ("general", "general_knowledge"):
        return await _chat(d.kind, text, ctx)

    if d.kind == "replay":
        res = await run_replay(d, ctx)
        if not res:
            ctx.action_declined = True
        return res or await _chat("general", text, ctx)

    if d.kind == "plan":
        await ctx.send_json(ctx.ws, {"type": "status", "state": "working"})
        res = await _run_plan(d.query, ctx)
        if not res:
            ctx.action_declined = True
        return res or await _chat("general", text, ctx)

    if d.kind == "jobs":
        return await _run_jobs(d, ctx)

    if d.kind == "rag":
        await ctx.send_json(ctx.ws, {"type": "status", "state": "working"})
        from engine.rag.runner import handle
        return await handle(d, ctx)

    if d.kind == "agent" and d.agent == "rag" and ctx.attachment_context is None:
        return await _say(ctx, _RAG_NEEDS_FILE)

    await ctx.send_json(ctx.ws, {"type": "status", "state": "working"})
    tasks = [{"agent": d.agent, "query": d.query}] if d.kind == "agent" else None

    offer_context = ""
    effective_user_text = d.query
    if d.kind == "orchestrator" and d.source == "gate":
        try:
            from engine.core import memory
            ask, tool = await asyncio.to_thread(memory.get_pending_offer)
        except Exception as exc:
            log.warning("[ROUTER] get_pending_offer failed: %s", exc)
            ask, tool = "", ""
        if ask and tool:
            from engine.router.ask_user import ask_to_command, reply_kind
            if reply_kind(d.query) == "affirm" or len(d.query.split()) <= 2:
                cmd = ask_to_command(ask)
                if cmd:
                    log.info("[ROUTER] Binding pending offer command '%s' for query '%s'", cmd, d.query)
                    effective_user_text = cmd
        from engine.prompts.router import build_offer_context
        offer_context = build_offer_context(ask, tool)

    from engine.orchestrator import AttachmentIgnored
    kwargs = dict(user_text=effective_user_text, conversation_history=ctx.conversation_history, ws=ctx.ws,
                  flow_tracker=ctx.flow_tracker, flow_agents=ctx.flow_agents,
                  attachment_context=ctx.attachment_context)
    try:
        res = await _run_orchestrator(**kwargs, predetermined_tasks=tasks, offer_context=offer_context)
    except AttachmentIgnored:
        selected = await _clarify_attachment(ctx)
        if selected is None:
            return _cancel_message(ctx.attachment_context)
        res = await _run_orchestrator(**kwargs, predetermined_tasks=[{"agent": selected, "query": d.query}])
    # Orchestrator trả "" = không có agent phù hợp → trò chuyện bình thường.
    if not res:
        ctx.action_declined = True
    return res or await _chat("general", text, ctx)
