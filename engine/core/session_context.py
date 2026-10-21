"""Session id của lượt chat hiện tại (contextvar).

Đặt một lần khi vào phiên (WebSocket connect / đầu xử lý tin Telegram). `asyncio.to_thread` và task con thừa hưởng giá trị này,
nên các hàm lưu/đọc hội thoại dùng nó làm mặc định mà không cần truyền tham số qua router. Rỗng = không thuộc phiên nào (tin cũ, tiến trình nền).
"""
import logging
import re
import secrets
from contextvars import ContextVar

log = logging.getLogger(__name__)

_current: ContextVar[str] = ContextVar("jarvis_session_id", default="")
_current_user: ContextVar[str] = ContextVar("jarvis_user_id", default="admin")

# ID phiên chat web: trang tự sinh một lần lúc mở (frontend/src/ws.ts) và gửi lại mỗi lần socket nối lại
WS_SESSION_RE = re.compile(r"web-[0-9a-f]{8}")


def resolve_ws_session(requested: str | None) -> str:
    """ID phiên cho một kết nối WebSocket: dùng lại ID trang gửi lên (iPhone ngắt socket khi thoát app nhưng giữ trang),
    chỉ nhận đúng dạng web-xxxxxxxx; thiếu/sai dạng thì cấp ID mới."""
    if requested and WS_SESSION_RE.fullmatch(requested):
        return requested
    return f"web-{secrets.token_hex(4)}"


def resume_history(session_id: str, limit: int = 20, user_id: str | None = None) -> list[dict]:
    """Các lượt user/assistant đã lưu của phiên (rỗng nếu phiên mới hoặc DB lỗi), để kết nối nối lại tiếp đúng mạch."""
    try:
        from engine.core import memory
        current_uid = user_id if user_id is not None else get_current_user_id()
        try:
            rows = memory.get_messages(limit=limit, session_id=session_id, user_id=current_uid)
        except TypeError:
            rows = memory.get_messages(limit=limit, session_id=session_id)
    except Exception as exc:
        log.warning("Không nạp lại được lịch sử phiên %s: %s", session_id, exc)
        return []
    return [{"role": r["role"], "content": r["content"]} for r in rows if r.get("role") in ("user", "assistant")]


def set_session(session_id: str) -> None:
    _current.set(session_id)


def get_session() -> str:
    return _current.get()


def set_current_user_id(user_id: str) -> None:
    _current_user.set(user_id or "admin")


def get_current_user_id() -> str:
    return _current_user.get()


def is_user_admin(user_id: str | None = None) -> bool:
    """Kiem tra quyen Quan tri vien (Admin) cua user_id hoac phien hien hanh."""
    uid = (user_id if user_id is not None else get_current_user_id()) or "admin"
    if uid == "admin":
        return True
    try:
        from engine.core.memory import _get_db
        with _get_db() as conn:
            row = conn.execute("SELECT role FROM users WHERE id = ?", (uid,)).fetchone()
            if row and row["role"] == "admin":
                return True
    except Exception:
        pass
    return False

