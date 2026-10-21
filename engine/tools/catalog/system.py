"""Tool máy tính Windows (spec 2026-10-12 mục 4)."""
import asyncio
import logging
import os
import shutil
import subprocess
import time

from engine.tools.registry import tool

log = logging.getLogger("jarvis.tools.system")

_MEDIA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "media")
GOOSE_PATH = r"C:\Users\erikpuw\AppData\Local\Programs\Goose-windows\Goose.exe"


@tool(kind="change")
async def open_app(app_name: str) -> str:
    from engine.tools import desktop_automation
    ok = await desktop_automation.open_application(app_name)
    return f"Mở ứng dụng '{app_name}': {'Thành công' if ok else 'Thất bại'}"


@tool(kind="change")
async def close_app(app_name: str) -> str:
    from engine.tools import desktop_automation
    ok = await desktop_automation.close_application(app_name)
    return f"Đóng ứng dụng '{app_name}': {'Thành công' if ok else 'Thất bại'}"


@tool(kind="change")
async def win_control(instruction: str, ctx=None) -> str:
    from engine.tools.desktop_control import execute_desktop_control
    return await execute_desktop_control(instruction, ctx.ws, ctx.send_json, record=ctx.trace, replay=ctx.replay_steps)


@tool(kind="change")
async def capture_screen(ctx=None) -> str:
    from engine.tools.screen import take_screenshot_file
    os.makedirs(_MEDIA_DIR, exist_ok=True)
    filename = f"screenshot_{int(time.time() * 1000)}.png"
    path = os.path.join(_MEDIA_DIR, filename)
    ok = await take_screenshot_file(path)
    if ok:
        try:
            shutil.copyfile(path, os.path.join(_MEDIA_DIR, "screenshot.png"))
        except Exception as exc:
            log.warning("Failed to copy screenshot to legacy path: %s", exc)
    if ok and ctx.ws is not None and ctx.send_json is not None:
        await ctx.send_json(ctx.ws, {"type": "screenshot_processed", "url": f"/api/media/local/{filename}",
                                     "filename": filename})
        return "Đã chụp màn hình và gửi về giao diện thành công."
    return "Không thể chụp hoặc gửi màn hình lúc này."


@tool(display=True)
async def read_screen() -> str:
    from engine.server.llm_server import get_llm_client
    from engine.tools.screen import describe_screen
    return await describe_screen(llm_client=get_llm_client(), stream=False)


@tool(display=True)
async def read_webcam(question: str = "") -> str:
    from engine.server.llm_server import get_llm_client
    from engine.tools.webcam import webcam_analyze
    return await webcam_analyze(client=get_llm_client(), prompt=question or "Mô tả những gì thấy qua webcam.",
                                is_vi=True)


@tool(display=True)  # bảng đủ số liệu hiện thẳng; model chỉ nhận xét (outcome #28: tóm tắt bỏ tiến trình, pin)
async def system_status() -> str:
    from engine.security.system_check import run_system_check
    return await asyncio.to_thread(run_system_check)


@tool()
async def check_security() -> str:
    from engine.security.monitor import run_security_check
    return await asyncio.to_thread(run_security_check)


def launch_goose() -> bool:
    """Mở giao diện Goose Desktop (endpoint /api/agents/goose/launch)."""
    if os.path.exists(GOOSE_PATH):
        try:
            # 0x00000008 = DETACHED_PROCESS trên Windows
            subprocess.Popen([GOOSE_PATH], creationflags=0x00000008, close_fds=True)
            log.info("Goose Desktop GUI launched successfully.")
            return True
        except Exception as e:
            log.error(f"Failed to launch Goose Desktop GUI: {e}")
            return False
    return False
