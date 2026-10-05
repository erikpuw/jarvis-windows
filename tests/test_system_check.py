"""Tests for engine.security.system_check. Run: python tests/test_system_check.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.core.command_registry import KNOWN_TOOL_NAMES
from engine.security.system_check import run_system_check


def test_report_has_all_sections():
    report = run_system_check()
    for marker in ("CPU", "RAM", "Ổ đĩa", "Tiến trình"):
        assert marker in report, marker


def test_report_lists_jarvis_process():
    assert "JARVIS" in run_system_check()


def test_check_system_is_registered_tool():
    assert "check_system" in KNOWN_TOOL_NAMES


def test_security_and_system_are_separate_tool_agents():
    from engine.orchestrator.registry import AGENT_REGISTRY
    assert AGENT_REGISTRY["security"]["tool"] == "check_security"
    assert AGENT_REGISTRY["system"]["tool"] == "check_system"


def test_slash_without_args_forces_the_tools_own_agent():
    import asyncio
    from types import SimpleNamespace
    from engine.server.slash_commands import handle_slash_message

    async def send(payload):
        pass

    for tool in ("check_system", "check_security"):
        ws = SimpleNamespace(pending_slash_command=None)
        asyncio.run(handle_slash_message(ws, "/" + tool, send))
        assert ws.forced_command and ws.forced_command["tool"] == tool, tool
    from engine.router.fast_paths import forced_command
    assert forced_command("check_system", "Thực hiện lệnh check_system").agent == "system"
    assert forced_command("check_security", "x").agent == "security"


if __name__ == "__main__":
    test_report_has_all_sections()
    test_report_lists_jarvis_process()
    test_check_system_is_registered_tool()
    test_security_and_system_are_separate_tool_agents()
    test_slash_without_args_forces_the_tools_own_agent()
    print("OK: system_check tests passed")


def test_replay_ignores_workflow_whose_tools_belong_to_other_agents(monkeypatch=None):
    import asyncio
    from engine.router import replay

    class Fake:
        def get_exact_workflow_candidates(self, text):
            return [{"id": 38, "agent": "security", "tool_chain": ["check_system", "check_security"]}]

    replay._learning = lambda: Fake()
    assert asyncio.run(replay.find_replay("kiểm tra hệ thống", None)) is None

    class Ok:
        def get_exact_workflow_candidates(self, text):
            return [{"id": 1, "agent": "system", "tool_chain": ["check_system"]}]

    replay._learning = lambda: Ok()
    assert asyncio.run(replay.find_replay("kiểm tra hệ thống", None))["agent"] == "system"
