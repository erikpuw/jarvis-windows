"""Regression tests for engine.main.ask_verifi queue handling. Run: python tests/test_ask_verifi.py"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.main.ask_verifi import (
    ask_user_confirmation, ask_user_text, ask_user_selection,
    pending_verifications, pending_input_cards, pending_selection_cards,
)

TIMEOUT = 3.0
# A correct abort reacts within a couple of poll ticks (0.1s each); anything
# approaching TIMEOUT means the sentinel was swallowed and we waited it out.
FAST = 1.0


class FakeWS:
    def __init__(self):
        self.message_queue = asyncio.Queue()


async def _noop_send(ws, payload):
    return None


def _reply_when_sent(ws, action, value=None):
    """safe_send stand-in that answers the card it just saw."""
    async def _send(_ws, payload):
        card_id = payload["card"]["id"]
        reply = {"type": "interactive_response", "cardId": card_id, "action": action}
        if value is not None:
            reply["value"] = value
        await ws.message_queue.put(reply)
    return _send


def _run(coro):
    return asyncio.run(coro)


def test_confirmation_aborts_on_disconnect_sentinel():
    async def scenario():
        ws = FakeWS()
        await ws.message_queue.put(None)  # ws_reader disconnect sentinel
        loop = asyncio.get_running_loop()
        started = loop.time()
        result = await ask_user_confirmation(ws, _noop_send, "act", "msg", timeout=TIMEOUT)
        return result, loop.time() - started, ws.message_queue
    result, elapsed, queue = _run(scenario())
    assert result is False, result
    assert elapsed < FAST, f"took {elapsed}s — sentinel was swallowed, waited out the timeout"
    assert queue.get_nowait() is None, "sentinel must be put back for the main loop to break on"
    assert not pending_verifications, pending_verifications


def test_text_aborts_on_disconnect_sentinel():
    async def scenario():
        ws = FakeWS()
        await ws.message_queue.put(None)
        loop = asyncio.get_running_loop()
        started = loop.time()
        result = await ask_user_text(ws, _noop_send, "act", "msg", timeout=TIMEOUT)
        return result, loop.time() - started, ws.message_queue
    result, elapsed, queue = _run(scenario())
    assert result is None, result
    assert elapsed < FAST, f"took {elapsed}s — sentinel was swallowed"
    assert queue.get_nowait() is None
    assert not pending_input_cards, pending_input_cards


def test_selection_aborts_on_disconnect_sentinel():
    async def scenario():
        ws = FakeWS()
        await ws.message_queue.put(None)
        loop = asyncio.get_running_loop()
        started = loop.time()
        # Before the fix this raises AttributeError on None.get(...)
        result = await ask_user_selection(
            ws, _noop_send, "act", "msg", [{"id": "a", "label": "A"}], timeout=TIMEOUT
        )
        return result, loop.time() - started, ws.message_queue
    result, elapsed, queue = _run(scenario())
    assert result is None, result
    assert elapsed < FAST, f"took {elapsed}s — sentinel was swallowed"
    assert queue.get_nowait() is None
    assert not pending_selection_cards, pending_selection_cards


def test_confirmation_requeues_response_for_another_card():
    """A reply belonging to a concurrent sibling ask must go back on the queue."""
    async def scenario():
        ws = FakeWS()
        await ws.message_queue.put(
            {"type": "interactive_response", "cardId": "input_deadbeef", "action": "submit"}
        )
        result = await ask_user_confirmation(ws, _noop_send, "act", "msg", timeout=1.0)
        return result, ws.message_queue
    result, queue = _run(scenario())
    assert result is False, result  # timed out, which is correct here
    foreign = queue.get_nowait()
    assert foreign["cardId"] == "input_deadbeef", "sibling's reply must survive"


def test_confirmation_resolves_its_own_card():
    async def scenario():
        ws = FakeWS()
        return await ask_user_confirmation(
            ws, _reply_when_sent(ws, "approve"), "act", "msg", timeout=TIMEOUT
        )
    assert _run(scenario()) is True
    assert not pending_verifications, pending_verifications


def test_confirmation_reject_returns_false():
    async def scenario():
        ws = FakeWS()
        return await ask_user_confirmation(
            ws, _reply_when_sent(ws, "reject"), "act", "msg", timeout=TIMEOUT
        )
    assert _run(scenario()) is False


def test_text_returns_submitted_value():
    async def scenario():
        ws = FakeWS()
        return await ask_user_text(
            ws, _reply_when_sent(ws, "submit", value="xin chao"), "act", "msg", timeout=TIMEOUT
        )
    assert _run(scenario()) == "xin chao"


def test_selection_returns_first_selected_option():
    async def scenario():
        ws = FakeWS()
        return await ask_user_selection(
            ws, _reply_when_sent(ws, "submit", value=["opt_b"]), "act", "msg",
            [{"id": "opt_a", "label": "A"}, {"id": "opt_b", "label": "B"}], timeout=TIMEOUT
        )
    assert _run(scenario()) == "opt_b"


def test_selection_card_options_carry_value_like_the_clients_read():
    """WebUI (main.ts) và Telegram đọc opt["value"]; card gửi {"id"} làm client trả [null]
    → "Đã hủy xử lý tệp" dù ngài đã chọn RAG (log 2026-09-28 07:27)."""
    async def scenario():
        ws = FakeWS()

        async def webui_click_second(_ws, payload):
            opt = payload["card"]["options"][1]
            await ws.message_queue.put({"type": "interactive_response", "cardId": payload["card"]["id"],
                                        "action": "submit", "value": [opt.get("value")]})
        return await ask_user_selection(
            ws, webui_click_second, "act", "msg",
            [{"id": "rag", "label": "RAG"}, {"id": "cancel", "label": "Không"}], timeout=TIMEOUT
        )
    assert _run(scenario()) == "cancel"


if __name__ == "__main__":
    test_selection_card_options_carry_value_like_the_clients_read()
    test_confirmation_aborts_on_disconnect_sentinel()
    test_text_aborts_on_disconnect_sentinel()
    test_selection_aborts_on_disconnect_sentinel()
    test_confirmation_requeues_response_for_another_card()
    test_confirmation_resolves_its_own_card()
    test_confirmation_reject_returns_false()
    test_text_returns_submitted_value()
    test_selection_returns_first_selected_option()
    print("OK: all ask_verifi regression tests passed")
