"""Tool media (spec 2026-10-12 mục 4)."""
from typing import Literal

from engine.tools.registry import tool


@tool(kind="change", display=True)
async def play_media(query: str, source: Literal["youtube", "local"] = "youtube", ctx=None) -> str:
    from engine.tools.media_search import execute_media_search
    return await execute_media_search({"query": query, "source": source, "user_text": ctx.user_text},
                                      ctx.ws, ctx.send_json)
