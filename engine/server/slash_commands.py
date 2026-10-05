"""Shared slash-command resolution used by both the WebUI and Telegram bots.

Slash commands defined in commands/ (with a `usage` JSON frontmatter) are
resolved deterministically into a directive the LLM pipeline can execute, so
arguments are not left to the router to guess from raw text.
"""

import json
from typing import Any


def load_command(command_name: str) -> Any:
    """Resolve a hot-loadable command definition from commands/."""
    try:
        from engine.tools.skill_manager import get_skill_manager
        manager = get_skill_manager()
        command = manager.commands.get(command_name)
        if command is None:
            manager.scan_commands(recursive=True)
            command = manager.commands.get(command_name)
        return command
    except Exception:
        return None


def command_spec(command: Any) -> dict:
    """Parse a command's `usage` frontmatter into a param-name -> hint dict."""
    usage = getattr(command, "usage", "") or ""
    try:
        spec = json.loads(usage) if str(usage).strip().startswith("{") else {}
    except (ValueError, TypeError):
        spec = {}
    return spec if isinstance(spec, dict) else {}


def build_command_prompt(command_name: str, spec: dict) -> str:
    """Ask the user to supply the command's required parameter(s)."""
    fields = ", ".join(f"*{name}* ({desc})" for name, desc in spec.items())
    return (
        f"Lệnh `/{command_name}` cần tham số: {fields}.\n"
        f"Hãy nhập giá trị (hoặc gõ `/{command_name} <giá trị>` ngay từ đầu)."
    )


def resolve_command_directive(command_name: str, spec: dict, value: str) -> str:
    """Turn a command argument value into a natural directive the pipeline executes.

    Builds a plain natural-language instruction (e.g. "/open_app task manager" ->
    "Mở ứng dụng task manager") instead of a JSON envelope, so the LLM agent and
    its parameter extraction treat the value as real text, not a JSON blob.
    """
    phrase = COMMAND_ACTION_PHRASES.get(command_name)
    if phrase:
        return f"{phrase} {value}"
    first_key = next(iter(spec))
    return f"Thực hiện lệnh {command_name} với tham số {first_key}: {value}"


# Natural-language action phrases for known commands. Commands not listed here
# fall back to a plain directive that names the command and its first parameter.
COMMAND_ACTION_PHRASES: dict[str, str] = {
    "open_app": "Mở ứng dụng",
    "close_app": "Đóng ứng dụng",
    "weather_search": "Tra cứu thời tiết",
    "search_news": "Tìm kiếm tin tức",
    "search_products": "Tra cứu giá sản phẩm",
    "search_media": "Tìm kiếm phim/video",
    "get_market_data": "Tra cứu dữ liệu thị trường",
    "get_cgv_movies": "Xem phim đang chiếu",
    "get_epic_free_games": "Xem game miễn phí Epic",
    "get_vannien_data": "Tra cứu lịch vạn niên",
    "get_zodiac_data": "Tra cứu cung hoàng đạo",
    "vietnam_data_lookup": "Tra cứu dữ liệu Việt Nam",
    "vietlott_analysis": "Phân tích kết quả Vietlott",
    "legal_lookup": "Tra cứu luật pháp",
    "map_pois": "Tìm địa điểm",
    "map_route": "Tìm đường đi",
    "office_tool": "Xử lý tài liệu Office",
    "rag_tool": "Trả lời từ tài liệu đính kèm",
    "upscale_image": "Tăng độ phân giải ảnh",
    "take_note": "Ghi chú",
    "read_note": "Đọc ghi chú",
    "query_history": "Xem lịch sử trò chuyện",
    "check_mail": "Kiểm tra email",
    "check_calendar": "Kiểm tra lịch",
    "install_extension": "Cài đặt extension",
    "mcp_call": "Gọi MCP",
    "win_control": "Điều khiển Windows",
}


def resolve_slash_command(text: str) -> dict | None:
    """Resolve a slash command line.

    Returns a dict, or None when `text` is not a slash command:
      {"kind": "directive", "text": ..., "command": ...}  feed into the pipeline
      {"kind": "prompt",    "text": ..., "command": ...}  bare command needs params
      {"kind": "not_found", "text": ..., "command": ...}  unknown command
    """
    if not text.startswith("/"):
        return None

    parts = text.split(maxsplit=1)
    cmd = parts[0].lower()
    args = parts[1].strip() if len(parts) > 1 else ""

    command_name = cmd.lstrip("/")
    if not command_name:
        return {
            "kind": "not_found",
            "command": "",
            "text": f"Không tìm thấy lệnh `{cmd}` trong hệ thống.",
        }

    command = load_command(command_name)
    if command is None:
        return {
            "kind": "not_found",
            "command": command_name,
            "text": f"Không tìm thấy lệnh `/{command_name}` trong hệ thống.",
        }

    spec = command_spec(command)
    if args:
        if spec:
            return {
                "kind": "directive",
                "command": command_name,
                "text": resolve_command_directive(command_name, spec, args),
                "value": args,
            }
        return {
            "kind": "directive",
            "command": command_name,
            "text": f"Thực hiện lệnh {command_name}",
        }
    if spec:
        return {
            "kind": "prompt",
            "command": command_name,
            "text": build_command_prompt(command_name, spec),
        }
    return {
        "kind": "directive",
        "command": command_name,
        "text": f"Thực hiện lệnh {command_name}",
    }


def _mark_forced(ws, command_name: str, value: str) -> None:
    """Lệnh của agent tra cứu (mỗi tool một agent) chạy đúng agent của nó (decide() đọc một lần); văn bản lệnh giữ nguyên."""
    from engine.orchestrator.registry import AGENT_REGISTRY
    from engine.prompts import catalog
    agent = catalog.tool_to_agent_map().get(command_name)
    if value and "tool" in AGENT_REGISTRY.get(agent, {}):
        ws.forced_command = {"tool": command_name, "value": value}


async def handle_slash_message(ws, text: str, send_json) -> str | None:
    """Process a WebUI message through slash-command resolution.

    Returns the resolved user_text to route to the pipeline, or None when the
    message was consumed by a param prompt / not-found reply (already sent via
    ``send_json``). ``ws.pending_slash_command`` holds the bare command waiting
    for its parameter value between turns.
    """
    ws.forced_command = None
    if text.startswith("/"):
        # A new slash command overrides any pending param prompt.
        ws.pending_slash_command = None
        result = resolve_slash_command(text)
        if result is not None:
            if result["kind"] == "directive":
                _mark_forced(ws, result["command"], result.get("value") or result["text"])
                return result["text"]
            await send_json({"type": "stream_start"})
            await send_json({"type": "text_chunk", "text": result["text"]})
            await send_json({"type": "stream_end"})
            if result["kind"] == "prompt":
                ws.pending_slash_command = result["command"]
            await send_json({"type": "status", "state": "idle"})
            return None

    pending = getattr(ws, "pending_slash_command", None)
    if pending:
        ws.pending_slash_command = None
        command = load_command(pending)
        spec = command_spec(command) if command else {}
        if spec:
            _mark_forced(ws, pending, text)
            return resolve_command_directive(pending, spec, text)
    return text
