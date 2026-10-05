# -*- coding: utf-8 -*-
"""
MemoryTree for Python — Quản lý bộ nhớ dài hạn dưới dạng thư mục Obsidian Wiki (Markdown).
"""

import os
import threading
import logging
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger("jarvis.memory_tree")

# Đường dẫn mặc định đến thư mục Wiki của Jarvis
WIKI_DIR = Path(__file__).parent.parent.parent / "data" / "wiki"

# Nhiều phiên cùng ghi nhật ký ngày: khóa việc kiểm tra tồn tại + ghi file để tiêu đề và liên kết tháng chỉ tạo một lần.
_digest_lock = threading.Lock()

def ensure_wiki_dirs():
    """Đảm bảo các thư mục lưu trữ wiki tồn tại."""
    try:
        os.makedirs(WIKI_DIR / "daily", exist_ok=True)
        os.makedirs(WIKI_DIR / "topics", exist_ok=True)
    except Exception as e:
        log.error(f"Failed to create wiki directories: {e}")


def daily_note_path(date_str: str) -> Path:
    """Return the canonical monthly Daily-note path for YYYY-MM-DD."""
    day = datetime.strptime(date_str, "%Y-%m-%d")
    return WIKI_DIR / "daily" / day.strftime("%m-%Y") / f"{date_str}.md"


def save_daily_digest(
    user_query: str, response_text: str, outcome_id: int | None = None
):
    """
    Ghi nhận hoạt động hội thoại vào file nhật ký ngày tương ứng.
    Định dạng lưu trữ tương thích hoàn toàn với Obsidian Wiki.
    Tự động liên kết với ngày hôm qua và ngày mai để tạo Graph chéo.
    """
    ensure_wiki_dirs()
    
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M:%S")
    month_key = now.strftime("%m-%Y")
    month_dir = WIKI_DIR / "daily" / month_key
    month_dir.mkdir(parents=True, exist_ok=True)
    daily_file = daily_note_path(today_str)
    month_file = month_dir / f"Tháng {month_key}.md"

    yesterday = now - timedelta(days=1)
    yesterday_link = (
        f"daily/{yesterday.strftime('%m-%Y')}/{yesterday.strftime('%Y-%m-%d')}"
    )
    month_link = f"daily/{month_key}/Tháng {month_key}"

    # Chuẩn bị nội dung Markdown
    log_entry = (
        f"### [{time_str}] Hội thoại với người dùng\n"
        f"- **User**: {user_query.strip()}\n"
        f"- **JARVIS**: {response_text.strip()}\n\n"
    )
    
    try:
        with _digest_lock:
            # Nếu file chưa tồn tại, tạo mới kèm theo tiêu đề và liên kết song phương Obsidian
            file_exists = daily_file.exists()
            with open(daily_file, "a", encoding="utf-8") as f:
                if not file_exists:
                    f.write(f"# Nhật ký hoạt động ngày {today_str}\n")
                    f.write("Tags: #daily #activity\n\n")
                    daily_nav = []
                    if daily_note_path(yesterday.strftime("%Y-%m-%d")).exists():
                        daily_nav.append(f"← [[{yesterday_link}|Ngày hôm trước]]")
                    daily_nav.append(f"[[{month_link}|Tổng quan tháng]]")
                    f.write(" | ".join(daily_nav) + "\n\n")
                f.write(log_entry)

            day_link = f"[[daily/{month_key}/{today_str}|{today_str}]]"
            if month_file.exists():
                month_content = month_file.read_text(encoding="utf-8")
            else:
                previous_month = (now.replace(day=1) - timedelta(days=1)).strftime("%m-%Y")
                previous_month_file = (
                    WIKI_DIR / "daily" / previous_month / f"Tháng {previous_month}.md"
                )
                month_nav = []
                if previous_month_file.exists():
                    month_nav.append(
                        f"← [[daily/{previous_month}/Tháng {previous_month}|Tháng trước]]"
                    )
                month_nav.append("[[topics/Công Cụ|Công cụ]]")
                month_content = (
                    f"# Hội thoại tháng {month_key}\n"
                    f"Tags: #daily #monthly\n\n"
                    f"{' | '.join(month_nav)}\n\n"
                    "## Các ngày\n"
                )
            if day_link not in month_content:
                month_content = month_content.rstrip() + f"\n- {day_link}\n"
                month_file.write_text(month_content, encoding="utf-8")

        log.info(f"Daily digest saved to {daily_file.relative_to(WIKI_DIR)}")
        
        # Gọi WikiSync tự động để nạp ngay vào Semantic Memory
        try:
            from engine.core.wiki_sync import sync_wiki_to_semantic_memory
            sync_wiki_to_semantic_memory()
        except Exception as sync_err:
            log.warning(f"Failed to auto-sync wiki on daily digest: {sync_err}")
            
    except Exception as e:
        log.error(f"Failed to save daily digest: {e}")
