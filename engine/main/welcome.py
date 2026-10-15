"""Lớp chào phiên mới của WebUI (spec 2026-10-16). Thay greeting cũ: không chữ dài, không TTS, không ghi lịch sử.
Mỗi kết nối nhận gói `welcome` với danh sách công cụ (dòng chữ xoay) ngay, rồi thời tiết khi có. Thời tiết đi qua
fetch_weather_snapshot (cache 10 phút, Open-Meteo → wttr.in → Báo Mới) nên mở trang liên tục không gọi thêm API."""
import asyncio
import logging
from typing import Optional

from engine.tools.weather_engine import fetch_weather_snapshot, _LOCATION_NAME

log = logging.getLogger("jarvis.welcome")

WEATHER_WAIT_SECONDS = 4.0
# Ngài 2026-10-16 bỏ đọc/chụp màn hình và Gmail; các nhãn còn lại đọc không tự nhiên sau "Thử hỏi về …".
_HIDDEN = { "read_screen", "capture_screen", "check_mail", "gym", "read_webcam", "win_control", "open_app", 
            "close_app", "check_project", "mcp_call", "dream", "install_extension", "office_edit", "check_security",
            "system_status",
}


def tool_labels() -> list[str]:
    from engine.tools import registry
    return [registry.label(n) for n in registry.chat_names(None) if n not in _HIDDEN]


def weather_payload(snap: Optional[dict]) -> Optional[dict]:
    if not snap or not snap.get("desc"):
        return None
    return {"desc": snap["desc"], "temp": snap.get("temp"), "kind": snap.get("kind"), "place": _LOCATION_NAME}


async def send_welcome(ws, send) -> None:
    await send(ws, {"type": "welcome", "tools": tool_labels()})
    try:
        snap = await asyncio.wait_for(fetch_weather_snapshot(), WEATHER_WAIT_SECONDS)
    except Exception as e:  # quá giờ hoặc mọi nguồn lỗi: lớp chào để trống dòng thời tiết
        log.info("Welcome weather skipped: %s", e)
        return
    weather = weather_payload(snap)
    if weather:
        await send(ws, {"type": "welcome", "weather": weather})
