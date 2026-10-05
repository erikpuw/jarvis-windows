"""Tests for engine.orchestrator.registry. Run: python tests/test_orchestrator_registry.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.orchestrator.registry import AGENT_REGISTRY, resolve_runner, self_check


def test_registry_has_all_agents():
    expected = {
        "goose", "office", "email", "desktop", "vietlott", "vision",
        "webcam", "media", "history", "notes", "project", "security", "system", "image",
        "legal", "win_control", "rag", "dream",
        # agent tra cứu: mỗi tool một agent (2026-10-03)
        "weather", "news", "market", "shop", "route", "places", "cinema", "games", "lunar", "zodiac", "vn_data", "web",
    }
    assert set(AGENT_REGISTRY.keys()) == expected, set(AGENT_REGISTRY.keys())


def test_resolve_runner_returns_callable_for_known_agent():
    runner = resolve_runner("email")
    assert callable(runner)
    assert runner.__name__ == "run_email_agent"


def test_resolve_runner_returns_none_for_unknown_agent():
    assert resolve_runner("does_not_exist") is None


def test_self_check_passes_for_every_registered_agent():
    errors = self_check()
    assert errors == [], errors


def test_self_check_reports_broken_entry():
    broken = {"fake": {"module": "engine.agents.agent_does_not_exist", "runner": "run_fake_agent"}}
    errors = self_check(broken)
    assert len(errors) == 1, errors
    assert "fake" in errors[0]


if __name__ == "__main__":
    test_registry_has_all_18_agents()
    test_resolve_runner_returns_callable_for_known_agent()
    test_resolve_runner_returns_none_for_unknown_agent()
    test_self_check_passes_for_every_registered_agent()
    test_self_check_reports_broken_entry()
    print("OK: all orchestrator registry tests passed")
