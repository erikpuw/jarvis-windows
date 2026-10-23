"""Phiên chat web giữ nguyên ID khi WebSocket nối lại (iPhone ngắt socket khi thoát app nhưng giữ trang).

Lỗi cũ: mỗi kết nối WebSocket là một ID mới, nên vào lại app thì bong bóng chat cũ vẫn còn nhưng lịch sử
trong DB bị tách sang ID khác, và model mất ngữ cảnh. Đúng: client gửi ID phiên của trang (?session=web-xxxxxxxx),
server dùng lại ID đó (chỉ nhận đúng dạng), và nạp lại lịch sử của phiên đó cho lượt tiếp theo.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.core import session_context as sc  # noqa: E402


def test_resume_history_loads_only_chat_turns(monkeypatch):
    import engine.core.memory as memory

    seen = {}

    def fake_get_messages(limit=100, session_id=""):
        seen["args"] = (limit, session_id)
        return [
            {"role": "user", "content": "giá vàng hôm nay"},
            {"role": "assistant", "content": "| Vàng SJC | ... |"},
            {"role": "system", "content": "bỏ qua"},
        ]

    monkeypatch.setattr(memory, "get_messages", fake_get_messages)
    assert sc.resume_history("web-1a2b3c4d") == [
        {"role": "user", "content": "giá vàng hôm nay"},
        {"role": "assistant", "content": "| Vàng SJC | ... |"},
    ]
    assert seen["args"][1] == "web-1a2b3c4d"


def test_resume_history_never_raises(monkeypatch):
    import engine.core.memory as memory

    def boom(**_):
        raise RuntimeError("db locked")

    monkeypatch.setattr(memory, "get_messages", boom)
    assert sc.resume_history("web-1a2b3c4d") == []
