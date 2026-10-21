"""Regression tests for the settings dashboard endpoints (review 2026-09-27).

1. /api/settings/status leaked MCP `args` (a context7 API key) and the raw
   mcp_config, and grew to ~93KB by inlining README/prompts/commands on every
   10s poll. The heavy lists now live in /api/settings/catalog.
2. status.mcp_servers turned from the {name: status} dict the HUD reads into a
   list, so the HUD rendered "0", "1", ... with error dots.
3. /api/mcp/servers crashed with NameError `_json`, and reported "connected"
   from the config `enabled` flag instead of the hub's real state.

Run: python -m pytest tests/test_settings_status_api.py -q
"""
import asyncio
import json
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import engine.server.mcp_server as mcp_server_mod
from engine.UIUX import ui_engine

SECRET = "ctx7sk-TEST-SECRET-123"


class FakeHub:
    def __init__(self):
        self.servers = {
            "context7": {"command": "npx", "args": ["--api-key", SECRET], "env": {"TOKEN": SECRET},
                         "status": "connected", "type": "stdio"},
            "wikipedia-mcp": {"command": "wikipedia-mcp", "args": [], "env": {}, "status": "disconnected", "type": "stdio"},
        }

    def get_stats(self):
        return {
            "total_servers": 2,
            "connected": 1,
            "servers": {k: v["status"] for k, v in self.servers.items()},
        }


def _fake_server_module():
    mod = types.ModuleType("server")
    mod._update_session_tokens_from_log = lambda: None
    mod._read_env = lambda: ("", {"LOCAL_API_KEY": "k", "LOCAL_URL": "http://x", "TTS_LOCAL_URL": "http://t",
                                  "LOCAL_MODEL": "gemma-4", "LOCAL_EMBED_MODEL": "bge-m3",
                                  "VIENEU_VOICE_ID": "Adam", "TTS_LOCAL_MODEL": "vi-VN-NamMinhNeural"})
    mod._active_voice_connections = 0
    mod._session_start = 0
    mod._session_tokens = {"input": 5, "output": 7}
    return mod


def _with_fakes(tmp_path, coro_fn):
    cfg = tmp_path / "mcp_config.json"
    cfg.write_text(json.dumps({"mcpServers": {
        "context7": {"command": "npx", "args": ["--api-key", SECRET], "enabled": True},
        "wikipedia-mcp": {"command": "wikipedia-mcp", "args": [], "enabled": True},
        "gitnexus": {"command": "gitnexus", "args": ["mcp"], "enabled": False},
    }}), encoding="utf-8")
    saved = (sys.modules.get("server"), mcp_server_mod.get_mcp_hub, mcp_server_mod.MCP_CONFIG_FILE)
    sys.modules["server"] = _fake_server_module()
    mcp_server_mod.get_mcp_hub = lambda: FakeHub()
    mcp_server_mod.MCP_CONFIG_FILE = cfg
    try:
        return asyncio.run(coro_fn())
    finally:
        if saved[0] is None:
            sys.modules.pop("server", None)
        else:
            sys.modules["server"] = saved[0]
        mcp_server_mod.get_mcp_hub = saved[1]
        mcp_server_mod.MCP_CONFIG_FILE = saved[2]


def test_status_is_light_and_leaks_no_secret(tmp_path):
    status = _with_fakes(tmp_path, lambda: ui_engine.api_settings_status(apps=False))
    dumped = json.dumps(status)
    assert SECRET not in dumped, "status leaks MCP args/env"
    for heavy in ("readme_content", "prompts_list", "commands_list", "skills_list",
                  "hooks_list", "plugins_list", "mcp_config"):
        assert heavy not in status, f"{heavy} must be served by /api/settings/catalog, not every status poll"
    assert len(dumped) < 30_000, f"status payload too large: {len(dumped)} bytes"
    # the Mention list lives in the catalog; the poll only carries the counts
    from engine.tools import registry
    assert "agents" not in status
    assert status["mentions_count"] == len(registry.names()) + 1  # + @rag
    assert status["command_count"] == len(registry.names()) + 1  # + /help


def test_status_mcp_servers_keeps_hud_contract(tmp_path):
    status = _with_fakes(tmp_path, lambda: ui_engine.api_settings_status(apps=False))
    servers = status["mcp_servers"]
    assert isinstance(servers, dict), "HUD reads mcp_servers as {name: status}"
    assert servers == {"context7": "connected", "wikipedia-mcp": "disconnected"}
    assert status["mcp_connected"] == 1 and status["mcp_total"] == 2


def test_mcp_servers_endpoint_uses_real_status_without_secrets(tmp_path):
    result = _with_fakes(tmp_path, ui_engine.api_get_mcp_servers)
    assert result["success"] is True, result
    dumped = json.dumps(result)
    assert SECRET not in dumped, "mcp endpoint leaks args/env"
    assert "config" not in result
    by_name = {s["name"]: s for s in result["servers"]}
    assert by_name["context7"]["status"] == "connected"
    assert by_name["wikipedia-mcp"]["status"] == "disconnected"
    assert by_name["gitnexus"]["status"] == "disabled" and by_name["gitnexus"]["enabled"] is False
    assert all(set(s) <= {"name", "type", "status", "enabled", "command", "args"} for s in result["servers"])
    # args are shown (the MCP page needs them) but secret values are masked
    assert by_name["context7"]["args"] == ["--api-key", "••••"], by_name["context7"]["args"]
    assert by_name["gitnexus"]["args"] == ["mcp"]
    assert result["connected"] == 1 and result["total"] == 3


def test_catalog_serves_the_heavy_lists():
    result = asyncio.run(ui_engine.api_settings_catalog())
    assert result["success"] is True
    for key in ("mentions", "hooks", "skills", "prompts", "commands", "plugins"):
        assert isinstance(result[key], list), key
    # repo ships hooks/ and commands/ — both must actually be scanned (the old
    # code only imported `re` inside the NPU probe, so a failed probe emptied them)
    assert result["hooks"] and result["commands"]


def test_redact_args_masks_secrets_only():
    r = ui_engine._redact_args
    assert r(["-y", "@upstash/context7-mcp", "--api-key", "abc"]) == ["-y", "@upstash/context7-mcp", "--api-key", "••••"]
    assert r(["--token=xyz", "--language", "VI"]) == ["--token=••••", "--language", "VI"]
    assert r(["sk-1234567890abcdef"]) == ["••••"]
    assert r(None) == []


def test_catalog_mentions_carry_real_mention():
    result = asyncio.run(ui_engine.api_settings_catalog())
    weather = next(a for a in result["mentions"] if a["id"] == "weather")
    assert weather["mention"] == "@weather"



def test_prompt_save_only_overwrites_existing_prompt_files(tmp_path, monkeypatch):
    (tmp_path / "chat.md").write_text("old", encoding="utf-8")
    monkeypatch.setattr(ui_engine, "PROMPT_DIR", tmp_path)
    ok = asyncio.run(ui_engine.api_prompt_save(ui_engine.PromptSave(id="chat", content="new text")))
    assert ok["success"] is True and (tmp_path / "chat.md").read_text(encoding="utf-8") == "new text"
    for bad in ("../secrets", "..\\x", "missing", "a/b", ""):
        res = asyncio.run(ui_engine.api_prompt_save(ui_engine.PromptSave(id=bad, content="x")))
        assert res["success"] is False, bad
    assert not (tmp_path.parent / "secrets.md").exists()


def test_status_reports_runtime_models_and_active_tts_engine(tmp_path, monkeypatch):
    # Giọng đọc page shows which engine runs (read-only; switching is manual in .env)
    monkeypatch.setenv("VIENEU_TTS_ENABLED", "true")
    monkeypatch.setenv("EDGE_TTS_ENABLED", "false")
    status = _with_fakes(tmp_path, lambda: ui_engine.api_settings_status(apps=False))
    assert status["runtime"] == {
        "llm_model": "gemma-4", "embed_model": "bge-m3", "tts_engine": "vieneu",
        "vieneu_voice": "Adam", "edge_voice": "vi-VN-NamMinhNeural",
    }
