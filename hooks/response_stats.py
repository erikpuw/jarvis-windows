"""
Hook: theo dõi độ dài phản hồi của Jarvis (ước lượng token) để phát hiện sớm
câu trả lời bất thường dài/tốn token — không sửa nội dung, chỉ log cảnh báo.

Bắn trên ON_RESPONSE_GENERATE, sau khi Jarvis đã trả lời xong (server.py:493-500),
ctx có sẵn 'user_text' và 'response_text'.
"""

import logging

log = logging.getLogger("jarvis.hooks.response_stats")

__description__ = "Log/cảnh báo khi phản hồi của Jarvis dài bất thường (ước lượng token)."

# Ngưỡng cảnh báo: ~3000 token ước lượng cho một câu trả lời là khá dài với
# use-case trợ lý cá nhân (chat/tool call), thường là dấu hiệu trả lời lan man.
WARN_TOKEN_THRESHOLD = 3000

_response_count = 0
_total_estimated_tokens = 0


def _estimate_tokens(text: str) -> int:
    # Cùng công thức ước lượng đang dùng trong skill_manager.py (~4 ký tự/token
    # cho tiếng Việt) để số liệu nhất quán giữa các module.
    return len(text) // 4 + 1 if text else 0


def on_response_generate(ctx: dict) -> dict:
    global _response_count, _total_estimated_tokens

    response_text = ctx.get("response_text", "") or ""
    user_text = ctx.get("user_text", "") or ""

    resp_tokens = _estimate_tokens(response_text)
    _response_count += 1
    _total_estimated_tokens += resp_tokens
    avg_tokens = _total_estimated_tokens / _response_count

    log.info(
        "[response_stats] #%d ~%d token phản hồi (câu hỏi ~%d token) | trung bình phiên: ~%.0f token/phản hồi",
        _response_count, resp_tokens, _estimate_tokens(user_text), avg_tokens,
    )

    if resp_tokens > WARN_TOKEN_THRESHOLD:
        log.warning(
            "[response_stats] Phản hồi #%d ước lượng ~%d token (> ngưỡng %d) — có thể đang trả lời lan man, nên xem lại.",
            _response_count, resp_tokens, WARN_TOKEN_THRESHOLD,
        )

    return ctx
