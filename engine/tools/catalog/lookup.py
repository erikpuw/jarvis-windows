"""Tool tra cứu (spec 2026-10-12 mục 4). Tất cả kind=read."""
import asyncio

from engine.tools.registry import tool


@tool()
async def weather(location: str, ctx=None) -> str:
    from engine.tools.weather_engine import weather_search
    return await weather_search(location, question=ctx.user_text)


@tool()
async def search_news(topic: str) -> str:
    from engine.tools.search_engine import handle_news_search
    res = await handle_news_search(topic)
    return res.get("display", "") if isinstance(res, dict) else str(res)


@tool(display=True)
async def market_price(item: str, ctx=None) -> str:
    from engine.tools import price_history
    from engine.tools.search_engine import handle_market_query
    result = await handle_market_query(item, user_text=ctx.user_text)
    if price_history.wants_compare(ctx.user_text):  # "hôm qua … hôm nay", "tăng hay giảm": code so với lần tra trước
        result = f"{result}\n\n{await asyncio.to_thread(price_history.compare, result)}"
    return result


@tool(display=True)
async def search_products(query: str, ctx=None) -> str:
    from engine.tools.shop_engine import search_products as _search
    return await _search(query, ws=ctx.ws)


@tool(display=True)
async def search_medicine(query: str, ctx=None) -> str:
    from engine.tools.pharmacy_engine import search_medicine as _search
    return await _search(query, ws=getattr(ctx, "ws", None) if ctx else None)


@tool()
async def cinema(ctx=None) -> str:
    from engine.tools.search_engine import handle_cgv_movies_query
    return await handle_cgv_movies_query("", user_text=ctx.user_text)


@tool()
async def free_games(ctx=None) -> str:
    from engine.tools.search_engine import handle_epic_free_games_query
    return await handle_epic_free_games_query("", user_text=ctx.user_text)


@tool()
async def lunar_today(day: str = "hôm nay") -> str:
    from engine.tools.search_engine import handle_vannien_query
    return await handle_vannien_query(day)


@tool()
async def zodiac(sign: str) -> str:
    from engine.tools.search_engine import handle_zodiac_query
    return await handle_zodiac_query(sign)


@tool()
async def legal_lookup(query: str) -> str:
    from engine.tools.legal_engine import legal_lookup as _lookup
    return await _lookup(query)


@tool()
async def vn_admin_lookup(query: str, ctx=None) -> str:
    from engine.tools.search_engine import handle_vietnam_data_query
    return await handle_vietnam_data_query(query, question=ctx.user_text)


@tool()
async def lookup_knowledge(query: str) -> str:
    from engine.core.mcp_context import build_mcp_context
    text = await build_mcp_context(query, route="general_knowledge")
    return text or "Không tìm thấy dữ liệu bách khoa phù hợp."


@tool(display=True)  # 2026-10-14: kho data/wiki/Documents chỉ hỏi được qua @rag → "dùng rag" vào gym, nói đại
async def search_documents(query: str) -> str:
    from engine.rag.runner import _ask
    return await _ask(query)


@tool(admin_only=True)
async def check_mail(query: str = "", message_id: str = "", ctx=None) -> str:
    from engine.core.session_context import is_user_admin, get_current_user_id
    uid = getattr(ctx, "user_id", None) or get_current_user_id()
    if not is_user_admin(uid):
        return "Lỗi bảo mật: Chỉ Quản trị viên (Admin) mới có quyền truy cập và kiểm tra Gmail."
    from engine.server.mcp_server import get_mcp_hub
    hub = get_mcp_hub()
    if hub.get_stats().get("servers", {}).get("gmail") != "connected":
        return "Lỗi: Gmail chưa kết nối (config/mcp_config.json, server gmail)."
    try:
        if message_id:  # hub chỉ cho search_emails/read_email, search tối đa 10 mail (mcp_server._read_only_guard)
            res = await hub.call_tool("gmail", "read_email", {"messageId": message_id})
        else:
            res = await hub.call_tool("gmail", "search_emails", {"query": query or "in:inbox", "maxResults": 10})
    except PermissionError as pe:
        return f"Lỗi bảo mật: {pe}"
    text = "\n".join(c.text for c in (res.content or []) if getattr(c, "type", "") == "text")
    return f"Lỗi: {text}" if res.isError else (text.strip() or "Không tìm thấy mail phù hợp.")
