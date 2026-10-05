"""'@commands/<tool>.md ...' và '/<tool> ...' chạy đúng agent của tool, không để classifier đoán."""
import asyncio, sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from engine.router.decide import decide
from engine.router.fast_paths import command_mention
from engine.router.types import TurnContext
from engine.server.slash_commands import handle_slash_message, resolve_slash_command


def _ctx():
    async def send(ws, data):
        return True
    return TurnContext(ws=SimpleNamespace(), send_json=send)


def test_command_mention_parses_tool_and_rest():
    assert command_mention("@commands/search_products.md  Tôi cần máy giặt") == ("search_products", "Tôi cần máy giặt")
    assert command_mention("@commands/search_products.md") == ("search_products", "")


def test_command_mention_ignores_everything_else():
    for text in ("@email xem thư", "@commands/khong_co.md x", "search_products x", "@agent_search máy giặt", ""):
        assert command_mention(text) is None, text


def test_decide_routes_a_tool_command_to_its_own_agent():
    d = asyncio.run(decide("@commands/search_products.md đánh giá máy giặt", _ctx()))
    assert (d.kind, d.agent, d.query, d.source) == ("agent", "shop", "đánh giá máy giặt", "mention")


def test_decide_routes_other_agents_commands_too():
    d = asyncio.run(decide("@commands/open_app.md notepad", _ctx()))
    assert d.agent == "desktop"


def test_slash_command_text_is_unchanged_and_carries_tool_and_value():
    r = resolve_slash_command("/search_products máy giặt dưới 10tr")
    assert r["kind"] == "directive" and r["command"] == "search_products"
    assert r["text"] == "Tra cứu giá sản phẩm máy giặt dưới 10tr"   # lệnh chung giữ nguyên, không viết lại
    assert r["value"] == "máy giặt dưới 10tr"
    assert resolve_slash_command("/open_app notepad")["text"] == "Mở ứng dụng notepad"


def _handle(text):
    ws = SimpleNamespace(pending_slash_command=None)

    async def send(payload):
        pass
    return ws, asyncio.run(handle_slash_message(ws, text, send))


def test_handle_slash_message_marks_search_tools_as_forced_but_returns_the_same_text():
    ws, text = _handle("/search_products máy giặt")
    assert text == "Tra cứu giá sản phẩm máy giặt"
    assert ws.forced_command == {"tool": "search_products", "value": "máy giặt"}


def test_handle_slash_message_leaves_other_agents_and_plain_text_alone():
    ws, text = _handle("/open_app notepad")
    assert text == "Mở ứng dụng notepad" and getattr(ws, "forced_command", None) is None
    ws, text = _handle("xin chào")
    assert text == "xin chào" and getattr(ws, "forced_command", None) is None


def test_decide_uses_forced_command_once_with_the_raw_value():
    ctx = _ctx()
    ctx.ws = SimpleNamespace(forced_command={"tool": "search_products", "value": "máy giặt dưới 10tr"})
    d = asyncio.run(decide("Tra cứu giá sản phẩm máy giặt dưới 10tr", ctx))
    assert (d.kind, d.agent, d.query, d.source) == ("agent", "shop", "máy giặt dưới 10tr", "mention")
    assert ctx.ws.forced_command is None      # một lần: lượt sau không dính


def test_naming_a_tool_with_an_imperative_runs_that_tool():
    """Log 2026-10-04: "Dùng lệnh check_system coi" / "Thực hiện lệnh check_system" lọt xuống gate+classifier, chạy nhầm agent."""
    from engine.router.fast_paths import tool_name_command
    assert tool_name_command("Dùng lệnh check_system coi") == "check_system"
    assert tool_name_command("Thực hiện lệnh check_system") == "check_system"
    assert tool_name_command("jarvis, chạy check_security đi") == "check_security"
    assert tool_name_command("chạy lại lệnh `check_system`") == "check_system"
    for text in ("check_system là gì vậy", "tôi có nên dùng lệnh nào đó", "dùng lệnh check_system hay check_security",
                 "xin chào", "dùng lệnh abc_xyz"):
        assert tool_name_command(text) is None, text


def test_decide_runs_a_named_tool_without_the_gate():
    d = asyncio.run(decide("Dùng lệnh check_system coi", _ctx()))
    assert (d.kind, d.agent, d.source) == ("agent", "system", "mention")
