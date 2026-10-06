"""Central agent registry — single source of truth for route name -> agent
module/runner. Replaces both AGENT_MULTI_TOOLS (the old route_agents.py) and
the importlib dispatch block that used to live in execute_agent_route.

THÊM AGENT MỚI: xem README.md, mục "Thêm agent mới". Tóm tắt các chỗ phải sửa:
registry này + prompt/tools.md (tên @, mô tả, tool) + prompt/agents.md (tiêu chí)
+ commands/<tool>.md, rồi cập nhật tests/golden/classifier_tools.json và
EXPECTED_AGENT_CRITERIA trong tests/test_prompts_catalog.py. Khởi động lại JARVIS."""

import functools
import importlib
import logging

log = logging.getLogger("jarvis.orchestrator.registry")

AGENT_REGISTRY: dict[str, dict[str, str]] = {
    "goose":       {"module": "engine.agents.agent_goose",    "runner": "run_goose_agent"},
    "office":      {"module": "engine.agents.agent_office",   "runner": "run_office_agent"},
    "email":       {"module": "engine.agents.agent_email",    "runner": "run_email_agent"},
    "desktop":     {"module": "engine.agents.agent_desktop",  "runner": "run_desktop_agent"},
    # Mỗi tool tra cứu một agent (2026-10-03: classifier chọn thẳng, đo 50/50 so với 48/50 của 1 agent + chọn tool,
    # một lần gọi LLM thay vì hai). "tool" = tool duy nhất agent chạy; phải khớp skills/agents/<tên>/skill.md.
    "weather":     {"module": "engine.agents.agent_search",   "runner": "run_search_agent", "tool": "weather_search"},
    "news":        {"module": "engine.agents.agent_search",   "runner": "run_search_agent", "tool": "search_news"},
    "market":      {"module": "engine.agents.agent_search",   "runner": "run_search_agent", "tool": "get_market_data"},
    "shop":        {"module": "engine.agents.agent_search",   "runner": "run_search_agent", "tool": "search_products"},
    "route":       {"module": "engine.agents.agent_search",   "runner": "run_search_agent", "tool": "map_route"},
    "places":      {"module": "engine.agents.agent_search",   "runner": "run_search_agent", "tool": "map_pois"},
    "cinema":      {"module": "engine.agents.agent_search",   "runner": "run_search_agent", "tool": "get_cgv_movies"},
    "games":       {"module": "engine.agents.agent_search",   "runner": "run_search_agent", "tool": "get_epic_free_games"},
    "lunar":       {"module": "engine.agents.agent_search",   "runner": "run_search_agent", "tool": "get_vannien_data"},
    "zodiac":      {"module": "engine.agents.agent_search",   "runner": "run_search_agent", "tool": "get_zodiac_data"},
    "web":         {"module": "engine.agents.agent_search",   "runner": "run_search_agent", "tool": "web_research"},
    "vision":      {"module": "engine.agents.agent_vision",   "runner": "run_vision_agent"},
    "webcam":      {"module": "engine.agents.agent_webcam",   "runner": "run_webcam_agent"},
    "media":       {"module": "engine.agents.agent_media",    "runner": "run_media_agent"},
    "history":     {"module": "engine.agents.agent_history",  "runner": "run_history_agent"},
    "notes":       {"module": "engine.agents.agent_notes",    "runner": "run_notes_agent"},
    "project":     {"module": "engine.agents.agent_project",  "runner": "run_project_agent"},
    "security":    {"module": "engine.agents.agent_security", "runner": "run_security_agent", "tool": "check_security"},
    "system":      {"module": "engine.agents.agent_security", "runner": "run_security_agent", "tool": "check_system"},
    "image":       {"module": "engine.agents.agent_image",    "runner": "run_image_agent"},
    "win_control": {"module": "engine.agents.agent_control",  "runner": "run_control_agent"},
    "rag":         {"module": "engine.agents.agent_rag",      "runner": "run_rag_agent"},
    "dream":       {"module": "engine.agents.agent_dream",    "runner": "run_dream_agent"},
}

# Chỉ vào bằng chế độ mục tiêu (@plans): không đưa cho classifier và không nằm trong prompt/agents.md.
PLAN_ONLY_AGENTS = {"web"}


def resolve_runner(agent_name: str, registry: dict = AGENT_REGISTRY):
    """Import and return the runner callable for agent_name, or None if the
    agent isn't registered. Agent có "tool" nhận runner đã gắn sẵn tool đó."""
    entry = registry.get(agent_name)
    if entry is None:
        return None
    module = importlib.import_module(entry["module"])
    runner = getattr(module, entry["runner"])
    return functools.partial(runner, tools=[entry["tool"]]) if "tool" in entry else runner


def self_check(registry: dict = AGENT_REGISTRY) -> list[str]:
    """Import every registry entry and verify its runner exists. Returns a
    list of error strings; empty list means every entry resolves cleanly."""
    errors = []
    for agent_name, entry in registry.items():
        try:
            module = importlib.import_module(entry["module"])
        except Exception as exc:
            errors.append(f"{agent_name}: cannot import {entry['module']} ({exc})")
            continue
        if not hasattr(module, entry["runner"]):
            errors.append(f"{agent_name}: {entry['module']} has no attribute {entry['runner']}")
    return errors


if __name__ == "__main__":
    problems = self_check()
    if problems:
        for p in problems:
            print(f"FAIL: {p}")
        raise SystemExit(1)
    print(f"OK: all {len(AGENT_REGISTRY)} registry entries resolve")
