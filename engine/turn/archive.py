"""Tệp nén đính kèm, xử lý trước vòng lặp (2026-09-28): đúng 1 tệp xử lý được → thay tệp đính kèm bằng tệp đó
(vòng lặp, bảng chọn, chốt chặn chạy như khi ngài gửi thẳng tệp); nhiều tệp / không có tệp → nói rõ, dừng lượt."""
import asyncio
import logging
from pathlib import PurePosixPath

log = logging.getLogger("jarvis.turn.archive")
_SHOW = 10


def _names(items: list[str]) -> str:
    names = [PurePosixPath(n.replace("\\", "/")).name for n in items]
    return ", ".join(names[:_SHOW]) + ("…" if len(names) > _SHOW else "")


async def unpack_archive(ctx) -> str | None:
    """None = đi tiếp (không phải tệp nén, hoặc đã thay bằng tệp bên trong). Chuỗi = câu trả lời, dừng lượt."""
    att = ctx.attachment_context
    from engine.tools.archive_tool import is_archive, scan_and_extract
    if att is None or not is_archive(att.filename):
        return None
    from types import SimpleNamespace
    from engine.tools import registry
    scan = await asyncio.to_thread(
        scan_and_extract,
        att.resolved_path,
        lambda ext: bool(registry.file_tools_for(SimpleNamespace(extension=ext))),
    )
    if scan.error:
        return f"Tôi không mở được tệp nén {att.filename}: {scan.error}, thưa ngài."
    if not scan.processable:
        extra = f" (có: {_names(scan.skipped)})" if scan.skipped else ""
        return f"Tệp nén {att.filename} không chứa tài liệu hay ảnh tôi xử lý được{extra}, thưa ngài."
    if len(scan.processable) > 1:
        return (f"Tệp nén {att.filename} chứa {len(scan.processable)} tệp: {_names(scan.processable)}. "
                "Ngài vui lòng gửi từng tệp riêng để tôi xử lý.")
    from engine.core.attachment_store import register_attachment
    inner = await asyncio.to_thread(register_attachment, scan.extracted,
                                    filename=scan.extracted.name, channel=att.channel)
    log.info("[TURN] Archive %s → %s", att.filename, inner.filename)
    ctx.attachment_context = inner
    return None
