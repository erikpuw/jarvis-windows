"""
Desktop Control Package — Điều khiển ứng dụng và giao diện Windows thống nhất.

Cung cấp:
- launcher: mở, đóng ứng dụng Windows an toàn (PowerShell Start-Process, Start menu search, kill process).
- window_ops: thu nhỏ, phóng to, khôi phục cửa sổ tức thì qua UIA/Win32.
- cua_runner: tương tác UI sâu qua cua-driver (UIA accessibility tree, cổng xác nhận ask_user_confirmation).
"""

from __future__ import annotations

import logging
import re
from typing import Any

from engine.tools.desktop_control.launcher import (
    _KNOWN_APPS,
    app_target_exists,
    clean_query,
    close_application,
    extract_app_name,
    open_application,
)
from engine.tools.desktop_control.window_ops import (
    WindowsControl,
    parse_window_state_request,
    run_window_state_workflow,
)
from engine.tools.desktop_control.cua_runner import (
    CuaSession,
    ShellUia,
    _confirm_mode,
    cua_driver_path,
    run_cua_task,
)

log = logging.getLogger("jarvis.desktop_control")


async def execute_desktop_control(user_text: str, ws: Any, safe_ws_send_json: Any, record: list | None = None,
                                  replay: list | None = None) -> str:
    """Điểm vào thống nhất điều khiển Windows/Desktop.

    1. Nếu là thao tác cửa sổ (thu nhỏ, phóng to, khôi phục): chạy tức thì qua window_ops (UIA).
    2. Các thao tác giao diện khác: chạy qua vòng lặp cua-driver có kiểm duyệt an toàn.
    """
    if parse_window_state_request(user_text):
        kwargs = {}
        if _confirm_mode() == "off":
            async def _yes(_message: str) -> bool:
                return True

            kwargs["confirm"] = _yes
        return await run_window_state_workflow(user_text, ws, safe_ws_send_json, **kwargs)

    task = re.sub(r"^\s*@control\s*", "", user_text or "", flags=re.I)
    return await run_cua_task(task, ws, safe_ws_send_json, record=record, replay=replay)


__all__ = [
    "WindowsControl",
    "CuaSession",
    "ShellUia",
    "app_target_exists",
    "clean_query",
    "close_application",
    "cua_driver_path",
    "execute_desktop_control",
    "extract_app_name",
    "open_application",
    "parse_window_state_request",
    "run_cua_task",
    "run_window_state_workflow",
    "_KNOWN_APPS",
]
