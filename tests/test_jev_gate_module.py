import sys
from pathlib import Path

WORKSPACE = Path(r"E:\workspace\jarvis")
sys.path.insert(0, str(WORKSPACE))

from engine.turn import jev_gate


def test_jev_gate_module():
    assert jev_gate.is_available() is True, "Jev Gate phải ở trạng thái available"

    # Test câu chat
    is_chat, conf = jev_gate.classify_chat("Xin chào bạn, hôm nay thế nào?")
    print(f"Chat test: is_chat={is_chat}, conf={conf:.1%}")
    assert is_chat is True
    assert conf >= 0.85

    # Test câu tool
    is_chat, conf = jev_gate.classify_chat("Thời tiết Hà Nội hôm nay thế nào có mưa không?")
    print(f"Tool test: is_chat={is_chat}, conf={conf:.1%}")
    assert is_chat is False

    jev_gate.close()
    print("Test module jev_gate thành công!")


if __name__ == "__main__":
    test_jev_gate_module()
