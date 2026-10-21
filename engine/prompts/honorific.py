"""Xưng hô do Settings cấu hình (HONORIFIC, USER_NAME).

Prompt và chuỗi dựng sẵn trong code viết cứng "ngài" / "thưa ngài" / "erikpuw". Thay đúng ba cụm này
ở các điểm tập trung (prompts.load, text_chunk gửi UI, prepare_tts_text); mặc định thì không đổi gì.
Admin đọc từ .env, User (Member) nạp từ hồ sơ tài khoản (users table).
"""
import logging
import os
import re

log = logging.getLogger("jarvis.honorific")

_DEFAULT_PRONOUN = "ngài"
_DEFAULT_NAME = "erikpuw"
# Mở khóa: Admin đọc cấu hình từ .env, Member đọc cấu hình từ DB
HONORIFIC_LOCKED = False
USER_NAME_LOCKED = False


def get_user_profile(user_id: str | None = None) -> dict:
    """Lấy thông tin (user_pronoun, ai_pronoun, name, role) cho user_id.
    - user_id là None hoặc 'admin': đọc từ .env (HONORIFIC, USER_NAME), mặc định ('ngài', 'tôi', 'erikpuw').
    - user_id của member: truy vấn bảng users trong jarvis.db.
    """
    if not user_id:
        try:
            from engine.core.session_context import get_current_user_id
            user_id = get_current_user_id()
        except Exception:
            user_id = "admin"

    if not user_id or user_id == "admin":
        honorific = ""
        if not HONORIFIC_LOCKED:
            h = os.environ.get("HONORIFIC", "").strip()
            if h.lower().startswith("thưa "):
                h = h[5:].strip()
            honorific = h
        user_pronoun = honorific or _DEFAULT_PRONOUN

        user_name = ""
        if not USER_NAME_LOCKED:
            user_name = os.environ.get("USER_NAME", "").strip()
        name = user_name or _DEFAULT_NAME

        return {
            "user_pronoun": user_pronoun,
            "ai_pronoun": "tôi",
            "name": name,
            "role": "admin",
        }

    # Member user
    try:
        from engine.core.memory import _get_db
        with _get_db() as conn:
            row = conn.execute(
                "SELECT id, username, display_name, user_pronoun, ai_pronoun FROM users WHERE id = ?",
                (user_id,)
            ).fetchone()
            if row:
                name = (row["display_name"] or row["username"] or user_id).strip()
                u_pronoun = (row["user_pronoun"] or "Anh").strip()
                if u_pronoun.lower().startswith("thưa "):
                    u_pronoun = u_pronoun[5:].strip()
                ai_pronoun = (row["ai_pronoun"] or "Jarvis").strip()
                return {
                    "user_pronoun": u_pronoun or "Anh",
                    "ai_pronoun": ai_pronoun or "Jarvis",
                    "name": name,
                    "role": "member",
                }
    except Exception as e:
        log.warning("get_user_profile failed for %s: %s", user_id, e)

    return {
        "user_pronoun": "Anh",
        "ai_pronoun": "Jarvis",
        "name": user_id,
        "role": "member",
    }


def _pronoun(user_id: str | None = None) -> str:
    return get_user_profile(user_id)["user_pronoun"]


def _name(user_id: str | None = None) -> str:
    return get_user_profile(user_id)["name"]


def _ai_pronoun(user_id: str | None = None) -> str:
    return get_user_profile(user_id)["ai_pronoun"]


def personalize(text: str, user_id: str | None = None) -> str:
    profile = get_user_profile(user_id)
    pronoun = profile["user_pronoun"]
    name = profile["name"]
    ai_pronoun = profile["ai_pronoun"]

    low = pronoun.lower()
    cap = low[:1].upper() + low[1:]

    # Nếu là admin và giá trị trùng mặc định thì không cần thay thế
    if profile.get("role") == "admin" and low == _DEFAULT_PRONOUN and name == _DEFAULT_NAME and ai_pronoun == "tôi":
        return text

    if low == "bạn":  # luật cũ "không dùng bạn" sẽ tự mâu thuẫn khi đại từ chính là "bạn"
        text = re.sub(r"\s*\((?:KHÔNG|không) dùng [^)]*\)", "", text)
        text = re.sub(r",\s*(?:KHÔNG|không) dùng [“\"']bạn[”\"']", "", text)

    # Nếu AI xưng hô khác "tôi" (ví dụ "Em" hoặc "Jarvis")
    if ai_pronoun and ai_pronoun.lower() != "tôi":
        text = re.sub(r'Xưng hô với người dùng là "tôi"', f'Xưng hô với người dùng là "{ai_pronoun}"', text)
        text = re.sub(r'xưng hô với người dùng là "tôi"', f'xưng hô với người dùng là "{ai_pronoun}"', text)
        text = re.sub(r'Xưng "tôi"', f'Xưng "{ai_pronoun}"', text)
        text = re.sub(r'xưng "tôi"', f'xưng "{ai_pronoun}"', text)

    text = re.sub(r'(?<!\w)gọi người dùng là "ngài"', f'gọi người dùng là "{low}"', text)
    text = re.sub(r'(?<!\w)gọi người dùng là “ngài”', f'gọi người dùng là “{low}”', text)
    text = re.sub(r"(?<!\w)Thưa ngài(?!\w)", f"Thưa {low}", text)
    text = re.sub(r"(?<!\w)thưa ngài(?!\w)", f"thưa {low}", text)
    text = re.sub(r"(?<!\w)Ngài(?!\w)", cap, text)
    text = re.sub(r"(?<!\w)ngài(?!\w)", low, text)
    text = text.replace(_DEFAULT_NAME, name)
    return text


def personalize_payload(data: dict, user_id: str | None = None) -> dict:
    """Chữ hiển thị gửi tới UI (text_chunk); loại tin khác giữ nguyên."""
    if data.get("type") == "text_chunk" and isinstance(data.get("text"), str):
        return {**data, "text": personalize(data["text"], user_id=user_id)}
    return data


def trailing_honorific_re(user_id: str | None = None) -> re.Pattern:
    """Dòng riêng 'Thưa …' ở cuối câu cũ trong lịch sử: đại từ mặc định và đại từ đang cấu hình."""
    words = "|".join(sorted({re.escape(_DEFAULT_PRONOUN), re.escape(_pronoun(user_id).lower())}))
    return re.compile(rf"\s*\n\s*thưa (?:{words})[.!]?\s*$", re.IGNORECASE)
