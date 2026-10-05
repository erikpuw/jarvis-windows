"""Runner dùng chung của các agent tra cứu (weather, news, market, shop, route, places, cinema, games, lunar, zodiac,
vn_data, web): mỗi agent trong AGENT_REGISTRY có "tool" riêng, registry gắn sẵn `tools=[tool]` khi resolve_runner."""
import logging
from typing import Any

log = logging.getLogger("jarvis.agent_search")


async def run_search_agent(
    user_text: str,
    conversation_history: list,
    ws: Any,
    flow_tracker=None,
    flow_agents=None,
    **kwargs
) -> str:
    from engine.core.actions import handle_user_intent_with_tools, get_agent_context_and_tools
    from engine.router.types import NoOpTracker
    flow_tracker = flow_tracker or NoOpTracker()
    flow_agents = flow_agents or NoOpTracker()

    tool_names = list(kwargs.get("tools") or [])
    if not tool_names:
        return "Lỗi thực thi Agent Search: agent chưa được gắn tool."
    log.info(f"Agent Search activated for query: '{user_text}' tools={tool_names}")
    if ws:
        ws.last_tools = tool_names
    search_tools = get_agent_context_and_tools(tool_names)
    friendly = f"Thực thi: {user_text}"
    try:
        async with flow_tracker.step("Agent Search"):
            async with flow_agents.step(friendly, emoji="🔍", agent_name="Agent Search"):
                response_text = await handle_user_intent_with_tools(
                    user_text=user_text,
                    add_tools=search_tools,
                    conversation_history=conversation_history,
                    ws=ws,
                    agent_name="Agent Search",
                    flow_tracker=flow_tracker,
                    flow_agents=flow_agents,
                    silent=kwargs.get("silent", False),
                )
            return response_text

    except Exception as e:
        log.error(f"Error in Agent Search execution: {e}", exc_info=True)
        return f"Lỗi thực thi Agent Search: {e}"
