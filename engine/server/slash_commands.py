"""Lệnh /tên_tool và @ (spec 2026-10-12 mục 8): danh sách lấy từ engine.tools.registry."""
import logging

log = logging.getLogger("jarvis.slash")

_MODES = ("@rag <câu hỏi>: hỏi kho tài liệu",)


def format_tools_help(user_id: str | None = None) -> str:
    from engine.tools import registry
    from engine.core.session_context import is_user_admin
    admin = is_user_admin(user_id)
    lines = ["**Danh sách lệnh (`/tên_lệnh <nội dung>`):**\n"]
    for name in sorted(registry.names()):
        spec = registry.get(name)
        if spec and spec.admin_only and not admin:
            continue
        params = registry.params(name)
        lines.append(f"• `/{name}{' <' + ', '.join(params) + '>' if params else ''}`: {registry.description(name)}")
    return "\n".join(lines)


def format_at_help() -> str:
    return ("**Lệnh @:**\n" + "\n".join(f"• `{m}`" for m in _MODES)
            + "\n• `@tên_lệnh <nội dung>`: gọi đúng một công cụ (xem `/help`)")


def _required(name: str) -> list[str]:
    from engine.tools import registry
    return list(registry.parameters(name)["required"])


def resolve_slash_command(text: str, user_id: str | None = None) -> dict | None:
    """{"kind": "forced"|"prompt"|"info"|"not_found", "command", "text", "value"?}; None nếu không phải lệnh /."""
    from engine.tools import registry
    clean = (text or "").strip()
    if not clean.startswith("/"):
        return None
    parts = clean.split(maxsplit=1)
    name = parts[0].lstrip("/").lower()
    value = parts[1].strip() if len(parts) > 1 else ""
    if name in ("", "help", "commands", "trogiup"):
        return {"kind": "info", "command": "help", "text": format_tools_help(user_id)}
    if not registry.allowed(name, user_id):  # tool admin_only với user thường: như không có lệnh này
        return {"kind": "not_found", "command": name,
                "text": f"Không tìm thấy lệnh `/{name}`. Gõ `/help` để xem các lệnh."}
    if not value and _required(name):
        return {"kind": "prompt", "command": name,
                "text": f"Gõ nội dung cho `/{name}` ({', '.join(_required(name))}), ví dụ: "
                        f"`{registry.usage(name)}`"}
    return {"kind": "forced", "command": name, "text": value or name, "value": value}


def resolve_at_command(text: str) -> dict | None:
    clean = (text or "").strip()
    if clean in ("@", "@help", "@?", "@trogiup"):
        return {"kind": "info", "command": "@", "text": format_at_help()}
    return None


async def _reply(send_json, text: str) -> None:
    await send_json({"type": "stream_start"})
    await send_json({"type": "text_chunk", "text": text})
    await send_json({"type": "stream_end"})
    await send_json({"type": "status", "state": "idle"})


async def handle_slash_message(ws, text: str, send_json) -> str | None:
    """Trả câu đưa vào router, hoặc None khi tin đã được trả lời tại đây. ws.pending_slash_command giữ lệnh
    đang chờ nội dung giữa hai lượt; ws.forced_command được engine.turn.entry.handle_turn đọc đúng một lần."""
    ws.forced_command = None
    clean = (text or "").strip()
    if clean.startswith("/"):
        ws.pending_slash_command = None
        user_id = getattr(ws, "user_id", None)
        result = resolve_slash_command(clean, user_id=user_id)
        if result["kind"] == "forced":
            ws.forced_command = {"tool": result["command"], "value": result["value"]}
            return result["text"]
        await _reply(send_json, result["text"])
        if result["kind"] == "prompt":
            ws.pending_slash_command = result["command"]
        return None
    at = resolve_at_command(clean)
    if at is not None:
        await _reply(send_json, at["text"])
        return None
    pending = getattr(ws, "pending_slash_command", None)
    if pending:
        ws.pending_slash_command = None
        ws.forced_command = {"tool": pending, "value": clean}
        return clean
    return text
