"""Kiểm tra hoạt động của module Jev Gate (chạy live khi có model/server, skip khi ở CI)."""
import os
from unittest.mock import MagicMock

import pytest

from engine.turn import jev_gate


@pytest.mark.skipif(
    os.getenv("JEV_LIVE_TESTS") != "1" or not jev_gate.is_available(),
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


def test_local_engine_defaults_to_cpu(monkeypatch, tmp_path):
    """Không đặt JEV_USE_CPU thì engine local chạy CPU (n_gpu_layers=0), dành VRAM cho LLM/TTS."""
    jev_gate.close()
    monkeypatch.delenv("JEV_USE_CPU", raising=False)
    picked = {}
    monkeypatch.setattr(jev_gate, "find_jev_binary", lambda use_cpu=False: picked.setdefault("cpu", use_cpu) and tmp_path)
    monkeypatch.setattr(jev_gate, "find_jev_gguf", lambda: tmp_path)
    constructor = MagicMock()
    monkeypatch.setattr(jev_gate, "JevStyleDecisionGGUF", constructor)
    try:
        assert jev_gate._get_engine() is constructor.return_value
        assert picked["cpu"] is True
        assert constructor.call_args.kwargs["n_gpu_layers"] == 0
    finally:
        jev_gate._ENGINE = None


@pytest.mark.parametrize("answer, conf, shows, hides", [
    ("chat", 0.567, ["CHAT", "56.7%", "router thường"], ["TOOL", "BYPASS"]),  # chat chưa đủ chắc
    ("chat", 0.979, ["CHAT", "97.9%", "BYPASS"], ["TOOL", "router"]),
    ("tool", 0.956, ["TOOL", "95.6%", "router chọn tool"], ["CHAT", "BYPASS"]),
])
def test_decision_line_shows_real_answer(capsys, answer, conf, shows, hides):
    """Dòng in phải ghi đúng lựa chọn của Jev, không gọi mọi trường hợp không bypass là TOOL."""
    jev_gate.print_decision("remote", "chưa cần đâu", answer, conf, 1070.3, 0.85)
    out = capsys.readouterr().out
    for word in shows:
        assert word in out
    for word in hides:
        assert word not in out
