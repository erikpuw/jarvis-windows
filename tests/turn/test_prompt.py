# tests/turn/test_prompt.py
import re

import pytest

from engine.core.evolution import style_lines
from engine.tools import registry as R
from engine.turn import prompt as P

STYLE = """# Self Evolution Style Rules
- Tôi luôn xưng 'tôi' và gọi người dùng là 'ngài'.
- Giọng văn hài hước, dí dỏm kiểu miền Nam.
- Giọng văn hài hước, dí dỏm kiểu miền Nam.
- Khi cung cấp danh sách các agent, trình bày dạng Agent [Tên].
- Hạn chế gọi nhiều tác nhân khi người dùng phàn nàn.
- **[MỚI]** Dùng emoji vừa phải. (Từ `prefer_emoji` trong Preferences.md)
- Trả lời thẳng vào vấn đề.
- Khi phàn nàn, không xin lỗi dài dòng.
- Ưu tiên câu ngắn.
- Giải thích từng bước khi khó.
- Tránh lặp ý.
- Kết thúc gọn.
- Một luật thứ chín.
"""


def test_style_lines_filters_and_caps():
    got = style_lines(STYLE)
    assert got[0] == "- Giọng văn hài hước, dí dỏm kiểu miền Nam."
    assert "- Dùng emoji vừa phải." in got
    assert not any(re.search(r"ngài|agent|tác nhân|\[MỚI\]|Preferences", g) for g in got)
    assert len(got) == len(set(got)) == 9  # trần 12 (cùng STYLE_SCHEMA); fixture có 9 luật hợp lệ


def test_style_lines_keeps_first_person_rules_drops_only_honorific_rules():
    """Log 2026-10-12: evolution viết luật ngôi thứ nhất "Tôi…"; lọc mọi dòng có "tôi/ngài" làm mất 10/11 luật."""
    got = style_lines("- Tôi luôn xưng 'tôi' và gọi người dùng là 'ngài' trong mọi tương tác.\n"
                      "- Giọng văn của tôi mang phong cách hài hước và dí dỏm đặc trưng của miền Nam Sài Gòn.\n"
                      "- Tôi sử dụng emoji phù hợp để làm cho cuộc trò chuyện sinh động hơn.\n"
                      "- Khi ngài bày tỏ sự không hài lòng, tôi tránh xin lỗi dài dòng.\n"
                      "- Tôi không tự ý thay đổi quy tắc xưng hô hay phong cách đã được thiết lập.\n"
                      "- Chỉ nói thưa ngài một lần ở cuối.\n"
                      "- Không gọi tool khi ngài chỉ trò chuyện.\n")
    assert got == ["- Giọng văn của tôi mang phong cách hài hước và dí dỏm đặc trưng của miền Nam Sài Gòn.",
                   "- Tôi sử dụng emoji phù hợp để làm cho cuộc trò chuyện sinh động hơn.",
                   "- Khi ngài bày tỏ sự không hài lòng, tôi tránh xin lỗi dài dòng."]


@pytest.fixture
def env(monkeypatch, tmp_path):
    R._reset_for_test()

    async def open_app(app_name: str) -> str:
        return ""
    R._register_for_test(open_app, doc="Mở app.\n\napp_name: tên app\n")
    style = tmp_path / "STYLE.md"
    style.write_text(STYLE, encoding="utf-8")
    prefs = tmp_path / "Preferences.md"
    prefs.write_text("# User preferences\n- [`food`] Thích cơm tấm.\n- [`voice_style`] Dùng giọng miền Nam.\n"
                     "- [`tone`] Luôn xưng tôi, gọi ngài.\n", encoding="utf-8")
    monkeypatch.setattr(P, "STYLE_FILE", style)
    monkeypatch.setattr(P, "PREFERENCES_FILE", prefs)
    monkeypatch.setattr(P, "_tts_vieneu", lambda: False)
    yield
    R._reset_for_test()


def test_system_prompt_blocks_once(env):
    s = P.system_prompt(["open_app"])
    for tag in ("danh_tinh", "cach_lam_viec", "cach_tra_loi", "dinh_dang", "cong_cu", "giong_dieu", "nguoi_dung",
                "thoi_gian"):
        assert s.count(f"<{tag}>") == 1, tag
    assert "- open_app: Mở app. (app_name: tên app)" in s
    assert "Thích cơm tấm" in s and "giọng miền Nam" not in s.split("<nguoi_dung>")[1]
    assert s.count('Xưng "tôi"') == 1
    for banned in ("agent", "email", "Vietlott", "@tên_agent", "không tự gọi tool"):
        assert banned not in s
    assert "<voice_cues>" not in s


def test_answer_prompt_plain_text_knows_its_tools(env):
    """Vòng trả lời: không giao kèo JSON; có danh mục công cụ (chỉ tên + mô tả) để biết mình làm được gì.
    Log 2026-10-12 19:50-20:07: không thấy danh mục → hứa 'tôi sẽ tìm', nhận dùng Google Maps, bịa tên quán."""
    s = P.system_prompt(["open_app"], answer=True)
    for tag in ("danh_tinh", "cach_lam_viec", "cach_tra_loi", "dinh_dang", "cong_cu", "giong_dieu", "nguoi_dung",
                "thoi_gian"):
        assert s.count(f"<{tag}>") == 1, tag
    assert "JSON" not in s and "- open_app: Mở app." in s and "app_name" not in s
    work = s.split("<cach_lam_viec>")[1].split("</cach_lam_viec>")[0]
    for rule in ("không nói đã làm", "chưa có công cụ", "tôi sẽ", "tên riêng"):
        assert rule in work, rule
    assert '"tool", "say", "args"' in P.system_prompt(["open_app"]).split("<cach_lam_viec>")[1]


def test_identity_points_tone_to_style_and_no_terse_rule(env):
    """Log 2026-10-12: chat cứng, cụt; jarvis.md không có câu nào về giọng điệu mà lại ép "hỏi ngắn trả lời ngắn"."""
    s = P.system_prompt(["open_app"])
    identity = s.split("<danh_tinh>")[1].split("</danh_tinh>")[0]
    assert "giong_dieu" in identity
    assert "câu hỏi ngắn thì trả lời ngắn" not in s


def test_missing_style_and_prefs_ok(env, monkeypatch, tmp_path):
    monkeypatch.setattr(P, "STYLE_FILE", tmp_path / "none.md")
    monkeypatch.setattr(P, "PREFERENCES_FILE", tmp_path / "none2.md")
    s = P.system_prompt([])
    assert "<giong_dieu>" not in s and "<nguoi_dung>" not in s and "<cong_cu>" in s
