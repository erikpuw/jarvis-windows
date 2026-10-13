"""Tests for engine.security.system_check."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.security.system_check import run_system_check
from engine.tools import registry


def test_report_has_all_sections():
    report = run_system_check()
    for marker in ("CPU", "RAM", "Ổ đĩa", "Tiến trình"):
        assert marker in report, marker


def test_report_lists_jarvis_process():
    assert "JARVIS" in run_system_check()


def test_system_status_and_check_security_are_registered_tools():
    assert "system_status" in registry.names()
    assert "check_security" in registry.names()


def test_slash_without_args_forces_check_security():
    import asyncio
    from types import SimpleNamespace
    from engine.server.slash_commands import handle_slash_message

    async def send(payload):
        pass

    ws = SimpleNamespace(pending_slash_command=None)
    asyncio.run(handle_slash_message(ws, "/check_security", send))
    assert ws.forced_command and ws.forced_command["tool"] == "check_security"
