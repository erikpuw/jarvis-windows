# -*- coding: utf-8 -*-
"""
JARVIS Hook Registry - Synchronous and async hook dispatch for lifecycle events.

Supports Python hooks (.py) and Node hooks (.js/.ts).
"""

import asyncio
import importlib
import json
import logging
import sys
import traceback
from collections import defaultdict
from typing import Any, Callable, Optional
from pathlib import Path

log = logging.getLogger("jarvis.hooks")

HOOKS_DIR = Path(__file__).resolve().parent.parent.parent / "hooks"

# Node hooks fire on every ON_MESSAGE_RECEIVE/ON_RESPONSE_GENERATE event — a
# hung/buggy hook process with no bound here would freeze the whole request
# pipeline for every user indefinitely.
NODE_HOOK_TIMEOUT_SECONDS = 10.0


def _to_json_safe(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            out[str(k)] = _to_json_safe(v)
        return out
    if isinstance(value, (list, tuple, set)):
        return [_to_json_safe(v) for v in value]
    return str(value)


class HOOKS:
    ON_STARTUP = "on_startup"
    ON_SHUTDOWN = "on_shutdown"
    ON_MESSAGE_RECEIVE = "on_message_receive"
    ON_RESPONSE_GENERATE = "on_response_generate"


class HookRegistry:
    _instance: Optional["HookRegistry"] = None

    def __init__(self):
        self._hooks: dict[str, list[Callable]] = defaultdict(list)

    @classmethod
    def get_instance(cls) -> "HookRegistry":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def register(self, hook_name: str, callback: Callable):
        self._hooks[hook_name].append(callback)

    async def fire_async(self, hook_name: str, **context) -> dict[str, Any]:
        ctx = dict(context)
        
        # 1. Thực thi các python callbacks đã đăng ký
        for cb in list(self._hooks.get(hook_name, [])):
            try:
                result = cb(ctx)
                if hasattr(result, "__await__"):
                    result = await result
                if isinstance(result, dict):
                    ctx.update(result)
            except Exception as e:
                log.warning("Hook '%s' async callback failed: %s", hook_name, e)

        # 2. Tự động quét và thực thi các Node.js/TypeScript hooks được nạp từ HookLoader
        try:
            loader = HookLoader.get_instance()
            for name, info in loader._hooks.items():
                if info.active and info.runtime == "node" and info.file_path:
                    if info.events and hook_name not in info.events:
                        continue
                    # Gửi event dạng JSON qua stdin sang file JS
                    event_data = {
                        "hook_event_name": hook_name,  # ON_STARTUP, ON_MESSAGE_RECEIVE, v.v.
                        "type": "hook",
                        "action": hook_name,
                        "context": _to_json_safe(ctx)
                    }
                    proc = None
                    try:
                        # Thực thi file Javascript của hook bằng Node.js
                        proc = await asyncio.create_subprocess_exec(
                            "node", info.file_path,
                            stdin=asyncio.subprocess.PIPE,
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.PIPE
                        )
                        try:
                            stdout, stderr = await asyncio.wait_for(
                                proc.communicate(input=json.dumps(event_data).encode('utf-8')),
                                timeout=NODE_HOOK_TIMEOUT_SECONDS,
                            )
                        except asyncio.TimeoutError:
                            proc.kill()
                            await proc.wait()
                            log.warning(
                                "Node hook '%s' timed out after %.0fs and was killed",
                                name, NODE_HOOK_TIMEOUT_SECONDS,
                            )
                            continue
                        if proc.returncode == 0 and stdout:
                            try:
                                # Nhận lại context đã chỉnh sửa từ stdout của file JS
                                res_json = json.loads(stdout.decode('utf-8'))
                                if isinstance(res_json, dict):
                                    if "hookSpecificOutput" in res_json:
                                        # Bọc định dạng output của GitNexus
                                        ctx["__injected_context"] = ctx.get("__injected_context", "") + "\n" + str(res_json["hookSpecificOutput"].get("additionalContext", ""))
                                    else:
                                        ctx.update(res_json)
                            except json.JSONDecodeError:
                                pass
                        elif stderr:
                            log.warning("Node hook '%s' stderr: %s", name, stderr.decode('utf-8').strip())
                    except Exception as ex:
                        log.warning("Failed to execute Node hook '%s': %s", name, ex)
        except Exception as e:
            log.warning("Node hooks dispatch failed: %s", e)
                
        return ctx


class HookInfo:
    def __init__(self, name: str, module, description: str = "", runtime: str = "python", file_path: str = ""):
        self.name = name
        self.module = module
        self.description = description
        self.active = False
        self.runtime = runtime
        self.file_path = file_path
        self.events: list[str] = []


class HookLoader:
    _instance: Optional["HookLoader"] = None

    def __init__(self):
        self._hooks: dict[str, HookInfo] = {}

    @classmethod
    def get_instance(cls) -> "HookLoader":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    _SKIP = {"__init__"}

    def discover(self) -> list[str]:
        discovered = []
        if not HOOKS_DIR.exists():
            return discovered
        for entry in sorted(HOOKS_DIR.rglob("*")):
            if entry.is_dir():
                continue
            if entry.suffix.lower() not in {".py", ".js", ".ts", ".cjs", ".mjs"}:
                continue
            parts = entry.relative_to(HOOKS_DIR).parts
            if any(p.startswith(".") or p.startswith("_") for p in parts):
                continue
            mod_name = ".".join(list(parts[:-1]) + [entry.stem])
            if entry.stem in self._SKIP or mod_name in self._SKIP:
                continue
            if mod_name not in discovered:
                discovered.append(mod_name)
        return discovered

    def _find_entry(self, name: str) -> Optional[Path]:
        rel = name.replace(".", "/")
        for ext in (".py", ".js", ".ts", ".cjs", ".mjs"):
            p = HOOKS_DIR / f"{rel}{ext}"
            if p.exists():
                return p
        return None

    def _load_hook_node(self, name: str, entry: Path) -> bool:
        info = HookInfo(name, None, runtime="node", file_path=str(entry))
        info.active = True
        # Đọc HOOK.md metadata để biết hook xử lý event nào
        hook_md = entry.parent / "HOOK.md"
        if hook_md.exists():
            try:
                for line in hook_md.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line.startswith("events:") or line.startswith('"events":') or line.startswith("'events':"):
                        raw = line.split(":", 1)[1].strip().strip('",[]\' ')
                        if raw:
                            info.events = [e.strip().strip('"\'') for e in raw.split(",")]
                            break
                # fallback: parse metadata JSON nếu events không có trong YAML đơn giản
                import re
                md_match = re.search(r'"events"\s*:\s*\[(.*?)\]', hook_md.read_text(encoding="utf-8"))
                if md_match:
                    raw_events = [e.strip().strip('"\'') for e in md_match.group(1).split(",")]
                    info.events = raw_events
            except Exception:
                pass
        log.info("Hook detected and ready (node): %s events=%s", name, info.events)
        return True

    def load_hook(self, name: str) -> bool:
        if name in self._hooks:
            return True
        try:
            entry = self._find_entry(name)
            if entry is None:
                log.warning("Hook entry not found: %s", name)
                return False
            if entry.suffix.lower() in {".js", ".ts", ".cjs", ".mjs"}:
                return self._load_hook_node(name, entry)

            root = str(HOOKS_DIR.parent)
            if root not in sys.path:
                sys.path.insert(0, root)
            mod = importlib.import_module(f"hooks.{name}")
            info = HookInfo(name, mod, getattr(mod, "__description__", ""), runtime="python", file_path=str(entry))
            
            # Tự động đăng ký các hàm lifecycle sự kiện chuẩn vào Registry
            registry = HookRegistry.get_instance()
            for event in [HOOKS.ON_STARTUP, HOOKS.ON_SHUTDOWN, HOOKS.ON_MESSAGE_RECEIVE, HOOKS.ON_RESPONSE_GENERATE]:
                if hasattr(mod, event):
                    callback = getattr(mod, event)
                    registry.register(event, callback)
                    log.info("Hook '%s' auto-registered for event '%s'", name, event)
            
            if hasattr(mod, "setup"):
                result = mod.setup()
                if isinstance(result, bool) and not result:
                    return False
            info.active = True
            self._hooks[name] = info
            log.info("Hook loaded: %s", name)
            return True
        except Exception as e:
            log.error("Failed to load hook '%s': %s\n%s", name, e, traceback.format_exc())
            return False

    def load_all(self) -> int:
        names = self.discover()
        log.info("Discovered %d hook(s): %s", len(names), names)
        success = 0
        for name in names:
            if self.load_hook(name):
                success += 1
        log.info("Loaded %d/%d hook(s)", success, len(names))
        return success

    def unload_all(self):
        self._hooks.clear()
