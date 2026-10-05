"""Confirms every non-**kwargs-forwarding agent passes `silent` through to
handle_user_intent_with_tools. Run: python tests/test_orchestrator_agent_silent_forwarding.py"""
import asyncio
import functools
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.core import actions

_CASES = [
    ("engine.agents.agent_desktop", "run_desktop_agent", "mở Word"),
    ("engine.agents.agent_search", "run_search_agent", "thoi tiet hom nay"),
    ("engine.agents.agent_vision", "run_vision_agent", "chup man hinh"),
    ("engine.agents.agent_webcam", "run_webcam_agent", "xem webcam"),
    ("engine.agents.agent_image", "run_image_agent", "nang do phan giai anh"),
    ("engine.agents.agent_security", "run_security_agent", "kiem tra an ninh"),
    ("engine.agents.agent_project", "run_project_agent", "quet loi project"),
    ("engine.agents.agent_dream", "run_dream_agent", "don dep hoi thoai"),
    ("engine.agents.agent_office", "run_office_agent", "sua file word"),
    ("engine.agents.agent_media", "run_media_agent", "nghe nhac"),
    ("engine.agents.agent_control", "run_control_agent", "dieu khien explorer"),
    ("engine.agents.agent_rag", "run_rag_agent", "tom tat tai lieu"),
]


def test_every_agent_forwards_silent():
    import importlib

    async def scenario():
        seen_silent = []

        async def fake_handle(**kwargs):
            seen_silent.append(kwargs.get("silent"))
            return "ok"

        original = actions.handle_user_intent_with_tools
        actions.handle_user_intent_with_tools = fake_handle
        try:
            for module_name, runner_name, text in _CASES:
                module = importlib.import_module(module_name)
                runner = getattr(module, runner_name)
                if module_name == "engine.agents.agent_search":  # agent tra cứu luôn được registry gắn sẵn tool
                    runner = functools.partial(runner, tools=["weather_search"])
                seen_silent.clear()
                # agent_rag and agent_office short-circuit before calling
                # handle_user_intent_with_tools when attachment_context is None (both
                # require a real attachment) - give them a stub so this case actually
                # exercises the silent-forwarding call site.
                attachment_context = (
                    SimpleNamespace(filename="test.pdf")
                    if module_name in ("engine.agents.agent_rag", "engine.agents.agent_office")
                    else None
                )
                await runner(
                    user_text=text,
                    conversation_history=[],
                    ws=None,
                    silent=True,
                    attachment_context=attachment_context,
                )
                assert seen_silent == [True], (
                    f"{module_name}.{runner_name} did not forward silent=True: {seen_silent}"
                )
        finally:
            actions.handle_user_intent_with_tools = original

    asyncio.run(scenario())


if __name__ == "__main__":
    test_every_agent_forwards_silent()
    print("OK: all agent silent-forwarding tests passed")
