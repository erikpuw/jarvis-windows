# tests/turn/test_history.py
import json

from engine.turn import history as H


def test_messages_format():
    a = H.assistant_message("Tôi mở Word.", "open_app", {"app_name": "word"})
    assert a["role"] == "assistant" and list(json.loads(a["content"])) == ["tool", "say", "args"]
    assert json.loads(a["content"]) == {"say": "Tôi mở Word.", "tool": "open_app", "args": {"app_name": "word"}}
    assert json.loads(H.assistant_message("Chào ngài.")["content"]) == {"say": "Chào ngài.", "tool": "none"}
    r = H.result_message("market_price", "x" * 9000, "success", True, "Nói ngắn.", 8000)
    assert r["role"] == "user"
    assert H.result_message("weather", "28°C", "success", False, "", 8000)["content"] == "[kết quả weather (success)]\n28°C"
    assert "x" * 8000 in r["content"] and "x" * 8001 not in r["content"]
    # e2e 2026-10-12 18:34: trả lời bằng chữ thường chép cả bảng lẫn chữ "(đã hiển thị cho ngài)" → chỉ dẫn nằm ở tiêu đề
    assert r["content"].startswith("[kết quả market_price (success) — ngài đã thấy bảng này trên màn hình: chỉ nhận xét")
    assert "Lưu ý khi trả lời: Nói ngắn." in r["content"]
    assert "đã thấy bảng" not in H.result_message("weather", "28°C", "success", False, "", 8000)["content"]


def test_for_model_rebuilds_contract_and_drops_old_format():
    hist = [
        {"role": "user", "content": "tắt notepad"},
        {"role": "assistant", "content": "Đã đóng Notepad thưa ngài 😊",
         "steps": [H.step_record("Tôi đóng Notepad.", "close_app", {"app_name": "notepad"}, "Thành công" + "!" * 500,
                                 "success")],
         "final_say": "Đã đóng Notepad thưa ngài 😊"},
        {"role": "user", "content": "chào"},
        {"role": "assistant", "content": "Chào ngài!", "tools_run": "[đã gọi open_app{...}]"},
        {"role": "user", "content": "mở lại đi"},
    ]
    out = H.for_model(hist)
    assert [m["role"] for m in out] == ["user", "assistant", "user", "assistant", "user", "assistant"]
    assert json.loads(out[1]["content"])["tool"] == "close_app"
    assert out[2]["content"].startswith("[kết quả close_app (success)]") and len(out[2]["content"]) < 400
    assert json.loads(out[3]["content"]) == {"say": "Đã đóng Notepad thưa ngài 😊", "tool": "none"}
    assert json.loads(out[5]["content"]) == {"say": "Chào ngài!", "tool": "none"}
    assert not any("[đã gọi" in m["content"] for m in out)


def test_for_model_keeps_last_three_turns_and_cuts_long_say():
    hist = []
    for i in range(5):
        hist += [{"role": "user", "content": f"câu {i}"}, {"role": "assistant", "content": "y" * 1000}]
    out = H.for_model(hist)
    assert [m["content"] for m in out if m["role"] == "user"] == ["câu 2", "câu 3", "câu 4"]
    assert len(json.loads(out[1]["content"])["say"]) == H.SHORT


def test_for_model_plain_for_answer_round():
    """Vòng trả lời bằng chữ thường: lịch sử là câu trả lời cuối, không JSON (JSON kéo Gemma về câu hứa ngắn).
    Log 2026-10-12 19:10: có cả câu báo "🛠️ Để tôi vào Cài đặt…" → vòng trả lời chép lại như vừa chạy tool."""
    hist = [{"role": "user", "content": "giá vàng"},
            {"role": "assistant", "content": "🛠️ Tôi xem giá.\n\n| Vàng | 1 |\n\nVàng tăng.", "final_say": "Vàng tăng.",
             "steps": [H.step_record("Tôi xem giá.", "market_price", {"item": "vàng"}, "| Vàng | 1 |", "success")]},
            {"role": "user", "content": "x" * 10}, {"role": "assistant", "content": "y" * 1000}]
    out = H.for_model(hist, plain=True)
    assert out == [{"role": "user", "content": "giá vàng"}, {"role": "assistant", "content": "Vàng tăng."},
                   {"role": "user", "content": "x" * 10}, {"role": "assistant", "content": "y" * 1000}]


def test_latest_turn_keeps_long_result_older_turns_stay_short():
    """Ngài 2026-10-13: hỏi tiếp "nói thêm bài 2" mà lịch sử chỉ còn 300 ký tự → model không còn nội dung.
    Lượt gần nhất giữ LAST ký tự (kết quả tool + câu trả lời), lượt cũ hơn vẫn SHORT."""
    long = "tin " * 1000

    def turn(q):
        return [{"role": "user", "content": q},
                {"role": "assistant", "content": "Tóm tắt.", "final_say": "Tóm tắt.",
                 "steps": [H.step_record("Tôi tìm tin.", "search_news", {"topic": q}, long, "success")]}]
    hist = turn("tin cũ") + turn("tin mới") + [{"role": "user", "content": "nói thêm bài 2"}]
    assert len(H.step_record("", "search_news", {}, long, "success")["result"]) == H.LAST
    tool_round = H.for_model(hist)
    results = [m["content"] for m in tool_round if m["content"].startswith("[kết quả")]
    assert len(results[0]) < H.SHORT + 100 and len(results[1]) > H.LAST - 10
    plain = H.for_model(hist, plain=True)
    assert [m["role"] for m in plain] == ["user", "assistant", "user", "assistant"]  # vẫn xen kẽ user/assistant
    assert plain[0]["content"] == "tin cũ"
    assert plain[2]["content"].startswith("tin mới\n\n[kết quả Tin tức (success)]")  # vòng trả lời: tên gọi, không tên hàm
    assert len(plain[2]["content"]) > H.LAST - 10 and plain[3]["content"] == "Tóm tắt."
