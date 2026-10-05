import logging
from typing import Any

log = logging.getLogger("jarvis.agent_legal")


async def run_legal_agent(user_text: str, conversation_history: list, ws: Any, **kwargs) -> str:
    """Route legal lookup requests through the normal tool execution and summary path."""
    from engine.core.actions import get_agent_context_and_tools, handle_user_intent_with_tools

    schemas = get_agent_context_and_tools(["legal_lookup"])
    return await handle_user_intent_with_tools(
        user_text=user_text,
        add_tools=schemas,
        conversation_history=conversation_history,
        ws=ws,
        agent_name="Agent Pháp Luật",
        **kwargs,
    )
