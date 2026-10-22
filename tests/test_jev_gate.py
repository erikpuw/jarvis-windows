import os
import sys
import time
from pathlib import Path
import pytest

# Add paths
WORKSPACE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKSPACE))

from engine.turn.jev.jev_style_decision_gguf import JevStyleDecisionGGUF
from engine.turn.jev_gate import find_jev_binary, find_jev_gguf


@pytest.mark.skipif(
    os.getenv("JEV_LIVE_TESTS") != "1" or not find_jev_binary(use_cpu=True) or not find_jev_gguf(),
    reason="Jev binary hoặc model GGUF không khả dụng trên môi trường hiện tại"
)
def test_jev_fast_gate_accuracy():
    """Kiểm tra độ chính xác và độ trễ của Jev khi phân loại Chat vs Tool."""
    model_dir = WORKSPACE / "engine" / "turn" / "jev"
    gguf_path = find_jev_gguf()
    binary_path = find_jev_binary(use_cpu=True)

    assert gguf_path.exists(), f"Không tìm thấy model: {gguf_path}"
    assert binary_path.exists(), f"Không tìm thấy binary: {binary_path}"

    print("\n[INIT] Khởi động Jev-Style GGUF server...")
    t0 = time.perf_counter()
    engine = JevStyleDecisionGGUF(
        model_dir=str(model_dir),
        gguf=str(gguf_path),
        binary=str(binary_path),
        n_gpu_layers=0,
    )
    init_time = (time.perf_counter() - t0) * 1000
    print(f"[INIT] Server sẵn sàng trong {init_time:.1f}ms")

    options = {
        "chat": "Trò chuyện, chào hỏi, tâm sự, hỏi về bản thân trợ lý (bạn là ai, ai tạo ra bạn), hỏi đáp kiến thức bách khoa, dịch thuật, thơ ca, giải thích khái niệm",
        "tool": "Yêu cầu hành động hoặc tra cứu dữ liệu thực tế: thời tiết, ngày âm lịch, giá thị trường, tin tức, tìm thuốc, mở app, kiểm tra CPU RAM máy tính, chụp màn hình, ghi chú, bật nhạc"
    }

    test_cases = [
        # 10 câu Chat
        ("Xin chào Jarvis, hôm nay bạn thế nào?", "chat"),
        ("Bạn có biết làm thơ lục bát không?", "chat"),
        ("Giải thích cho tôi khái niệm Machine Learning là gì?", "chat"),
        ("Cảm ơn bạn nhiều nhé, câu trả lời rất hay!", "chat"),
        ("Hôm nay tôi thấy hơi mệt mỏi và buồn trong người", "chat"),
        ("Thủ đô của nước Pháp là gì vậy bạn?", "chat"),
        ("Kể cho tôi nghe một câu chuyện cười ngắn đi", "chat"),
        ("Bạn được tạo ra bởi ai và dùng mô hình gì?", "chat"),
        ("Dịch câu 'Hello World' sang tiếng Pháp giúp tôi", "chat"),
        ("Tạm biệt bạn, hẹn gặp lại sau nhé", "chat"),
        # 10 câu Tool
        ("Thời tiết Hà Nội hôm nay có mưa không?", "tool"),
        ("Mở ứng dụng Zalo trên máy tính giúp tôi", "tool"),
        ("Giá vàng SJC hôm nay tăng hay giảm bao nhiêu?", "tool"),
        ("Kiểm tra mức sử dụng RAM và nhiệt độ CPU hiện tại", "tool"),
        ("Tìm mua thuốc Panadol Extra trị đau đầu", "tool"),
        ("Hôm nay là ngày bao nhiêu âm lịch thế?", "tool"),
        ("Tìm kiếm tin tức thời sự nóng nhất sáng nay", "tool"),
        ("Chụp lại màn hình máy tính gửi cho tôi xem", "tool"),
        ("Tạo một ghi chú mới nhắc nhở tôi đi họp lúc 3h", "tool"),
        ("Bật bài nhạc Sơn Tùng M-TP trên YouTube", "tool"),
    ]

    correct = 0
    total = len(test_cases)
    latencies = []

    print("\n" + "=" * 70)
    print(f"{'CÂU LỆNH':<45} | {'DỰ ĐOÁN':<6} | {'TỰ TIN':<6} | {'ĐỘ TRỄ'}")
    print("=" * 70)

    for query, expected in test_cases:
        t_start = time.perf_counter()
        res = engine.decide(
            state=f"Người dùng: {query}",
            question="Xác định đây là trò chuyện hay yêu cầu dùng công cụ:",
            options=options
        )
        dt_ms = (time.perf_counter() - t_start) * 1000
        latencies.append(dt_ms)

        pred = res["answer"]
        conf = res["top_probability"]
        is_correct = (pred == expected)
        if is_correct:
            correct += 1

        mark = "✓" if is_correct else "✗"
        print(f"{mark} {query[:43]:<43} | {pred:<6} | {conf:.1%} | {dt_ms:5.1f}ms")

    engine.close()

    accuracy = (correct / total) * 100
    avg_latency = sum(latencies) / len(latencies)
    p95_latency = sorted(latencies)[int(len(latencies) * 0.95)]

    print("=" * 70)
    print(f"Tổng kết: {correct}/{total} ({accuracy:.1f}%) chính xác")
    print(f"Độ trễ trung bình: {avg_latency:.1f}ms (P95: {p95_latency:.1f}ms)")
    print("=" * 70)

    assert accuracy >= 95.0, f"Độ chính xác {accuracy}% không đạt yêu cầu >= 95%"
    assert avg_latency <= engine.request_timeout * 1000, "Vượt ngân sách suy luận CPU"


if __name__ == "__main__":
    test_jev_fast_gate_accuracy()
