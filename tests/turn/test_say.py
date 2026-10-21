# tests/turn/test_say.py
import json

from engine.turn.say import SayReader, parse_turn

RAW = json.dumps({"say": 'Tôi mở "Word"\tngay 😀 \\ xong', "tool": "open_app", "args": {"app_name": "word"}},
                 ensure_ascii=True)  # ép \uXXXX + cặp surrogate cho emoji


def test_every_split_point_gives_same_text():
    want = 'Tôi mở "Word"\tngay 😀 \\ xong'
    for cut in range(len(RAW) + 1):
        r = SayReader()
        got = r.feed(RAW[:cut]) + r.feed(RAW[cut:])
        assert got == want, cut


def test_char_by_char():
    r = SayReader()
    assert "".join(r.feed(ch) for ch in RAW) == 'Tôi mở "Word"\tngay 😀 \\ xong'


def test_spaces_before_say_and_nothing_after_close():
    r = SayReader()
    assert r.feed('{ "say" : "chào') == "chào"
    assert r.feed('", "tool": "none"}') == ""


def test_parse_turn_ok_and_broken():
    assert parse_turn(RAW)["tool"] == "open_app" and parse_turn(RAW)["args"] == {"app_name": "word"}
    bad = parse_turn('{"say": "dở dang')
    assert bad == {"say": "dở dang", "tool": "none", "args": {}}
    assert parse_turn('{"say": "x", "tool": "none"}') == {"say": "x", "tool": "none", "args": {}}


def test_say_after_tool():
    r = SayReader()
    assert r.feed('{"tool": "open_app", "say": "Tôi mở') == "Tôi mở"
    assert r.feed(' Word.", "args": {"app_name": "word"}}') == " Word."
    assert SayReader().feed('{"tool": "none"}') == ""


def test_say_stops_at_first_line():
    """Log 2026-10-20 02:19: "say" của vòng chọn tool viết thêm cả đoạn "đã tạo skill thành công…" trước khi tool chạy,
    rồi vòng trả lời báo lần nữa → "say" chỉ là dòng đầu, khi stream lẫn khi lưu."""
    raw = json.dumps({"tool": "save_skill", "say": "Tôi tạo skill liền nha!\n\nĐã tạo skill thành công rồi!",
                      "args": {"request": "x"}}, ensure_ascii=False)
    r = SayReader()
    assert "".join(r.feed(ch) for ch in raw) == "Tôi tạo skill liền nha!"
    assert parse_turn(raw)["say"] == "Tôi tạo skill liền nha!"
    assert parse_turn('{"say": "dòng một\ndòng hai')["say"] == "dòng một\ndòng hai"   # JSON hỏng: chữ là câu trả lời
