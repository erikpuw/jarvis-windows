"""Evolution ghi STYLE.md sạch, tối đa 12 luật tinh gọn, khử trùng lặp và loại bỏ luật lạc đề."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.core import evolution as evo


def test_cap_rules_strips_admin_labels():
    out = evo._cap_rules("# Self Evolution Style Rules\n- **[MỚI]** Dùng emoji vừa phải. (Từ `prefer_emoji`)\n"
                         "- Giữ giọng thân mật. (Từ `casual` trong Preferences.md)\n")
    assert out == "# Self Evolution Style Rules\n- Dùng emoji vừa phải.\n- Giữ giọng thân mật.\n"


def test_style_keeps_up_to_twelve_rules_routing_stays_six():
    text = "# Self Evolution Style Rules\n" + "\n".join(f"- Luật giao tiếp số {i} về một chủ đề riêng." for i in range(25))
    assert len(evo._extract_bullets(evo._cap_rules(text, evo._STYLE_MAX_BULLETS, evo._STYLE_MAX_CHARS))) == 12
    assert len(evo._extract_bullets(evo._cap_rules(text))) == 6


def test_existing_style_rules_count_as_grounded():
    old = "# Self Evolution Style Rules\n- **[MỚI]** Dùng emoji vừa phải để câu trả lời sinh động. (Từ `x`)\n"
    sources = evo._style_sources(["Trả lời ngắn gọn."], old)
    assert evo._bad_rule("- Dùng emoji vừa phải để câu trả lời sinh động.", sources, routing=False) is None


def test_off_topic_style_rules_are_rejected():
    sources = ["Một số bài học."]
    assert evo._bad_rule("- Khi người dùng hỏi về giá một mặt hàng chung, cần yêu cầu khu vực cụ thể.", sources, routing=False) is not None
    assert evo._bad_rule("- Tuân thủ yêu cầu đi ngủ hoặc chế độ chờ của ngài.", sources, routing=False) is not None
    assert evo._bad_rule("- Hạn chế gọi các tác nhân khi ngài chỉ đưa ra nhận xét.", sources, routing=False) is not None


def test_deduplicate_style_bullets_merges_redundant_rules():
    raw_bullets = [
        "- Tôi luôn xưng 'tôi' và gọi người dùng là 'ngài' trong mọi tương tác.",
        "- Tôi sẽ không tự ý thay đổi các quy tắc về xưng hô và giọng văn đã được thiết lập.",
        "- Giọng văn của tôi phải mang phong cách hài hước và dí dỏm đặc trưng của miền Nam Sài Gòn.",
        "- Tôi sẽ thêm sự hài hước và dí dỏm vào các cuộc hội thoại.",
        "- Tôi thường xuyên sử dụng emoji để làm cho cuộc trò chuyện trở nên sinh động hơn.",
    ]
    deduped = evo._deduplicate_style_bullets(raw_bullets)
    assert len(deduped) == 3
    assert any("xưng 'tôi'" in d for d in deduped)
    assert any("miền Nam Sài Gòn" in d for d in deduped)
    assert any("emoji" in d for d in deduped)


def test_merge_keeps_old_wording_but_without_labels():
    old = "# Self Evolution Style Rules\n- **[MỚI]** Giữ giọng thân mật khi trò chuyện phiếm. (Từ `casual`)\n"
    new = "# Self Evolution Style Rules\n- Giữ giọng thân mật khi trò chuyện phiếm.\n- Khi xin lỗi chỉ dùng một câu ngắn.\n"
    out = evo._merge_rules(new, old)
    assert "[MỚI]" not in out and "(Từ `" not in out and "Giữ giọng thân mật khi trò chuyện phiếm." in out
