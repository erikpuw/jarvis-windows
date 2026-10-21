"""
MCP: cấu hình (config/mcp_config.json) và MCPHub — kết nối các MCP server, bật/tắt/thêm lúc chạy.

Không giao tiếp với llm_server.py (tầng hạ tầng tách biệt).
"""

import asyncio
import json
import logging
import os
import re
import shutil
from pathlib import Path
from typing import Optional, Any

import httpx

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamable_http_client

log = logging.getLogger("jarvis.mcp_server")

# Paths
PROJECT_ROOT = Path(__file__).parent.parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
MCP_CONFIG_FILE = CONFIG_DIR / "mcp_config.json"


def read_config() -> dict:
    """Nội dung config/mcp_config.json. Thiếu file thì trả cấu hình rỗng.

    Đây là nơi DUY NHẤT đọc file này: MCPHub, trang Settings và các API bật/tắt/thêm đều đi qua đây.
    """
    if not MCP_CONFIG_FILE.exists():
        return {"mcpServers": {}}
    data = json.loads(MCP_CONFIG_FILE.read_text(encoding="utf-8-sig"))
    if not isinstance(data.get("mcpServers"), dict):
        data["mcpServers"] = {}
    return data


def write_config(data: dict) -> None:
    """Ghi config/mcp_config.json qua file tạm rồi thay thế, không để lại file ghi dở khi lỗi giữa chừng."""
    MCP_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = MCP_CONFIG_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, MCP_CONFIG_FILE)


def _runtime_entry(cfg: dict) -> dict:
    """Mục cấu hình → trạng thái chạy của một server trong MCPHub."""
    return {
        "command": cfg.get("command"),
        "args": cfg.get("args", []),
        "env": {**os.environ, **(cfg.get("env") or {})},
        "status": "disconnected",
        "type": cfg.get("type", "stdio"),
        "url": cfg.get("url"),
        "headers": cfg.get("headers") or {},
    }


# Server chỉ được đọc (ngài 2026-10-13): mọi tool ngoài danh sách bị chặn bằng code, không dựa vào prompt.
_READ_ONLY_TOOLS = {"gmail": {"search_emails", "read_email"}}
_GMAIL_MAX_RESULTS = 10


def _read_only_guard(server_name: str, tool_name: str, arguments: dict) -> dict:
    allowed = _READ_ONLY_TOOLS.get(server_name)
    if allowed is None:
        return arguments
    if tool_name not in allowed:
        raise PermissionError(f"'{tool_name}' trên '{server_name}' bị chặn: chỉ cho phép {', '.join(sorted(allowed))}")
    if tool_name == "search_emails":
        try:
            n = int(arguments.get("maxResults") or _GMAIL_MAX_RESULTS)
        except (TypeError, ValueError):
            n = _GMAIL_MAX_RESULTS
        arguments = {**arguments, "maxResults": max(1, min(n, _GMAIL_MAX_RESULTS))}
    return arguments


# ─── MCPHub — Quản lý kết nối MCP servers ───
class MCPHub:
    """Manages multiple MCP server connections and exposes their tools to JARVIS."""

    def __init__(self):
        self.servers: dict[str, dict[str, Any]] = {}
        self.sessions: dict[str, ClientSession] = {}
        self._stop_events: dict[str, asyncio.Event] = {}
        self._lifecycle_tasks: dict[str, asyncio.Task] = {}
        self._background: set[asyncio.Task] = set()
        self._load_config()

    def _load_config(self):
        """Nạp các server đang bật từ config/mcp_config.json."""
        try:
            for name, cfg in read_config()["mcpServers"].items():
                if cfg.get("enabled", True):
                    self.servers[name] = _runtime_entry(cfg)
            log.info("Loaded %d MCP servers from config", len(self.servers))
        except Exception as e:
            log.error("Failed to load MCP config: %s", e)

    def get_stats(self) -> dict:
        """Return connection statistics."""
        total = len(self.servers)
        connected = sum(1 for s in self.servers.values() if s["status"] == "connected")
        return {
            "total_servers": total,
            "connected": connected,
            "disconnected": total - connected,
            "servers": {k: v["status"] for k, v in self.servers.items()},
        }

    def add_server(self, name: str, cfg: dict) -> None:
        """Đăng ký một server (mục cấu hình dạng config/mcp_config.json) vào hub, chưa kết nối."""
        self.servers[name] = _runtime_entry(cfg)
        log.info("Registered MCP server '%s'", name)

    def connect_in_background(self, name: str) -> None:
        """Kết nối không chờ (connect_server có thể chờ tới 60s); trạng thái theo dõi qua get_stats()."""
        if name not in self.servers:
            return
        self.servers[name]["status"] = "connecting"
        task = asyncio.get_running_loop().create_task(self.connect_server(name))
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    async def stop_server(self, name: str) -> None:
        """Ngắt kết nối và bỏ server khỏi hub. Đợi vòng đời kết thúc TRƯỚC khi xoá mục, vì vòng đó còn ghi status."""
        event = self._stop_events.pop(name, None)
        if event is not None:
            event.set()
        task = self._lifecycle_tasks.pop(name, None)
        if task is not None:
            _, pending = await asyncio.wait({task}, timeout=10)
            if pending:
                task.cancel()
                await asyncio.wait({task}, timeout=5)
        self.sessions.pop(name, None)
        self.servers.pop(name, None)

    async def connect_server(self, name: str) -> bool:
        """Connect to a registered MCP server."""
        if name not in self.servers:
            log.error("MCP server '%s' not registered", name)
            return False

        if name in self._lifecycle_tasks and not self._lifecycle_tasks[name].done():
            log.warning("MCP server '%s' already connected or connecting", name)
            return True

        config = self.servers[name]
        server_type = config.get("type", "stdio")

        stop_event = asyncio.Event()
        self._stop_events[name] = stop_event

        connected_future = asyncio.get_running_loop().create_future()

        if server_type == "sse":
            url = config.get("url")
            if not url:
                log.error("MCP server '%s' is type '%s' but lacks 'url'", name, server_type)
                return False
            task = asyncio.create_task(self._run_server_sse(name, url, connected_future, stop_event, config.get("headers") or {}))
        elif server_type in ("remote", "http", "streamable-http"):
            url = config.get("url")
            if not url:
                log.error("MCP server '%s' is type '%s' but lacks 'url'", name, server_type)
                return False
            task = asyncio.create_task(self._run_server_streamable_http(name, url, connected_future, stop_event, config.get("headers") or {}))
        else:
            params = StdioServerParameters(
                command=config["command"],
                args=config["args"],
                env=config["env"],
            )
            task = asyncio.create_task(self._run_server(name, params, connected_future, stop_event))
            
        self._lifecycle_tasks[name] = task

        try:
            return await asyncio.wait_for(connected_future, timeout=60)
        except asyncio.TimeoutError:
            log.warning("Connection to '%s' timed out (>60s), retrying in background", name)
            return False
        except Exception as e:
            log.error("Connection to '%s' failed: %s", name, e)
            config["status"] = "failed"
            return False

    async def _run_server_streamable_http(self, name: str, url: str, connected_future: asyncio.Future, stop_event: asyncio.Event, headers: dict[str, str] = None):
        """Background task to run the server lifecycle via Streamable HTTP with auto-reconnect."""
        retry_delay = 5
        max_delay = 60
        max_retries = 5
        attempts = 0

        while not stop_event.is_set():
            if attempts >= max_retries:
                log.error("MCP server '%s' (Streamable HTTP) failed after %d attempts", name, max_retries)
                self.servers[name]["status"] = "failed_permanently"
                break

            try:
                http_client = httpx.AsyncClient(headers=headers or {})
                try:
                    async with streamable_http_client(url, http_client=http_client) as (read, write, _):
                        async with ClientSession(read, write) as session:
                            await session.initialize()
                            self.sessions[name] = session
                            self.servers[name]["status"] = "connected"
                            log.info("Connected to MCP server '%s' (Streamable HTTP) successfully", name)

                            if not connected_future.done():
                                connected_future.set_result(True)

                            retry_delay = 5
                            attempts = 0
                            await stop_event.wait()
                            break
                finally:
                    await http_client.aclose()

            except asyncio.CancelledError:
                log.info("MCP server '%s' (Streamable HTTP) cancelled", name)
                break
            except Exception as e:
                attempts += 1
                self.servers[name]["status"] = "failed"
                log.error("MCP server '%s' (Streamable HTTP) error: %s", name, e)

                if stop_event.is_set():
                    break

                log.info("Retrying '%s' (Streamable HTTP) in %ds (attempt %d/%d)", name, retry_delay, attempts, max_retries)
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=retry_delay)
                    break
                except asyncio.TimeoutError:
                    retry_delay = min(retry_delay * 2, max_delay)
            finally:
                if name in self.sessions:
                    del self.sessions[name]
                if not stop_event.is_set():
                    self.servers[name]["status"] = "reconnecting"
                else:
                    self.servers[name]["status"] = "disconnected"

        if not connected_future.done():
            connected_future.set_result(False)

    async def _run_server_sse(self, name: str, url: str, connected_future: asyncio.Future, stop_event: asyncio.Event, headers: dict[str, str] = None):
        """Background task to run the server lifecycle via SSE with auto-reconnect."""
        retry_delay = 5
        max_delay = 60
        max_retries = 5
        attempts = 0

        while not stop_event.is_set():
            if attempts >= max_retries:
                log.error("MCP server '%s' (SSE) failed after %d attempts", name, max_retries)
                self.servers[name]["status"] = "failed_permanently"
                break

            try:
                async with sse_client(url, headers=headers or {}) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        self.sessions[name] = session
                        self.servers[name]["status"] = "connected"
                        log.info("Connected to MCP server '%s' (SSE) successfully", name)

                        if not connected_future.done():
                            connected_future.set_result(True)

                        retry_delay = 5
                        attempts = 0
                        await stop_event.wait()
                        break

            except asyncio.CancelledError:
                log.info("MCP server '%s' (SSE) cancelled", name)
                break
            except Exception as e:
                attempts += 1
                self.servers[name]["status"] = "failed"
                log.error("MCP server '%s' (SSE) error: %s", name, e)

                if stop_event.is_set():
                    break

                log.info("Retrying '%s' (SSE) in %ds (attempt %d/%d)", name, retry_delay, attempts, max_retries)
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=retry_delay)
                    break
                except asyncio.TimeoutError:
                    retry_delay = min(retry_delay * 2, max_delay)
            finally:
                if name in self.sessions:
                    del self.sessions[name]
                if not stop_event.is_set():
                    self.servers[name]["status"] = "reconnecting"
                else:
                    self.servers[name]["status"] = "disconnected"

        if not connected_future.done():
            connected_future.set_result(False)

    async def _run_server(self, name: str, params: StdioServerParameters, connected_future: asyncio.Future, stop_event: asyncio.Event):
        """Background task to run the server lifecycle with auto-reconnect."""
        retry_delay = 5
        max_delay = 60
        max_retries = 5
        attempts = 0

        while not stop_event.is_set():

            if attempts >= max_retries:
                log.error("MCP server '%s' failed after %d attempts", name, max_retries)
                self.servers[name]["status"] = "failed_permanently"
                break

            try:
                async with stdio_client(params) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        self.sessions[name] = session
                        self.servers[name]["status"] = "connected"
                        log.info("Connected to MCP server '%s' successfully", name)

                        if not connected_future.done():
                            connected_future.set_result(True)

                        retry_delay = 5
                        attempts = 0
                        await stop_event.wait()
                        break

            except asyncio.CancelledError:
                log.info("MCP server '%s' cancelled", name)
                break
            except Exception as e:
                attempts += 1
                self.servers[name]["status"] = "failed"
                log.error("MCP server '%s' error: %s", name, e)

                if stop_event.is_set():
                    break

                log.info("Retrying '%s' in %ds (attempt %d/%d)", name, retry_delay, attempts, max_retries)
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=retry_delay)
                    break
                except asyncio.TimeoutError:
                    retry_delay = min(retry_delay * 2, max_delay)
            finally:
                if name in self.sessions:
                    del self.sessions[name]
                if not stop_event.is_set():
                    self.servers[name]["status"] = "reconnecting"
                else:
                    self.servers[name]["status"] = "disconnected"

        if not connected_future.done():
            connected_future.set_result(False)

    async def connect_all(self) -> bool:
        """Connect to all enabled servers."""
        tasks = [self.connect_server(name) for name in self.servers]
        if not tasks:
            return True
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return all(r is True for r in results)

    async def list_all_tools(self) -> dict[str, list[Any]]:
        """List tools from all connected servers."""
        all_tools = {}
        for name, session in self.sessions.items():
            try:
                tools_result = await session.list_tools()
                all_tools[name] = [
                    {"name": t.name, "description": t.description, "inputSchema": t.inputSchema}
                    for t in tools_result.tools
                ]
            except Exception as e:
                log.error("Failed to list tools from '%s': %s", name, e)
        return all_tools

    async def get_all_tools_openai(self) -> list[dict]:
        """List all tools from connected servers as OpenAI function calling schemas.
        
        Used for diagnostics/admin. Not passed to LLM (MCP is infrastructure tier).
        """
        openai_tools: list[dict] = []
        for server_name, session in self.sessions.items():
            try:
                tools_result = await session.list_tools()
                for tool in tools_result.tools:
                    openai_tools.append({
                        "type": "function",
                        "function": {
                            "name": tool.name,
                            "description": tool.description,
                            "parameters": tool.inputSchema,
                        }
                    })
            except Exception as e:
                log.warning("Failed to list tools from '%s': %s", server_name, e)
        return openai_tools

    async def call_tool(
        self, server_name: str, tool_name: str, arguments: dict[str, Any] = None, timeout: float = 60.0
    ) -> Any:
        """Call a tool on a specific MCP server.

        Bounded by `timeout` — a hung MCP stdio/HTTP server used to stall
        whichever user request invoked it indefinitely, with no fallback.
        """
        if (server_name or "").lower() == "gmail":
            from engine.core.session_context import is_user_admin
            if not is_user_admin():
                raise PermissionError("Chỉ Quản trị viên (Admin) mới có quyền truy cập máy chủ Gmail.")

        if server_name not in self.sessions:
            raise ValueError(f"Server '{server_name}' not connected")
        arguments = _read_only_guard(server_name, tool_name, arguments or {})
        session = self.sessions[server_name]
        try:
            result = await asyncio.wait_for(session.call_tool(tool_name, arguments or {}), timeout=timeout)
        except asyncio.TimeoutError as exc:
            raise TimeoutError(
                f"MCP tool '{tool_name}' on server '{server_name}' timed out after {timeout}s"
            ) from exc
        return result

    async def shutdown(self):
        """Close all sessions."""
        for name, event in self._stop_events.items():
            event.set()
        if self._lifecycle_tasks:
            await asyncio.gather(*self._lifecycle_tasks.values(), return_exceptions=True)
        self.sessions.clear()
        self._stop_events.clear()
        self._lifecycle_tasks.clear()


# ─── Globals ───

_hub: Optional[MCPHub] = None


def get_mcp_hub() -> MCPHub:
    """Get or create the global MCPHub instance"""
    global _hub
    if _hub is None:
        _hub = MCPHub()
    return _hub


# ─── Bật / tắt / thêm server lúc chạy (cho API của Settings) ───

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SERVER_TYPES = ("stdio", "sse", "http")


def _str_map(value: Any, label: str) -> dict[str, str]:
    if not isinstance(value, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
        raise ValueError(f"{label} phải là các cặp chuỗi.")
    return dict(value)


def validate_new_server(name: str, body: dict) -> dict:
    """Kiểm tra dữ liệu thêm server và trả mục cấu hình sạch. ValueError nếu không hợp lệ.

    Server stdio nghĩa là chạy một lệnh trên máy này, nên lệnh phải tồn tại thật và không đi qua shell.
    """
    if not isinstance(name, str) or not _NAME_RE.match(name):
        raise ValueError("Tên máy chủ chỉ gồm chữ, số, '.', '_', '-' (tối đa 64 ký tự).")
    kind = body.get("type") or "stdio"
    if kind not in _SERVER_TYPES:
        raise ValueError("Loại máy chủ phải là stdio, sse hoặc http.")
    entry: dict[str, Any] = {"type": kind, "enabled": bool(body.get("enabled", True))}
    if kind == "stdio":
        command = str(body.get("command") or "").strip()
        if not command or any(c in command for c in "\r\n\0"):
            raise ValueError("Thiếu lệnh chạy.")
        if not (shutil.which(command) or Path(command).is_file()):
            raise ValueError(f"Không tìm thấy lệnh '{command}' trong PATH.")
        args = body.get("args") or []
        if not isinstance(args, list) or not all(isinstance(a, str) and "\0" not in a and len(a) <= 2000 for a in args):
            raise ValueError("args phải là danh sách chuỗi.")
        entry["command"], entry["args"] = command, args
        if body.get("env"):
            env = _str_map(body["env"], "env")
            bad = next((k for k in env if not _ENV_KEY_RE.match(k)), None)
            if bad is not None:
                raise ValueError(f"Tên biến env không hợp lệ: '{bad}'.")
            entry["env"] = env
    else:
        url = str(body.get("url") or "").strip()
        if not re.match(r"^https?://\S+$", url):
            raise ValueError("URL phải bắt đầu bằng http:// hoặc https://.")
        entry["url"] = url
        if body.get("headers"):
            entry["headers"] = _str_map(body["headers"], "headers")
    return entry


async def set_server_enabled(name: str, enabled: bool) -> str:
    """Ghi cờ enabled vào config rồi áp dụng ngay vào hub, không cần khởi động lại. KeyError nếu không có server."""
    # Đọc-sửa-ghi liền nhau, không có await xen giữa nên hai lời gọi đồng thời không ghi đè nhau.
    data = read_config()
    entry = data["mcpServers"].get(name)
    if entry is None:
        raise KeyError(name)
    entry["enabled"] = bool(enabled)
    write_config(data)
    hub = get_mcp_hub()
    if enabled:
        if name not in hub.servers:
            hub.add_server(name, entry)
        hub.connect_in_background(name)
        return hub.servers[name]["status"]
    await hub.stop_server(name)
    return "disabled"


async def add_server_config(name: str, body: dict) -> None:
    """Thêm server mới vào config và (nếu bật) kết nối ngay. ValueError nếu dữ liệu sai, FileExistsError nếu trùng tên."""
    entry = validate_new_server(name, body)
    data = read_config()
    if name in data["mcpServers"]:
        raise FileExistsError(name)
    data["mcpServers"][name] = entry
    write_config(data)
    if entry["enabled"]:
        hub = get_mcp_hub()
        hub.add_server(name, entry)
        hub.connect_in_background(name)
