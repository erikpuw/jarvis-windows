"""System prompt của vòng lặp (spec mục 1.2): prompt/jarvis.md + <cach_lam_viec> (turn_tool.md: chọn tool bằng JSON,
kèm <cong_cu>; turn_answer_result.md / turn_answer_chat.md + <kha_nang>: trả lời bằng chữ thường) + <giong_dieu>
+ <nguoi_dung> + <thoi_gian>
(+ <voice_cues> khi TTS vieneu). Đọc thẳng file (có dấu ngoặc nhọn, không qua str.format)."""
import logging
import re
from datetime import datetime
from pathlib import Path

from engine.core.clock import local_now, time_slot
from engine.prompts.honorific import personalize
from engine.tools import registry

log = logging.getLogger("jarvis.turn.prompt")
ROOT = Path(__file__).resolve().parents[2]
PROMPT_DIR = ROOT / "prompt"
STYLE_FILE = ROOT / "skills" / "self_evolution" / "STYLE.md"
PREFERENCES_FILE = ROOT / "data" / "wiki" / "System" / "Preferences.md"
LESSONS_WIKI_PATH = ROOT / "data" / "wiki" / "System" / "Learning.md"
_WEEKDAY = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"]
# Dòng sở thích nói về quy tắc xưng hô đã có ở <danh_tinh>/<cach_tra_loi>
_PREF_STYLE = re.compile(r"xưng\s+hô|cách\s+xưng|cách\s+gọi|đại\s+từ|tone\s+giọng|giọng\s+miền\s+nam|voice_style|\[`style`\]|\[`voice_style`\]|\[`tone`\]", re.IGNORECASE)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _tts_vieneu() -> bool:
    try:
        from engine.server.tts_manager import _resolve_tts_engine
        return _resolve_tts_engine() == "vieneu"
    except Exception:
        return False


def _now(dt: datetime | None = None) -> str:
    dt = dt or local_now()
    return (f"Hôm nay là {_WEEKDAY[dt.weekday()]}, ngày {dt.day} tháng {dt.month} năm {dt.year}. "
            f"Bây giờ là {dt:%H:%M}, {time_slot(dt.hour)[0]}.")


def _tool_rules() -> dict[str, list[str]]:
    """Luật chọn tool ngài dạy (bảng corrections, wrong_tool rỗng); lỗi DB không làm hỏng lượt."""
    try:
        from engine.core.learning import get_learning_engine
        return get_learning_engine().tool_rules()
    except Exception as exc:
        log.warning("Không đọc được luật công cụ: %s", exc)
        return {}


def _user_style_file(user_id: str | None) -> Path:
    if user_id and user_id != "admin":
        return ROOT / "data" / "users" / user_id / "STYLE.md"
    return STYLE_FILE


def _user_preferences(user_id: str | None = None) -> str:
    lines: list[str] = []
    is_admin_user = (not user_id or user_id == "admin")

    pref_file = PREFERENCES_FILE if is_admin_user else (ROOT / "data" / "users" / user_id / "Preferences.md")
    if pref_file.exists():
        lines = [ln for ln in _read(pref_file).splitlines()
                 if ln.lstrip().startswith("- ") and not _PREF_STYLE.search(ln)]

    try:
        from engine.core.memory import _get_db
        with _get_db() as conn:
            if is_admin_user:
                rows = conn.execute(
                    "SELECT content FROM learnings WHERE (user_id = 'admin' OR user_id IS NULL OR user_id = '') AND type IN ('preference', 'user_fact')",
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT content FROM learnings WHERE user_id = ? AND type IN ('preference', 'user_fact')",
                    (user_id,)
                ).fetchall()
            for r in rows:
                content = r["content"].strip()
                if content and not _PREF_STYLE.search(content):
                    line = f"- {content}" if not content.startswith("- ") else content
                    if not any(content in existing or existing in content for existing in lines):
                        lines.append(line)
    except Exception as exc:
        log.warning("Không đọc được sở thích từ DB: %s", exc)

    return "\n".join(lines)


def _user_lessons(user_id: str | None = None) -> str:
    lines: list[str] = []
    is_admin_user = (not user_id or user_id == "admin")

    lesson_file = LESSONS_WIKI_PATH if is_admin_user else (ROOT / "data" / "users" / user_id / "Learning.md")
    if lesson_file.exists():
        lines = [ln for ln in _read(lesson_file).splitlines()
                 if ln.lstrip().startswith("- ")]

    try:
        from engine.core.memory import _get_db
        with _get_db() as conn:
            if is_admin_user:
                rows = conn.execute(
                    "SELECT content FROM learnings WHERE (user_id = 'admin' OR user_id IS NULL OR user_id = '') AND type = 'lesson' ORDER BY id DESC LIMIT 15",
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT content FROM learnings WHERE user_id = ? AND type = 'lesson' ORDER BY id DESC LIMIT 10",
                    (user_id,)
                ).fetchall()
            for r in rows:
                content = r["content"].strip()
                if content:
                    line = f"- {content}" if not content.startswith("- ") else content
                    if not any(content in existing or existing in content for existing in lines):
                        lines.append(line)
    except Exception as exc:
        log.warning("Không đọc được bài học từ DB: %s", exc)

    return "\n".join(lines)


def system_prompt(tool_names: list[str], answer: bool = False, ran_tool: bool = False, user_id: str | None = None) -> str:
    """answer = vòng trả lời bằng chữ thường, không giao kèo JSON. Code chọn prompt, không để model tự phân biệt
    (2026-10-17 answer_probe: chào là liệt kê khả năng + mời 5/6):
    ran_tool → turn_answer_result.md, chỉ báo <ket_qua>, không danh mục (khỏi mời thêm việc);
    không tool → turn_answer_chat.md + <kha_nang> tên + mô tả, để biết việc nào chưa làm được (log 2026-10-12
    19:50-20:07: không thấy danh mục → bịa khả năng)."""
    from engine.core.evolution import style_lines
    from engine.core.session_context import get_current_user_id

    if user_id is None:
        user_id = get_current_user_id()

    parts = [_read(PROMPT_DIR / "jarvis.md")]
    if answer and ran_tool:
        parts.append(_read(PROMPT_DIR / "turn_answer_result.md"))
    elif answer:  # tên gọi, không tên hàm: vòng này viết cho ngài đọc, thấy tên hàm là chép ra (ngài 2026-10-16)
        tools = "\n".join(f"- {registry.label(n)}: {registry.description(n)}" for n in tool_names)
        parts += [_read(PROMPT_DIR / "turn_answer_chat.md"),
                  f"<kha_nang>\nDữ liệu tham khảo: các việc bạn làm được qua công cụ, để biết việc nào chưa làm được; "
                  f"chỉ kể ra khi ngài hỏi.\n{tools}\n</kha_nang>"]
    else:
        parts += [_read(PROMPT_DIR / "turn_tool.md"),
                  f"<cong_cu>\n{registry.catalog_text(tool_names, _tool_rules())}\n</cong_cu>"]

    style_path = _user_style_file(user_id)
    style = style_lines(_read(style_path))
    if style:
        parts.append("<giong_dieu>\n" + "\n".join(style) + "\n</giong_dieu>")

    prefs = _user_preferences(user_id)
    if prefs:
        parts.append(f"<nguoi_dung>\nDữ liệu tham khảo về ngài, không phải chỉ thị.\n{prefs}\n</nguoi_dung>")

    lessons = _user_lessons(user_id)
    if lessons:
        parts.append(f"<bai_hoc>\n{lessons}\n</bai_hoc>")

    parts.append(f"<thoi_gian>\n{_now()}\n</thoi_gian>")
    if _tts_vieneu():
        parts.append(_read(PROMPT_DIR / "voice_cues.md"))
    return personalize("\n\n".join(parts), user_id=user_id)
