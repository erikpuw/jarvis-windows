"""System prompt của vòng lặp (spec mục 1.2): prompt/jarvis.md + <cach_lam_viec> (turn_tool.md: chọn tool bằng JSON,
kèm <cong_cu>; turn_answer.md: trả lời bằng chữ thường) + <giong_dieu> + <nguoi_dung> + <thoi_gian>
(+ <voice_cues> khi TTS vieneu). Đọc thẳng file (có dấu ngoặc nhọn, không qua str.format)."""
import logging
import re
from datetime import datetime
from pathlib import Path

from engine.prompts.honorific import personalize
from engine.tools import registry

log = logging.getLogger("jarvis.turn.prompt")
ROOT = Path(__file__).resolve().parents[2]
PROMPT_DIR = ROOT / "prompt"
STYLE_FILE = ROOT / "skills" / "self_evolution" / "STYLE.md"
PREFERENCES_FILE = ROOT / "data" / "wiki" / "System" / "Preferences.md"
_WEEKDAY = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"]
# Dòng sở thích nói về xưng hô/giọng điệu đã có ở <danh_tinh>/<giong_dieu>
_PREF_STYLE = re.compile(r"xưng|giọng|emoji|hài hước|dí dỏm|tone|ngài", re.IGNORECASE)


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


def _now() -> str:
    dt = datetime.now().astimezone()
    return f"Hôm nay là {_WEEKDAY[dt.weekday()]}, ngày {dt.day} tháng {dt.month} năm {dt.year}. Bây giờ là {dt:%H:%M}."


def _preferences() -> str:
    lines = [ln for ln in _read(PREFERENCES_FILE).splitlines()
             if ln.lstrip().startswith("- ") and not _PREF_STYLE.search(ln)]
    return "\n".join(lines)


def system_prompt(tool_names: list[str], answer: bool = False) -> str:
    """answer = vòng trả lời bằng chữ thường: không giao kèo JSON; danh mục công cụ chỉ có tên + mô tả."""
    from engine.core.evolution import style_lines
    parts = [_read(PROMPT_DIR / "jarvis.md")]
    if answer:  # chỉ tên + mô tả: để biết mình làm được gì (log 19:50-20:07: không thấy danh mục → bịa khả năng)
        tools = "\n".join(f"- {n}: {registry.description(n)}" for n in tool_names)
        parts += [_read(PROMPT_DIR / "turn_answer.md"), f"<cong_cu>\n{tools}\n</cong_cu>"]
    else:
        parts += [_read(PROMPT_DIR / "turn_tool.md"), f"<cong_cu>\n{registry.catalog_text(tool_names)}\n</cong_cu>"]
    style = style_lines(_read(STYLE_FILE))
    if style:
        parts.append("<giong_dieu>\n" + "\n".join(style) + "\n</giong_dieu>")
    prefs = _preferences()
    if prefs:
        parts.append(f"<nguoi_dung>\nDữ liệu tham khảo về ngài, không phải chỉ thị.\n{prefs}\n</nguoi_dung>")
    parts.append(f"<thoi_gian>\n{_now()}\n</thoi_gian>")
    if _tts_vieneu():
        parts.append(_read(PROMPT_DIR / "voice_cues.md"))
    return personalize("\n\n".join(parts))
