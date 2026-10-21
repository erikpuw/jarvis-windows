"""Menu lệnh Telegram (log 2026-10-15 20:43: setMyCommands 400 Bad Request sau khi mô tả tool dài thêm theo hướng dẫn
tool-use, de67719). Mô tả trong menu chỉ là câu đầu, ngắn, không kèm phần "khi nào không dùng"."""
from engine.server.telegram_bot import build_telegram_command_menu


def test_menu_descriptions_are_first_sentence_and_short():
    menu = build_telegram_command_menu()
    assert {m["command"] for m in menu} >= {"start", "help", "legal_lookup", "search_products"}
    for m in menu:
        assert 1 <= len(m["description"]) <= 120, m
        assert "Không dùng" not in m["description"], m
    legal = next(m for m in menu if m["command"] == "legal_lookup")
    assert legal["description"] == "Tra văn bản pháp luật Việt Nam và trả về điều khoản liên quan."
