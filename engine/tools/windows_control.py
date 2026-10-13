"""
Windows Control — Bridge tương thích ngược cho engine.tools.desktop_control.

Toàn bộ logic điều khiển Windows (UIA, cua-driver, window state) đã được quy hoạch
vào package engine.tools.desktop_control.
Module này giữ lại để đảm bảo tương thích 100% với các import cũ.
"""

from __future__ import annotations

import re
from typing import Any

from engine.tools.desktop_control.cua_runner import (
    _CLICK_ARGS,
    _CUA_DEFAULT_EXE,
    _CUA_FINISH_TOOLS,
    _CUA_KEYBOARD,
    _CUA_MAX_ROWS,
    _CUA_PROMPT,
    _CUA_RISKY,
    _CUA_TOOLS,
    _CUA_VERBS,
    _INSTALL_ALL,
    _INSTALL_BUTTON,
    _PREVIEW_UPDATE,
    _SHELL_HOSTS,
    _SHELL_ROLES,
    CuaSession,
    ShellUia,
    _confirm_mode,
    _cua_llm,
    _cua_loop,
    _describe,
    _fmt_state,
    _fmt_windows,
    _int_env,
    _parse_action,
    _preview_install,
    _shell_pool,
    _tool_result,
    cua_driver_path,
    run_cua_task,
)
from engine.tools.desktop_control.window_ops import (
    _WINDOW_STATE_PATTERNS,
    WindowsControl,
    parse_window_state_request,
    run_window_state_workflow,
)


async def run_win_control_workflow(user_text: str, ws: Any, safe_ws_send_json: Any) -> str:
    """Điểm vào tương thích ngược của @control."""
    if parse_window_state_request(user_text):
        kwargs = {}
        if _confirm_mode() == "off":
            async def _yes(_message: str) -> bool:
                return True

            kwargs["confirm"] = _yes
        return await run_window_state_workflow(user_text, ws, safe_ws_send_json, **kwargs)

    task = re.sub(r"^\s*@control\s*", "", user_text or "", flags=re.I)
    return await run_cua_task(task, ws, safe_ws_send_json)


__all__ = [
    "WindowsControl",
    "CuaSession",
    "ShellUia",
    "cua_driver_path",
    "parse_window_state_request",
    "run_cua_task",
    "run_win_control_workflow",
    "run_window_state_workflow",
    "_CUA_MAX_ROWS",
]
