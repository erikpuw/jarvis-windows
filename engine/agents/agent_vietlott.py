import logging
from typing import Any

log = logging.getLogger("jarvis.agent_vietlott")


async def run_vietlott_agent(user_text: str, conversation_history: list, ws: Any, **kwargs) -> str:
    """Route Vietlott requests through the normal tool execution and summary path."""
    from engine.core.actions import get_agent_context_and_tools, handle_user_intent_with_tools

    schemas = get_agent_context_and_tools(["vietlott_analysis"])
    return await handle_user_intent_with_tools(
        user_text=user_text,
        add_tools=schemas,
        conversation_history=conversation_history,
        ws=ws,
        agent_name="Agent Vietlott",
        **kwargs,
    )
