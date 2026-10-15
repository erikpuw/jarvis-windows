from engine.tools import registry as R


def test_file_tools_only_for_supported_extension():
    pdf = type("A", (), {"extension": ".pdf"})()
    docx = type("A", (), {"extension": ".docx"})()
    png = type("A", (), {"extension": ".png"})()
    assert "rag_ask" in R.file_tools_for(pdf) and "office_edit" not in R.file_tools_for(pdf)
    assert "office_edit" in R.file_tools_for(docx)
    assert set(R.file_tools_for(png)) >= {"read_image", "upscale_image"}
    assert R.file_tools_for(None) == []


def test_internal_tools_hidden_from_decide():
    shown = set(R.chat_names(None))
    for name in ("dream", "install_extension", "mcp_call", "check_project"):
        assert name in R.names() and name not in shown


def test_chat_tool_set_is_exactly_the_spec_list():
    shown = set(R.chat_names(None))
    assert shown == {"open_app", "close_app", "win_control", "capture_screen", "read_screen", "read_webcam",
                     "system_status", "check_security", "play_media", "weather", "search_news", "market_price",
                     "search_products", "cinema", "free_games", "lunar_today", "zodiac", "legal_lookup",
                     "vn_admin_lookup", "lookup_knowledge", "gym", "check_mail", "search_documents"}


def test_self_summarizing_tools_are_shown_verbatim():
    """Ngài 2026-10-13: vision/rag đã tự tổng hợp; vòng trả lời tóm lại lần nữa làm mất nội dung → hiện nguyên văn,
    vòng trả lời chỉ nhận xét."""
    for name in ("read_screen", "read_webcam", "read_image", "rag_ask"):
        assert R.display(name) is True, name
