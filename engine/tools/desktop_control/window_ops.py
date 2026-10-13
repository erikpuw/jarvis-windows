"""
Window State Operations — Thu nhỏ, phóng to, khôi phục cửa sổ Windows.

Sử dụng trực tiếp UIA qua pywinauto và Win32 ctypes.
Xác minh trạng thái cửa sổ tức thì (0.05s-1s), không qua LLM để đảm bảo tốc độ và độ chính xác cao.
"""

from __future__ import annotations

import asyncio
import logging
import re
import unicodedata
from typing import Any

log = logging.getLogger("jarvis.desktop_control.window_ops")


class WindowsControl:
    """Tìm cửa sổ và đổi trạng thái của nó bằng UIA."""

    def __init__(self, desktop: Any | None = None, process_name_resolver=None) -> None:
        if desktop is None:
            from pywinauto import Desktop

            desktop = Desktop(backend="uia")
        self._desktop = desktop
        self._process_name_resolver = process_name_resolver or self._process_name

    @staticmethod
    def _normalized(value: str) -> str:
        """Compare UIA text without invisible browser title characters."""
        return "".join(
            char for char in (value or "").casefold()
            if unicodedata.category(char) != "Cf"
        )

    @staticmethod
    def _process_name(window: Any) -> str:
        import psutil

        return psutil.Process(window.process_id()).name().removesuffix(".exe").casefold()

    def find_windows(
        self, query: str, *, include_hidden: bool = False
    ) -> list[Any]:
        """Find windows by process identity, optionally including minimized ones."""
        requested = self._normalized(query).strip()
        requested_process = re.sub(r"\s+", "", requested)
        process_matches = []
        title_matches = []
        for candidate in self._desktop.windows(visible_only=not include_hidden):
            if not include_hidden and not candidate.is_visible():
                continue
            title = self._normalized(candidate.window_text())
            process_name = self._normalized(
                self._process_name_resolver(candidate)
            ).removesuffix(".exe")
            if (
                process_name == requested_process
                or process_name.endswith(requested_process)
            ):
                process_matches.append(candidate)
            elif requested in title:
                title_matches.append(candidate)
        return process_matches or title_matches

    @staticmethod
    def _window_state(window: Any) -> str:
        handle = getattr(window, "handle", None)
        if handle:
            try:
                import ctypes

                user32 = ctypes.windll.user32
                if user32.IsIconic(int(handle)):
                    return "minimized"
                if user32.IsZoomed(int(handle)):
                    return "maximized"
                return "normal"
            except (AttributeError, OSError, TypeError, ValueError):
                pass
        if window.is_minimized():
            return "minimized"
        if window.is_maximized():
            return "maximized"
        if window.is_normal():
            return "normal"
        return "unknown"

    def set_window_state(self, window: Any, action: str) -> dict[str, Any]:
        """Change one resolved window state and verify the resulting UIA state."""
        operations = {
            "minimize": ("minimize", "minimized"),
            "maximize": ("maximize", "maximized"),
            "restore": ("restore", "normal"),
        }
        if action not in operations:
            raise ValueError(f"Unsupported window state action: {action}")
        method_name, expected_state = operations[action]
        before_state = WindowsControl._window_state(window)
        getattr(window, method_name)()
        state = WindowsControl._window_state(window)
        if state != expected_state:
            import time

            deadline = time.monotonic() + 1.0
            while state != expected_state and time.monotonic() < deadline:
                time.sleep(0.05)
                state = WindowsControl._window_state(window)
        if state != expected_state:
            raise ValueError(
                f"Window state verification failed: expected {expected_state}, got {state}"
            )
        return {
            "window_title": str(window.window_text()),
            "before_state": before_state,
            "state": state,
            "verified": True,
        }


_WINDOW_STATE_PATTERNS = (
    ("minimize", "thu nhỏ", r"(?:thu\s+nh(?:ỏ|o)|minimi[sz]e)"),
    ("maximize", "phóng to", r"(?:ph(?:ó|o)ng\s+(?:to|l(?:ớ|o)n)|maximi[sz]e)"),
    (
        "restore",
        "khôi phục",
        r"(?:restore\s+down|ph(?:ó|o)ng\s+nh(?:ỏ|o)|kh(?:ô|o)i\s+ph(?:ụ|u)c|restore)",
    ),
)


def parse_window_state_request(user_text: str) -> tuple[str, str] | None:
    """Parse one explicit state action and its application/window target."""
    command = re.sub(r"^\s*@control\s*", "", user_text or "", flags=re.I)
    for action, _label, pattern in _WINDOW_STATE_PATTERNS:
        match = re.search(pattern, command, flags=re.I)
        if not match:
            continue
        target = command[match.end():].strip()
        target = re.sub(
            r"^(?:(?:cửa\s+sổ|ứng\s+dụng|app)\s+)+",
            "",
            target,
            flags=re.I,
        ).strip()
        if target:
            return action, target
    return None


async def run_window_state_workflow(
    user_text: str,
    ws: Any,
    safe_ws_send_json: Any,
    *,
    automation_factory=WindowsControl,
    confirm=None,
    select_window=None,
) -> str:
    """Select, confirm, change, and verify one existing application window."""
    request = parse_window_state_request(user_text)
    if request is None:
        return "Không xác định được thao tác hoặc cửa sổ ứng dụng cần điều khiển."
    action, target = request
    action_label = next(
        label for candidate, label, _pattern in _WINDOW_STATE_PATTERNS
        if candidate == action
    )

    if confirm is None:
        from engine.main.ask_verifi import ask_user_confirmation

        async def confirm(message: str) -> bool:
            return await ask_user_confirmation(
                ws, safe_ws_send_json, "desktop_control", message
            )
    if select_window is None:
        from engine.main.ask_verifi import ask_user_selection

        async def select_window(
            message: str, options: list[dict[str, str]]
        ) -> str | None:
            return await ask_user_selection(
                ws, safe_ws_send_json, "desktop_control", message, options
            )

    automation = automation_factory()
    matches = await asyncio.to_thread(
        automation.find_windows,
        target,
        include_hidden=action == "restore",
    )
    if not matches:
        return (
            f"Không tìm thấy cửa sổ ứng dụng '{target}' đang hoạt động; "
            "tôi không tự mở thêm ứng dụng."
        )

    selected = matches[0]
    if len(matches) > 1:
        options = [
            {"id": str(index), "label": str(window.window_text())}
            for index, window in enumerate(matches)
        ]
        selected_id = await select_window(
            f"Tìm thấy nhiều cửa sổ khớp '{target}'. Chọn cửa sổ cần {action_label}.",
            options,
        )
        if selected_id is None:
            return "Đã hủy vì bạn chưa chọn cửa sổ cần điều khiển."
        try:
            selected = matches[int(selected_id)]
        except (ValueError, IndexError):
            return "Lựa chọn cửa sổ không hợp lệ; tôi chưa thực hiện thao tác."

    title = str(selected.window_text())
    if not await confirm(
        f"Tôi sẽ {action_label} cửa sổ '{title}'. Bạn có đồng ý không?"
    ):
        return f"Đã không {action_label} cửa sổ vì bạn chưa xác nhận."

    try:
        receipt = await asyncio.to_thread(
            automation.set_window_state, selected, action
        )
    except (LookupError, ValueError, AttributeError) as exc:
        return f"Không thể {action_label} cửa sổ '{title}': {exc}"
    return (
        f"Đã {action_label} và xác minh trạng thái cửa sổ "
        f"'{receipt['window_title']}'."
    )
