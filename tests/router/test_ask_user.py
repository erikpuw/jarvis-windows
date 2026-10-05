import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from engine.router.ask_user import StreamTagFilter, ask_to_command, extract, extract_action, is_actionable, reply_kind


def test_extract_tolerates_bad_closing_tags():
    assert extract("Chào. <ask_user>Ngài có muốn tôi tra giá vàng không?</ask_user>") == (
        "Chào. Ngài có muốn tôi tra giá vàng không?", "Ngài có muốn tôi tra giá vàng không?")
    assert extract("Tin. <ask_user>Có cần tôi tra tin tức không? <ask_user>")[1] == "Có cần tôi tra tin tức không?"
    assert extract("x <ask_user>\nNgài có cần tôi sao lưu không?")[1] == "Ngài có cần tôi sao lưu không?"
    assert extract("Không có thẻ.") == ("Không có thẻ.", "")
    assert "ask_user" not in extract("a <ask_user>b không?<ask_user>")[0]


def test_stream_filter_hides_markers_split_across_chunks():
    f = StreamTagFilter()
    out = "".join(f.filter_chunk(c) for c in ["Chào ngài. <as", "k_user>Ngài có muốn ", "tôi mở Notepad không?</ask", "_user>"]) + f.flush()
    # 2026-09-27 (user): ý định đề nghị hiện nổi bật dạng `…` thay vì ẩn thẻ không dấu vết
    assert out == "Chào ngài. `Ngài có muốn tôi mở Notepad không?`"
    f = StreamTagFilter()
    assert f.filter_chunk("a < b") + f.flush() == "a < b"  # dấu < thường không bị nuốt


def test_stream_filter_drops_unfinished_marker_at_end_of_stream():
    f = StreamTagFilter()
    out = f.filter_chunk("Chào ngài. <ask_us") + f.flush()
    assert out == "Chào ngài. " and "<" not in out


def test_extract_strips_trailing_partial_marker():
    assert extract("Chào ngài. <ask_us") == ("Chào ngài.", "")


def test_is_actionable_accepts_single_yes_no_offer_only():
    ok = ["Ngài có muốn tôi tra giá vàng hôm nay không?", "Cho tôi phép tra giá vàng nhé?",
          "Ngài có muốn tôi xem email xem có thư quan trọng nào cần xử lý không ạ?",
          "Ngài có muốn tôi xem lại lịch sử trò chuyện không ạ? 🤔"]
    bad = ["Một việc cụ thể nào trên máy tính mà ngài muốn tôi làm thay cho ngài?", "Ngài muốn ghi nội dung cụ thể nào?",
           "Ngài muốn tôi tra tin công nghệ hay gợi ý phim?", 'Ngài có muốn tôi mở "A" hoặc "B" không?',
           "Ngài có cần tôi hỗ trợ gì trong Excel không? Hãy cho tôi biết."]
    assert all(is_actionable(q) for q in ok) and not any(is_actionable(q) for q in bad)


def test_ask_to_command_strips_the_offer_wrapper():
    assert ask_to_command("Ngài có muốn tôi xem hộp thư Outlook của ngài không ạ?") == "xem hộp thư Outlook của ngài"
    assert ask_to_command("Tôi có nên mở Notepad cho ngài không?") == "mở Notepad"
    assert ask_to_command("Cho tôi phép tra giá vàng nhé?") == "tra giá vàng"


def test_reply_kind_whole_sentence_word_lists():
    for t in ["ừ", "Ok", "có nhé", "vâng ạ", "jarvis làm đi", "đồng ý", "ok làm đi!",
              "ừ đi", "ok đi", "oke đi", "dạ vâng", "được rồi", "có đi"]:
        assert reply_kind(t) == "affirm", t
    for t in ["không", "thôi khỏi", "để sau nha", "khoan đã", "không cần đâu"]:
        assert reply_kind(t) == "deny", t
    for t in ["ừ nhưng mở word", "chắc vậy", "giá vàng hôm nay", ""]:
        assert reply_kind(t) == "", t


def test_reply_kind_handles_trailing_thua_ngai_before_tail_stripping():
    # M3: "thưa ngài" must strip before the tail-word loop runs, otherwise a
    # leading tail word ("nhé") sitting before it never gets stripped.
    for t in ["ok nhé thưa ngài", "ừ thưa ngài", "được rồi thưa ngài"]:
        assert reply_kind(t) == "affirm", t


def test_action_run_block_is_hidden_and_validated():
    body = "Chào. <ask_user>Ngài có muốn tôi mở Notepad không?</ask_user><action_run>open_app</action_run>"
    assert extract(body) == ("Chào. Ngài có muốn tôi mở Notepad không?", "Ngài có muốn tôi mở Notepad không?")
    assert extract_action(body) == "open_app"
    assert extract_action("x <ask_user>q không?</ask_user><action_run>get_news</action_run>") == ""  # không có thật
    assert extract_action("x <action_run> `open_app` </action_run>") == "open_app"
    assert extract_action("x <action_run>open_app") == "open_app"  # không đóng thẻ
    assert extract("a <ask_user>b không?</ask_user><action_run>open_app")[0] == "a b không?"
    assert extract_action("không có thẻ") == ""


def test_stream_filter_shows_intent_and_tool_across_chunks():
    """2026-09-27 (user): hiện ý định `…` và công cụ model chọn, để thấy model muốn gì (kể cả tên bịa)."""
    f = StreamTagFilter()
    chunks = ["Chào. Ngài có muốn tôi <ask_user>mở Notepad</ask_user> không?<act", "ion_run>open_", "app</action_run>"]
    assert "".join(f.filter_chunk(c) for c in chunks) + f.flush() == "Chào. Ngài có muốn tôi `mở Notepad` không? (công cụ: `open_app`)"
    f = StreamTagFilter()
    out = f.filter_chunk("Muốn tôi <ask_user>kiểm tra dự án code</ask_user> không?<action_run>check_project_code</action_run> Thưa ngài.") + f.flush()
    assert out == ("Muốn tôi `kiểm tra dự án code` không? (công cụ: `check_project_code` — không tồn tại, sẽ không chạy)"
                   " Thưa ngài.")
    f = StreamTagFilter()
    assert f.filter_chunk("A <action_run>open_app") + f.flush() == "A (công cụ: `open_app`)"  # không đóng thẻ
    f = StreamTagFilter()  # model đóng sai bằng <ask_user> thứ hai, hoặc không đóng trước <action_run>
    assert f.filter_chunk("x <ask_user>mở Word<ask_user> không?") + f.flush() == "x `mở Word` không?"
    f = StreamTagFilter()
    assert f.filter_chunk("x <ask_user>mở Word<action_run>open_app</action_run>") + f.flush() == "x `mở Word` (công cụ: `open_app`)"
    f = StreamTagFilter()
    assert f.filter_chunk("x <ask_user>mở Word") + f.flush() == "x `mở Word`"  # dừng giữa chừng: vẫn đóng dấu `


def test_reply_kind_affirm_word_plus_filler():
    for t in ["ừ mở đi", "ừ mở cho tôi đi", "ok làm luôn", "được mở giúp tôi", "đồng ý mở đi",
              "vâng thưa ngài ạ", "dạ thưa ngài ạ", "ok thưa ngài nhé", "ok nhé thưa ngài"]:
        assert reply_kind(t) == "affirm", t
    assert reply_kind("không thưa ngài ạ") == "deny"
    for t in ["ừ nhưng mở word", "chắc vậy", "ừ mở excel đi", "có mở notepad đâu"]:
        assert reply_kind(t) == "", t


def test_ask_to_command_wider_wrappers():
    assert ask_to_command("Ngài có đồng ý cho tôi mở Task Manager lần nữa không?") == "mở Task Manager"
    assert ask_to_command("Ngài có muốn tôi mở Notepad cho ngài ngay bây giờ không ạ?") == "mở Notepad"
    assert ask_to_command("Để tôi mở nhạc Đen Vâu nhé?") == "mở nhạc Đen Vâu"
    assert ask_to_command("Tôi có thể tra giá vàng giúp ngài không?") == "tra giá vàng"


def test_reply_kind_M2a_affirm_head_with_toi_means_user_will_do_it():
    """Task 19 M2a: affirm-head followed by 'tôi' + verb = user will do it themselves → return ""."""
    # User will do it themselves: "ok tôi mở", "dạ tôi làm"
    for t in ["ok tôi mở", "ừ tôi làm", "được tôi xem", "dạ tôi ghi note"]:
        assert reply_kind(t) == "", (t, reply_kind(t))

    # User wants Jarvis to do it: affirm + someone else gets it done
    for t in ["ừ mở cho tôi đi", "ok mở giúp tôi"]:
        assert reply_kind(t) == "affirm", (t, reply_kind(t))


def test_reply_kind_M2b_roi_in_filler():
    """Task 19 M2b: add 'rồi' to _FILLER so 'được rồi mở đi' → affirm."""
    assert reply_kind("được rồi mở đi") == "affirm"
    assert reply_kind("ok rồi làm ngay") == "affirm"


INLINE = "Tôi hiểu. Ngài có muốn tôi <ask_user>mở Notepad</ask_user> cho ngài không?<action_run>open_app</action_run>"


def test_inline_tag_wraps_only_the_command():
    """User 2026-09-25: <ask_user> bọc đúng phần việc bên trong câu hỏi, không bọc cả câu."""
    clean, ask = extract(INLINE)
    assert clean == "Tôi hiểu. Ngài có muốn tôi mở Notepad cho ngài không?"
    assert ask == "mở Notepad" and extract_action(INLINE) == "open_app"
    f = StreamTagFilter()
    shown = "".join(f.filter_chunk(INLINE[i:i + 5]) for i in range(0, len(INLINE), 5)) + f.flush()
    assert shown == "Tôi hiểu. Ngài có muốn tôi `mở Notepad` cho ngài không? (công cụ: `open_app`)"  # 2026-09-27
    assert is_actionable("mở Notepad") and ask_to_command("mở Notepad") == "mở Notepad"


def test_command_form_actionable_only_for_one_short_task():
    for bad in ["mở Notepad hay Word", "mở Notepad hoặc Excel", "", "mở " + "rất " * 15 + "nhiều"]:
        assert not is_actionable(bad), bad


def test_reply_kind_again_words_are_filler():
    """Live 2026-09-25: 'ừ mở lại cho tôi' đi qua gate xuống orchestrator thay vì chạy lại đề nghị."""
    for t in ["ừ mở lại cho tôi", "ok mở lại đi", "ừ thử lại lần nữa", "được mở giùm tôi", "ừ làm hộ tôi"]:
        assert reply_kind(t) == "affirm", t
    assert reply_kind("ừ mở lại word") == ""  # có đối tượng mới → không phải đồng ý suông


def test_extract_M5_strips_stray_action_run_close():
    """Task 19 M5: strip stray </action_run> tag with updated _MARKER_RE."""
    # Stray </action_run> outside a block should be removed
    text = "Chào ngài. Mở Notepad? </action_run> Xong."
    clean, ask = extract(text)
    assert "</action_run>" not in clean, clean
    assert clean == "Chào ngài. Mở Notepad?  Xong."

    # StreamTagFilter should also handle it
    f = StreamTagFilter()
    out = f.filter_chunk("A </action_run> B") + f.flush()
    assert "</action_run>" not in out, out
    assert out == "A  B"


def test_extract_drops_the_template_brackets_the_model_copies():
    """Log 2026-10-04: model chép nguyên "[việc]" của khuôn → câu lệnh gửi classifier có dấu "[" ("[mở bài hát ...")."""
    clean, ask = extract("Ngài có muốn tôi <ask_user>[mở bài hát Making My Way]</ask_user> không?<action_run>search_media</action_run>")
    assert ask == "mở bài hát Making My Way"
    assert clean == "Ngài có muốn tôi mở bài hát Making My Way không?"
    assert extract("Ngài có muốn tôi <ask_user>mở Notepad</ask_user> không?")[1] == "mở Notepad"


def test_stream_filter_drops_template_brackets_inside_the_ask():
    f = StreamTagFilter()
    out = f.filter_chunk("Ngài có muốn tôi <ask_user>[mở bài") + f.filter_chunk(" hát]</ask_user> không?") + f.flush()
    assert "[" not in out and "]" not in out and "mở bài hát" in out
