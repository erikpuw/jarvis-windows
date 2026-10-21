# tests/turn/test_loop.py
import asyncio
import json
from types import SimpleNamespace

import pytest

from engine.tools import registry as R
from engine.turn import loop as L
from engine.turn.context import TurnContext


class _WS:
    cancel_requested = False
    session_id = "t"


def _chunks(obj, size=7):
    raw = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False)
    for i in range(0, len(raw), size):
        yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=raw[i:i + size]))])


@pytest.fixture
def env(monkeypatch):
    R._reset_for_test()
    state = {"script": [], "calls": [], "ran": [], "sent": []}

    async def open_app(app_name: str) -> str:
        state["ran"].append(("open_app", app_name))
        return f"Mở ứng dụng '{app_name}': Thành công"

    async def market_price(item: str) -> str:
        state["ran"].append(("market_price", item))
        return "| Sản phẩm | Giá |\n|---|---|\n| Vàng | 144.800.000 |"

    async def news(topic: str) -> str:
        return "x" * 20000
    R._register_for_test(open_app, doc="Mở app.\n\napp_name: tên app\n", kind="change")
    R._register_for_test(market_price, doc="Giá.\n\nitem: mặt hàng\n\n## answer\nNói ngắn.", display=True)
    R._register_for_test(news, doc="Tin.\n\ntopic: chủ đề\n")
    monkeypatch.setattr("engine.core.trace_logger.TraceLogger.log_trace", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr("engine.core.guardrails.verify_output", lambda n, a: (True, ""))
    monkeypatch.setattr("engine.turn.prompt.system_prompt", lambda names, answer=False, ran_tool=False, **kw:
                        ("RESULT" if ran_tool else "ANS" if answer else "SYS ") + ("" if ran_tool else ",".join(names)))
    monkeypatch.setattr("engine.turn.outcome.save_turn",
                        lambda *a, **k: state.setdefault("saved", []).append((a, k)))
    monkeypatch.setattr("engine.turn.corrections.lookup", lambda text: [])

    async def fake_llm(**kw):
        state["calls"].append(kw)
        item = state["script"].pop(0)
        if isinstance(item, Exception):
            raise item
        if kw.get("stream"):
            async def gen():
                for c in _chunks(item):
                    yield c
            return gen()
        raw = item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=raw))])
    monkeypatch.setattr("engine.server.llm_server.call_llm", fake_llm)

    class _VS:
        def __init__(self, ws): pass
        def start(self): return None
        async def put(self, s): state.setdefault("tts", []).append(s)
        async def stop(self, clear_queue=False): pass
    monkeypatch.setattr("engine.server.voice_streamer.VoiceStreamer", _VS)
    yield state
    R._reset_for_test()


def _ctx(state, att=None, history=None):
    async def send(ws, data):
        state["sent"].append(data)
        return True
    return TurnContext(ws=_WS(), send_json=send, attachment_context=att, conversation_history=history or [])


def _text(state):
    return "".join(e["text"] for e in state["sent"] if e["type"] == "text_chunk")


def _ends(state):
    return sum(e["type"] == "stream_end" for e in state["sent"])


def test_chat_json_none_then_plain_answer_streams_once(env):
    """Log 2026-10-12 18:08: trả lời trong chuỗi JSON → Gemma chỉ viết câu hứa. Giờ JSON chọn none, câu trả lời
    là chữ thường ở vòng riêng, prompt không giao kèo JSON."""
    env["script"] = [{"tool": "none"}, "Chào ngài!"]
    ctx = _ctx(env)
    out = asyncio.run(L.run_loop("xin chào", ctx))
    assert out == "Chào ngài!" and _text(env) == "Chào ngài!" and _ends(env) == 1
    c = env["calls"][0]
    assert c["stream"] is True and c["temperature"] == 0.0 and "tools" not in c
    assert c["thinking"] is True and c["thinking_budget"] == L.THINK_BUDGET == 128  # người dùng chốt 2026-10-12
    assert c["response_format"]["type"] == "json_schema"
    assert c["messages"][0]["content"].startswith("SYS open_app,market_price,news")
    a = env["calls"][1]
    assert a["stream"] is True and "response_format" not in a
    assert a["messages"][0]["content"] == "ANSopen_app,market_price,news"  # vòng trả lời biết danh mục
    assert a["thinking"] is True and a["messages"][-1] == {"role": "user", "content": "xin chào"}
    assert ctx.ws.last_turn == {"steps": [], "final_say": "Chào ngài!"}


def test_displayed_table_not_repeated_in_final_say(env):
    """Khi tool có display=True (da_hien='có'), nếu model chép lại bảng markdown ở vòng answer thì bị cắt bỏ."""
    repeated_table = (
        "Giá sữa chua dao động từ 27.000₫ đến 400.000₫ ngài nhé.\n\n"
        "📋 Bảng giá chi tiết:\n"
        "| Sản phẩm | Giá |\n"
        "| :--- | ---: |\n"
        "| Lốc sữa chua | 27.000₫ |\n"
    )
    env["script"] = [
        {"tool": "market_price", "say": "Tôi tra giá.", "args": {"item": "sữa chua"}},
        {"tool": "none"},
        repeated_table,
    ]
    ctx = _ctx(env)
    asyncio.run(L.run_loop("giá sữa chua", ctx))
    final = ctx.ws.last_turn["final_say"]
    assert "27.000₫" in final
    assert "| Sản phẩm |" not in final
    assert "Lốc sữa chua" not in final
    assert "Bảng giá chi tiết" not in final


def test_tool_then_answer_say_before_result_display_once(env):
    env["script"] = [{"tool": "market_price", "say": "Tôi xem giá vàng.", "args": {"item": "vàng"}},
                     {"tool": "none"}, "Vàng đang 144,8 triệu thưa ngài."]
    ctx = _ctx(env)
    asyncio.run(L.run_loop("giá vàng", ctx))
    text = _text(env)
    assert text.index("Tôi xem giá vàng.") < text.index("| Vàng | 144.800.000 |") < text.index("Vàng đang")
    assert text.count("| Vàng | 144.800.000 |") == 1 and _ends(env) == 1
    second = env["calls"][1]["messages"]
    assert json.loads(second[-2]["content"])["tool"] == "market_price"
    answer = env["calls"][2]["messages"]
    assert answer[-2] == {"role": "assistant", "content": "Tôi xem giá vàng."}
    assert 'da_hien="có"' in answer[-1]["content"] and "Nói ngắn." in answer[-1]["content"]
    assert not any("|" in s for s in env.get("tts", []))          # TTS không đọc bảng
    assert ctx.ws.last_turn["steps"][0]["tool"] == "market_price"
    assert ctx.ws.last_turn["final_say"] == "Vàng đang 144,8 triệu thưa ngài."


def test_invalid_args_do_not_run_and_user_is_told(env):
    env["script"] = [{"say": "Tôi mở ứng dụng.", "tool": "open_app", "args": {"app_name": ""}}]
    asyncio.run(L.run_loop("mở", _ctx(env)))
    assert env["ran"] == [] and "chưa làm được" in _text(env) and _ends(env) == 1


def test_repeat_call_forces_final_round(env):
    same = {"say": "Tôi mở Word.", "tool": "open_app", "args": {"app_name": "word"}}
    env["script"] = [same, same, "Xong thưa ngài."]
    asyncio.run(L.run_loop("mở word", _ctx(env)))
    assert env["ran"] == [("open_app", "word")]
    assert "response_format" not in env["calls"][2] and "Xong thưa ngài." in _text(env)


def test_round_cap_then_final(env):
    env["script"] = [{"say": f"Mở {i}.", "tool": "open_app", "args": {"app_name": f"a{i}"}} for i in range(4)]
    env["script"].append("Đã xong.")
    asyncio.run(L.run_loop("mở nhiều", _ctx(env)))
    assert len(env["ran"]) == L.MAX_ROUNDS and len(env["calls"]) == L.MAX_ROUNDS + 1
    assert "response_format" not in env["calls"][-1]


def test_long_result_cut_for_model(env):
    env["script"] = [{"say": "Tôi tìm tin.", "tool": "news", "args": {"topic": "bão"}},
                     {"tool": "none"}, "Có tin bão."]
    asyncio.run(L.run_loop("tin bão", _ctx(env)))
    assert len(env["calls"][1]["messages"][-1]["content"]) < L.RESULT_CHARS + 200


def test_cancel_during_tool_stops_without_extra_end(env, monkeypatch):
    env["script"] = [{"say": "Tôi mở Word.", "tool": "open_app", "args": {"app_name": "word"}}]
    ctx = _ctx(env)

    async def cancel_run(name, args, tctx=None):
        ctx.ws.cancel_requested = True
        return R.ToolResult("ok", "success")
    monkeypatch.setattr(R, "run", cancel_run)
    asyncio.run(L.run_loop("mở word", ctx))
    assert len(env["calls"]) == 1 and _ends(env) == 0


def test_llm_error_message_and_one_end(env):
    env["script"] = [RuntimeError("down")]
    out = asyncio.run(L.run_loop("chào", _ctx(env)))
    assert "lỗi kết nối" in out and _ends(env) == 1


def test_forced_tool_round1_only_then_final(env):
    env["script"] = [{"say": "Tôi mở Word.", "tool": "open_app", "args": {"app_name": "word"}},
                     "Đã mở Word."]
    asyncio.run(L.run_loop("word", _ctx(env), only="open_app"))
    first = env["calls"][0]["response_format"]["json_schema"]["schema"]["anyOf"]
    assert [b["properties"]["tool"]["const"] for b in first] == ["open_app"]
    assert len(env["calls"]) == 2 and "response_format" not in env["calls"][1]


def test_step_non_stream_for_probe(env):
    env["script"] = [{"say": "Tôi mở Word.", "tool": "open_app", "args": {"app_name": "word"}}]
    d = asyncio.run(L.step("mở word", []))
    assert d == {"say": "Tôi mở Word.", "tool": "open_app", "args": {"app_name": "word"}}
    assert env["calls"][0]["stream"] is False


def test_attachment_none_with_file_tool_asks_user(env, monkeypatch):
    async def read_doc(question: str, ctx=None) -> str:
        return "nội dung"
    R._register_for_test(read_doc, doc="Đọc tài liệu.\n\nquestion: câu hỏi\n", needs_attachment=True,
                         extensions=lambda: {".pdf"})
    att = SimpleNamespace(extension=".pdf", filename="a.pdf", router_metadata=lambda: {"filename": "a.pdf"})
    picked = {}

    async def fake_select(ws, send, action, message, options, **kw):
        picked["options"] = options
        return "read_doc"
    monkeypatch.setattr("engine.main.ask_verifi.ask_user_selection", fake_select)
    env["script"] = [{"tool": "none"}, {"tool": "none"}, "Tệp nói về X."]
    asyncio.run(L.run_loop("xem file này", _ctx(env, att=att)))
    assert [o["id"] for o in picked["options"]] == ["read_doc", "rag_save", "cancel"]
    assert "Tệp nói về X." in _text(env) and _ends(env) == 1


def test_attachment_pick_save_to_library_shows_save_result(env, monkeypatch):
    """2026-10-14: bảng hỏi có "Lưu vào kho tài liệu" → lưu + tổng hợp, không vòng trả lời bịa thêm."""
    async def read_doc(question: str, ctx=None) -> str:
        return "nội dung"
    R._register_for_test(read_doc, doc="Đọc tài liệu.\n\nquestion: câu hỏi\n", needs_attachment=True,
                         extensions=lambda: {".pdf"})
    att = SimpleNamespace(extension=".pdf", filename="a.pdf", router_metadata=lambda: {"filename": "a.pdf"})

    async def fake_select(ws, send, action, message, options, **kw):
        return "rag_save"

    async def fake_save(a):
        return "Đã lưu a.pdf vào kho: 3 đoạn.\n\n**a.pdf**: Thực đơn"
    monkeypatch.setattr("engine.main.ask_verifi.ask_user_selection", fake_select)
    monkeypatch.setattr("engine.rag.runner.save_document", fake_save)
    env["script"] = [{"tool": "none"}]
    out = asyncio.run(L.run_loop("", _ctx(env, att=att)))
    assert "Đã lưu a.pdf vào kho: 3 đoạn." in out and "**a.pdf**: Thực đơn" in out
    assert len(env["calls"]) == 1 and _ends(env) == 1


def _thinking_stream(n_chars):
    """Gemma đôi khi tự mở kênh suy nghĩ dù enable_thinking=False và không thoát (đo 2026-10-12)."""
    async def gen():  # stream thật: delta rỗng, reasoning_content None (đo 2026-10-12)
        for _ in range(n_chars):
            d = SimpleNamespace(content=None, model_extra={"reasoning_content": None})
            yield SimpleNamespace(choices=[SimpleNamespace(delta=d)])
    return gen()


@pytest.mark.parametrize("n", [600, 5000])
def test_thinking_is_never_cut(env, monkeypatch, n):
    """Đo 2026-10-12 (think_mode_probe): Gemma tự nghĩ (reasoning_content, không lên UI) rồi trả lời đúng;
    bộ chặn cũ cắt cả hai lần → "lỗi kết nối" (log 15:46, 15:47). Người dùng: nghĩ thì kệ nó, không cắt."""
    calls, items = [], [{"tool": "none"}, "Dạ, tôi nghe ngài."]

    async def fake_llm(**kw):
        calls.append(kw)
        item = items.pop(0)
        async def gen():
            async for c in _thinking_stream(n):
                yield c
            for c in _chunks(item):
                yield c
        return gen()
    monkeypatch.setattr("engine.server.llm_server.call_llm", fake_llm)
    out = asyncio.run(L.run_loop("sao thấy bạn trả lời không tự nhiên", _ctx(env)))
    assert out == "Dạ, tôi nghe ngài." and len(calls) == 2 and _ends(env) == 1


def test_step_retries_when_length_and_empty(env, monkeypatch):
    seq = [SimpleNamespace(choices=[SimpleNamespace(finish_reason="length", message=SimpleNamespace(content=""))]),
           SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(
               content=json.dumps({"say": "Tôi mở Word.", "tool": "open_app", "args": {"app_name": "word"}})))])]

    async def fake_llm(**kw):
        return seq.pop(0)
    monkeypatch.setattr("engine.server.llm_server.call_llm", fake_llm)
    assert asyncio.run(L.step("mở word", []))["tool"] == "open_app"


def test_empty_final_say_is_never_silent(env):
    env["script"] = ["", ""]  # JSON rỗng (server cắt giữa chừng), rồi câu trả lời rỗng
    out = asyncio.run(L.run_loop("tăng âm lượng", _ctx(env)))
    assert out and "ngài" in out and _ends(env) == 1


def test_plain_answer_with_quotes_and_braces_is_shown_verbatim(env):
    env["script"] = [{"tool": "none"}, 'Thực đơn "tăng cơ" {sáng}: yến mạch.']
    out = asyncio.run(L.run_loop("thực đơn gym", _ctx(env)))
    assert out == 'Thực đơn "tăng cơ" {sáng}: yến mạch.'


class _Tracker:
    def __init__(self):
        self.done = []

    async def track(self, label, status="completed"):
        self.done.append((label, status))

    def step(self, label):
        tracker = self

        class _S:
            def __init__(self):
                self.label = label

            async def __aenter__(self):
                return self

            async def __aexit__(self, et, ev, tb):
                tracker.done.append((self.label, "failed" if et else "completed"))
        return _S()


def test_flow_steps_follow_the_loop(env):
    """Ngài 2026-10-12: luồng flow_tracker không theo hệ thống — trước chỉ có 'Công cụ X', hai lần gọi model không hiện."""
    env["script"] = [{"tool": "market_price", "say": "Tôi xem giá vàng.", "args": {"item": "vàng"}},
                     {"tool": "none"}, "Vàng đang 144,8 triệu thưa ngài."]
    ctx = _ctx(env)
    ctx.flow_tracker = _Tracker()
    asyncio.run(L.run_loop("giá vàng", ctx))
    # ngài 2026-10-12 (ảnh flow): vòng kiểm tra sau tool không phải bước "Chọn công cụ" thứ hai → gộp vào tổng hợp
    assert ctx.flow_tracker.done == [("Chọn công cụ → Giá thị trường", "completed"), ("Chạy Giá thị trường", "completed"),
                                     ("Tổng hợp & trả lời", "completed"), ("Hoàn thành", "completed")]


def test_flow_steps_chat_and_multi_tool(env):
    env["script"] = [{"tool": "none"}, "Chào ngài!"]
    ctx = _ctx(env)
    ctx.flow_tracker = _Tracker()
    asyncio.run(L.run_loop("chào", ctx))
    assert ctx.flow_tracker.done == [("Chọn công cụ → không cần", "completed"), ("Trả lời", "completed"),
                                     ("Hoàn thành", "completed")]
    env["script"] = [{"tool": "open_app", "say": "Mở Word.", "args": {"app_name": "word"}},
                     {"tool": "open_app", "say": "Mở Paint.", "args": {"app_name": "paint"}}, {"tool": "none"}, "Xong."]
    ctx = _ctx(env)
    ctx.flow_tracker = _Tracker()
    asyncio.run(L.run_loop("mở word rồi paint", ctx))
    assert [d[0] for d in ctx.flow_tracker.done] == ["Chọn công cụ → Mở ứng dụng", "Chạy Mở ứng dụng", "Chọn công cụ → Mở ứng dụng",
                                                     "Chạy Mở ứng dụng", "Tổng hợp & trả lời", "Hoàn thành"]


def test_tool_say_has_icon_and_status_working_then_thinking(env):
    """Ngài 2026-10-12: câu báo gọi tool có emoji công cụ đứng trước; chạy tool → status working (status-label,
    status-orb), xong tool → thinking cho vòng model kế tiếp. TTS không đọc emoji."""
    env["script"] = [{"tool": "open_app", "say": "Tôi mở Word.", "args": {"app_name": "word"}},
                     {"tool": "none"}, "Xong thưa ngài."]
    asyncio.run(L.run_loop("mở word", _ctx(env)))
    assert _text(env).startswith(L.TOOL_ICON + "Tôi mở Word.")
    assert not any(L.TOOL_ICON.strip() in s for s in env.get("tts", []))
    st = [e for e in env["sent"] if e["type"] == "status"]
    assert [e["state"] for e in st] == ["working", "thinking", "thinking", "idle"]
    assert st[0]["message"] == "Công cụ: Mở ứng dụng" and st[2]["message"] == "Đang trả lời…"
    i = env["sent"].index(st[0])
    assert "Tôi mở Word." in "".join(e["text"] for e in env["sent"][:i] if e["type"] == "text_chunk")


def test_chat_has_no_icon_and_no_working(env):
    env["script"] = [{"tool": "none"}, "Chào ngài!"]
    asyncio.run(L.run_loop("chào", _ctx(env)))
    assert _text(env) == "Chào ngài!"
    assert [e["state"] for e in env["sent"] if e["type"] == "status"] == ["thinking", "idle"]


def test_status_idle_as_soon_as_llm_is_done_before_tts(env, monkeypatch):
    """Ngài 2026-10-15: LLM trả đủ chữ là status phải tắt (thinking → idle) ngay; gõ chữ là việc của bong bóng, đọc là
    status của TTS. Cũ: idle cuối lượt chỉ tới sau khi TTS tổng hợp hết + lưu DB (server.py) → kẹt "Đang nghĩ…"."""
    order = []

    class _VS:
        def __init__(self, ws): pass
        def start(self): return None
        async def put(self, s): pass
        async def stop(self, clear_queue=False): order.append("tts_stop")
    monkeypatch.setattr("engine.server.voice_streamer.VoiceStreamer", _VS)
    env["script"] = [{"tool": "market_price", "say": "Tôi xem giá.", "args": {"item": "vàng"}}, {"tool": "none"}, "Vàng 144 triệu."]
    ctx = _ctx(env)
    send = ctx.send_json

    async def spy(ws, data):
        if data.get("type") == "status":
            order.append(data["state"])
        elif data.get("type") == "stream_end":
            order.append("stream_end")
        return await send(ws, data)
    ctx.send_json = spy
    asyncio.run(L.run_loop("giá vàng", ctx))
    # ngài 2026-10-15: idle là trạng thái LLM, không gắn với bộ gõ chữ (stream_start/text_chunk/stream_end): LLM xong là idle
    assert order == ["working", "thinking", "thinking", "idle", "stream_end", "tts_stop"]


def test_answering_status_once_when_first_sentence_is_emitted(env):
    """Ngài chốt B 2026-10-15 (log iPhone 02:15: model viết 8,4 giây, chữ hiện dần mà nhãn vẫn "Đang nghĩ…"):
    câu đầu của vòng trả lời ra → thinking "Đang trả lời…" một lần, trước chữ câu đó; trả lời trống thì không gửi."""
    env["script"] = [{"tool": "none"}, "Dạ ngài. Hôm nay trời đẹp. Ngài cần gì nữa không?"]
    asyncio.run(L.run_loop("chào", _ctx(env)))
    sent = env["sent"]
    answering = [i for i, e in enumerate(sent) if e.get("message") == "Đang trả lời…"]
    first_text = next(i for i, e in enumerate(sent) if e["type"] == "text_chunk" and "Dạ ngài" in e["text"])
    assert len(answering) == 1 and answering[0] < first_text and sent[answering[0]]["state"] == "thinking"
    sent.clear()
    env["script"] = [{"tool": "none"}, ""]
    asyncio.run(L.run_loop("chào", _ctx(env)))
    assert not any(e.get("message") == "Đang trả lời…" for e in sent)


def test_flow_done_is_sent_before_waiting_for_tts(env, monkeypatch):
    """Ngài 2026-10-12: 'Hoàn thành' gửi sau khi TTS tổng hợp hết (server.py) → island đã thu lại rồi bật lên giữa lúc đọc."""
    order = []

    class _VS:
        def __init__(self, ws): pass
        def start(self): return None
        async def put(self, s): pass
        async def stop(self, clear_queue=False): order.append("tts_stop")
    monkeypatch.setattr("engine.server.voice_streamer.VoiceStreamer", _VS)
    env["script"] = [{"tool": "none"}, "Chào ngài!"]
    ctx = _ctx(env)
    ctx.flow_tracker = _Tracker()
    orig = ctx.flow_tracker.track

    async def track(label, status="completed"):
        order.append(label)
        await orig(label, status)
    ctx.flow_tracker.track = track
    send = ctx.send_json

    async def spy(ws, data):
        if data.get("type") == "stream_end":
            order.append("stream_end")
        return await send(ws, data)
    ctx.send_json = spy
    asyncio.run(L.run_loop("chào", ctx))
    # log 2026-10-15 00:12: chờ TTS tổng hợp hết (22 giây) rồi mới stream_end → chữ đã xong mà vẫn "Đang nghĩ…"
    assert order == ["Hoàn thành", "stream_end", "tts_stop"]


def test_promise_without_tool_is_dropped_and_told_honestly(env):
    """honesty_probe 2026-10-12: 'nhắc tôi uống nước' → '30 phút nữa tôi sẽ nhắc ngài' dù không có công cụ nhắc giờ.
    Prompt chỉ giảm (0/10 → 9/10), code chặn câu hứa: lượt không chạy tool thì không được hứa làm."""
    env["script"] = [{"tool": "none"}, "Dạ, ghi nhận nha! 30 phút nữa tôi sẽ nhắc ngài uống nước. Ngài cứ làm việc đi."]
    out = asyncio.run(L.run_loop("nhắc tôi uống nước", _ctx(env)))
    assert "tôi sẽ nhắc" not in out and "Ngài cứ làm việc đi." in out and L._NO_PROMISE in out
    assert not any("tôi sẽ nhắc" in s for s in env.get("tts", []))


def test_fake_tool_result_without_tool_is_cut(env):
    """log 2026-10-14 01:19: system_status bị chặn → vòng chat chép khuôn lịch sử, bịa '[kết quả system_status] CPU: 15%…'."""
    env["script"] = [{"tool": "none"}, "[kết quả system_status]\nCPU: 15% (Idle)\nRAM: 8.5 GB\n[kết quả system_status]\n\n"
                                       "Hệ thống ổn, CPU còn dư."]
    out = asyncio.run(L.run_loop("kiểm tra hệ thống", _ctx(env)))
    assert "kết quả" not in out and "CPU" not in out and L._NO_PROMISE in out
    assert not any("CPU" in s or "kết quả" in s for s in env.get("tts", []))


def test_offer_questions_and_plain_answers_are_kept(env):
    text = "Trời nóng thật. Ngài có muốn tôi kiểm tra thời tiết không? Để tôi tìm hiểu thêm nhé?"
    env["script"] = [{"tool": "none"}, text]
    out = asyncio.run(L.run_loop("trời nóng", _ctx(env)))
    assert out == text and L._NO_PROMISE not in out


def test_future_promise_dropped_even_after_a_tool(env):
    """log 19:03: sau win_control, 'Tôi sẽ theo dõi và báo lại cho ngài khi mọi thứ hoàn tất' — không có cơ chế đó."""
    env["script"] = [{"tool": "open_app", "say": "Tôi mở Word.", "args": {"app_name": "word"}}, {"tool": "none"},
                     "Word đã mở. Tôi sẽ theo dõi và báo lại cho ngài khi xong. Để tôi tra thêm cho ngài."]
    out = asyncio.run(L.run_loop("mở word", _ctx(env)))
    assert "theo dõi" not in out and "Word đã mở." in out and "Để tôi tra thêm cho ngài." in out


def test_capability_bullets_are_not_promises(env):
    """honesty_probe 2026-10-12: 'bạn làm được những gì' → dòng '* **Bảo mật:** Tôi sẽ kiểm tra an ninh mạng…' bị bỏ nhầm."""
    text = "Tôi làm được:\n*   **Bảo mật:** Tôi sẽ kiểm tra an ninh mạng cho ngài.\n- Thời tiết: tôi sẽ tra dự báo."
    env["script"] = [{"tool": "none"}, text]
    out = asyncio.run(L.run_loop("bạn làm được gì", _ctx(env)))
    assert out == text and L._NO_PROMISE not in out


def test_turn_with_tool_saves_outcome_chat_does_not(env):
    env["script"] = [{"tool": "open_app", "say": "Tôi mở Word.", "args": {"app_name": "word"}}, {"tool": "none"},
                     "Đã mở Word thưa ngài."]
    asyncio.run(L.run_loop("mở word", _ctx(env)))
    (args, kw), = env["saved"]
    text, steps, final_say, replay_id, workflow = args
    assert text == "mở word" and steps[0]["tool"] == "open_app" and replay_id is None and workflow is True
    env["script"] = [{"tool": "none"}, "Chào ngài!"]
    asyncio.run(L.run_loop("chào", _ctx(env)))
    assert len(env["saved"]) == 1


def test_forced_tool_turn_saves_outcome_but_not_workflow(env):
    env["script"] = [{"tool": "open_app", "say": "Tôi mở Word.", "args": {"app_name": "word"}}, "Xong."]
    asyncio.run(L.run_loop("word", _ctx(env), only="open_app"))
    (args, _), = env["saved"]
    assert args[4] is False


def test_win_control_trace_lands_in_step(env, monkeypatch):
    async def fake_run(name, args, tctx=None):
        tctx.trace.append({"action": "launch_app", "name": "notepad"})
        return R.ToolResult("ok", "success")
    monkeypatch.setattr(R, "run", fake_run)

    async def win_control(instruction: str) -> str:
        return ""
    R._register_for_test(win_control, doc="Điều khiển.\n\ninstruction: việc\n", kind="change")
    env["script"] = [{"tool": "win_control", "say": "Tôi làm.", "args": {"instruction": "mở notepad"}},
                     {"tool": "none"}, "Xong."]
    ctx = _ctx(env)
    asyncio.run(L.run_loop("mở notepad", ctx))
    assert ctx.ws.last_turn["steps"][0]["cua_steps"] == [{"action": "launch_app", "name": "notepad"}]


def test_unreplayable_trace_is_dropped(env, monkeypatch):
    async def fake_run(name, args, tctx=None):
        tctx.trace.append(None)
        return R.ToolResult("ok", "success")
    monkeypatch.setattr(R, "run", fake_run)

    async def win_control(instruction: str) -> str:
        return ""
    R._register_for_test(win_control, doc="Điều khiển.\n\ninstruction: việc\n", kind="change")
    env["script"] = [{"tool": "win_control", "say": "Tôi làm.", "args": {"instruction": "x"}}, {"tool": "none"}, "Xong."]
    ctx = _ctx(env)
    asyncio.run(L.run_loop("x", ctx))
    assert "cua_steps" not in ctx.ws.last_turn["steps"][0]


def test_replay_skips_tool_choice_and_answers(env):
    env["script"] = ["Đã mở Word thưa ngài."]  # chỉ vòng trả lời
    ctx = _ctx(env)
    wf = {"id": 5, "tools": "open_app", "tool_chain": [{"tool": "open_app", "args": {"app_name": "word"}, "say": "Tôi mở Word."}]}
    out = asyncio.run(L.run_loop("mở word", ctx, replay=wf))
    assert env["ran"] == [("open_app", "word")] and len(env["calls"]) == 1
    assert "response_format" not in env["calls"][0]
    assert out.startswith(L.TOOL_ICON + "Tôi mở Word.") and "Đã mở Word thưa ngài." in out
    (args, _), = env["saved"]
    assert args[3] == 5


def test_replay_stops_after_failed_step_and_answers(env, monkeypatch):
    async def flaky(name, args, tctx=None):
        env["ran"].append((name, args))
        return R.ToolResult("Lỗi: không mở được", "failed")
    monkeypatch.setattr(R, "run", flaky)
    env["script"] = ["Tôi chưa mở được Word, thưa ngài."]
    wf = {"id": 6, "tools": "open_app+open_app", "tool_chain": [
        {"tool": "open_app", "args": {"app_name": "word"}, "say": "Mở Word."},
        {"tool": "open_app", "args": {"app_name": "excel"}, "say": "Mở Excel."}]}
    out = asyncio.run(L.run_loop("mở word rồi excel", _ctx(env), replay=wf))
    assert len(env["ran"]) == 1 and "chưa mở được" in out


def test_replay_passes_cua_steps_to_win_control(env, monkeypatch):
    seen = {}

    async def fake_run(name, args, tctx=None):
        seen["replay"] = tctx.replay_steps
        return R.ToolResult("ok", "success")
    monkeypatch.setattr(R, "run", fake_run)

    async def win_control(instruction: str) -> str:
        return ""
    R._register_for_test(win_control, doc="Điều khiển.\n\ninstruction: việc\n", kind="change")
    cua = [{"action": "launch_app", "name": "notepad"}]
    env["script"] = ["Xong."]
    wf = {"id": 8, "tools": "win_control", "tool_chain": [
        {"tool": "win_control", "args": {"instruction": "mở notepad"}, "say": "Tôi làm.", "cua_steps": cua}]}
    asyncio.run(L.run_loop("mở notepad", _ctx(env), replay=wf))
    assert seen["replay"] == cua


def test_reply_to_a_question_saves_outcome_but_not_workflow(env):
    # review 2026-10-13: "ừ" trả lời lời mời → lưu workflow "ừ" thì lần sau "ừ" cho việc khác bị phát lại nhầm
    env["script"] = [{"tool": "open_app", "say": "Tôi mở Word.", "args": {"app_name": "word"}}, {"tool": "none"}, "Xong."]
    hist = [{"role": "user", "content": "chán quá"}, {"role": "assistant", "content": "Ngài có muốn tôi mở Word không?"}]
    asyncio.run(L.run_loop("ừ", _ctx(env, history=hist)))
    (args, _), = env["saved"]
    assert args[4] is False


def test_answer_stuck_repeating_a_word_is_cut(env):
    """Log 2026-10-13 16:10: temperature 0 kẹt "quên hết hết hết…" tới max_tokens 1500 → một nùi chữ."""
    env["script"] = [{"tool": "none"}, "Không sao đâu ngài ơi! Ai cũng có lúc quên hết" + " hết" * 300]
    out = asyncio.run(L.run_loop("tôi quên mất", _ctx(env)))
    assert out.endswith("quên hết") and "hết hết" not in out
    assert _ends(env) == 1


def test_answer_stuck_repeating_a_phrase_is_cut(env):
    env["script"] = [{"tool": "none"}, "Dạ ngài" + " rất vui được giúp ngài" * 40]
    out = asyncio.run(L.run_loop("cảm ơn", _ctx(env)))
    assert out.count("rất vui được giúp ngài") == 1


def _register_screen_tools(env):
    async def read_screen() -> str:
        env["ran"].append(("read_screen",))
        return "Màn hình có trình duyệt."

    async def system_status() -> str:
        env["ran"].append(("system_status",))
        return "CPU 20%"
    R._register_for_test(read_screen, doc="Nhìn màn hình.\n")
    R._register_for_test(system_status, doc="CPU, RAM.\n")


def test_narrated_watching_does_not_fire_screen_or_system_tools(env):
    """Ngài 2026-10-13: "tôi đang xem…" là ngài kể việc mình làm; prompt/bài học đều không chặn được (spike 0/2)
    → code chặn read_screen khi câu không nói tới màn hình, system_status khi không hỏi số liệu máy."""
    _register_screen_tools(env)
    env["script"] = [{"tool": "read_screen", "say": "Để tôi xem màn hình cho ngài.", "args": {}},
                     "Ngài cứ theo dõi nhé."]
    out = asyncio.run(L.run_loop("tôi đang xem cái quả cầu trên mobile có nóng không", _ctx(env)))
    env["script"] = [{"tool": "system_status", "say": "Để tôi kiểm tra hệ thống.", "args": {}}, "Dạ ngài."]
    out2 = asyncio.run(L.run_loop("tôi đang xem hệ thống hoạt động ra sao", _ctx(env)))
    assert env["ran"] == []
    assert "Để tôi xem màn hình" not in out and L.TOOL_ICON not in out and "Ngài cứ theo dõi nhé." in out
    assert "Để tôi kiểm tra hệ thống" not in out2


def test_explicit_screen_and_system_requests_still_run(env):
    _register_screen_tools(env)
    env["script"] = [{"tool": "read_screen", "say": "Tôi nhìn màn hình.", "args": {}}, {"tool": "none"}, "Có trình duyệt."]
    asyncio.run(L.run_loop("nhìn màn hình xem có gì", _ctx(env)))
    env["script"] = [{"tool": "system_status", "say": "Tôi xem RAM.", "args": {}}, {"tool": "none"}, "20%."]
    asyncio.run(L.run_loop("máy đang dùng bao nhiêu ram", _ctx(env)))
    env["script"] = [{"tool": "system_status", "say": "Tôi xem.", "args": {}}, "20%."]
    asyncio.run(L.run_loop("tôi đang xem", _ctx(env), only="system_status"))  # @tool: ngài chọn rõ, không chặn
    assert env["ran"] == [("read_screen",), ("system_status",), ("system_status",)]


def test_status_and_flow_show_tool_label_not_raw_name(env, monkeypatch):
    monkeypatch.setattr(R, "label", lambda n: {"open_app": "Mở ứng dụng"}.get(n, n))
    env["script"] = [{"tool": "open_app", "say": "Tôi mở Word.", "args": {"app_name": "word"}}, {"tool": "none"}, "Xong."]
    ctx = _ctx(env)
    ctx.flow_tracker = _Tracker()
    asyncio.run(L.run_loop("mở word", ctx))
    working = [e["message"] for e in env["sent"] if e.get("type") == "status" and e.get("state") == "working"]
    assert working == ["Công cụ: Mở ứng dụng"]
    labels = [d[0] for d in ctx.flow_tracker.done]
    assert "Chạy Mở ứng dụng" in labels and "Chọn công cụ → Mở ứng dụng" in labels


def test_system_gate_lets_explicit_check_through():
    """log 2026-10-14 01:19: "kiểm tra hệ thống" bị chặn → vòng chat bịa số CPU/RAM."""
    for t in ("kiểm tra hệ thống", "check hệ thống giúp tôi", "kiểm tra máy tính xem sao", "xem tình trạng máy"):
        assert not L._off_target("system_status", t), t
    assert L._off_target("system_status", "tôi đang xem hệ thống hoạt động ra sao")


def test_place_and_service_requests_never_go_to_shop_or_encyclopedia():
    """honesty_probe 2026-10-17: tìm khách sạn/quán → search_products (mô tả đã ghi "không dùng" vẫn chọn; nói lại
    yêu cầu đã lỗi thì luật "gọi lại công cụ đó" thắng). Chưa có công cụ tìm địa điểm → code chặn, lượt thành trò chuyện."""
    for t in ("tìm khách sạn ở Đà Lạt giá rẻ", "vậy tìm đi, tìm quán cà phê ở quận 6 xem", "nhà hàng nào ngon gần đây",
              "đặt bàn tối nay 4 người", "homestay view đẹp", "đặt giúp tôi vé máy bay đi Hà Nội tối nay"):
        assert L._off_target("search_products", t) and L._off_target("lookup_knowledge", t), t
    for t in ("giá airpods pro 3", "mua nồi chiên không dầu", "cà phê hạt rang xay loại nào ngon"):
        assert not L._off_target("search_products", t), t
    assert not L._off_target("lookup_knowledge", "Hồ Chí Minh sinh năm nào")


def test_place_names_from_model_memory_are_cut_when_no_tool_ran(env):
    """honesty_probe 2026-10-17: "tìm quán cà phê" → không tool (đúng) nhưng vòng trả lời kể tên quán theo trí nhớ
    model ("The Note Coffee", "The Coffee House"); prompt đã dặn vẫn kể. Code bỏ dòng tên riêng + câu dẫn ":"."""
    env["script"] = [{"tool": "none"}, "À, quận 6 có nhiều chỗ lắm, tôi gợi ý mấy quán này nha:\n"
                                       "* **The Note Coffee:** không gian ấm cúng. Giá ổn.\n"
                                       "* **Cộng Cà Phê:** phong cách vintage.\n"
                                       "*   **The Coffee House (Chi nhánh Quận 6):** ngồi xa tiếng ồn.\n"
                                       "*   **Quán cà phê sách:** thường yên tĩnh.\n"
                                       "*   **Cà phê Góc Phố:** decor ấm cúng.\n"
                                       "*   **Quán cà phê ở các con hẻm nhỏ:** ít khách.\n"
                                       "Ngài nhớ mang áo khoác nha."]
    out = asyncio.run(L.run_loop("tìm quán cà phê yên tĩnh ở quận 6", _ctx(env)))
    for gone in ("The Note", "Cộng Cà Phê", "Giá ổn", "gợi ý mấy quán này nha:", "The Coffee House", "Góc Phố"):
        assert gone not in out, gone
    assert "Quán cà phê sách" in out and "con hẻm nhỏ" in out  # loại quán chung chung, không phải tên riêng
    assert "Ngài nhớ mang áo khoác nha." in out and L._NO_PROMISE in out
    assert not any("The Note" in s for s in env.get("tts", []))


def test_capability_labels_are_not_taken_for_place_names(env, monkeypatch):
    """honesty_probe 2026-10-17: "bạn tìm quán xá ở đâu" → model kể khả năng "* Phát Youtube" → bị bỏ nhầm."""
    monkeypatch.setattr(R, "label", lambda n: {"open_app": "Mở ứng dụng", "news": "Phát Youtube"}.get(n, n))
    env["script"] = [{"tool": "none"}, "Tôi chưa có công cụ tìm quán. Tôi làm được:\n* Phát Youtube\n* **Mở ứng dụng:** mở app."]
    out = asyncio.run(L.run_loop("bạn tìm thông tin quán xá ở đâu vậy", _ctx(env)))
    assert "Phát Youtube" in out and "Mở ứng dụng" in out and L._NO_PROMISE not in out


def test_named_lists_stay_when_the_question_is_not_about_places(env):
    env["script"] = [{"tool": "none"}, "Mấy vị vua đầu nhà Nguyễn:\n* **Gia Long:** lập triều.\n* **Minh Mạng:** cải cách."]
    out = asyncio.run(L.run_loop("kể tên vài vị vua nhà Nguyễn", _ctx(env)))
    assert "Gia Long" in out and "Minh Mạng" in out and "vua đầu nhà Nguyễn:" in out and L._NO_PROMISE not in out


def test_webcam_gate():
    """held_out 2026-10-13: "để tôi xem lại cái trang web…" → read_webcam."""
    assert L._off_target("read_webcam", "để tôi xem lại cái trang web load có nhanh không đã")
    for t in ("nhìn qua webcam xem có ai không", "camera đang thấy gì", "bật cam xem tôi cầm gì"):
        assert not L._off_target("read_webcam", t), t


FIX = {"id": 7, "query": "giá thịt bò", "wrong_tool": "market_price", "right_tool": "open_app", "count": 1, "sim": 0.9}


def test_corrections_become_examples(env, monkeypatch):
    monkeypatch.setattr("engine.turn.corrections.lookup", lambda text: [FIX])
    env["script"] = [{"tool": "none"}, "Dạ."]
    asyncio.run(L.run_loop("giá thịt heo", _ctx(env)))
    system = env["calls"][0]["messages"][0]["content"]
    assert "<vi_du>" in system and '"giá thịt bò"' in system and "dùng open_app" in system


def test_force_needs_count_and_same_wrong_tool(env, monkeypatch):
    strong = {**FIX, "count": 2, "sim": 0.97}
    monkeypatch.setattr("engine.turn.corrections.lookup", lambda text: [strong])
    env["script"] = [{"tool": "market_price", "say": "Tôi xem giá thị trường.", "args": {"item": "bò"}},
                     {"tool": "open_app", "say": "Tôi mở.", "args": {"app_name": "shop"}}, {"tool": "none"}, "Xong."]
    out = asyncio.run(L.run_loop("giá thịt bò", _ctx(env)))
    assert env["ran"] == [("open_app", "shop")] and "Tôi xem giá thị trường" not in out
    forced = env["calls"][1]["response_format"]["json_schema"]["schema"]["anyOf"]
    assert [b["properties"]["tool"]["const"] for b in forced] == ["open_app"]
    from engine.turn import corrections as C
    assert C.forced_tool([{**FIX, "count": 1, "sim": 0.97}], "market_price", ["market_price", "open_app"]) is None
    assert C.forced_tool([{**FIX, "count": 2, "sim": 0.94}], "market_price", ["market_price", "open_app"]) is None
    assert C.forced_tool([strong], "weather", ["weather", "open_app"]) is None
    assert C.forced_tool([strong], "market_price", ["market_price"]) is None  # tool đúng không có trong lượt này


def test_tool_mention_skips_corrections(env, monkeypatch):
    called = []
    monkeypatch.setattr("engine.turn.corrections.lookup", lambda text: called.append(text) or [])
    env["script"] = [{"tool": "market_price", "say": "Tôi xem.", "args": {"item": "vàng"}}, "Xong."]
    asyncio.run(L.run_loop("vàng", _ctx(env), only="market_price"))
    assert called == []


def test_result_header_echo_is_dropped_after_tool(env):
    """log 2026-10-15 17:29/18:51: chạy tool rồi, vòng trả lời vẫn chép dòng "[kết quả search_documents (success) —
    ngài đã thấy bảng…]" ra màn hình và TTS đọc. Có chạy tool thì chỉ bỏ dòng tiêu đề đó, giữ phần nhận xét."""
    env["script"] = [{"tool": "market_price", "say": "Tôi xem giá.", "args": {"item": "vàng"}}, {"tool": "none"},
                     "[kết quả market_price (success) — ngài đã thấy bảng này trên màn hình: chỉ nhận xét]\nVàng đang cao, thưa ngài."]
    out = asyncio.run(L.run_loop("giá vàng", _ctx(env)))
    assert "[kết quả" not in out and "Vàng đang cao, thưa ngài." in out and L._NO_PROMISE not in out
    assert not any("kết quả" in s for s in env.get("tts", []))


def test_answer_never_shows_tool_function_names(env):
    """Ngài 2026-10-16: câu trả lời lộ tên hàm ("cứ bảo tôi `system_status` liền", "[system_status]"). Vòng trả lời
    chỉ được nói tên gọi; tên hàm còn sót (chép từ lịch sử cũ) được đổi sang tên gọi trước khi hiện và đọc."""
    env["script"] = [{"tool": "none"}, "Ngài cứ bảo tôi `open_app` hoặc [market_price] nhé.\nTin xem ở news."]
    out = asyncio.run(L.run_loop("tôi mệt quá", _ctx(env)))
    assert out == "Ngài cứ bảo tôi mở ứng dụng hoặc giá thị trường nhé.\nTin xem ở news."
    assert not any("open_app" in s or "market_price" in s for s in env.get("tts", []))


def test_answer_round_sees_result_xml_by_tool_label_and_no_catalog(env):
    env["script"] = [{"tool": "market_price", "say": "Tôi xem giá.", "args": {"item": "vàng"}}, {"tool": "none"}, "Vàng cao."]
    asyncio.run(L.run_loop("giá vàng", _ctx(env)))
    msgs = env["calls"][-1]["messages"]
    answer = "\n".join(m["content"] for m in msgs[1:])
    assert '<ket_qua cong_cu="Giá thị trường" trang_thai="success"' in answer and "market_price" not in answer
    assert "[kết quả" not in answer and msgs[0]["content"] == "RESULT"  # prompt báo kết quả, không danh mục


def test_copied_result_tag_is_cut_like_the_old_header(env):
    """Vòng trả lời giờ thấy <ket_qua …>: chép thẻ đó ra (có tool) thì bỏ dòng, bịa thẻ (không tool) thì cắt."""
    env["script"] = [{"tool": "market_price", "say": "Tôi xem giá.", "args": {"item": "vàng"}}, {"tool": "none"},
                     '<ket_qua cong_cu="Giá thị trường" trang_thai="success">\nVàng đang cao, thưa ngài.']
    out = asyncio.run(L.run_loop("giá vàng", _ctx(env)))
    assert "ket_qua" not in out and "Vàng đang cao, thưa ngài." in out
    env["script"] = [{"tool": "none"}, '<ket_qua cong_cu="Tình trạng máy">\nCPU: 15%\n\nMáy ổn.']
    out = asyncio.run(L.run_loop("kiểm tra máy", _ctx(env)))
    assert "CPU" not in out and L._NO_PROMISE in out


def test_save_note_needs_a_note_word():
    """probe 2026-10-18: 'ghi nhớ…' là dạy JARVIS (learning), không phải ghi chú."""
    for t in ("ghi chú giúp tôi: hạn trả nợ là 25/10", "ghi lại cái này", "lưu cái tin vừa tra"):
        assert not L._off_target("save_note", t), t
    for t in ("ghi nhớ là tôi thích cà phê đen", "nhớ giùm tôi thích trà"):
        assert L._off_target("save_note", t), t


def test_answer_after_tool_drops_echo_opening(env):
    """Ngài 2026-10-20: sau tool, câu trả lời mở đầu nói lại câu báo / câu hỏi ("Ngài muốn … hả? Được thôi ngài!",
    "Tôi đã nhận được kết quả…"); 19/60 tin gần đây mở đầu "Ngài muốn … hả" → code bỏ các câu đó khi còn nội dung sau."""
    env["script"] = [{"tool": "market_price", "say": "Tôi xem giá vàng.", "args": {"item": "vàng"}}, {"tool": "none"},
                     "[cười] Ngài muốn xem giá vàng hả? Được thôi ngài! Tôi đã nhận được kết quả từ công cụ rồi nha! "
                     "Vàng đang 144,8 triệu thưa ngài."]
    ctx = _ctx(env)
    asyncio.run(L.run_loop("giá vàng", ctx))
    text = _text(env)
    assert "Ngài muốn xem giá vàng hả" not in text and "Được thôi" not in text and "nhận được kết quả" not in text
    assert "Vàng đang 144,8 triệu thưa ngài." in text
    assert ctx.ws.last_turn["final_say"].startswith("Vàng đang")


def test_echo_kept_when_it_is_all_there_is_or_has_numbers(env):
    env["script"] = [{"tool": "market_price", "say": "Tôi xem.", "args": {"item": "vàng"}}, {"tool": "none"},
                     "Được rồi ngài, vàng hôm nay 144,8 triệu."]                      # có số: là nội dung, giữ
    asyncio.run(L.run_loop("giá vàng", _ctx(env)))
    assert "Được rồi ngài, vàng hôm nay 144,8 triệu." in _text(env)
    env["sent"].clear()
    env["script"] = [{"tool": "none"}, "Ngài muốn tâm sự hả? Tôi nghe nè."]            # không chạy tool: không đụng
    asyncio.run(L.run_loop("tôi buồn", _ctx(env)))
    assert "Ngài muốn tâm sự hả?" in _text(env)


def test_echo_only_answer_is_still_shown(env):
    env["script"] = [{"tool": "market_price", "say": "Tôi xem.", "args": {"item": "vàng"}}, {"tool": "none"},
                     "Ngài muốn xem giá vàng hả?"]
    asyncio.run(L.run_loop("giá vàng", _ctx(env)))
    assert "Ngài muốn xem giá vàng hả?" in _text(env)                                 # không bao giờ im lặng


def test_cot_leak_monologue_and_drafting_dropped(env):
    """Log 2026-10-21: Gemma 4 rò rỉ dàn bài suy nghĩ tiếng Anh.
    Bộ lọc bỏ sạch các dòng CoT, cắt gọt prefix và chỉ giữ lại lời đáp tiếng Việt với ngài."""
    leaked_cot = (
        "Chào ngài! [cười]\n"
        "*   **Style:** Southern Vietnamese (Sài Gòn), dí dỏm, hòa đồng, natural, professional use of emojis.\n"
        "*   **Goal:** Acknowledge the feedback, express gratitude, and confirm the commitment to improvement.\n\n"
        "4.  **Drafting the Response (Internal Monologue & Refinement):**\n"
        "    *   *Initial thought:* Okay, ngài. I will keep improving. Thank you for the feedback.\n"
        "    *   *Adding Southern flair:* Dạ, ngài ơi!\n"
        "    *   *Adding emotion/acknowledgment:* Cảm ơn ngài đã cho tôi nhận xét nha.\n"
        "    *   *Adding a concluding touch (natural flow):* Coi như là bước đi mới, tôi xin nhận ạ!\n\n"
        "5.      *   *Language:* Vietnamese (Check).\n"
        "    *   *Pronouns:* Tôi (self), Ngài (user) (Check).\n"
        "    *   *Emoji:* Used professionally (Check).\n"
        "    *   *Cue:* Used appropriately (Check).\n"
        "    *   *Structure:* Natural conversational flow (Check).\n\n"
        "6.\n"
    )
    env["script"] = [{"tool": "none"}, leaked_cot]
    asyncio.run(L.run_loop("tạm ổn", _ctx(env)))
    text = _text(env)
    assert "Style:" not in text
    assert "Goal:" not in text
    assert "Drafting" not in text
    assert "Internal Monologue" not in text
    assert "Initial thought" not in text
    assert "keep improving" not in text
    assert "Thank you for the feedback" not in text
    assert "Adding" not in text
    assert "Language" not in text
    assert "Check" not in text
    assert "Pronouns" not in text
    assert "Dạ, ngài ơi!" in text
    assert "Cảm ơn ngài đã cho tôi nhận xét nha." in text
    assert "Coi như là bước đi mới, tôi xin nhận ạ!" in text

def test_cue_filter_and_output_strip_leading_whitespace(env):
    """Cues [cười]... ở đầu câu không làm thụt đầu dòng hay để lại dòng trống."""
    from engine.server.text_streamer import StreamCueFilter, strip_voice_cues

    assert strip_voice_cues("[cười] Chào ngài!") == "Chào ngài!"
    assert strip_voice_cues("[cười]\nChào ngài!") == "Chào ngài!"
    assert strip_voice_cues("[cười]\n\nChào ngài!") == "Chào ngài!"
    assert strip_voice_cues("[thở dài] Mệt quá.") == "Mệt quá."

    # Lượt trả lời bắt đầu bằng cue: chữ gửi ra text_chunk không có dấu cách hay newline ở đầu
    env["script"] = [{"tool": "none"}, "[cười]\nChào ngài! Hôm nay thế nào?"]
    asyncio.run(L.run_loop("chào", _ctx(env)))
    text = _text(env)
    assert text.startswith("Chào ngài!")
    assert not text.startswith(" ") and not text.startswith("\n")



    # Lượt trả lời có cue giữa hai câu: bảo toàn dấu cách, không dính liền "Chào ngài!Nghe"
    env["sent"].clear()
    env["script"] = [{"tool": "none"}, "Chào ngài! [cười] Nghe ngài gọi là tôi vui quá trời luôn nha."]
    asyncio.run(L.run_loop("xin chào", _ctx(env)))
    text2 = _text(env)
    assert "Chào ngài! Nghe ngài gọi" in text2
    assert "Chào ngài!Nghe" not in text2