"""Tests for '@' mention guidance and slash commands resolution."""
from engine.server import slash_commands as sc


def test_bare_at_returns_full_guidance():
    """Gõ '@' đơn hoặc '@help' trả về hướng dẫn các chế độ @ và tool."""
    for text in ["@", "  @  ", "@help", "@?"]:
        res = sc.resolve_at_command(text)
        assert res is not None, f"Expected info dict for '{text}'"
        assert res["kind"] == "info"
        assert "@plans" not in res["text"] and "@jobs" not in res["text"]  # bỏ 2026-10-12
        assert "@rag" in res["text"]


def test_bare_slash_returns_tools_help():
    """Gõ '/' đơn lẻ hoặc '/help' trả về danh sách toàn bộ tool registry."""
    for text in ["/", "  /  ", "/help", "/commands"]:
        res = sc.resolve_slash_command(text)
        assert res is not None and res["kind"] == "info"
        assert "/open_app" in res["text"]
        assert "/weather" in res["text"]


def test_slash_command_prompt_when_missing_required():
    res = sc.resolve_slash_command("/open_app")
    assert res is not None and res["kind"] == "prompt"
    assert "open_app" in res["text"]


def test_slash_command_forced_when_args_provided():
    res = sc.resolve_slash_command("/weather Hà Nội")
    assert res is not None and res["kind"] == "forced"
    assert res["command"] == "weather"
    assert res["value"] == "Hà Nội"
