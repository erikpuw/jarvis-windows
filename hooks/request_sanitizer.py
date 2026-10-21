"""
request-sanitizer — Vệ sinh đầu vào người dùng trước khi gửi lên LLM.
Tránh crash do ký tự lạ, null byte, control char, hoặc message quá dài.
"""

import logging
import re

log = logging.getLogger("jarvis.hooks.request_sanitizer")

MAX_TEXT_LEN = 10000
MAX_HISTORY_LEN = 5000

# Control characters to strip (keep \n \r \t)
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# Zero-width / invisible Unicode
_INVISIBLE_RE = re.compile(r"[\u200b-\u200f\u2028-\u202f\u2060-\u2064\ufeff]")
# Excessive whitespace (3+ newlines → 2)
_EXCESS_NEWLINES_RE = re.compile(r"\n{3,}")


def _sanitize_text(text: str) -> str:
    if not text:
        return text
    text = _CONTROL_CHARS_RE.sub("", text)
    text = _INVISIBLE_RE.sub("", text)
    text = _EXCESS_NEWLINES_RE.sub("\n\n", text)
    text = text.strip()
    if len(text) > MAX_TEXT_LEN:
        halfway = MAX_TEXT_LEN // 2
        text = text[:halfway] + "\n\n...[truncated]...\n\n" + text[-halfway:]
    return text


def _sanitize_msg(msg: dict) -> dict:
    content = msg.get("content", "")
    if content and isinstance(content, str):
        content = _CONTROL_CHARS_RE.sub("", content)
        content = _INVISIBLE_RE.sub("", content)
        if len(content) > MAX_HISTORY_LEN:
            content = content[:MAX_HISTORY_LEN] + "\n...[truncated]..."
        msg["content"] = content
    return msg


def on_message_receive(ctx: dict) -> dict:
    text = ctx.get("text", "")
    if text:
        before = len(text)
        text = _sanitize_text(text)
        if len(text) != before:
            log.info(f"Sanitized user text: {before} → {len(text)} chars")
        ctx["text"] = text

    history = ctx.get("conversation_history", [])
    if history:
        sanitized = [_sanitize_msg(m) for m in history]
        ctx["conversation_history"] = sanitized

    return ctx
