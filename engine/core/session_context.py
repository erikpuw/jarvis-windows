"""Session id của lượt chat hiện tại (contextvar).

Đặt một lần khi vào phiên (WebSocket connect / đầu xử lý tin Telegram). `asyncio.to_thread` và task con thừa hưởng giá trị này,
nên các hàm lưu/đọc hội thoại dùng nó làm mặc định mà không cần truyền tham số qua router. Rỗng = không thuộc phiên nào (tin cũ, tiến trình nền).
"""
from contextvars import ContextVar

_current: ContextVar[str] = ContextVar("jarvis_session_id", default="")


def set_session(session_id: str) -> None:
    _current.set(session_id)


def get_session() -> str:
    return _current.get()
