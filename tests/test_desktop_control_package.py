"""
Unit tests cho package engine.tools.desktop_control.
Kiểm tra cấu trúc module, trích xuất tham số, và điều phối thống nhất.
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.tools.desktop_control import (
    WindowsControl,
    CuaSession,
    ShellUia,
    app_target_exists,
    clean_query,
    close_application,
    cua_driver_path,
    execute_desktop_control,
    extract_app_name,
    open_application,
    parse_window_state_request,
    run_cua_task,
    run_window_state_workflow,
)


def test_desktop_control_exports():
    """Tất cả các thành phần cốt lõi đều được export đầy đủ từ package desktop_control."""
    assert callable(execute_desktop_control)
    assert callable(open_application)
    assert callable(close_application)
    assert callable(parse_window_state_request)
    assert callable(run_window_state_workflow)
    assert callable(run_cua_task)
    assert WindowsControl is not None
    assert CuaSession is not None
    assert ShellUia is not None


def test_parse_window_state_requests():
    """Nhận diện chính xác các câu lệnh thu nhỏ, phóng to, khôi phục cửa sổ."""
    assert parse_window_state_request("@control phóng to notepad") == ("maximize", "notepad")
    assert parse_window_state_request("thu nhỏ cửa sổ Chrome") == ("minimize", "Chrome")
    assert parse_window_state_request("khôi phục app Word") == ("restore", "Word")
    assert parse_window_state_request("mở edge và gõ tìm kiếm") is None


def test_extract_and_clean_app_name():
    """Kiểm tra tách tên ứng dụng trong launcher."""
    assert clean_query("vui lòng mở notepad") == "mở notepad"
    assert extract_app_name("vui lòng mở notepad") == "notepad"
    assert extract_app_name("mở Chrome") == "chrome"
    assert extract_app_name("tắt calculator") == "calculator"


@pytest.mark.asyncio
async def test_execute_desktop_control_routes_to_window_state():
    """Lệnh điều khiển cửa sổ được định tuyến sang window_state workflow."""
    with patch("engine.tools.desktop_control.run_window_state_workflow", new_callable=AsyncMock) as mock_win:
        mock_win.return_value = "window-ok"
        res = await execute_desktop_control("@control phóng to notepad", None, None)
        assert res == "window-ok"
        mock_win.assert_awaited_once()


@pytest.mark.asyncio
async def test_execute_desktop_control_routes_to_cua_task():
    """Lệnh tương tác UI sâu được định tuyến sang cua_runner."""
    with patch("engine.tools.desktop_control.run_cua_task", new_callable=AsyncMock) as mock_cua:
        mock_cua.return_value = "cua-ok"
        res = await execute_desktop_control("@control bấm vào nút cập nhật", None, None)
        assert res == "cua-ok"
        mock_cua.assert_awaited_once_with("bấm vào nút cập nhật", None, None, record=None, replay=None)


def test_preview_protection_and_update_triggers():
    """Kiểm tra bộ lọc bản Preview và nhận diện nút cập nhật Windows."""
    from engine.tools.desktop_control.cua_runner import (
        _UPDATE_TRIGGER,
        _preview_install,
    )

    # 1. Triggers nhận diện Check for updates và Install all
    assert _UPDATE_TRIGGER.search("Check for updates")
    assert _UPDATE_TRIGGER.search("Kiểm tra bản cập nhật")
    assert _UPDATE_TRIGGER.search("Kiểm tra các bản cập nhật")
    assert _UPDATE_TRIGGER.search("Install all")
    assert _UPDATE_TRIGGER.search("Cài đặt tất cả")
    assert _UPDATE_TRIGGER.search("Download and install all")
    assert _UPDATE_TRIGGER.search("Tải xuống và cài đặt tất cả")

    # 2. Bộ lọc Preview: Chặn nút Install riêng của bản Preview
    preview_rows = [
        {"element_index": 0, "label": "Check for updates"},
        {"element_index": 1, "label": "2026-09 Preview Cumulative Update (KB5124010)"},
        {"element_index": 2, "label": "Download & install"},
        {"element_index": 3, "label": "Install all"},
    ]
    # Nút Download & install ở index 2 bị chặn vì nằm ngay sau bản Preview
    assert _preview_install(preview_rows, 2) is True
    # Nút Install all ở index 3 KHÔNG bị chặn
    assert _preview_install(preview_rows, 3) is False
