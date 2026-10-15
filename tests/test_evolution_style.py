"""Evolution ghi STYLE.md sạch, tối đa 12 luật tinh gọn, khử trùng lặp và loại bỏ luật lạc đề."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.core import evolution as evo


def test_off_topic_style_rules_are_rejected():
    sources = ["Một số bài học."]
    assert evo._bad_rule("- Khi người dùng hỏi về giá một mặt hàng chung, cần yêu cầu khu vực cụ thể.", sources) is not None
    assert evo._bad_rule("- Tuân thủ yêu cầu đi ngủ hoặc chế độ chờ của ngài.", sources) is not None
    assert evo._bad_rule("- Hạn chế gọi các tác nhân khi ngài chỉ đưa ra nhận xét.", sources) is not None


