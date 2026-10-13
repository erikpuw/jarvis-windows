"""Tool tra cứu (spec 2026-10-12 mục 4). Tất cả kind=read."""
from engine.tools.registry import tool


@tool()
async def weather(location: str) -> str:
    from engine.tools.weather_engine import weather_search
    return await weather_search(location)


@tool()
async def search_news(topic: str) -> str:
    from engine.tools.search_engine import handle_news_search
    res = await handle_news_search(topic)
    return res.get("display", "") if isinstance(res, dict) else str(res)


@tool(display=True)
async def market_price(item: str, ctx=None) -> str:
    from engine.tools.search_engine import handle_market_query
    return await handle_market_query(item, user_text=ctx.user_text)


@tool(display=True)
async def search_products(query: str, ctx=None) -> str:
    from engine.tools.shop_engine import search_products as _search
    return await _search(query, ws=ctx.ws)


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
async def lookup_knowledge(query: str) -> str:
    from engine.core.mcp_context import build_mcp_context
    text = await build_mcp_context(query, route="general_knowledge")
    return text or "Không tìm thấy dữ liệu bách khoa phù hợp."
