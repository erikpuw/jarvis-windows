"""MCP: một chỗ đọc/ghi cấu hình, bật/tắt/thêm server lúc chạy, API chỉ nhận từ máy này."""
import asyncio, json, sys, types
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.server import mcp_server as m


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    path = tmp_path / "config" / "mcp_config.json"
    monkeypatch.setattr(m, "MCP_CONFIG_FILE", path)
    monkeypatch.setattr(m, "_hub", None)
    connected = []

    async def fake_connect(self, name):
        connected.append(name)
        return True
    monkeypatch.setattr(m.MCPHub, "connect_server", fake_connect)
    return types.SimpleNamespace(path=path, connected=connected)


def _write(cfg, servers):
    path = cfg.path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"mcpServers": servers}), encoding="utf-8")


def test_old_registry_is_gone():
    assert not hasattr(m, "MCPServer") and not hasattr(m, "initialize_mcp")


def test_read_missing_config(cfg):
    assert m.read_config() == {"mcpServers": {}}


def test_write_config_roundtrip_keeps_other_keys(cfg):
    m.write_config({"mcpServers": {"a": {"command": "x"}}, "note": "giữ"})
    assert m.read_config() == {"mcpServers": {"a": {"command": "x"}}, "note": "giữ"}
    assert not list(cfg.path.parent.glob("*.tmp"))


def test_hub_loads_only_enabled_servers(cfg):
    _write(cfg, {"a": {"command": "x"}, "b": {"command": "y", "enabled": False}})
    assert list(m.MCPHub().servers) == ["a"]


@pytest.mark.parametrize("name,body,msg", [
    ("bad name!", {"command": sys.executable}, "Tên"),
    ("ok", {"type": "ftp"}, "Loại"),
    ("ok", {"type": "stdio", "command": ""}, "lệnh"),
    ("ok", {"type": "stdio", "command": "khong-co-lenh-nay-xyz"}, "Không tìm thấy"),
    ("ok", {"type": "http", "url": "file:///etc/passwd"}, "URL"),
    ("ok", {"type": "stdio", "command": sys.executable, "args": "không phải list"}, "args"),
    ("ok", {"type": "stdio", "command": sys.executable, "env": {"bad key": "1"}}, "env"),
])
def test_validate_rejects(name, body, msg):
    with pytest.raises(ValueError, match=msg):
        m.validate_new_server(name, body)


def test_validate_accepts_stdio_and_http():
    e = m.validate_new_server("srv-1", {"command": sys.executable, "args": ["-m", "x"], "env": {"API_KEY": "k"}})
    assert e == {"type": "stdio", "enabled": True, "command": sys.executable, "args": ["-m", "x"], "env": {"API_KEY": "k"}}
    assert m.validate_new_server("web", {"type": "http", "url": "https://example.com/mcp"})["url"] == "https://example.com/mcp"


def test_add_server_writes_config_and_connects(cfg):
    async def go():
        await m.add_server_config("new", {"command": sys.executable})
        await asyncio.sleep(0.05)
        with pytest.raises(FileExistsError):
            await m.add_server_config("new", {"command": sys.executable})
    asyncio.run(go())
    assert m.read_config()["mcpServers"]["new"]["command"] == sys.executable
    assert "new" in m.get_mcp_hub().servers and cfg.connected == ["new"]


def test_disable_then_enable_at_runtime(cfg):
    _write(cfg, {"a": {"command": "x"}})

    async def go():
        hub = m.get_mcp_hub()
        stop = hub._stop_events["a"] = asyncio.Event()

        async def lifecycle():          # giống _run_server: finally đụng lại hub.servers[name]
            try:
                await stop.wait()
            finally:
                hub.servers["a"]["status"] = "disconnected"
        hub._lifecycle_tasks["a"] = asyncio.create_task(lifecycle())
        await m.set_server_enabled("a", False)
        assert "a" not in hub.servers and hub._lifecycle_tasks == {}
        assert m.read_config()["mcpServers"]["a"]["enabled"] is False
        assert hub.get_stats()["total_servers"] == 0
        await m.set_server_enabled("a", True)
        await asyncio.sleep(0.05)
        assert "a" in hub.servers and m.read_config()["mcpServers"]["a"]["enabled"] is True
        with pytest.raises(KeyError):
            await m.set_server_enabled("khong-co", True)
    asyncio.run(go())
    assert cfg.connected == ["a"]


def test_views_read_through_shared_config_and_hide_secrets(cfg):
    _write(cfg, {"a": {"command": "npx", "args": ["--api-key", "SECRET123"], "env": {"K": "SECRET456"}}})
    from engine.UIUX.ui_engine import _mcp_server_views
    rows = _mcp_server_views({})
    assert rows[0]["name"] == "a" and "SECRET123" not in json.dumps(rows) and "SECRET456" not in json.dumps(rows)


def _client(cfg, host):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from engine.UIUX.ui_engine import router
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, client=(host, 50000))


def test_api_add_and_toggle_only_from_this_machine(cfg):
    _write(cfg, {"a": {"command": "x"}})
    body = {"name": "n1", "command": sys.executable}
    remote = _client(cfg, "192.168.1.50")
    assert remote.post("/api/mcp/servers", json=body).status_code == 403
    assert remote.post("/api/mcp/servers/a/enabled", json={"enabled": False}).status_code == 403
    assert "n1" not in m.read_config()["mcpServers"]

    local = _client(cfg, "127.0.0.1")
    assert local.post("/api/mcp/servers", json=body).json()["success"] is True
    assert local.post("/api/mcp/servers", json=body).status_code == 409
    assert local.post("/api/mcp/servers", json={"name": "bad name", "command": sys.executable}).status_code == 400
    assert local.post("/api/mcp/servers/a/enabled", json={"enabled": False}).json()["success"] is True
    assert local.post("/api/mcp/servers/zzz/enabled", json={"enabled": True}).status_code == 404
    assert m.read_config()["mcpServers"]["a"]["enabled"] is False
