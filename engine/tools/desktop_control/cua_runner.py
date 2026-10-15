"""
Cua Runner — Tương tác sâu giao diện Windows qua cua-driver (Accessibility/UIA).

Chạy nền không chiếm chuột/bàn phím.
LLM chọn từng bước theo element_index trong cây UIA.
Mọi thao tác thay đổi máy (mutating) đều qua cổng xác nhận ask_user_confirmation.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
from concurrent.futures import ThreadPoolExecutor
from contextlib import AsyncExitStack
from typing import Any

log = logging.getLogger("jarvis.desktop_control.cua_runner")

_CUA_DEFAULT_EXE = r"%LOCALAPPDATA%\Programs\Cua\cua-driver\bin\cua-driver.exe"
_CUA_MAX_ROWS = 80
_CUA_CALL_TIMEOUT = 30.0
# Mở qua URI (ms-settings:...) driver trả pid 0: chờ cửa sổ hiện rồi tự liệt kê cho model.
# ponytail: chờ cố định, đổi sang dò tới khi có cửa sổ mới nếu Settings mở chậm hơn
_URI_WINDOW_WAIT = 1.5

_CLICK_ARGS = ({"pid", "window_id", "element_index"}, {"pid", "window_id", "element_index"}, True)
_CUA_TOOLS = {
    "list_windows": ({"on_screen_only", "pid"}, set(), False),
    "get_window_state": ({"pid", "window_id", "query"}, {"pid", "window_id"}, False),
    "scroll": ({"pid", "window_id", "element_index", "direction", "amount"}, {"pid", "direction"}, False),
    "launch_app": ({"name"}, {"name"}, True),
    "click": _CLICK_ARGS,
    "double_click": _CLICK_ARGS,
    "right_click": _CLICK_ARGS,
    "type_text": ({"pid", "window_id", "element_index", "text"}, {"pid", "text"}, True),
    "set_value": ({"pid", "window_id", "element_index", "value"}, {"pid", "value"}, True),
    "press_key": ({"pid", "window_id", "element_index", "key", "modifiers"}, {"pid", "key"}, True),
    "hotkey": ({"pid", "window_id", "element_index", "keys"}, {"pid", "keys"}, True),
    "invoke_menu": ({"pid", "window_id", "path"}, {"pid", "window_id", "path"}, True),
    "shell_state": ({"query"}, set(), False),
    "shell_click": ({"element_index"}, {"element_index"}, True),
    "shell_set_text": ({"element_index", "text"}, {"element_index", "text"}, True),
}
_CUA_KEYBOARD = {"type_text", "press_key", "hotkey"}
_CUA_FINISH_TOOLS = {"finish", "done", "final", "stop", "complete"}
_CUA_VERBS = {
    "launch_app": "mở ứng dụng", "click": "bấm", "double_click": "bấm đúp", "right_click": "bấm chuột phải",
    "type_text": "gõ", "set_value": "đặt giá trị", "press_key": "nhấn phím", "hotkey": "nhấn tổ hợp phím",
    "invoke_menu": "chọn menu", "shell_click": "bấm", "shell_set_text": "gõ",
}
_CUA_RISKY = re.compile(
    r"delete|remove|uninstall|format|erase|wipe|reset|shut\s*down|restart|sign\s*out|log\s*off"
    r"|xóa|xoá|gỡ|định\s+dạng|tắt\s+máy|khởi\s+động\s+lại|đăng\s+xuất",
    re.I,
)

_INSTALL_BUTTON = re.compile(r"install|cài\s+đặt|tải\s+xuống", re.I)
_INSTALL_ALL = re.compile(
    r"install\s+all|cài\s+đặt\s+tất\s+cả|download\s+(?:and|&)?\s+install\s+all|tải\s+(?:xuống\s+)?(?:và\s+)?cài\s+đặt\s+tất\s+cả",
    re.I,
)
_PREVIEW_UPDATE = re.compile(r"preview\s+(?:cumulative\s+)?update|update\s+preview|xem\s+trước", re.I)
_UPDATE_TRIGGER = re.compile(
    r"check\s+for\s+updates|kiểm\s+tra\s+(?:các\s+)?bản\s+cập\s+nhật|install\s+all|cài\s+đặt\s+tất\s+cả|download\s+(?:and|&)?\s+install\s+all|tải\s+(?:xuống\s+)?(?:và\s+)?cài\s+đặt\s+tất\s+cả",
    re.I,
)

_CUA_PROMPT = """You control Windows apps through the cua-driver accessibility (UIA) API, one step at a time.
Reply with ONE JSON object and nothing else:
{"tool": "<name>", "args": {...}}  to act, or  {"finish": "<result for the user, in Vietnamese>"}  when done or impossible (finish is NOT a tool).
Start the finish text with "Lỗi:" only when the task failed or you could not verify it; if a conditional step ("if X appears, click it") has its condition unmet, just report that plainly, without "Lỗi".

Tools:
- list_windows {on_screen_only?}: windows with pid and window_id.
- launch_app {name}: open an app by name (e.g. "notepad", "msedge") or a Settings page (e.g. "ms-settings:windowsupdate"); then find its window with list_windows.
- get_window_state {pid, window_id, query?}: UI elements of one window as [element_index] role "label". query is a plain substring of the label; leave it out if unsure. Call it before any element action and again after acting to verify.
- click / double_click / right_click {pid, window_id, element_index}
- set_value {pid, window_id, element_index, value}: set a text field directly (prefer it when the element lists set_value). type_text {pid, window_id, element_index, text}: type into an element.
- press_key {pid, key: "Enter", modifiers?} / hotkey {pid, keys: ["ctrl","s"]}: keyboard input to that app (e.g. Enter to submit an address bar).
- scroll {pid, window_id, element_index, direction: up|down|left|right}
- invoke_menu {pid, window_id, path: ["File","Save"]}
- shell_state {query?}: the taskbar (Start button, pinned/running apps, system tray, clock) and the Start/Search menu when open, as [element_index] role "label". shell_click {element_index}, shell_set_text {element_index, text} act on the latest shell_state. Elements from shell_state must be acted on ONLY with shell_click / shell_set_text (never click/type_text). Only for things the user names as Start menu, taskbar or tray; to just open an app use launch_app. shell_set_text already fills the box: do not click it again. Typical Start flow: shell_state -> shell_click "Start" -> shell_state query "Search box" -> shell_set_text -> shell_state query <app name> -> shell_click the result.
Rules: never guess an element_index, read it from the latest get_window_state (for app windows) or shell_state (for taskbar/Start). Always call shell_state BEFORE calling shell_click or shell_set_text. Never click an install button that belongs to a Preview update. For Windows Update tasks: click 'Install all' or 'Check for updates' once and then immediately finish (do not click individual preview updates or loop further). Do only what the task asks. If a window or element is missing, finish with "Lỗi: ...". Never ask the user questions."""


def cua_driver_path() -> str | None:
    for candidate in (os.getenv("CUA_DRIVER_PATH"), shutil.which("cua-driver"), os.path.expandvars(_CUA_DEFAULT_EXE)):
        if candidate and os.path.isfile(candidate):
            return candidate
    return None


class CuaSession:
    """Một tiến trình `cua-driver mcp` cho một lệnh (khởi động ~0.2s, không cần daemon/Docker)."""

    async def __aenter__(self) -> "CuaSession":
        exe = cua_driver_path()
        if not exe:
            raise FileNotFoundError("cua-driver")
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        self._stack = AsyncExitStack()
        try:
            read, write = await self._stack.enter_async_context(
                stdio_client(StdioServerParameters(command=exe, args=["mcp"]))
            )
            self._session = await self._stack.enter_async_context(ClientSession(read, write))
            await self._session.initialize()
        except BaseException:
            await self._stack.aclose()
            raise
        return self

    async def __aexit__(self, *exc) -> bool:
        await self._stack.aclose()
        return False

    async def call(self, tool: str, args: dict) -> dict:
        if "element_index" in args:  # cua-driver-rs 0.34: element_token "<snapshot_id>:<index>" thay element_index
            args = dict(args)
            args["element_token"] = f"{args.pop('snapshot_id', '')}:{args.pop('element_index')}"
        res = await asyncio.wait_for(self._session.call_tool(tool, args), _CUA_CALL_TIMEOUT)
        text = "".join(getattr(c, "text", "") for c in res.content if getattr(c, "type", "") == "text")
        return {"is_error": bool(res.isError), "text": text, "data": res.structuredContent or {}}


_SHELL_HOSTS = {"startmenuexperiencehost.exe", "searchhost.exe"}
_SHELL_ROLES = {"Button", "ListItem", "Edit", "Hyperlink", "CheckBox", "MenuItem", "TabItem", "SplitButton",
                "ComboBox", "RadioButton"}
_shell_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="shell-uia")


def _tool_result(text: str, *, error: bool = False, data: dict | None = None) -> dict:
    return {"is_error": error, "text": text, "data": data or {}}


class ShellUia:
    """Taskbar và Start/Search menu qua pywinauto (UIA), vì cua-driver không thấy hai bề mặt này."""

    def __init__(self, surfaces=None) -> None:
        self._surfaces = surfaces or self._live_surfaces
        self._els: list = []

    @staticmethod
    def _live_surfaces() -> list:
        import psutil
        from pywinauto import Desktop

        desktop = Desktop(backend="uia")
        found = []
        tray = desktop.window(class_name="Shell_TrayWnd")
        if tray.exists(timeout=1):
            found.append(tray.wrapper_object())
        for w in desktop.windows():
            try:
                if psutil.Process(w.process_id()).name().lower() in _SHELL_HOSTS and w.rectangle().width() > 100:
                    found.append(w)
            except Exception:  # noqa: BLE001 - tiến trình vừa thoát
                continue
        return found

    async def call(self, tool: str, args: dict) -> dict:
        return await asyncio.get_running_loop().run_in_executor(_shell_pool, self._dispatch, tool, args)

    def _dispatch(self, tool: str, args: dict) -> dict:
        try:
            if tool == "shell_state":
                return self._state(str(args.get("query") or ""))
            if tool == "shell_click":
                return self._click(args["element_index"])
            if tool == "shell_set_text":
                return self._set_text(args["element_index"], str(args["text"]))
        except Exception as exc:  # noqa: BLE001
            return _tool_result(f"{tool}: {type(exc).__name__}: {exc}", error=True)
        return _tool_result(f"tool lạ: {tool}", error=True)

    def _state(self, query: str) -> dict:
        self._els, rows = [], []
        for surface in self._surfaces():
            for el in surface.descendants():
                info = el.element_info
                label = (info.name or "").strip() or (info.automation_id or "").strip()
                if info.control_type in _SHELL_ROLES and label:
                    rows.append({"element_index": len(self._els), "role": info.control_type, "label": label})
                    self._els.append(el)
        q = query.lower()
        shown = [r for r in rows if q in r["label"].lower()] if q else rows
        return _tool_result("", data={"elements": shown, "total_element_count": len(rows)})

    def _pick(self, index: Any):
        if not self._els:
            return None, _tool_result("Chưa có snapshot: gọi shell_state trước.", error=True)
        if not isinstance(index, int) or not 0 <= index < len(self._els):
            return None, _tool_result(f"element_index {index} không có trong shell_state mới nhất.", error=True)
        return self._els[index], None

    def _click(self, index: Any) -> dict:
        el, err = self._pick(index)
        if err:
            return err
        label = el.element_info.name or el.element_info.automation_id
        for how in ("invoke", "toggle", "select"):
            try:
                getattr(el, how)()
                return _tool_result(f"✅ {how} '{label}' (UIA, không dùng chuột)")
            except Exception:  # noqa: BLE001
                continue
        return _tool_result(f"'{label}' không hỗ trợ thao tác nền (invoke/toggle/select).", error=True)

    def _set_text(self, index: Any, text: str) -> dict:
        el, err = self._pick(index)
        if err:
            return err
        label = el.element_info.name or el.element_info.automation_id
        try:
            value = el.iface_value
        except Exception:  # noqa: BLE001
            value = None
        if value is None or el.element_info.control_type != "Edit":
            return _tool_result(f"'{label}' không phải ô nhập.", error=True)
        value.SetValue(text)
        return _tool_result(f"✅ đã điền '{label}' (UIA ValuePattern)")


def _confirm_mode() -> str:
    return "off" if (os.getenv("CUA_CONFIRM") or "each").strip().lower() == "off" else "each"


def _int_env(key: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(key, default)))
    except ValueError:
        return default


def _parse_action(text: str) -> dict | None:
    """Lấy object JSON đầu tiên có 'tool' hoặc 'finish'."""
    decoder = json.JSONDecoder()
    for m in re.finditer(r"\{", text or ""):
        try:
            obj, _ = decoder.raw_decode(text[m.start():])
        except ValueError:
            continue
        if not isinstance(obj, dict):
            continue
        args = obj.get("args") if isinstance(obj.get("args"), dict) else {}
        if str(obj.get("tool") or "").lower() in _CUA_FINISH_TOOLS or (
            "finish" in obj and not (isinstance(obj["finish"], str) and obj["finish"].strip())
        ):
            if isinstance(obj.get("args"), str) and obj["args"].strip():
                return {"finish": obj["args"].strip()}
            pools = [obj.get("finish"), args, obj]
            texts = (v for pool in pools if isinstance(pool, dict) for k, v in pool.items()
                     if k not in ("tool", "args") and isinstance(v, str) and v.strip())
            return {"finish": next(texts, "")}
        if "tool" in obj and not args and not isinstance(obj.get("args"), str):  # log 19:08: tham số ghi ngoài "args" → launch_app {} lặp 12 bước
            nested = next((obj[k] for k in ("arguments", "parameters", "input") if isinstance(obj.get(k), dict)), None)
            obj = {**obj, "args": nested if nested is not None
                   else {k: v for k, v in obj.items() if k not in ("tool", "args", "finish")}}
        if "finish" in obj or "tool" in obj:
            return obj
    return None


def _fmt_windows(data: dict) -> str:
    rows = []
    for w in data.get("windows") or []:
        title = (w.get("title") or "").strip()
        if not title or "cua-driver" in (w.get("app_name") or "").lower():
            continue
        rows.append(
            f"pid={w.get('pid')} window_id={w.get('window_id')} {w.get('app_name')} | {title[:80]}"
            + (" (minimized)" if w.get("minimized") else "")
        )
    return "\n".join(rows[:30]) or "(không có cửa sổ nào)"


def _remember_windows(data: dict, last_window: dict) -> None:
    """pid chỉ có một cửa sổ → nhớ window_id để tự điền (DB 2026-10-12 18:52: get_window_state {pid} sau launch
    ms-settings bị từ chối "thiếu tham số" dù danh sách cửa sổ đã có window_id)."""
    seen: dict[Any, list] = {}
    for w in data.get("windows") or []:
        seen.setdefault(w.get("pid"), []).append(w.get("window_id"))
    for pid, ids in seen.items():
        if pid and len(ids) == 1:
            last_window.setdefault(pid, ids[0])


def _window_names(data: dict) -> dict:
    """(pid, window_id) → {app, title}: nhận lại cửa sổ khi phát lại (pid/window_id đổi mỗi lần mở)."""
    return {(w.get("pid"), w.get("window_id")): {"app": w.get("app_name") or "", "title": (w.get("title") or "").strip()}
            for w in data.get("windows") or [] if w.get("window_id") is not None}


_STEP_KEYS = ("name", "text", "value", "key", "modifiers", "keys", "path")


async def _describe_step(tool: str, args: dict, rows: list[dict], windows: dict, cua) -> dict | None:
    """Thao tác vừa chạy → bước lưu theo cửa sổ + nhãn (không index). None = không mô tả được."""
    step = {"action": tool, **{k: args[k] for k in _STEP_KEYS if k in args}}
    if "pid" in args and not tool.startswith("shell_"):
        key = (args.get("pid"), args.get("window_id"))
        if key not in windows:
            listed = await cua.call("list_windows", {"on_screen_only": True})
            windows.update(_window_names(listed.get("data") or {}))
        if key not in windows:
            return None
        step["window"] = windows[key]
    if "element_index" in args:
        el = next((e for e in rows if e.get("element_index") == args["element_index"]), None)
        if el is None or not el.get("label"):
            return None
        step["target"] = {"role": el.get("role") or "", "label": el.get("label")}
    return step


def _fmt_state(data: dict) -> str:
    elements = data.get("elements") or []
    total = data.get("total_element_count") or len(elements)
    rows = []
    for e in elements[:_CUA_MAX_ROWS]:
        row = f'[{e.get("element_index")}] {e.get("role")} "{str(e.get("label") or "")[:80]}"'
        if e.get("value"):
            row += f' value="{str(e["value"])[:60]}"'
        if e.get("actions"):
            row += f' ({",".join(e["actions"])})'
        rows.append(row)
    head = f"{len(rows)}/{total} phần tử" + (" (dùng query để lọc)" if total > len(rows) else "")
    return head + "\n" + "\n".join(rows)


def _preview_install(rows: list[dict], index: Any) -> bool:
    pos = next((i for i, e in enumerate(rows) if e.get("element_index") == index), None)
    if pos is None:
        return False
    label = str(rows[pos].get("label") or "")
    if not _INSTALL_BUTTON.search(label) or _INSTALL_ALL.search(label):
        return False
    return any(_PREVIEW_UPDATE.search(str(e.get("label") or "")) for e in rows[max(0, pos - 4):pos])


def _describe(tool: str, args: dict, label: str) -> str:
    what = args.get("text") if args.get("text") is not None else args.get("value")
    if what is not None:
        detail = f"{str(what)[:100]!r}" + (f" vào {label!r}" if label else "")
    else:
        detail = repr(str(label or args.get("name") or " > ".join(args.get("path") or []) or args.get("key")
                          or "+".join(args.get("keys") or []) or "")[:100])
    return f"Tôi sẽ {_CUA_VERBS.get(tool, tool)} {detail}. Bạn có đồng ý không?"


# Kiểu tham số theo inputSchema của cua-driver v0.34 (list_tools 2026-10-14); element_index là số của bảng
# get_window_state/shell_state (CuaSession.call đổi sang element_token). shell_* là của ShellUia.
_ARG_TYPES = {
    "pid": {"type": "integer"}, "window_id": {"type": "integer"}, "element_index": {"type": "integer"},
    "amount": {"type": "integer"}, "on_screen_only": {"type": "boolean"},
    "direction": {"enum": ["up", "down", "left", "right"]},
    "name": {"type": "string", "minLength": 1}, "text": {"type": "string"}, "value": {"type": "string"},
    "key": {"type": "string", "minLength": 1}, "query": {"type": "string"},
    "modifiers": {"type": "array", "items": {"type": "string"}},
    "keys": {"type": "array", "items": {"type": "string"}, "minItems": 1},
    "path": {"type": "array", "items": {"type": "string"}, "minItems": 1},
}


def _action_schema() -> dict:
    """Grammar một bước: {"tool", "args"} đúng tool + kiểu, hoặc {"finish"}. window_id không bắt buộc vì code tự
    điền từ cửa sổ đã biết; các chốt còn lại (thiếu tham số, snapshot, xác nhận) vẫn ở _cua_loop."""
    branches = [{"type": "object", "properties": {
        "tool": {"const": tool},
        "args": {"type": "object", "properties": {k: _ARG_TYPES[k] for k in sorted(allowed)},
                 "required": sorted(required - {"window_id"}), "additionalProperties": False}},
        "required": ["tool", "args"], "additionalProperties": False}
        for tool, (allowed, required, _) in _CUA_TOOLS.items()]
    finish = {"type": "object", "properties": {"finish": {"type": "string", "minLength": 1}},
              "required": ["finish"], "additionalProperties": False}
    return {"anyOf": [*branches, finish]}


ACTION_SCHEMA = _action_schema()


async def _cua_llm(messages: list) -> str:
    from engine.prompts.learning import json_format
    from engine.server.llm_server import call_llm

    resp = await call_llm(messages=messages, temperature=0.0, thinking=True, thinking_budget=128, max_tokens=600,
                          response_format=json_format("cua_action", ACTION_SCHEMA))
    return (resp.choices[0].message.content or "").strip()


def _find_window(data: dict, want: dict) -> tuple | None:
    app, title = (want.get("app") or "").casefold(), (want.get("title") or "").casefold()
    for w in data.get("windows") or []:
        if (w.get("app_name") or "").casefold() == app and title in (w.get("title") or "").casefold():
            return w.get("pid"), w.get("window_id")
    return None


def _find_element(rows: list[dict], target: dict) -> dict | None:
    label, role = (target.get("label") or "").casefold(), target.get("role") or ""
    return next((e for e in rows if (e.get("label") or "").casefold() == label and (e.get("role") or "") == role),
                None)


def _step_text(step: dict) -> str:
    target = step.get("target") or {}
    return f"{_CUA_VERBS.get(step.get('action'), step.get('action'))} {target.get('label') or step.get('name') or ''}".strip()


async def _replay(steps: list[dict], cua, shell, confirm, mode, record) -> tuple[str | None, str | None]:
    """Phát lại thao tác đã lưu (spec 2026-10-13 mục 4.2). → (kết quả, None) xong / bị từ chối;
    (None, lý do) lệch → vòng model làm tiếp."""
    for i, st in enumerate(steps, 1):
        action = st.get("action") or ""
        spec = _CUA_TOOLS.get(action)
        if spec is None or not spec[2]:
            return None, f"bước {i}: thao tác '{action}' không hợp lệ"
        args = {k: st[k] for k in _STEP_KEYS if k in st}
        rows: list[dict] = []
        target = st.get("target")
        if action.startswith("shell_"):
            res = await shell.call("shell_state", {"query": (target or {}).get("label", "")})
            if res["is_error"]:
                return None, f"bước {i}: {res['text'][:200]}"
            rows = (res["data"] or {}).get("elements") or []
        elif "window" in st:
            listed = await cua.call("list_windows", {"on_screen_only": True})
            found = _find_window(listed.get("data") or {}, st["window"])
            if not found:
                return None, f"bước {i}: không thấy cửa sổ {st['window'].get('title')!r}"
            args["pid"], args["window_id"] = found
            if target:
                # không lọc query: _preview_install cần các dòng phía trên nút (review 2026-10-13)
                res = await cua.call("get_window_state", {"pid": found[0], "window_id": found[1],
                                                          "include_screenshot": False})
                if res["is_error"]:
                    return None, f"bước {i}: {res['text'][:200]}"
                rows = (res["data"] or {}).get("elements") or []
                if (res["data"] or {}).get("snapshot_id"):
                    args["snapshot_id"] = res["data"]["snapshot_id"]
        label = ""
        if target:
            el = _find_element(rows, target)
            if el is None:
                return None, f"bước {i}: không thấy {target.get('role')} {target.get('label')!r}"
            args["element_index"], label = el["element_index"], el.get("label") or ""
        if _preview_install(rows, args.get("element_index")):
            return "Lỗi: Bị chặn: nút cài đặt này thuộc bản cập nhật Preview.", None
        risky = _CUA_RISKY.search(f"{label} {' '.join(map(str, args.get('path') or []))}")
        if (mode == "each" or risky) and not await confirm(_describe(action, args, label)):
            return f"Lỗi: đã dừng ở bước {i} vì bạn không xác nhận.", None
        backend = shell if action.startswith("shell_") else cua
        result = await backend.call(action, args)
        if result["is_error"] and action in _CUA_KEYBOARD and "Background delivery is not available" in result["text"]:
            result = await cua.call(action, {**args, "delivery_mode": "foreground"})
        if result["is_error"]:
            return None, f"bước {i}: {result['text'][:200]}"
        log.info("[CUA] phát lại bước %d/%d: %s", i, len(steps), _step_text(st))
        if action == "launch_app" and "(pid 0)" in (result["text"] or ""):
            await asyncio.sleep(_URI_WINDOW_WAIT)
        if record is not None:
            record.append(st)
    return "Đã làm lại các bước đã lưu: " + " → ".join(_step_text(s) for s in steps), None


async def run_cua_task(
    task: str, ws: Any, safe_ws_send_json: Any, *,
    session_factory=None, ask_llm=None, confirm=None, max_steps: int | None = None, shell=None,
    record: list | None = None, replay: list | None = None,
) -> str:
    """Vòng lặp: LLM chọn một tool cua-driver -> chạy -> đưa kết quả lại cho LLM."""
    task = (task or "").strip()
    if not task:
        return "Lỗi: Chưa có yêu cầu để điều khiển máy."
    if confirm is None:
        async def confirm(message: str) -> bool:
            if not ws or not safe_ws_send_json:
                return False
            from engine.main.ask_verifi import ask_user_confirmation

            return await ask_user_confirmation(ws, safe_ws_send_json, "desktop_control", message, timeout=300.0)
    try:
        async with (session_factory or CuaSession)() as cua:
            return await _cua_loop(
                task, cua, ask_llm or _cua_llm, confirm, _confirm_mode(), max_steps or _int_env("CUA_MAX_STEPS", 12),
                shell or ShellUia(), record=record, replay=replay,
            )
    except FileNotFoundError:
        return "Lỗi: chưa tìm thấy cua-driver. Hãy cài cua-driver hoặc đặt CUA_DRIVER_PATH trong .env."
    except Exception as exc:  # noqa: BLE001
        log.warning("[CUA] lỗi: %s", exc, exc_info=True)
        return f"Lỗi: cua-driver: {exc}"


async def _cua_loop(task, cua, ask_llm, confirm, mode, steps, shell, record=None, replay=None) -> str:
    messages = [{"role": "system", "content": _CUA_PROMPT}, {"role": "user", "content": f"Task: {task}"}]
    if replay:
        done, drift = await _replay(replay, cua, shell, confirm, mode, record)
        if done is not None:
            return done
        log.info("[CUA] phát lại lệch, model làm tiếp: %s", drift)
        messages[1]["content"] += (f"\n\nĐã làm lại các bước đã lưu nhưng dừng ở {drift}. "
                                   "Hãy làm tiếp nhiệm vụ từ trạng thái hiện tại.")
    snapshots: dict[tuple, list[dict]] = {}
    last_window: dict[Any, Any] = {}
    snapshot_ids: dict[tuple, str] = {}
    state_at: dict[str, int] = {}
    last_mutation = None
    last_step = None
    windows: dict[tuple, dict] = {}
    bad_replies = 0
    for step in range(1, steps + 1):
        reply = await ask_llm(messages)
        act = _parse_action(reply)
        if act is None:
            bad_replies += 1
            if bad_replies >= 2:
                return "Lỗi: mô hình không trả về hành động hợp lệ nên tôi dừng để tránh thao tác sai."
            messages += [{"role": "assistant", "content": reply[:300]},
                         {"role": "user", "content": "Reply with exactly one JSON object."}]
            continue
        bad_replies = 0
        if "finish" in act:
            log.info("[CUA] kết thúc: %s", " ".join(reply[:200].split()))
            return str(act["finish"]).strip() or "Lỗi: mô hình kết thúc mà không nêu kết quả cụ thể nên tôi không xác nhận là đã xong."

        tool = str(act.get("tool") or "")
        raw_args = act.get("args") if isinstance(act.get("args"), dict) else {}
        spec = _CUA_TOOLS.get(tool)
        observation, snapshot, label = None, False, ""
        if spec is None:
            observation = f"Tool '{tool}' không được phép. Chỉ dùng: {', '.join(_CUA_TOOLS)}."
        else:
            allowed, required, mutating = spec
            if isinstance(act.get("args"), str) and len(required) == 1:  # log 19:12: "args": "ms-settings:…"
                raw_args = {next(iter(required)): act["args"]}
            args = {k: v for k, v in raw_args.items() if k in allowed}
            if isinstance(args.get("pid"), str) and args["pid"].isdigit():
                args["pid"] = int(args["pid"])
            if "window_id" in allowed and "window_id" not in args and args.get("pid") in last_window:
                args["window_id"] = last_window[args["pid"]]
            if missing := required - args.keys():
                observation = f"Thiếu tham số: {', '.join(sorted(missing))}."
                log.info("[CUA] model trả: %s", " ".join(reply[:300].split()))
            else:
                if tool == "get_window_state":
                    args["include_screenshot"] = False
                snap = (args.get("pid"), args.get("window_id"))
                rows = snapshots.get(snap, [])
                if "element_index" in args and not tool.startswith("shell_"):
                    if snap not in snapshot_ids:
                        observation = "Chưa có snapshot của cửa sổ này: gọi get_window_state(pid, window_id) trước khi thao tác theo element_index. (Phần tử lấy từ shell_state thì dùng shell_click / shell_set_text, không dùng tool này.)"
                    else:
                        args["snapshot_id"] = snapshot_ids[snap]
                elif tool in ("shell_click", "shell_set_text") and (None, None) not in snapshots:
                    observation = "Chưa có snapshot: gọi shell_state trước khi dùng shell_click hoặc shell_set_text."
                if observation is None and mutating and _preview_install(rows, args.get("element_index")):
                    observation = "Bị chặn: nút cài đặt này thuộc bản cập nhật Preview, không được bấm. Dừng lại và báo người dùng."
                if observation is None and mutating:
                    key = (tool, json.dumps(args, sort_keys=True, default=str))
                    if key == last_mutation:
                        return "Lỗi: mô hình lặp lại cùng một thao tác nên tôi dừng, không để nó chạy lung tung."
                    last_mutation = key
                    label = next((str(e.get("label") or "") for e in rows if e.get("element_index") == args.get("element_index")), "")
                    risky = _CUA_RISKY.search(f"{label} {' '.join(map(str, args.get('path') or []))}")
                    if (mode == "each" or risky) and not await confirm(_describe(tool, args, label)):
                        return f"Lỗi: đã dừng ở bước {step} vì bạn không xác nhận."
                if observation is None:
                    backend = shell if tool.startswith("shell_") else cua
                    result = await backend.call(tool, args)
                    if result["is_error"] and tool in _CUA_KEYBOARD and "Background delivery is not available" in result["text"]:
                        result = await cua.call(tool, {**args, "delivery_mode": "foreground"})
                    if result["is_error"]:
                        observation = f"Lỗi từ công cụ: {result['text'][:300]}"
                    elif tool == "list_windows":
                        observation = _fmt_windows(result["data"])
                        _remember_windows(result["data"], last_window)
                        windows.update(_window_names(result["data"]))
                    elif tool in ("get_window_state", "shell_state"):
                        observation, snapshot = _fmt_state(result["data"]), True
                        snapshots[snap] = result["data"].get("elements") or []
                        if tool == "get_window_state":
                            if result["data"].get("snapshot_id"):
                                snapshot_ids[snap] = result["data"]["snapshot_id"]
                            last_window[snap[0]] = snap[1]
                    else:
                        observation = (result["text"] or "ok")[:400]
                        if tool == "launch_app" and "(pid 0)" in observation:
                            await asyncio.sleep(_URI_WINDOW_WAIT)
                            listed = await cua.call("list_windows", {"on_screen_only": True})
                            _remember_windows(listed["data"] or {}, last_window)
                            windows.update(_window_names(listed["data"] or {}))
                            observation += ("\npid 0 không phải cửa sổ thật. Cửa sổ đang mở (dùng pid/window_id ở đây):\n"
                                            + _fmt_windows(listed["data"] or {}))
                        if tool == "click" and _UPDATE_TRIGGER.search(label):
                            observation += "\n(Đã bấm nút cập nhật thành công. Hãy kết thúc bằng finish ngay bây giờ, không bấm thêm.)"
                        if record is not None and mutating:
                            record.append(await _describe_step(tool, args, rows, windows, cua))
        log.info("[CUA] bước %d: %s %s%s -> %s", step, tool, json.dumps(raw_args, ensure_ascii=False)[:200],
                 f" {label!r}" if label else "", str(observation).splitlines()[0][:160] if observation else "")
        this_step = (tool, json.dumps(raw_args, sort_keys=True, default=str), observation)
        if this_step == last_step and not snapshot:
            return f"Lỗi: mô hình lặp lại cùng một lệnh không chạy được ({observation}) nên tôi dừng."
        last_step = this_step
        if snapshot and tool in state_at:
            messages[state_at[tool]]["content"] = "(bản chụp cũ đã bỏ, dùng bản mới nhất)"
        messages += [{"role": "assistant", "content": reply[:400]},
                     {"role": "user", "content": f"Kết quả {tool}:\n{observation}"}]
        if snapshot:
            state_at[tool] = len(messages) - 1
    return f"Lỗi: đã chạy tối đa {steps} bước nhưng chưa xác nhận được việc hoàn thành: {task}"
