"""Tách agent search (12 tool) thành mỗi tool một agent, một nguồn duy nhất (skills/agents + registry + prompt/agents.md).
Run: python -m pytest tests/test_tool_agents.py"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.orchestrator import classifier, registry
from engine.prompts import catalog

TOOL_AGENTS = {
    "weather": "weather_search", "news": "search_news", "market": "get_market_data", "shop": "search_products",
    "route": "map_route", "places": "map_pois", "cinema": "get_cgv_movies", "games": "get_epic_free_games",
    "lunar": "get_vannien_data", "zodiac": "get_zodiac_data",
    "web": "web_research",
}


def test_registry_has_one_agent_per_search_tool_and_no_search_agent():
    assert "search" not in registry.AGENT_REGISTRY
    got = {n: e["tool"] for n, e in registry.AGENT_REGISTRY.items() if "tool" in e}
    assert got == {**TOOL_AGENTS, "security": "check_security", "system": "check_system"}


def test_registry_and_catalog_agree_on_every_agent_tool():
    agents = catalog.agents()
    for name, tool in TOOL_AGENTS.items():
        assert [t["name"] for t in agents[name]["tools"]] == [tool], name
        assert catalog.tool_to_agent_map()[tool] == name


def test_resolved_runner_is_bound_to_its_tool(monkeypatch):
    seen = {}

    async def fake_runner(**kw):
        seen.update(kw)
        return "ok"
    import engine.agents.agent_search as mod
    monkeypatch.setattr(mod, "run_search_agent", fake_runner)
    out = asyncio.run(registry.resolve_runner("weather")(user_text="Hà Nội", conversation_history=[], ws=None))
    assert out == "ok" and seen["tools"] == ["weather_search"] and seen["user_text"] == "Hà Nội"


def test_plan_only_agent_is_hidden_from_classifier_but_every_other_agent_is_offered():
    names = [t["function"]["name"] for t in classifier._build_tools()]
    assert "web" not in names and "search" not in names
    assert set(names) == set(registry.AGENT_REGISTRY) - registry.PLAN_ONLY_AGENTS
    for tool in classifier._build_tools():
        fn = tool["function"]
        assert fn["description"] != fn["name"], f"{fn['name']} thiếu tiêu chí trong prompt/agents.md"


def test_search_agents_results_stay_marked_as_untrusted_external_content():
    assert set(TOOL_AGENTS) <= classifier._EXTERNAL_CONTENT_AGENTS


def test_every_plan_target_points_to_a_registered_agent():
    from engine.plans import PLAN_TARGETS
    for target, (agent, tools) in PLAN_TARGETS.items():
        assert agent in registry.AGENT_REGISTRY, target
    assert PLAN_TARGETS["web"][0] == "web"


def test_forced_command_routes_to_the_tools_own_agent():
    from engine.router.fast_paths import forced_command
    d = forced_command("search_products", "máy giặt")
    assert (d.kind, d.agent, d.query, d.source) == ("agent", "shop", "máy giặt", "mention")
    assert forced_command("open_app", "notepad").agent == "desktop"
    assert not hasattr(d, "tools")


def test_slash_marks_only_tool_agent_commands_as_forced():
    from types import SimpleNamespace
    from engine.server.slash_commands import handle_slash_message

    async def send(payload):
        pass

    ws = SimpleNamespace(pending_slash_command=None)
    asyncio.run(handle_slash_message(ws, "/weather_search Hà Nội", send))
    assert ws.forced_command == {"tool": "weather_search", "value": "Hà Nội"}
    ws = SimpleNamespace(pending_slash_command=None)
    asyncio.run(handle_slash_message(ws, "/open_app notepad", send))
    assert ws.forced_command is None
