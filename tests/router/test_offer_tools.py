import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from engine.prompts.catalog import offerable_tools, tool_list_text
OFFERABLE_TOOLS = offerable_tools()
from engine.orchestrator.registry import AGENT_REGISTRY


def test_offerable_tools_map_to_real_agents_and_exclude_risky_tools():
    assert all(agent in AGENT_REGISTRY for agent, _ in OFFERABLE_TOOLS.values())
    for risky in ("win_control", "office_tool", "rag_tool", "dream", "install_extension", "mcp_call"):
        assert risky not in OFFERABLE_TOOLS
    assert OFFERABLE_TOOLS["open_app"][0] == "desktop"
    assert "open_app (mở ứng dụng), close_app (đóng ứng dụng)" in tool_list_text()


def test_offerable_tools_are_registered_commands():
    from engine.tools.skill_manager import get_skill_manager
    mgr = get_skill_manager()
    if not mgr.commands:
        mgr.scan_commands()
    assert set(OFFERABLE_TOOLS) <= set(mgr.commands)
