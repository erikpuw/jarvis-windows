"""Điểm vào duy nhất cho WebUI và Telegram (spec mục 3.1): tệp nén → /tool, @tool → @rag → vòng lặp."""
import logging
import re
from types import SimpleNamespace

from engine.tools import registry

log = logging.getLogger("jarvis.turn.entry")

_TOOL_MENTION = re.compile(r"^@(\w+)(?![\w])[\s,:]*(.*)$", re.S)
_RAG_MENTION = re.compile(r"^@rag(?![\w])[\s,:]*(.*)$", re.I | re.S)
# skill_probe 2026-10-20: "tạo skill báo cáo sáng gồm thời tiết, giá vàng…" → vòng chọn ra weather 2/2 (từ nội dung lấn
# chữ "tạo skill") → code: câu bảo tạo/lưu skill đi thẳng save_skill như @save_skill
_SKILL_REQUEST = re.compile(r"\b(tạo|lưu|thêm|viết)\s+(một\s+|cái\s+|thành\s+)?(skill|kỹ năng)\b"
                            r"|\bthành\s+(một\s+)?(skill|kỹ năng)\b", re.I)


def skill_request(text: str) -> bool:
    return bool(_SKILL_REQUEST.search(text or ""))


def tool_mention(text: str) -> tuple[str, str] | None:
    m = _TOOL_MENTION.match((text or "").strip())
    if not m or registry.get(m.group(1).lower()) is None:
        return None
    return m.group(1).lower(), m.group(2).strip()


def rag_mention(text: str) -> str | None:
    m = _RAG_MENTION.match(text or "")
    return m.group(1).strip() if m else None


def mention_list(user_id: str | None = None) -> list[dict]:
    """Gợi ý @ cho ô nhập (/api/command-bar/context): @rag + mọi tool trong registry."""
    from engine.core.session_context import is_user_admin
    admin = is_user_admin(user_id)
    items = [{"name": "rag", "description": "Hỏi đáp trên tài liệu đã nạp"}]
    for n in registry.names():
        spec = registry.get(n)
        if spec and spec.admin_only and not admin:
            continue
        items.append({"name": n, "description": registry.description(n)})
    return items


def _find_workflow(text: str) -> dict | None:
    from engine.core.learning import get_learning_engine
    try:
        return get_learning_engine().find_workflow(text)
    except Exception as exc:
        log.warning("[TURN] không đọc được workflow: %s", exc)
        return None


async def _say_once(ctx, message: str) -> str:
    await ctx.send_json(ctx.ws, {"type": "text_chunk", "text": message})
    await ctx.send_json(ctx.ws, {"type": "stream_end"})
    return message


async def handle_turn(text: str, ctx) -> str:
    from engine.turn import archive, loop
    try:
        archive_msg = await archive.unpack_archive(ctx)
    except Exception as exc:
        log.warning("[TURN] archive unpack failed: %s", exc)
        archive_msg = None
    if archive_msg:
        out = await _say_once(ctx, archive_msg)
        await ctx.flow_tracker.track("Hoàn thành", "completed")  # run_loop tự gửi; lối tắt thì gửi ở đây
        return out
    forced = getattr(ctx.ws, "forced_command", None)  # đặt bởi slash_commands.handle_slash_message, dùng một lượt
    if forced:
        ctx.ws.forced_command = None
        return await loop.run_loop(forced.get("value") or text, ctx, only=forced["tool"])
    clean = (text or "").strip()
    rag = rag_mention(clean)
    if rag is not None:
        from engine.rag.runner import handle
        out = await handle(SimpleNamespace(query=rag), ctx)
        await ctx.flow_tracker.track("Hoàn thành", "completed")
        return out
    mention = tool_mention(clean)
    if mention:
        return await loop.run_loop(mention[1] or clean, ctx, only=mention[0])
    if skill_request(clean):
        return await loop.run_loop(clean, ctx, only="save_skill")
    if ctx.attachment_context is None:
        import asyncio
        wf = await asyncio.to_thread(_find_workflow, clean)
        if wf:
            return await loop.run_loop(clean, ctx, replay=wf)
        from engine.turn import skills
        skill = await asyncio.to_thread(skills.match, clean, set(registry.chat_names(None)))
        if skill:
            return await loop.run_loop(clean, ctx, skill=skill)
        from engine.turn import jev_gate
        if jev_gate.is_available():
            is_chat, conf = await asyncio.to_thread(jev_gate.classify_chat, clean)
            if is_chat:
                log.info("[TURN] Jev fast-path chat bypass (conf=%.1f%%)", conf * 100)
                return await loop.run_loop(clean, ctx, skip_tool_round=True)
    return await loop.run_loop(clean, ctx)
