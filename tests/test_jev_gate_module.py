"""Kiểm tra hoạt động của module Jev Gate (chạy live khi có model/server, skip khi ở CI)."""
import pytest

from engine.turn import jev_gate


@pytest.mark.skipif(
    not jev_gate.is_available(),
    reason="Jev model hoặc standalone server không có sẵn trong môi trường này (CI)",
)
def test_jev_gate_module_live():
    """Test thực tế phân loại chat/tool với model Jev thật nếu có sẵn."""
    # Test câu chat
    is_chat, conf = jev_gate.classify_chat("Xin chào bạn, hôm nay thế nào?")
    assert is_chat is True
    assert conf >= 0.85

    # Test câu tool
    is_chat, conf = jev_gate.classify_chat("Thời tiết Hà Nội hôm nay thế nào có mưa không?")
    assert is_chat is False

    jev_gate.close()
