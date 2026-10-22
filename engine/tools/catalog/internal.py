"""Tool nội bộ (chat=False): chỉ gọi bằng /tên_tool, @tên_tool hoặc từ code."""

from engine.tools.registry import tool


@tool(kind="change", chat=False)
async def dream() -> str:
    from engine.core.dream import trigger_dream_cycle_now
    trigger_dream_cycle_now()
    return ("Đã kích hoạt 1 chu kỳ Dream ở nền: tóm tắt hội thoại thừa, gọn log tác vụ cũ và tái tổ chức wiki. "
            "Bản gốc luôn được sao lưu trước khi gộp.")


@tool(kind="change", chat=False)
async def install_extension(ext_type: str, name: str, url: str = "", code_content: str = "", ctx=None) -> str:
    from engine.tools.extension_installer import install_extension as _install
    return await _install({"ext_type": ext_type, "name": name, "url": url, "code_content": code_content},
                          ctx.ws, ctx.send_json)


@tool(chat=False, admin_only=True)
async def mcp_call(server: str, tool: str, arguments: str = "{}") -> str:
    from engine.core.json_parser import safe_json_loads
    from engine.server.mcp_server import get_mcp_hub
    try:
        tool_args = safe_json_loads(arguments) if arguments.strip() else {}
    except Exception:
        return "Lỗi: Tham số 'arguments' của mcp_call phải là JSON hợp lệ."
    try:
        result = await get_mcp_hub().call_tool(server, tool, tool_args)
    except (ValueError, TimeoutError) as exc:
        return f"Lỗi: {exc}"
    parts = [item.text for item in getattr(result, "content", []) if getattr(item, "text", "")]
    raw = "\n".join(parts) if parts else str(result)
    return raw.strip() or f"MCP tool '{tool}' trên '{server}' không trả về nội dung."


@tool(chat=False)
async def check_project(instruction: str = "", ctx=None) -> str:
    from engine.tools.check_project import check_project as _check
    return await _check(ctx.ws, ctx.send_json, instruction or ctx.user_text)
