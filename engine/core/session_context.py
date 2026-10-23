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

# ID phiên chat web: server cấp ID, trang gửi lại ID đó mỗi lần socket nối lại (frontend/src/ws.ts)
WS_SESSION_RE = re.compile(r"web-[0-9a-f]{8}")


def _owner_of(user_id: str | None) -> str:
    """Chủ của một dòng: rỗng/NULL = admin (cùng quy tắc với _owner_clause ở sessions_api)."""
    return user_id or "admin"


def ws_user_for_token(token: str) -> str | None:
    """user_id của token đăng nhập; None khi token rỗng hoặc lạ (voice_handler đóng 1008). Lỗi DB được ném ra (voice_handler đóng 1011)."""
    if not token:
        return None
    from engine.core.memory import _get_db
    with _get_db() as conn:
        row = conn.execute("SELECT user_id FROM user_tokens WHERE token = ?", (token,)).fetchone()
    return (row[0] or None) if row else None


def claim_ws_session(requested: str | None, user_id: str) -> str:
    """ID phiên cho một kết nối WebSocket: dùng lại ID trang gửi lên (iPhone ngắt socket khi thoát app nhưng giữ trang)
    khi đúng dạng web-xxxxxxxx và không có thiết bị/tin nhắn nào của người khác; còn lại cấp ID mới."""
    if not (requested and WS_SESSION_RE.fullmatch(requested)):
        return f"web-{secrets.token_hex(4)}"
    try:
        from engine.core.memory import _get_db
        with _get_db() as conn:
            rows = conn.execute(
                "SELECT user_id FROM session_devices WHERE session_id = ? "
                "UNION ALL SELECT user_id FROM messages WHERE session_id = ?",
                (requested, requested),
            ).fetchall()
    except Exception as exc:
        log.warning("Không kiểm tra được chủ phiên %s: %s", requested, exc)
        return f"web-{secrets.token_hex(4)}"
    owners = {_owner_of(r[0]) for r in rows}
    if owners - {_owner_of(user_id)}:
        return f"web-{secrets.token_hex(4)}"
    return requested


_TITLE_LEAD = re.compile(r"^\s*(?:#{1,6}\s+|>\s*|[-*+]\s+|\d+[.)]\s+)")
_TITLE_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
# **đậm**, __đậm__, *nghiêng*, _nghiêng_ (chỉ khi bao quanh một từ, để my_var giữ nguyên)
_TITLE_EMPHASIS = re.compile(r"(\*\*|__)(\S.*?\S|\S)\1|\*(\S.*?\S|\S)\*|(?<!\w)_(\S.*?\S|\S)_(?!\w)")


def session_title(text: str, limit: int = 48) -> str:
    """Tên phiên trên thanh bên: dòng đầu, bỏ tiền tố @lệnh hoặc /lệnh, dấu markdown đầu dòng, cặp nhấn mạnh, backtick và link;
    cắt ở khoảng trắng ≤ limit rồi thêm …."""
    line = next((ln for ln in (text or "").splitlines() if ln.strip()), "")
    line = re.sub(r"^\s*[@/]\S+", "", line)
    line = _TITLE_LEAD.sub("", line)
    line = _TITLE_LINK.sub(lambda m: m.group(1), line)
    line = _TITLE_EMPHASIS.sub(lambda m: m.group(2) or m.group(3) or m.group(4), line)
    line = " ".join(line.replace("`", "").split())
    if not line:
        return "Phiên trống"
    if len(line) <= limit:
        return line
    cut = line[:limit]
    if line[limit] != " ":  # không nằm sát khoảng trắng: bỏ phần từ bị cắt dở
        space = cut.rfind(" ")
        if space > 0:
            cut = cut[:space]
    return cut + "…"


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

