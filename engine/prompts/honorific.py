"""Xưng hô do Settings cấu hình (HONORIFIC, USER_NAME).

Prompt và chuỗi dựng sẵn trong code viết cứng "ngài" / "thưa ngài" / "erikpuw". Thay đúng ba cụm này
ở các điểm tập trung (prompts.load, text_chunk gửi UI, prepare_tts_text); mặc định thì không đổi gì.
ponytail: thay theo chuỗi, chưa phủ tin nhắn Telegram và văn bản ghi ra file (ghi chú, wiki).
"""
import os
import re

_DEFAULT_PRONOUN = "ngài"
_DEFAULT_NAME = "erikpuw"
# Ngài 2026-10-15: tạm khoá — HONORIFIC trong .env ("bro") không được áp; luôn "ngài". Mở lại: đặt False.
HONORIFIC_LOCKED = True
# Ngài 2026-10-15: tạm khoá cả USER_NAME (.env) — dùng tên có sẵn trong prompt. Mở lại: đặt False.
USER_NAME_LOCKED = True


def _pronoun() -> str:
    if HONORIFIC_LOCKED:
        return _DEFAULT_PRONOUN
    value = os.environ.get("HONORIFIC", "").strip()
    if value.lower().startswith("thưa "):
        value = value[5:].strip()
    return value or _DEFAULT_PRONOUN


def _name() -> str:
    if USER_NAME_LOCKED:
        return _DEFAULT_NAME
    return os.environ.get("USER_NAME", "").strip() or _DEFAULT_NAME


def personalize(text: str) -> str:
    pronoun, name = _pronoun(), _name()
    low = pronoun.lower()
    if low == _DEFAULT_PRONOUN and name == _DEFAULT_NAME:
        return text
    if low == "bạn":  # luật cũ "không dùng bạn" sẽ tự mâu thuẫn khi đại từ chính là "bạn"
        text = re.sub(r"\s*\((?:KHÔNG|không) dùng [^)]*\)", "", text)
        text = re.sub(r",\s*(?:KHÔNG|không) dùng [“\"']bạn[”\"']", "", text)
    cap = low[:1].upper() + low[1:]
    text = re.sub(r"(?<!\w)Thưa ngài(?!\w)", f"Thưa {low}", text)
    text = re.sub(r"(?<!\w)thưa ngài(?!\w)", f"thưa {low}", text)
    text = re.sub(r"(?<!\w)Ngài(?!\w)", cap, text)
    text = re.sub(r"(?<!\w)ngài(?!\w)", low, text)
    return text.replace(_DEFAULT_NAME, name)


def personalize_payload(data: dict) -> dict:
    """Chữ hiển thị gửi tới UI (text_chunk); loại tin khác giữ nguyên."""
    if data.get("type") == "text_chunk" and isinstance(data.get("text"), str):
        return {**data, "text": personalize(data["text"])}
    return data


def trailing_honorific_re() -> re.Pattern:
    """Dòng riêng 'Thưa …' ở cuối câu cũ trong lịch sử: đại từ mặc định và đại từ đang cấu hình."""
    words = "|".join(sorted({re.escape(_DEFAULT_PRONOUN), re.escape(_pronoun().lower())}))
    return re.compile(rf"\s*\n\s*thưa (?:{words})[.!]?\s*$", re.IGNORECASE)
