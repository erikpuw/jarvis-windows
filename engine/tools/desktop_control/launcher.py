"""
Desktop Control Launcher — Điều phối mở và đóng ứng dụng.

Kế thừa và sử dụng trực tiếp engine.tools.desktop_automation (nơi đảm nhận open_app/close_app ổn định).
"""

from __future__ import annotations

from engine.tools.desktop_automation import (
    _KNOWN_APPS,
    _MAX_APP_NAME_WORDS,
    _PS_CMD,
    _clean_app_name,
    _get_process_name,
    _is_process_running,
    _open_via_start_menu,
    _run_ps,
    app_target_exists,
    clean_query,
    close_application,
    extract_app_name,
    open_application,
)

__all__ = [
    "open_application",
    "close_application",
    "app_target_exists",
    "clean_query",
    "extract_app_name",
    "_clean_app_name",
    "_get_process_name",
    "_is_process_running",
    "_open_via_start_menu",
    "_run_ps",
    "_KNOWN_APPS",
    "_MAX_APP_NAME_WORDS",
    "_PS_CMD",
]
