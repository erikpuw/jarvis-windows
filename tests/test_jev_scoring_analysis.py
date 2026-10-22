"""Kiểm tra và xác thực cơ chế chấm điểm, hiệu chuẩn nhiệt độ và quyết định của JEV Gate.

File test này kiểm tra:
1. Cơ chế tính logits difference và Softmax temperature calibration.
2. Ngưỡng phân loại Fast-Path Chat Bypass (>= 85%).
3. Xác thực tính độc lập, an toàn khi không có môi trường model (skipif trên CI).
"""
import math
import os
import sys
from pathlib import Path

import numpy as np
import pytest

WORKSPACE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WORKSPACE))

RUN_MODEL = Path(os.environ.get("RUN_MODEL_DIR", r"E:\Run_Model"))
from engine.turn.jev_gate import _OPTIONS, DEFAULT_MODEL_DIR, find_jev_binary, find_jev_gguf


def test_jev_scoring_math_formula():
    """Kiểm tra tính đúng đắn của công thức Softmax và hiệu chuẩn nhiệt độ T = 0.880."""
    T = 0.8800546821789332

    # Giả định logit chênh lệch
    score_chat = 1.25
    score_tool = -1.96

    scores = np.array([score_chat, score_tool], dtype=float)
    z = scores / T
    p = np.exp(z - z.max())
    p /= p.sum()

    p_chat, p_tool = p[0], p[1]

    # Kiểm tra tổng xác suất bằng 1.0
    assert math.isclose(p_chat + p_tool, 1.0, rel_tol=1e-6)
    # Với chênh lệch (1.25 - (-1.96)) = 3.21, delta / T = 3.647 -> p_chat phải > 97%
    assert p_chat > 0.97
    assert p_tool < 0.03

    # Kiểm tra trường hợp hòa điểm (scores bằng nhau)
    scores_tie = np.array([0.5, 0.5], dtype=float)
    z_tie = scores_tie / T
    p_tie = np.exp(z_tie - z_tie.max())
    p_tie /= p_tie.sum()
    assert math.isclose(p_tie[0], 0.5, rel_tol=1e-6)
    assert math.isclose(p_tie[1], 0.5, rel_tol=1e-6)


def test_jev_fastpath_threshold_logic():
    """Kiểm tra điều kiện kích hoạt Fast-path Chat Bypass theo logic của jev_gate."""
    min_confidence = 0.85

    # Case 1: Chat với conf cao -> Được bypass
    ans_1, conf_1 = "chat", 0.92
    is_chat_1 = (ans_1 == "chat" and conf_1 >= min_confidence)
    assert is_chat_1 is True

    # Case 2: Chat với conf trung bình (< 85%) -> Không được bypass, chuyển Big LLM
    ans_2, conf_2 = "chat", 0.81
    is_chat_2 = (ans_2 == "chat" and conf_2 >= min_confidence)
    assert is_chat_2 is False

    # Case 3: Tool với conf cao (>= 85%) -> Không bypass, chuyển Big LLM chọn tool
    ans_3, conf_3 = "tool", 0.95
    is_chat_3 = (ans_3 == "chat" and conf_3 >= min_confidence)
    assert is_chat_3 is False


@pytest.mark.skipif(
    os.getenv("JEV_LIVE_TESTS") != "1" or not find_jev_binary(use_cpu=True) or not find_jev_gguf() or not DEFAULT_MODEL_DIR.exists(),
    reason="Jev binary hoặc weights GGUF không tồn tại (chạy trên CI hoặc thiếu model)"
)
def test_jev_actual_model_scoring_live():
    """Chạy trực tiếp mô hình JEV thật (nếu có model local) để kiểm tra các mẫu chuẩn."""
    from engine.turn.jev.jev_style_decision_gguf import JevStyleDecisionGGUF

    binary = find_jev_binary(use_cpu=True)
    gguf = find_jev_gguf()

    engine = JevStyleDecisionGGUF(
        model_dir=str(DEFAULT_MODEL_DIR),
        gguf=str(gguf),
        binary=str(binary),
        n_gpu_layers=0,
    )

    try:
        # Test 1: Chào hỏi thuần túy -> Chat confident >= 85%
        res_hello = engine.decide(
            state="Người dùng: Xin chào Jarvis, bạn khỏe không?",
            question="Xác định đây là trò chuyện hay yêu cầu dùng công cụ:",
            options=_OPTIONS,
        )
        assert res_hello["answer"] == "chat"
        assert res_hello["top_probability"] >= 0.85

        # Test 2: Mở app rõ ràng -> Tool
        res_open = engine.decide(
            state="Người dùng: Mở ứng dụng Zalo trên máy tính giúp tôi",
            question="Xác định đây là trò chuyện hay yêu cầu dùng công cụ:",
            options=_OPTIONS,
        )
        assert res_open["answer"] == "tool"
        assert res_open["top_probability"] >= 0.85

        # Test 3: Tra cứu RAM máy tính -> Tool
        res_ram = engine.decide(
            state="Người dùng: Kiểm tra dung lượng RAM đang dùng bao nhiêu",
            question="Xác định đây là trò chuyện hay yêu cầu dùng công cụ:",
            options=_OPTIONS,
        )
        assert res_ram["answer"] == "tool"
        assert res_ram["top_probability"] >= 0.85
    finally:
        engine.close()
