"""Tests for engine.core.activity_gate. Run: python tests/test_activity_gate.py"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.core.activity_gate import ActivityGate, InferenceGate


async def _returns_within(coro, timeout):
    try:
        await asyncio.wait_for(coro, timeout=timeout)
        return True
    except asyncio.TimeoutError:
        return False


def test_starts_idle():
    async def scenario():
        g = ActivityGate(idle_grace_seconds=0)
        assert g.is_chat_active() is False
        return await _returns_within(g.wait_until_idle(), 0.5)
    assert asyncio.run(scenario()) is True


def test_active_while_a_turn_is_open():
    g = ActivityGate(idle_grace_seconds=0)
    g.begin()
    assert g.is_chat_active() is True
    g.end()
    assert g.is_chat_active() is False


def test_nested_turns_need_matching_ends():
    """WebUI and Telegram can each hold a turn; one ending must not open the gate."""
    g = ActivityGate(idle_grace_seconds=0)
    g.begin()
    g.begin()
    g.end()
    assert g.is_chat_active() is True, "gate opened while a second turn was still live"
    g.end()
    assert g.is_chat_active() is False


def test_end_without_begin_does_not_go_negative():
    g = ActivityGate(idle_grace_seconds=0)
    g.end()
    g.end()
    assert g.interactive_chats == 0
    g.begin()
    assert g.is_chat_active() is True


def test_wait_blocks_while_a_turn_is_live():
    async def scenario():
        g = ActivityGate(idle_grace_seconds=0)
        g.begin()
        return await _returns_within(g.wait_until_idle(), 0.3)
    assert asyncio.run(scenario()) is False, "background work was let through mid-turn"


def test_wait_returns_after_the_turn_ends():
    async def scenario():
        g = ActivityGate(idle_grace_seconds=0)
        g.begin()
        waiter = asyncio.create_task(g.wait_until_idle())
        await asyncio.sleep(0.05)
        assert not waiter.done(), "returned while the turn was still open"
        g.end()
        return await _returns_within(waiter, 1.0)
    assert asyncio.run(scenario()) is True


def test_grace_period_covers_a_fast_follow_up_turn():
    """A quick back-and-forth must not let background work slip between
    two sentences."""
    async def scenario():
        g = ActivityGate(idle_grace_seconds=0.3)
        g.begin()
        g.end()
        waiter = asyncio.create_task(g.wait_until_idle())
        await asyncio.sleep(0.1)
        g.begin()  # user speaks again inside the grace window
        released_early = await _returns_within(asyncio.shield(waiter), 0.5)
        g.end()
        done_after = await _returns_within(waiter, 2.0)
        return released_early, done_after
    released_early, done_after = asyncio.run(scenario())
    assert released_early is False, "gate opened during a fast follow-up turn"
    assert done_after is True, "gate never reopened once the conversation settled"


def test_learning_engine_delegates_to_the_shared_gate():
    """server.py/telegram_bot.py still call the LearningEngine API; it must
    move the same gate the background jobs wait on."""
    from engine.core import activity_gate
    from engine.core.learning import LearningEngine
    engine = LearningEngine()
    shared = activity_gate.get_gate()
    before = shared.interactive_chats
    engine.begin_interactive_chat()
    try:
        assert shared.is_chat_active() is True, "LearningEngine no longer drives the shared gate"
        assert engine._interactive_chats == before + 1
    finally:
        engine.end_interactive_chat()
    assert shared.interactive_chats == before


def test_call_llm_wrapper_forwards_every_argument():
    """call_llm gained an admission-control wrapper in front of the real body.
    It is the choke point for every LLM caller in the process, so a dropped or
    reordered argument would break all of them at once."""
    from engine.server import llm_server
    seen = {}

    async def fake_inner(messages, model=None, thinking=False, stream=False,
                         tools=None, tool_choice=None, temperature=None,
                         max_tokens=None, response_format=None, thinking_budget=None):
        seen.update(
            messages=messages, model=model, thinking=thinking, stream=stream,
            tools=tools, tool_choice=tool_choice, temperature=temperature,
            max_tokens=max_tokens, response_format=response_format, thinking_budget=thinking_budget,
        )
        return "sentinel-result"

    original = llm_server._call_llm_inner
    llm_server._call_llm_inner = fake_inner
    try:
        result = asyncio.run(llm_server.call_llm(
            [{"role": "user", "content": "xin chao"}],
            model="m", thinking=True, stream=True, tools=["t"],
            tool_choice="auto", temperature=0.4, max_tokens=128,
            response_format={"type": "json_object"}, thinking_budget=64,
        ))
    finally:
        llm_server._call_llm_inner = original

    assert result == "sentinel-result", "wrapper dropped the return value"
    assert seen["messages"] == [{"role": "user", "content": "xin chao"}]
    assert seen["model"] == "m"
    assert seen["thinking"] is True
    assert seen["stream"] is True
    assert seen["tools"] == ["t"]
    assert seen["tool_choice"] == "auto"
    assert seen["temperature"] == 0.4
    assert seen["max_tokens"] == 128
    assert seen["response_format"] == {"type": "json_object"}
    assert seen["thinking_budget"] == 64


def test_inference_gate_never_blocks_an_interactive_call():
    """Blocking a live turn could deadlock a turn that fans out into several
    LLM calls, so interactive callers always pass straight through."""
    async def scenario():
        g = InferenceGate(limit=1)
        order = []
        async def live():
            async with g.slot(interactive=True):
                order.append("live-in")
                await asyncio.sleep(0.05)
                order.append("live-out")
        # Two concurrent live calls with limit=1 must not serialize each other.
        await asyncio.wait_for(asyncio.gather(live(), live()), timeout=1.0)
        return order
    order = asyncio.run(scenario())
    assert order == ["live-in", "live-in", "live-out", "live-out"], order


def test_background_waits_for_the_live_turn():
    async def scenario():
        g = InferenceGate(limit=1)
        order = []

        async def live():
            async with g.slot(interactive=True):
                order.append("live-start")
                await asyncio.sleep(0.15)
                order.append("live-end")

        async def background():
            await asyncio.sleep(0.02)  # arrives while the turn is running
            async with g.slot(interactive=False):
                order.append("bg")

        await asyncio.wait_for(asyncio.gather(live(), background()), timeout=3.0)
        return order
    order = asyncio.run(scenario())
    assert order == ["live-start", "live-end", "bg"], f"background cut in front of the turn: {order}"


def test_background_calls_do_not_stampede():
    """Bounded so several idle-time jobs cannot pile onto the GPU at once."""
    async def scenario():
        g = InferenceGate(limit=1)
        concurrent = 0
        peak = 0

        async def background():
            nonlocal concurrent, peak
            async with g.slot(interactive=False):
                concurrent += 1
                peak = max(peak, concurrent)
                await asyncio.sleep(0.05)
                concurrent -= 1

        await asyncio.wait_for(asyncio.gather(*(background() for _ in range(4))), timeout=5.0)
        return peak
    assert asyncio.run(scenario()) == 1


if __name__ == "__main__":
    test_starts_idle()
    test_active_while_a_turn_is_open()
    test_nested_turns_need_matching_ends()
    test_end_without_begin_does_not_go_negative()
    test_wait_blocks_while_a_turn_is_live()
    test_wait_returns_after_the_turn_ends()
    test_grace_period_covers_a_fast_follow_up_turn()
    test_learning_engine_delegates_to_the_shared_gate()
    test_call_llm_wrapper_forwards_every_argument()
    test_inference_gate_never_blocks_an_interactive_call()
    test_background_waits_for_the_live_turn()
    test_background_calls_do_not_stampede()
    print("OK: all activity_gate tests passed")
