import sys
from pathlib import Path

WORKSPACE = Path(r"E:\workspace\jarvis")
sys.path.insert(0, str(WORKSPACE))

from engine.turn import loop


def test_cot_leak_regex():
    leaked_samples = [
        "*   **Trang thái:** Kết quả báo là không có dữ liệu bách khoa phù hợp nha ngài.",
        "*   **Cách trả lời:** Phải nói đúng như vậy kèm lý do trong kết quả.",
        "4.  **Draft the Response (incorporating `giong_dieu` and `dinh_dang`):**",
        "    *   *Tone:* Southern Vietnamese, dí dỏm, hòa đồng, natural.",
        "    *   *Greeting/Opening:* Acknowledge the question and the result.",
        "    *   *Content:* State clearly that the encyclopedia didn't find suitable data.",
        "    *   *Refinement:* Add a friendly closing/suggestion (since the data was missing, I should suggest another search).",
        "5.  **Final Polish (Self-Correction/Review):** The response is clear, uses the required tone, and addresses the 'no_result' status perfectly.",
        "6.  **Generate Output.**"
    ]

    for line in leaked_samples:
        assert loop._COT_LEAK.search(line) is not None, f"Dòng CoT rò rỉ này phải bị chặn: {line}"
        print(f"✓ Chặn thành công CoT leak: {line[:50]}...")

    normal_samples = [
        "Xin chào ngài, hôm nay trời Hà Nội mát mẻ không mưa.",
        "Dạ thưa ngài, bách khoa toàn thư hiện chưa có dữ liệu chi tiết về sự kiện này.",
        "Tôi đã mở ứng dụng Spotify cho ngài rồi nha!",
        "Giá vàng hôm nay là 85 triệu đồng một lượng."
    ]

    for line in normal_samples:
        assert loop._COT_LEAK.search(line) is None, f"Dòng bình thường không được chặn: {line}"
        print(f"✓ Cho phép hiển thị bình thường: {line[:50]}...")

    print("Test lọc rò rỉ CoT hoàn tất thành công 100%!")


if __name__ == "__main__":
    test_cot_leak_regex()
