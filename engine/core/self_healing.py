# -*- coding: utf-8 -*-
"""
JARVIS Self-Healing Engine — Quản lý việc tự động phát hiện lỗi qua logs và vá lỗi mã nguồn.
Tách biệt hoàn toàn phần logic kỹ thuật ra khỏi Learning và Evolution.
"""

import json
import logging
import re
import time
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Optional
from engine.server.llm_server import call_llm

log = logging.getLogger("jarvis.self_healing")

PROJECT_ROOT = Path(__file__).parent.parent.parent
ERRORS_FILE = PROJECT_ROOT / "data" / "wiki" / "System" / "Errors.md"
_last_fix_self_time: float = 0
_FIX_SELF_COOLDOWN = 120.0  # 2 phút giữa các lần tự sửa code
_last_log_position: int = 0


def is_known_transient_log_error(entry: str) -> bool:
    """Skip known Telegram long-poll transport timeouts and server waiting connection errors before any LLM assessment."""
    normalized = entry.lower()
    if "telegram polling request failed; retrying" in normalized:
        return any(
            marker in normalized
            for marker in ("timeouterror", "timed out", "urlerror", "temporary failure")
        )
    if any(marker in normalized for marker in (
        "chưa hoạt động", "chờ kết nối", "all connection attempts failed",
        "apiconnectionerror", "connecterror", "stream_tts", "port 8082"
    )):
        return True
    return False


def _error_blocks(entries: list[str]) -> list[str]:
    """Dòng log có lỗi, bỏ lỗi tạm thời đã biết. Lọc lỗi trước rồi mới xét tạm thời: log 2026-10-14 22:15 dòng khởi
    động "stream_tts… port 8082" (không phải lỗi) bị báo "skipped transient Telegram polling timeout"."""
    blocks = []
    for entry in entries:
        if not any(kw in entry.lower() for kw in ("error", "failed", "exception", "traceback")):
            continue
        if is_known_transient_log_error(entry):
            log.info("Self-Healing skipped transient error: %s", " ".join(entry.split())[:160])
            continue
        blocks.append(entry)
    return blocks


def _find_project_file_in_error(error_message: str) -> Optional[str]:
    """Tìm đường dẫn file nguồn trong dự án từ traceback một cách chính xác (slash-agnostic)."""
    try:
        project_root = PROJECT_ROOT.resolve()
        matches = re.findall(r'File "([^"]+)", line (\d+)', error_message)
        for file_path_str, _ in reversed(matches):
            try:
                file_path = Path(file_path_str).resolve()
                if project_root in file_path.parents or project_root == file_path:
                    name_lower = file_path.name.lower()
                    if name_lower not in ["fix_self.py", "self_healing.py"]:
                        if "site-packages" not in str(file_path).lower():
                            return str(file_path)
            except Exception:
                continue
    except Exception as e:
        log.warning(f"Error parsing project file from traceback: {e}")
    return None

async def _assess_and_log_error(error_message: str, project_file: str) -> bool:
    """
    Gọi LLM 1 lượt duy nhất để:
    - Phân loại lỗi (CODE_BUG hay không)
    - Đồng thời tạo và ghi entry vào data/wiki/System/Errors.md theo contract nội bộ của Jarvis
    """
    try:
        err_snippet = error_message[:2000]
        from engine.prompts.learning import SELF_HEALING_SCHEMA, build_self_healing_prompt, json_format
        response = await call_llm(
            messages=[{"role": "user", "content": build_self_healing_prompt(project_file, err_snippet)}],
            temperature=0.0, thinking=True, thinking_budget=128, max_tokens=600,
            response_format=json_format("self_healing", SELF_HEALING_SCHEMA),
        )
        # grammar JSON: hỏng là bỏ qua lượt này (trước: lấy chữ thô có "CODE_BUG" làm lỗi code → hỏi ngài gửi Goose)
        data = json.loads((response.choices[0].message.content or "").strip())
        classification = data["classification"]
        if classification not in SELF_HEALING_SCHEMA["properties"]["classification"]["enum"]:
            raise ValueError(f"classification lạ: {classification!r}")
        is_code_bug = classification == "CODE_BUG"
        log.info(f"🛡️ Self-Healing assessment for {Path(project_file).name}: {classification} → {'FIX' if is_code_bug else 'SKIP'}")

        # Errors.md: code ghép giờ/tệp/lỗi đã biết, model chỉ góp phân loại + tóm tắt + bước xử lý
        now = datetime.now()
        last_line = (error_message.strip().splitlines() or [""])[-1][:300]
        entry = (f"## [ERR-{now:%Y%m%d-%H%M%S}] {data['summary']}\n- Time: {now.isoformat(timespec='seconds')}\n"
                 f"- Classification: {classification}\n- File: {project_file}\n- Error: {last_line}\n"
                 f"- Suggested action: {data['action']}")
        ERRORS_FILE.parent.mkdir(parents=True, exist_ok=True)
        if not ERRORS_FILE.exists():
            ERRORS_FILE.write_text("# Errors\n\nCommand failures and integration errors.\n\n---\n", encoding="utf-8")
        with open(ERRORS_FILE, "a", encoding="utf-8") as f:
            f.write(f"\n{entry}\n")
        log.info("🛡️ Self-Healing: Đã ghi nhận lỗi vào data/wiki/System/Errors.md")
        return is_code_bug
    except Exception as e:
        log.warning(f"Failed to assess/log error: {e}")
        return False


async def request_repair_approval(
    project_file: str,
    error_message: str,
    ws=None,
    safe_send=None,
) -> bool:
    """Chỉ cho phép Goose sửa mã sau khi người dùng duyệt trên phiên WebSocket đang mở."""
    if ws is None or safe_send is None:
        try:
            import server
            ws = getattr(server, "_active_ws_session", None)
            safe_send = getattr(server, "safe_ws_send_json", None)
        except Exception as e:
            log.warning(f"Self-Healing: không lấy được phiên xác nhận: {e}")
            return False

    if ws is None or safe_send is None:
        log.warning(
            "Self-Healing: phát hiện lỗi nhưng không có phiên người dùng để xác nhận; không gọi Goose CLI."
        )
        return False

    from engine.main.ask_verifi import ask_user_confirmation

    error_summary = " ".join(error_message.strip().splitlines()[-2:])[:500]
    message = (
        "Jarvis phát hiện lỗi mã nguồn và muốn gửi Goose CLI sửa đúng một tệp.\n"
        f"Tệp: {project_file}\n"
        f"Lỗi: {error_summary}\n"
        "Goose chỉ được phép sửa tệp trên, không được cài đặt, xóa, đổi tên tệp hoặc thay đổi cấu hình hệ thống."
    )
    return await ask_user_confirmation(
        ws,
        safe_send,
        "repair_code",
        message,
        timeout=300.0,
    )


def _read_new_log_lines(log_path: Path, last_position: int) -> tuple[list[str], int]:
    """Blocking file read, meant to be called via asyncio.to_thread."""
    with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
        size = log_path.stat().st_size
        if size < last_position:
            last_position = 0
        f.seek(last_position)
        raw = f.readlines()
        new_position = f.tell()
    return raw, new_position


async def trigger_self_healing_from_logs():
    """Quét log hệ thống, đánh giá lỗi và chỉ sửa khi người dùng đã phê duyệt."""
    global _last_fix_self_time, _last_log_position
    now = time.time()
    log_path = PROJECT_ROOT / "logs" / "jarvis.log"
    if not log_path.exists():
        return

    try:
        # Đọc logs mới phát sinh — file I/O đồng bộ, chạy trong thread pool để
        # không chặn event loop (hàm này được watcher loop gọi mỗi ~60s)
        raw, _last_log_position = await asyncio.to_thread(
            _read_new_log_lines, log_path, _last_log_position
        )

        if not raw:
            return

        # Gom nhóm logs và tìm traceback lỗi
        log_entries = []
        current_entry = []
        for line in raw:
            if re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", line):
                if current_entry:
                    log_entries.append("".join(current_entry))
                    current_entry = []
            current_entry.append(line)
        if current_entry:
            log_entries.append("".join(current_entry))

        error_blocks = _error_blocks(log_entries)
        if not error_blocks:
            return

        # Chỉ kiểm tra sửa lỗi mới nhất
        if (now - _last_fix_self_time) > _FIX_SELF_COOLDOWN:
            from engine.server.llm_server import check_llm_server
            llm_online, _, _ = check_llm_server()
            if not llm_online:
                return  # Máy chủ LLM chưa hoạt động, bỏ qua tự sửa để tránh spam kết nối

            for err_line in reversed(error_blocks):
                project_file = _find_project_file_in_error(err_line)
                if project_file:
                    should_fix = await _assess_and_log_error(err_line, project_file)
                    if not should_fix:
                        log.info(f"🛡️ Self-Healing: Bỏ qua sửa {project_file} — LLM đánh giá không phải lỗi code nguồn.")
                        continue
                    approved = await request_repair_approval(project_file, err_line)
                    if not approved:
                        log.info(f"🛡️ Self-Healing: Không được phê duyệt sửa {project_file}; không gọi Goose CLI.")
                        break

                    log.info(f"🛡️ Self-Healing: Người dùng đã phê duyệt sửa {project_file}. Kích hoạt Goose CLI...")
                    from engine.tools.fix_self import run_goose_repair_loop
                    repaired, report = await run_goose_repair_loop(project_file, err_line)
                    if repaired:
                        log.info(
                            "🛡️ Self-Healing: Bản vá đã vượt kiểm tra cú pháp/import; "
                            "cần xác nhận runtime sau khi worker reload: %s",
                            project_file,
                        )
                        _last_fix_self_time = now
                    else:
                        log.warning(f"🛡️ Self-Healing: Tự sửa code thất bại: {project_file}")
                    break  # Chỉ xử lý sửa 1 file mỗi lần quét
    except Exception as e:
        log.error(f"Failed to run self-healing from logs: {e}", exc_info=True)


_watcher_task: Optional[asyncio.Task] = None

async def _self_healing_watcher_loop():
    log.info("🛡️ Self-Healing: Background watcher loop started.")
    from engine.core.activity_gate import wait_until_chat_idle
    while True:
        try:
            # Never scan or repair while a turn is live. This path calls the
            # same local LLM the user's reply is queued behind, and
            # request_repair_approval drains the live WebSocket's message queue
            # — which is how a background job ended up stealing the user's own
            # transcript out from under the main loop.
            await wait_until_chat_idle()
            await trigger_self_healing_from_logs()
        except Exception as e:
            log.warning(f"Self-Healing watcher error: {e}")
        await asyncio.sleep(60)  # Quét log định kỳ mỗi 60 giây

def start_self_healing_watcher():
    """Khởi động task chạy nền quét log định kỳ của Self-Healing."""
    global _watcher_task
    if _watcher_task is None:
        _watcher_task = asyncio.create_task(_self_healing_watcher_loop())
