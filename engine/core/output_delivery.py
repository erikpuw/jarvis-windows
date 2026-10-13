# -*- coding: utf-8 -*-
"""Gửi tệp do tool tạo ra (ảnh upscale, tài liệu Office) về frontend.

Trước đây tool chỉ trả về đường dẫn nên người dùng trên Telegram không xem
được cũng không tải được: họ chỉ thấy một chuỗi đường dẫn trên máy chủ. Mỗi
lần tool tạo xong tệp, gọi ``deliver_output_file`` để bắn event ``output_file``
qua kênh ws hiện tại. ``TelegramSession`` đổi event này thành sendPhoto (xem
ngay trong chat) + sendDocument (tải tệp gốc), còn web ws render thẻ tệp có
nút Tải về trỏ tới ``/api/outputs/{token}``.

Token là bí danh bất đối xứng với đường dẫn thật: frontend chỉ cầm được URL,
không biết và không thể đọc file tuỳ ý ngoài danh sách tool đã bàn giao.
"""
import logging
import re
import secrets
import time
from pathlib import Path
from typing import Any

log = logging.getLogger("jarvis.output_delivery")

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}

# Bí danh → (đường dẫn, thời điểm đăng ký). Dọn bản ghi quá hạn khi đăng ký mới.
_OUTPUT_TTL_SECONDS = 24 * 3600
_output_files: dict[str, tuple[float, Path]] = {}

# Đuôi → tên hiển thị trên thẻ tài liệu (Word/Excel/PowerPoint/PDF…).
OFFICE_LABELS = {
    "doc": "Word", "docx": "Word", "odt": "Word",
    "xls": "Excel", "xlsx": "Excel", "csv": "Excel", "ods": "Excel",
    "ppt": "PowerPoint", "pptx": "PowerPoint", "odp": "PowerPoint",
    "pdf": "PDF",
}


def guess_kind(path: str | Path) -> str:
    """Ảnh xem được inline; phần còn lại (docx/xlsx/pptx/…) là tài liệu."""
    return "image" if Path(path).suffix.lower() in IMAGE_SUFFIXES else "document"


def file_label(path: str | Path) -> str:
    """Tên bộ ứng dụng để frontend gắn icon (Word/Excel/PowerPoint/PDF)."""
    return OFFICE_LABELS.get(Path(path).suffix.lower().lstrip("."), "")


def _register(path: Path) -> str:
    """Cấp token cho tệp và lưu vào bảng đăng ký (dọn bản ghi hết hạn)."""
    now = time.time()
    for token, (born, _) in list(_output_files.items()):
        if now - born > _OUTPUT_TTL_SECONDS:
            _output_files.pop(token, None)
    token = secrets.token_urlsafe(16)
    _output_files[token] = (now, path)
    return token


def lookup_output_file(token: str) -> Path | None:
    """Tra tệp theo token cho route ``/api/outputs/{token}``; hết hạn trả None."""
    entry = _output_files.get(token)
    if entry is None:
        return None
    born, path = entry
    if time.time() - born > _OUTPUT_TTL_SECONDS:
        _output_files.pop(token, None)
        return None
    return path


async def deliver_output_file(
    ws: Any,
    path: str | Path | None,
    *,
    kind: str | None = None,
    caption: str = "",
) -> bool:
    """Bắn event ``output_file`` tới frontend. Trả False nếu không gửi được.

    Không nâng lỗi lên caller: tệp đã tạo xong trên đĩa, frontend gửi được
    hay không không được phép làm hỏng kết quả trả về của tool.
    """
    if ws is None or not path:
        return False

    file_path = Path(path)
    send_json = getattr(ws, "send_json", None)
    if send_json is None:
        log.warning(
            "Không gửi được output_file: ws không có send_json (%s)", type(ws).__name__
        )
        return False

    token = _register(file_path)
    url = f"/api/outputs/{token}"
    payload = {
        "type": "output_file",
        "path": str(file_path),
        "name": re.split(r"[\\/]", str(file_path))[-1],  # đường dẫn Windows vẫn cắt đúng khi chạy trên Linux/CI
        "ext": file_path.suffix.lower().lstrip("."),
        "label": file_label(file_path),
        "kind": kind or guess_kind(file_path),
        "caption": caption,
        "url": url,
        "download_url": f"{url}?download=1",
    }
    try:
        # Cùng thứ tự như safe_ws_send_json: ws có dispatcher thì xếp hàng để
        # giữ nguyên thứ tự với các text_chunk, không thì gửi thẳng.
        dispatcher = getattr(ws, "_event_dispatcher", None)
        if dispatcher is not None:
            await dispatcher.enqueue(payload)
        else:
            await send_json(payload)
        return True
    except Exception as exc:
        log.warning("Gửi event output_file thất bại (%s): %s", re.split(r"[\\/]", str(file_path))[-1], exc)
        return False
