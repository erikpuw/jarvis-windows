"""Evolution dọn bài học có rào chắn + STYLE.md (spec 2026-10-13 §3.3). DB tạm, STYLE/Evolution tạm (conftest)."""
import asyncio
import json
import re
from types import SimpleNamespace

import pytest

import engine.core.memory as memory
from engine.core import evolution, learning

LESSONS = [(1, "lesson", "Trả lời chi tiết toàn diện mọi câu hỏi.", 100),
           (2, "lesson", "Tránh trả lời dài dòng lan man.", 200),
           (3, "lesson", "Danh sách agent trình bày ngắn gọn.", 150),
           (4, "preference", "Dùng emoji cho cuộc trò chuyện sinh động.", 120)]


@pytest.fixture
def le(tmp_path, monkeypatch):
    monkeypatch.setattr(learning, "MEMORY_DB_PATH", tmp_path / "jarvis.db")
    monkeypatch.setattr(memory, "DB_PATH", tmp_path / "jarvis.db")
    monkeypatch.setattr(learning.LearningEngine, "_embed_text", staticmethod(lambda c: None))
    memory.init_db()
    engine = learning.LearningEngine()
    c = engine._get_learning_db()
    for i, t, content, at in LESSONS:
        c.execute("INSERT INTO learnings(id,type,semantic_key,content,created_at) VALUES(?,?,?,?,?)",
                  (i, t, f"k{i}", content, at))
    c.commit()
    c.close()
    monkeypatch.setattr(learning, "get_learning_engine", lambda: engine)
    evolution._last_inputs = None
    return engine


def _llm(monkeypatch, cleanup, style, calls):
    """Evolution 2 lần gọi (dọn → viết STYLE từ bài còn lại): trả theo schema được gửi."""
    async def fake(messages, **kw):
        calls.append({"prompt": messages[0]["content"], **kw})
        props = kw["response_format"]["json_schema"]["schema"]["properties"]
        payload = {"style": style} if "style" in props else cleanup
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))])
    monkeypatch.setattr(evolution, "call_llm", fake)


def _ids(le):
    c = le._get_learning_db()
    ids = [r[0] for r in c.execute("SELECT id FROM learnings ORDER BY id")]
    c.close()
    return ids


def test_conflict_is_not_deleted_and_style_sees_dates(le, monkeypatch):
    """Ngài 2026-10-14 (chọn 1): cosine không tách được trái ý / khác chủ đề (0.853 vs 0.851) nên "mâu thuẫn" không xoá
    (tránh mất bài học thật); bài trái ý vẫn giữ, lượt viết STYLE nhận ngày và theo bài mới hơn."""
    calls = []
    _llm(monkeypatch, {"remove": [{"id": 2, "why": "mâu thuẫn", "keep_id": 1}, {"id": 99, "why": "trùng", "keep_id": 1}],
                       "merge": []},
         ["Trả lời ngắn gọn, tránh dài dòng lan man.", "Dùng emoji cho cuộc trò chuyện sinh động.",
          "Luôn gọi công cụ market_price khi ngài hỏi giá."], calls)
    asyncio.run(evolution._run_cognitive_evolution())
    assert _ids(le) == [1, 2, 4]  # mâu thuẫn không xoá; #3 (agent) lỗi thời → code gỡ; #99 không có
    style = evolution.STYLE_FILE.read_text(encoding="utf-8")
    assert "ngắn gọn" in style and "emoji" in style and "market_price" not in style
    assert "Danh sách agent" in evolution.EVOLUTION_LOG.read_text(encoding="utf-8")
    clean, write = calls
    for c in calls:
        assert c["thinking"] is True and c["thinking_budget"] == 128
    assert set(clean["response_format"]["json_schema"]["schema"]["properties"]) == {"remove", "merge"}
    why = clean["response_format"]["json_schema"]["schema"]["properties"]["remove"]["items"]["properties"]["why"]
    assert why["enum"] == ["trùng"]
    assert set(write["response_format"]["json_schema"]["schema"]["properties"]) == {"style"}
    assert "#1 [lesson" in clean["prompt"] and "<bai_hoc>" in clean["prompt"]
    assert "#2 [1970-01-01] Tránh trả lời dài dòng lan man" in write["prompt"] and "mới hơn" in write["prompt"]


def test_duplicate_needs_similar_embeddings(le, monkeypatch):
    c = le._get_learning_db()
    c.execute("UPDATE learnings SET embedding=? WHERE id=2", (json.dumps([1.0, 0.0]),))
    c.execute("UPDATE learnings SET embedding=? WHERE id=4", (json.dumps([0.0, 1.0]),))  # khác ý
    c.execute("UPDATE learnings SET embedding=? WHERE id=1", (json.dumps([0.97, 0.24]),))  # gần #2
    c.commit()
    c.close()
    _llm(monkeypatch, {"remove": [{"id": 4, "why": "trùng", "keep_id": 2}, {"id": 1, "why": "trùng", "keep_id": 2},
                                  {"id": 3, "why": "trùng", "keep_id": 2}], "merge": []}, [], [])
    asyncio.run(evolution._run_cognitive_evolution())
    assert _ids(le) == [2, 4]  # #1 thật sự gần #2 → gỡ; #4 khác ý → giữ; #3 (agent) lỗi thời → code gỡ


def test_cleanup_capped_at_5(le, monkeypatch):
    c = le._get_learning_db()
    for i in range(10, 18):
        c.execute("INSERT INTO learnings(id,type,semantic_key,content,created_at,embedding) VALUES(?,?,?,?,?,?)",
                  (i, "lesson", f"x{i}", f"Bài học thừa số {i}.", 50, json.dumps([1.0, 0.0])))
    c.execute("UPDATE learnings SET embedding=? WHERE id=2", (json.dumps([1.0, 0.0]),))
    c.commit()
    c.close()
    _llm(monkeypatch, {"remove": [{"id": i, "why": "trùng", "keep_id": 2} for i in range(10, 18)], "merge": []}, [], [])
    asyncio.run(evolution._run_cognitive_evolution())
    assert len([i for i in _ids(le) if i >= 10]) == 4  # trần 5 gồm cả #3 (agent) đã gỡ do lỗi thời


def test_obsolete_removed_by_code_not_model(le, monkeypatch):
    """Ngài 2026-10-13 (chọn 1): model đoán "lỗi thời" sai (sót bài agent, gỡ nhầm bài khen) → code gỡ bài nhắc tới thứ
    Jarvis đã bỏ (OBSOLETE_TERMS); model không còn lý do "lỗi thời"."""
    calls = []
    _llm(monkeypatch, {"remove": [], "merge": []}, [], calls)
    asyncio.run(evolution._run_cognitive_evolution())
    assert 3 not in _ids(le)  # "Danh sách agent trình bày ngắn gọn." gỡ dù model không đề xuất
    assert "Danh sách agent" in evolution.EVOLUTION_LOG.read_text(encoding="utf-8")
    assert "Danh sách agent" not in calls[0]["prompt"]  # bài lỗi thời không đưa cho model dọn
    why = calls[0]["response_format"]["json_schema"]["schema"]["properties"]["remove"]["items"]["properties"]["why"]
    assert why["enum"] == ["trùng"]


def test_merge_updates_newest_and_deletes_rest(le, monkeypatch):
    c = le._get_learning_db()
    c.execute("UPDATE learnings SET embedding=? WHERE id=2", (json.dumps([1.0, 0.0]),))
    c.execute("UPDATE learnings SET embedding=? WHERE id=1", (json.dumps([0.97, 0.24]),))
    c.commit()
    c.close()
    _llm(monkeypatch, {"remove": [], "merge": [{"ids": [1, 2], "content": "Trả lời vừa đủ ý, không lan man."}]}, [], [])
    asyncio.run(evolution._run_cognitive_evolution())
    c = le._get_learning_db()
    row = c.execute("SELECT content FROM learnings WHERE id=2").fetchone()
    c.close()
    assert 1 not in _ids(le) and row[0] == "Trả lời vừa đủ ý, không lan man."


def test_merge_of_different_ideas_is_refused(le, monkeypatch):
    """evolution_probe 2026-10-13: gộp bài "chi tiết" (cũ) với "ngắn gọn" (mới) bằng nội dung "chi tiết" → ý cũ đè ý mới.
    Cosine hai bài trái ý 0.853 (EmbeddingGemma 2) < DEDUPE_SIM: không gộp."""
    c = le._get_learning_db()
    c.execute("UPDATE learnings SET embedding=? WHERE id=2", (json.dumps([1.0, 0.0]),))
    c.execute("UPDATE learnings SET embedding=? WHERE id=1", (json.dumps([0.85, 0.53]),))
    c.commit()
    c.close()
    _llm(monkeypatch, {"remove": [], "merge": [{"ids": [1, 2], "content": "Trả lời chi tiết toàn diện."}]}, [], [])
    asyncio.run(evolution._run_cognitive_evolution())
    c = le._get_learning_db()
    row = c.execute("SELECT content FROM learnings WHERE id=2").fetchone()
    c.close()
    assert _ids(le) == [1, 2, 4] and row[0] == "Tránh trả lời dài dòng lan man."  # #3 agent: code gỡ


def test_empty_style_keeps_current(le, monkeypatch):
    evolution.STYLE_FILE.parent.mkdir(parents=True, exist_ok=True)
    evolution.STYLE_FILE.write_text("# Self Evolution Style Rules\n- Dùng emoji cho cuộc trò chuyện sinh động.\n",
                                    encoding="utf-8")
    _llm(monkeypatch, {"remove": [], "merge": []}, [], [])
    asyncio.run(evolution._run_cognitive_evolution())
    assert "emoji" in evolution.STYLE_FILE.read_text(encoding="utf-8")


def test_removed_content_logged_even_if_llm_fails(le, monkeypatch):
    """Review 2026-10-14: xoá trước, gọi LLM lỗi sau → except bỏ qua _write_evolution_log → mất nội dung đã gỡ."""
    async def boom(messages, **kw):
        raise RuntimeError("llama.cpp tắt")
    monkeypatch.setattr(evolution, "call_llm", boom)
    asyncio.run(evolution._run_cognitive_evolution())
    assert 3 not in _ids(le) and "Danh sách agent" in evolution.EVOLUTION_LOG.read_text(encoding="utf-8")


def test_obsolete_only_lessons_and_capped(le, monkeypatch):
    """Review 2026-10-14: "agent" khớp cả sở thích ("phim về các agent tình báo") và không có trần."""
    c = le._get_learning_db()
    c.execute("INSERT INTO learnings(id,type,semantic_key,content,created_at) VALUES(20,'preference','p','Ngài thích phim về các agent tình báo.',10)")
    for i in range(30, 37):
        c.execute("INSERT INTO learnings(id,type,semantic_key,content,created_at) VALUES(?,?,?,?,?)",
                  (i, "lesson", f"a{i}", f"Gọi agent số {i} khi cần.", 10))
    c.commit()
    c.close()
    _llm(monkeypatch, {"remove": [], "merge": []}, [], [])
    asyncio.run(evolution._run_cognitive_evolution())
    ids = _ids(le)
    assert 20 in ids  # sở thích không phải bài học cách cư xử
    assert len([i for i in ids if i == 3 or i >= 30]) == 3  # 8 bài agent, trần 5 mỗi lần


def test_style_keeps_every_rule_the_model_may_write():
    """2026-10-14: model viết tối đa 12 luật (STYLE_SCHEMA) nhưng style_lines cắt còn 8 → luật emoji (vị trí sau)
    mất khỏi STYLE.md lẫn <giong_dieu>. Một trần duy nhất cho schema, ghi file và nạp prompt."""
    from engine.core import evolution as ev
    from engine.prompts.learning import STYLE_SCHEMA
    cap = STYLE_SCHEMA["properties"]["style"]["maxItems"]
    lines = "\n".join(f"- Luật số {i} về cách nói." for i in range(cap))
    assert len(ev.style_lines(lines)) == cap


def test_pronoun_sentences_are_cut_before_style_so_mixed_rules_survive(le, monkeypatch):
    """Log 2026-10-24: "ít dùng 'nha'" bị gộp vào bài xưng hô #5 → model viết một dòng STYLE "xưng hô … đồng thời giảm
    'nha'" → style_lines bỏ cả dòng (có chữ "xưng"), không log. Câu xưng hô bị cắt trước khi viết STYLE; dòng bị lọc có log."""
    c = le._get_learning_db()
    c.execute("INSERT INTO learnings(id,type,semantic_key,content,created_at) VALUES(5,'lesson','cach_xung_ho',?,300)",
              ("Khi nói chuyện với ngài, Jarvis nên dùng cách xưng hô thân mật. Khi tự xưng, Jarvis chỉ dùng 'tôi'. "
               "Đặc biệt, nên giảm tần suất sử dụng từ 'nha' để câu chuyện tự nhiên hơn.",))
    c.commit()
    c.close()
    calls, warned = [], []
    # ghi thẳng, không qua caplog: chạy cả bộ thì logger "jarvis" có thể đã tắt propagate (CI 2026-10-24)
    monkeypatch.setattr(evolution.log, "warning", lambda msg, *a: warned.append(msg % a))
    _llm(monkeypatch, {"remove": [], "merge": []},
         ["Giảm tần suất sử dụng từ 'nha' để câu chuyện tự nhiên hơn.", "Dùng cách xưng hô thân mật với ngài."], calls)
    asyncio.run(evolution._run_cognitive_evolution())
    lessons = calls[-1]["prompt"].rsplit("<bai_hoc>", 1)[1].split("</bai_hoc>")[0]
    assert "giảm tần suất sử dụng từ 'nha'" in lessons and "xưng" not in lessons
    style = evolution.STYLE_FILE.read_text(encoding="utf-8")
    assert "nha" in style and "xưng" not in style
    assert any("xưng hô thân mật" in w for w in warned)


def test_each_run_logs_style_added_removed_and_filtered(le, monkeypatch):
    """Ngài 2026-10-24: Evolution.md (wiki) ghi mỗi lần chạy: luật thêm vào / bỏ khỏi STYLE và luật bị lọc kèm lý do,
    khối có ngày trong tiêu đề (Dream xoay vòng theo ngày); lần ghi "Đã dọn" sau đó không làm mất khối."""
    evolution.STYLE_FILE.parent.mkdir(parents=True, exist_ok=True)
    evolution.STYLE_FILE.write_text("# Self Evolution Style Rules\n- Trả lời chi tiết toàn diện mọi câu hỏi.\n",
                                    encoding="utf-8")
    _llm(monkeypatch, {"remove": [], "merge": []},
         ["Dùng emoji cho cuộc trò chuyện sinh động.", "Dùng cách xưng hô thân mật với ngài.",
          "Luôn gọi công cụ market_price khi ngài hỏi giá."], [])
    asyncio.run(evolution._run_cognitive_evolution())
    evolution._write_evolution_log(["- [gỡ #9, trùng] X."])
    log_text = evolution.EVOLUTION_LOG.read_text(encoding="utf-8")
    block = log_text[log_text.index("· STYLE"):]
    assert re.search(r"^## \d{4}-\d{2}-\d{2} \d{2}:\d{2} · STYLE", log_text, re.M)
    assert "- Thêm: Dùng emoji cho cuộc trò chuyện sinh động." in block
    assert "- Bỏ: Trả lời chi tiết toàn diện mọi câu hỏi." in block
    assert re.search(r"^- Bị lọc \(.+\): Dùng cách xưng hô thân mật với ngài\.$", block, re.M)
    assert re.search(r"^- Bị lọc \(.+\): Luôn gọi công cụ market_price", block, re.M)
    assert "[gỡ #9, trùng] X." in log_text


def test_unchanged_style_writes_no_run_block(le, monkeypatch):
    evolution.STYLE_FILE.parent.mkdir(parents=True, exist_ok=True)
    evolution.STYLE_FILE.write_text("# Self Evolution Style Rules\n- Dùng emoji cho cuộc trò chuyện sinh động.\n",
                                    encoding="utf-8")
    _llm(monkeypatch, {"remove": [], "merge": []}, ["Dùng emoji cho cuộc trò chuyện sinh động."], [])
    asyncio.run(evolution._run_cognitive_evolution())
    assert "· STYLE" not in (evolution.EVOLUTION_LOG.read_text(encoding="utf-8")
                             if evolution.EVOLUTION_LOG.exists() else "")
