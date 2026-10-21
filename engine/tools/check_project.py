"""
JARVIS Verification Engine - Quản lý việc xác nhận hành động của người dùng (Yes/No) và kiểm tra project.
"""

import asyncio
import logging
import shutil
import subprocess
import os
import time
from pathlib import Path
from typing import Any

from engine.main.ask_verifi import ask_user_confirmation

log = logging.getLogger("jarvis.check_project")


def build_project_check_command(system_instructions: str, prompt: str) -> list[str]:
    """Chạy quét tổng quát bằng Analyze tích hợp, không nạp MCP hoặc Headroom."""
    return [
        "goose", "run", "--no-session", "--no-profile", "-q", "--max-turns", "8",
        "--with-builtin", "analyze",
        "--system", system_instructions, "--text", prompt,
    ]


def truncate_goose_output(text: str, max_chars: int = 12000) -> str:
    """Rút gọn kết quả Goose CLI nếu quá dài để tránh quá tải token (16348) cho LLM Vòng 2."""
    if len(text) <= max_chars:
        return text
        
    log.info(f"Goose output too long ({len(text)} chars), truncating to {max_chars} chars...")
    half = max_chars // 2
    # Lấy một nửa đầu và một nửa cuối, nối với dòng thông báo
    return (
        text[:half] + 
        f"\n\n... [ĐÃ CẮT BỚT {len(text) - max_chars} KÝ TỰ ĐỂ TRÁNH QUÁ TẢI TOKEN 16348] ...\n\n" + 
        text[-half:]
    )


def build_project_check_prompts(root: Path, instruction: str | None) -> tuple[str, str]:
    """Prompt ngắn, không mâu thuẫn — model cục bộ nhỏ dễ bỏ gọi tool nếu prompt dài."""
    system = (
        f"Thư mục gốc dự án Jarvis: {root}\n"
        "Chỉ dùng công cụ analyze, chỉ đọc, không sửa hay tạo tệp, không hỏi lại người dùng.\n"
        "Gọi analyze với path='.' để xem cây thư mục trước; chỉ phân tích tệp có trong cây đó, không đoán path.\n"
        "Bạn PHẢI thực sự gọi công cụ rồi mới viết báo cáo. Không in JSON tool call ra văn bản."
    )
    task = instruction.strip() if instruction else "Đánh giá tổng quan hiện trạng dự án và đề xuất tối ưu."
    prompt = (
        f"Yêu cầu: {task}\n"
        f"Hãy dùng analyze trên {root}, sau đó viết báo cáo ngắn bằng tiếng Việt. "
        "Dòng đầu báo cáo: 'Dự án: <đường dẫn gốc lấy từ kết quả analyze>'."
    )
    return system, prompt


async def check_project(ws: Any, safe_send: Any, instruction: str = None) -> str:
    """
    Thực hiện gọi Goose CLI quét dự án và kiểm tra code có lỗi hay không (không sửa đổi).
    """
    if ws and safe_send:
        # Gửi yêu cầu xác nhận phê duyệt trước khi kích hoạt Goose CLI
        message = "Jarvis muốn kích hoạt Goose CLI để quét và phân tích dự án của bạn."
        approved = await ask_user_confirmation(ws, safe_send, "check_project", message, timeout=300.0)
        if not approved:
            log.warning("User rejected or timeout occurred for check_project action.")
            return "Yêu cầu quét dự án đã bị từ chối hoặc hết thời gian chờ xác nhận."

    root = Path(__file__).resolve().parent.parent.parent
    goose_bin = shutil.which("goose")
    if not goose_bin:
        log.error("check_project: không tìm thấy 'goose' trong PATH của tiến trình JARVIS.")
        return "Không tìm thấy Goose CLI (`goose`) trong PATH của JARVIS nên không thể quét dự án."
    if not (root / "engine").is_dir():
        log.error(f"check_project: thư mục gốc dự án không hợp lệ: {root}")
        return f"Thư mục gốc dự án không hợp lệ: {root}"
    log.info(f"check_project: goose={goose_bin} cwd={root} instruction={instruction!r}")
    system_instructions, prompt = build_project_check_prompts(root, instruction)

    try:
        # Thiết lập environment
        env = os.environ.copy()
        env["GOOSE_MODE"] = "auto"
        
        started = time.monotonic()
        # Khởi chạy subprocess bất đồng bộ và pipe stdout/stderr
        proc = await asyncio.create_subprocess_exec(
            *build_project_check_command(system_instructions, prompt),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,  # Gộp stderr vào stdout
            env=env,
            cwd=str(root),
        )
        
        # Gửi tiêu đề stream về cho Frontend trước
        if ws and safe_send:
            await safe_send(ws, {"type": "text_chunk", "text": f"=== KẾT QUẢ QUÉT DỰ ÁN (Goose CLI) ===\n[Thư mục quét: {root}]\n"})

        output_chunks = []
        timed_out = False
        # Đọc liên tục stdout cho đến khi tiến trình kết thúc
        while True:
            try:
                line = await asyncio.wait_for(proc.stdout.readline(), timeout=90.0)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                timed_out = True
                break
            if not line:
                break
            text_line = line.decode("utf-8", errors="ignore")
            output_chunks.append(text_line)
            log.debug("goose> %s", text_line.rstrip())

            # Gửi trực tiếp từng dòng về Frontend
            if ws and safe_send:
                await safe_send(ws, {"type": "text_chunk", "text": text_line})

        if timed_out:
            log.error("check_project: goose bị kill do im lặng 90s (cwd=%s)", root)
            return "Quá trình kiểm tra dự án bằng Goose CLI bị hết thời gian chờ (không có log mới trong 90s)."

        await asyncio.wait_for(proc.wait(), timeout=120)

        clean_output = "".join(output_chunks).strip()
        log.info(
            "check_project: goose exit=%s, %d ký tự, %.1fs, nhắc tới thư mục gốc=%s",
            proc.returncode, len(clean_output), time.monotonic() - started,
            str(root).lower() in clean_output.lower(),
        )
        if "▸" not in clean_output:
            log.warning("check_project: output không có dấu vết gọi tool (▸) — Goose có thể chưa thực thi analyze.")
            clean_output += "\n\n[CẢNH BÁO: Goose không thực thi công cụ nào; báo cáo trên chưa được xác minh bằng dữ liệu thật.]"
        if proc.returncode != 0:
            tail = truncate_goose_output(clean_output, 2000) or "(không có output)"
            return f"Goose CLI thất bại (exit code {proc.returncode}) khi quét {root}:\n{tail}"
        if not clean_output:
            clean_output = "Dự án ở trạng thái bình thường, không phát hiện lỗi cấu trúc từ Goose CLI."
            if ws and safe_send:
                await safe_send(ws, {"type": "text_chunk", "text": f"=== KẾT QUẢ QUÉT DỰ ÁN (Goose CLI) ===\n{clean_output}"})
            
        output_for_transport = (
            clean_output if getattr(ws, "is_telegram", False)
            else truncate_goose_output(clean_output)
        )
        return f"=== KẾT QUẢ QUÉT DỰ ÁN (Goose CLI) ===\n{output_for_transport}"
        
    except subprocess.TimeoutExpired:
        return "Quá trình kiểm tra dự án bằng Goose CLI bị hết thời gian chờ (Timeout)."
    except Exception as e:
        return f"Không thể kết nối và kiểm tra dự án qua Goose CLI: {str(e)}"
