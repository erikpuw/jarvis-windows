"""Tool cho tệp đính kèm (spec 2026-10-12 mục 4): chỉ khai báo khi có tệp đúng định dạng; save_note ghi chú vào kho."""
import asyncio
import json
import os
import re
import sqlite3
import time
import unicodedata
from datetime import datetime
from pathlib import Path

from engine.core.memory import DB_PATH
from engine.tools.registry import tool

_OFFICE_EXT = (".docx", ".xlsx", ".pptx")
NOTES_DIR = Path(__file__).resolve().parents[3] / "data" / "wiki" / "Documents" / "Ghi_chu"  # watcher tự nạp
_LAST_RESULT_SECONDS = 3600  # "lưu cái vừa tra": chỉ kết quả trong 1 giờ gần nhất


def _docs():
    from engine.tools.rag_tool import SUPPORTED_DOCUMENTS
    return SUPPORTED_DOCUMENTS


def _images():
    from engine.tools.image_engine import SUPPORTED_INPUT
    return SUPPORTED_INPUT


def _slug(text: str) -> str:
    text = unicodedata.normalize("NFD", text.lower().replace("đ", "d"))
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return "-".join(re.findall(r"[a-z0-9]+", text)[:8]) or "ghi-chu"


def _last_result() -> tuple[str, str] | None:
    """(câu hỏi, kết quả tool) của lần tra thành công gần nhất, không tính chính save_note."""
    # ponytail: outcomes không có session_id → lấy lần tra gần nhất của mọi phiên; thêm cột nếu nhiều người dùng
    conn = sqlite3.connect(DB_PATH)
    try:
        row = conn.execute(
            "SELECT query, traces FROM outcomes WHERE status='success' AND tools NOT LIKE '%save_note%'"
            " AND created_at >= ? ORDER BY created_at DESC LIMIT 1", (time.time() - _LAST_RESULT_SECONDS,)).fetchone()
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    if not row:
        return None
    results = [t.get("result", "") for t in json.loads(row[1] or "[]") if t.get("result")]
    return (row[0], "\n\n".join(results)) if results else None


def _last_run() -> list[dict]:
    """Chuỗi {tool, args} của lượt thành công gần nhất trong 1 giờ, không tính lượt ghi chú/tạo skill."""
    conn = sqlite3.connect(DB_PATH)
    try:
        row = conn.execute(
            "SELECT traces FROM outcomes WHERE status='success' AND tools NOT LIKE '%save_note%'"
            " AND tools NOT LIKE '%save_skill%' AND created_at >= ? ORDER BY created_at DESC LIMIT 1",
            (time.time() - _LAST_RESULT_SECONDS,)).fetchone()
    except sqlite3.Error:
        return []
    finally:
        conn.close()
    return [{"tool": t["tool"], "args": t.get("args") or {}} for t in json.loads(row[0] or "[]")] if row else []


@tool(kind="change")
async def save_skill(request: str) -> str:
    from engine.tools.skill_writer import write_skill
    return await write_skill(request, await asyncio.to_thread(_last_run))


def _write_note(title: str, body: str) -> Path:
    NOTES_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    base = f"{now:%Y-%m-%d}-{_slug(title)}"
    path, n = NOTES_DIR / f"{base}.md", 2
    while path.exists():  # không bao giờ ghi đè ghi chú cũ
        path, n = NOTES_DIR / f"{base}-{n}.md", n + 1
    path.write_text(f"# {title}\n\n_Ghi lúc {now:%H:%M ngày %d/%m/%Y}_\n\n{body.strip()}\n", encoding="utf-8")
    return path


@tool(kind="change")
async def save_note(content: str = "", title: str = "", from_last_result: bool = False) -> str:
    source = ""
    if from_last_result:
        last = await asyncio.to_thread(_last_result)
        if not last:
            return "Chưa có kết quả tra cứu nào trong 1 giờ gần đây để lưu."
        source, content = last[0], (content.strip() + "\n\n" if content.strip() else "") + last[1]
    if not content.strip():
        return "Chưa có nội dung để ghi chú."
    title = title.strip() or source or content.strip().splitlines()[0][:60]
    body = f"Tra cứu: {source}\n\n{content}" if source else content
    path = await asyncio.to_thread(_write_note, title, body)
    return f"Đã ghi chú vào Ghi_chu/{path.name}."


@tool(kind="change", needs_attachment=True,
      extensions=lambda: _OFFICE_EXT)
async def office_edit(instruction: str, ctx=None) -> str:
    from engine.tools.office_tools import handle_office_command
    return await handle_office_command(prompt=instruction, filepath=str(ctx.attachment_context.resolved_path),
                                       conversation_history=ctx.conversation_history, ws=ctx.ws)


@tool(display=True, needs_attachment=True, extensions=_docs)
async def rag_ask(question: str, ctx=None) -> dict:
    from engine.tools.rag_tool import handle_rag_query
    return await handle_rag_query(query=question, attachment_context=ctx.attachment_context)


@tool(display=True, needs_attachment=True, extensions=_images)
async def read_image(question: str = "", ctx=None) -> str:
    from engine.server.llm_server import get_llm_client
    from engine.tools.screen import describe_image
    return await describe_image(ctx.attachment_context.resolved_path, question or None,
                                llm_client=get_llm_client(), stream=False)


@tool(kind="change", needs_attachment=True, extensions=_images)
async def upscale_image(ctx=None) -> str:
    from engine.core.output_delivery import deliver_output_file
    from engine.tools.image_engine import upscale_image as _upscale
    result = await _upscale(input_path=str(ctx.attachment_context.resolved_path), output_path=None, scale=4,
                            model_name="upscayl-standard-4x", output_format="png")
    if str(result).startswith("Lỗi") or not os.path.exists(str(result)):
        return str(result)
    name = os.path.basename(str(result))
    if await deliver_output_file(ctx.ws, result, kind="image"):
        return f"Đã nâng cấp ảnh x4 và gửi hình xem trước. Tệp: {name}"
    return f"Đã nâng cấp ảnh x4 thành công. Tệp: {name}"
