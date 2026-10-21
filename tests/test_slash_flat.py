import asyncio
from engine.server import slash_commands as S


class _WS:
    forced_command = None
    pending_slash_command = None


def _send_collector():
    sent = []

    async def send(data):
        sent.append(data)
    return sent, send


def test_slash_tool_with_value_marks_forced():
    ws = _WS(); sent, send = _send_collector()
    assert asyncio.run(S.handle_slash_message(ws, "/weather huế", send)) == "huế"
    assert ws.forced_command == {"tool": "weather", "value": "huế"}


def test_slash_tool_without_required_param_prompts_then_forces():
    ws = _WS(); sent, send = _send_collector()
    assert asyncio.run(S.handle_slash_message(ws, "/open_app", send)) is None
    assert ws.pending_slash_command == "open_app"
    assert asyncio.run(S.handle_slash_message(ws, "word", send)) == "word"
    assert ws.forced_command == {"tool": "open_app", "value": "word"}


def test_slash_no_param_tool_runs_and_unknown_says_not_found():
    ws = _WS(); sent, send = _send_collector()
    assert asyncio.run(S.handle_slash_message(ws, "/capture_screen", send)) == "capture_screen"
    assert ws.forced_command == {"tool": "capture_screen", "value": ""}
    assert asyncio.run(S.handle_slash_message(_WS(), "/khongco", send)) is None
    assert any("Không tìm thấy" in s.get("text", "") for s in sent)


def test_help_lists_registry_tools():
    text = S.format_tools_help()
    assert "/open_app" in text and "/weather" in text and "agent" not in text.lower()
