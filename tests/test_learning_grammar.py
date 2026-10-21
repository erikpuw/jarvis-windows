"""Learning theo grammar + think 128 (spec 2026-10-13 §3). DB/wiki tạm."""
import asyncio
import json
from types import SimpleNamespace

import pytest

import engine.core.memory as memory
from engine.core import learning


@pytest.fixture
def engine(tmp_path, monkeypatch):
    monkeypatch.setattr(learning, "MEMORY_DB_PATH", tmp_path / "jarvis.db")
    monkeypatch.setattr(learning, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(memory, "DB_PATH", tmp_path / "jarvis.db")
    monkeypatch.setattr(learning.LearningEngine, "_embed_text", staticmethod(lambda c: None))
    memory.init_db()
    return learning.LearningEngine()


def _fake_llm(monkeypatch, responses, calls):
    import engine.server.llm_server as ls

    async def fake(messages, **kw):
        calls.append({"prompt": messages[0]["content"], **kw})
        payload = responses.pop(0) if responses else {"proposals": []}
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))])
    monkeypatch.setattr(ls, "call_llm", fake)


FIX = {"kind": "tool_fix", "query": "giá thịt bò", "wrong_tool": "market_price", "right_tool": "search_products",
       "evidence": "giá thịt bò phải dùng search_products"}


def test_propose_uses_grammar_think_and_shows_used_tools(engine, monkeypatch):
    calls = []
    _fake_llm(monkeypatch, [{"proposals": []}], calls)
    engine.record_outcome("market_price", "giá thịt bò", "success", "ok", [])
    asyncio.run(engine.process_conversation_learning("ghi nhớ giúp tôi điều này", "Dạ."))
    c = calls[0]
    assert c["thinking"] is True and c["thinking_budget"] == 128
    schema = c["response_format"]["json_schema"]["schema"]
    item = schema["properties"]["proposals"]["items"]["anyOf"]
    fix = next(b for b in item if b["properties"]["kind"].get("const") == "tool_fix")
    assert "search_products" in fix["properties"]["right_tool"]["enum"]
    assert "<hoi_thoai>" in c["prompt"] and "giá thịt bò → market_price" in c["prompt"] and "agent" not in c["prompt"]


def test_tool_fix_saved_only_with_outcome(engine, monkeypatch):
    import engine.core.memory as memory
    _fake_llm(monkeypatch, [{"proposals": [FIX]}, {"proposals": [FIX]}], [])
    msg = "sai rồi, giá thịt bò phải dùng search_products"
    monkeypatch.setattr(memory, "get_messages", lambda limit=100, session_id="": [
        {"role": "user", "content": "giá thịt bò"}, {"role": "assistant", "content": "Giá thị trường…"},
        {"role": "user", "content": msg}])
    asyncio.run(engine.process_conversation_learning(msg, "Dạ."))
    assert engine.list_correction_records()["total"] == 0
    engine.record_outcome("market_price", "giá thịt bò", "success", "ok", [])
    res = asyncio.run(engine.process_conversation_learning(msg, "Dạ."))
    assert res["stored"] == 1 and engine.list_correction_records()["total"] == 1


def test_routing_note_is_gone(engine, monkeypatch):
    _fake_llm(monkeypatch, [{"proposals": [{"kind": "routing_note", "key": "x", "content": "y", "evidence": "z"}]}], [])
    res = asyncio.run(engine.process_conversation_learning("z", "Dạ."))
    assert res["stored"] == 0 and not hasattr(engine, "_handle_routing_note_proposal")


def test_embedding_duplicate_skips_critique(engine, monkeypatch):
    vec = {"Trả lời ngắn gọn, đi thẳng vào ý chính.": [1.0, 0.0], "Tránh trả lời dài dòng lan man.": [0.95, 0.31]}
    monkeypatch.setattr(learning.LearningEngine, "_embed_text", staticmethod(lambda c: vec.get(c)))
    engine._store_learning("Tránh trả lời dài dòng lan man.", "behaviour_lesson", "tranh_dai")
    calls = []
    lesson = {"kind": "lesson", "key": "ngan_gon", "content": "Trả lời ngắn gọn, đi thẳng vào ý chính.",
              "evidence": "ngắn thôi"}
    _fake_llm(monkeypatch, [{"proposals": [lesson]}], calls)
    res = asyncio.run(engine.process_conversation_learning("dài quá, ngắn thôi, ghi nhớ giúp tôi", "Dạ."))
    assert res["stored"] == 0 and len(calls) == 1  # chỉ propose, không gọi critique


def test_critique_uses_grammar_and_think(engine, monkeypatch):
    calls = []
    lesson = {"kind": "lesson", "key": "emoji_vua_phai", "content": "Dùng emoji vừa phải trong câu trả lời.",
              "evidence": "bớt emoji"}
    _fake_llm(monkeypatch, [{"proposals": [lesson]}, {"decision": "new", "reason": "mới", "merged_content": ""}], calls)
    engine._store_learning("Nói giọng miền Nam Sài Gòn.", "behaviour_lesson", "giong_nam")
    asyncio.run(engine.process_conversation_learning("bớt emoji đi, ghi nhớ giúp tôi", "Dạ."))
    crit = calls[1]
    assert crit["thinking"] is True and crit["thinking_budget"] == 128
    assert crit["response_format"]["json_schema"]["schema"]["properties"]["decision"]["enum"] == ["skip", "merge",
                                                                                                    "replace", "new"]
    assert "<de_xuat>" in crit["prompt"]


def test_tool_fix_evidence_must_come_after_the_request(engine, monkeypatch):
    """Review 2026-10-14: model bịa tool_fix lấy chính câu hỏi làm evidence → lưu correction dù ngài không sửa.
    Evidence phải nằm trong lời ngài SAU câu yêu cầu gốc."""
    import engine.core.memory as memory
    engine.record_outcome("market_price", "giá iphone 16", "success", "ok", [])
    fake = {"kind": "tool_fix", "query": "giá iphone 16", "wrong_tool": "market_price",
            "right_tool": "search_products", "evidence": "giá iphone 16"}
    _fake_llm(monkeypatch, [{"proposals": [fake]}], [])
    monkeypatch.setattr(memory, "get_messages", lambda limit=100, session_id="": [
        {"role": "user", "content": "giá iphone 16"}, {"role": "assistant", "content": "Giá thị trường…"}])
    asyncio.run(engine.process_conversation_learning("giá iphone 16", "Giá thị trường…"))
    assert engine.list_correction_records()["total"] == 0


def _history(monkeypatch, *pairs):
    msgs = [{"role": r, "content": c} for r, c in pairs]
    monkeypatch.setattr(memory, "get_messages", lambda limit=100, session_id="": msgs)


def _new(n):
    return [{"decision": "new", "reason": "mới", "merged_content": ""} for _ in range(n)]


def test_no_teaching_words_means_no_learning_call(engine, monkeypatch):
    """Ngài 2026-10-14: chỉ học khi ngài dạy rõ (ghi nhớ, học đi…) hoặc sửa tool; trò chuyện, chê trách → không học."""
    calls = []
    _fake_llm(monkeypatch, [], calls)
    for text in ("tôi là lập trình viên", "trả lời gì mà dài quá", "chào buổi sáng", "tệ quá"):
        res = asyncio.run(engine.process_conversation_learning(text, "Dạ."))
        assert res["stored"] == 0 and res["discarded"]
    assert calls == []


def test_learns_only_from_the_latest_turn(engine, monkeypatch):
    """log 2026-10-14 19:33: model đề xuất lại 2 bài của lượt trước, chiếm hết chỗ → luật mới không được xét."""
    old = "ghi nhớ: dùng giọng miền Nam Sài Gòn"
    new = "ghi nhớ thêm: luôn xin lỗi ngắn một câu"
    _history(monkeypatch, ("user", old), ("assistant", "Dạ."), ("user", new))
    again = {"kind": "lesson", "key": "giong_nam", "content": "Dùng giọng miền Nam Sài Gòn.",
             "evidence": "dùng giọng miền Nam Sài Gòn"}
    fresh = {"kind": "lesson", "key": "xin_loi_ngan", "content": "Xin lỗi ngắn gọn trong một câu.",
             "evidence": "luôn xin lỗi ngắn một câu"}
    calls = []
    _fake_llm(monkeypatch, [{"proposals": [again, fresh]}, *_new(1)], calls)
    res = asyncio.run(engine.process_conversation_learning(new, "Dạ."))
    assert [p["key"] for p in res["items"]] == ["xin_loi_ngan"]
    assert "<luot_moi>" in calls[0]["prompt"] and new in calls[0]["prompt"]


def test_one_message_can_teach_four_items(engine, monkeypatch):
    text = "ghi nhớ: nói giọng Huế; dùng emoji ở tiêu đề; xin lỗi ngắn; trả lời ngắn gọn"
    taught = (("Nói giọng Huế khi trò chuyện.", "nói giọng Huế"), ("Đặt emoji ở tiêu đề.", "dùng emoji ở tiêu đề"),
              ("Xin lỗi ngắn trong một câu.", "xin lỗi ngắn"), ("Trả lời ngắn gọn, đi thẳng ý chính.", "trả lời ngắn gọn"))
    items = [{"kind": "lesson", "key": f"k{i}", "content": c, "evidence": e} for i, (c, e) in enumerate(taught)]
    calls = []
    _fake_llm(monkeypatch, [{"proposals": items}, *_new(4)], calls)
    res = asyncio.run(engine.process_conversation_learning(text, "Dạ."))
    assert res["stored"] == 4
    assert calls[0]["response_format"]["json_schema"]["schema"]["properties"]["proposals"]["maxItems"] == 4


def test_explicit_teaching_is_kept_even_if_critique_says_skip(engine, monkeypatch):
    engine._store_learning("Nói giọng miền Nam Sài Gòn.", "behaviour_lesson", "giong_nam")
    lesson = {"kind": "lesson", "key": "emoji", "content": "Dùng emoji ở tiêu đề.", "evidence": "dùng emoji ở tiêu đề"}
    _fake_llm(monkeypatch, [{"proposals": [lesson]}, {"decision": "skip", "reason": "x", "merged_content": ""}], [])
    res = asyncio.run(engine.process_conversation_learning("ghi nhớ: dùng emoji ở tiêu đề", "Dạ."))
    assert res["stored"] == 1


def test_tool_rule_is_saved_and_shown_in_tool_catalog(engine, monkeypatch):
    """log 2026-10-14 19:33: "tra giá thực phẩm… dùng products" không có loại nào để lưu (tool_fix cần một lần sai cụ thể)."""
    text = "ghi nhớ thêm: tra giá vàng, xăng dùng market; tra giá thực phẩm, đồ công nghệ dùng products"
    rules = [{"kind": "tool_rule", "topic": "giá vàng, xăng", "right_tool": "market_price",
              "evidence": "tra giá vàng, xăng dùng market"},
             {"kind": "tool_rule", "topic": "giá thực phẩm, đồ công nghệ", "right_tool": "search_products",
              "evidence": "tra giá thực phẩm, đồ công nghệ dùng products"}]
    _fake_llm(monkeypatch, [{"proposals": rules}], [])
    res = asyncio.run(engine.process_conversation_learning(text, "Dạ."))
    assert res["stored"] == 2
    assert engine.tool_rules() == {"market_price": ["giá vàng, xăng"], "search_products": ["giá thực phẩm, đồ công nghệ"]}
    assert engine.similar_corrections("giá thực phẩm, đồ công nghệ", 0.0, 5) == []  # luật chung không ép tool
    from engine.tools import registry
    line = next(l for l in registry.catalog_text(["search_products"], engine.tool_rules()).splitlines())
    assert "Ngài dạy dùng cho: giá thực phẩm, đồ công nghệ." in line
