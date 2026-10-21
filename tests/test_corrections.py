"""Bảng corrections (spec 2026-10-13 §1). Run: python -m pytest tests/test_corrections.py -q"""
import sqlite3
import time

import pytest

import engine.core.memory as memory
from engine.core import learning

VEC = {"giá thịt bò": [1.0, 0.0, 0.0], "giá thịt heo": [0.96, 0.28, 0.0], "giá vàng": [0.0, 1.0, 0.0]}


@pytest.fixture
def engine(tmp_path, monkeypatch):
    monkeypatch.setattr(learning, "MEMORY_DB_PATH", tmp_path / "jarvis.db")
    monkeypatch.setattr(learning, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(memory, "DB_PATH", tmp_path / "jarvis.db")
    monkeypatch.setattr(learning.LearningEngine, "_embed_text",
                        staticmethod(lambda c: VEC.get(learning.normalize_query(c))))
    memory.init_db()
    return learning.LearningEngine()


def _rows(le):
    c = le._get_learning_db()
    rows = [dict(r) for r in c.execute("SELECT * FROM corrections")]
    c.close()
    return rows


def test_cosine_handles_missing_and_dim_mismatch():
    assert learning._cosine([1, 0], [1, 0]) == pytest.approx(1.0)
    assert learning._cosine([1, 0], [1, 0, 0]) is None
    assert learning._cosine(None, [1]) is None and learning._cosine([], [1]) is None


def test_record_requires_outcome(engine):
    assert engine.record_correction("giá thịt bò", "market_price", "search_products") is False
    assert _rows(engine) == []


def test_record_then_repeat_counts(engine):
    engine.record_outcome("market_price", "Giá thịt bò!", "success", "ok", [])
    assert engine.record_correction("giá thịt bò", "market_price", "search_products") is True
    c = engine._get_learning_db()
    c.execute("UPDATE corrections SET updated_at=updated_at-10")
    c.commit()
    c.close()
    engine.record_outcome("market_price", "Giá thịt bò", "success", "ok", [])  # tái phạm rồi bị sửa lại
    assert engine.record_correction("Giá thịt bò", "market_price", "search_products") is True
    rows = _rows(engine)
    assert len(rows) == 1 and rows[0]["count"] == 2 and rows[0]["query_norm"] == "giá thịt bò"


def test_record_rejects_bad_tools_and_old_outcome(engine):
    engine.record_outcome("market_price", "giá thịt bò", "success", "ok", [])
    assert engine.record_correction("giá thịt bò", "market_price", "market_price") is False
    assert engine.record_correction("giá thịt bò", "market_price", "khong_co_tool") is False
    assert engine.record_correction("giá thịt bò", "weather", "search_products") is False  # chưa từng dùng weather
    c = engine._get_learning_db()
    c.execute("UPDATE outcomes SET created_at=?", (time.time() - 90000,))
    c.commit()
    c.close()
    assert engine.record_correction("giá thịt bò", "market_price", "search_products") is False


def test_similar_corrections_threshold_and_dims(engine):
    engine.record_outcome("market_price", "giá thịt bò", "success", "ok", [])
    engine.record_correction("giá thịt bò", "market_price", "search_products")
    c = engine._get_learning_db()
    c.execute("INSERT INTO corrections(query,query_norm,wrong_tool,right_tool,count,embedding,created_at,updated_at) "
              "VALUES('cũ','cũ','weather','search_news',1,'[1.0, 0.0]',1,1)")  # vector 2d cũ
    c.commit()
    c.close()
    got = engine.similar_corrections("giá thịt heo", 0.85, 3)
    assert [g["right_tool"] for g in got] == ["search_products"] and got[0]["sim"] == pytest.approx(0.96, abs=0.01)
    assert engine.similar_corrections("giá vàng", 0.85, 3) == []


def test_wiki_list_and_delete(engine):
    engine.record_outcome("market_price", "giá thịt bò", "success", "ok", [])
    engine.record_correction("giá thịt bò", "market_price", "search_products")
    wiki = learning.LESSONS_WIKI_PATH.read_text(encoding="utf-8")
    assert "giá thịt bò" in wiki and "search_products" in wiki
    page = engine.list_correction_records()
    assert page["total"] == 1 and engine.get_memory_control_counts()["corrections"] == 1
    assert engine.delete_learning_control_record("correction", page["items"][0]["id"]) is True
    assert _rows(engine) == [] and "giá thịt bò" not in learning.LESSONS_WIKI_PATH.read_text(encoding="utf-8")


def test_count_rises_only_when_the_mistake_recurs(engine):
    """Review 2026-10-14: transcript học đọc lại lời sửa cũ → tool_fix lặp → count 2 → ép tool dù ngài sửa 1 lần.
    count chỉ tăng khi sau lần sửa trước có thêm lượt dùng đúng tool sai đó."""
    engine.record_outcome("market_price", "giá thịt bò", "success", "ok", [])
    assert engine.record_correction("giá thịt bò", "market_price", "search_products") is True
    assert engine.record_correction("giá thịt bò", "market_price", "search_products") is False  # chỉ đọc lại
    assert _rows(engine)[0]["count"] == 1
    c = engine._get_learning_db()
    c.execute("UPDATE corrections SET updated_at=updated_at-10")
    c.commit()
    c.close()
    engine.record_outcome("market_price", "giá thịt bò", "success", "ok", [])  # tái phạm
    assert engine.record_correction("giá thịt bò", "market_price", "search_products") is True
    assert _rows(engine)[0]["count"] == 2


def test_corrected_query_never_replays_the_wrong_workflow(engine):
    """log 2026-10-14 17:04/17:16: "giá thịt bò" (đã sửa 2 lần) vẫn phát lại workflow market_price → bỏ qua model
    lẫn corrections, sai mãi ở lượt đầu. Câu đã sửa thì không phát lại workflow có wrong_tool; tool khác vẫn phát."""
    chain = [{"tool": "market_price", "args": {"item": "thịt bò"}, "say": ""}]
    engine.save_workflow("giá thịt bò", chain, "ok")
    engine.save_workflow("giá vàng", [{"tool": "market_price", "args": {"item": "vàng"}, "say": ""}], "ok")
    assert engine.find_workflow("Giá thịt bò")["tools"] == "market_price"
    engine.record_outcome("market_price", "giá thịt bò", "success", "ok", [])
    assert engine.record_correction("giá thịt bò", "market_price", "search_products") is True
    assert engine.find_workflow("Giá thịt bò") is None
    assert engine.find_workflow("giá vàng")["tools"] == "market_price"
    right = [{"tool": "search_products", "args": {"query": "thịt bò"}, "say": ""}]
    engine.save_workflow("giá thịt bò", right, "ok")  # sửa xong chạy đúng → workflow đúng được phát lại
    assert engine.find_workflow("giá thịt bò")["tools"] == "search_products"


def _seed(engine):
    engine.record_outcome("market_price", "giá thịt bò", "success", "ok", [])
    assert engine.record_correction("giá thịt bò", "market_price", "search_products") is True
    return _rows(engine)[0]["id"]


def test_memory_control_edits_a_correction(engine):
    """Ngài 2026-10-16: Memory Control mục "Sửa công cụ" không sửa/xoá được (kind correction không có trong API)."""
    rid = _seed(engine)
    assert engine.update_learning_control_record("correction", rid, {"query": "Giá thịt heo", "count": 3}) is True
    row = _rows(engine)[0]
    assert (row["query"], row["query_norm"], row["count"]) == ("Giá thịt heo", "giá thịt heo", 3)
    assert row["embedding"] == "[0.96, 0.28, 0.0]"  # câu đổi → vector theo câu mới (similar_corrections dùng nó)
    assert [c["id"] for c in engine.similar_corrections("giá thịt heo", 0.99, 5)] == [rid]


def test_memory_control_rejects_bad_correction_values(engine):
    rid = _seed(engine)
    for values, code in (({"right_tool": "khong_co_tool"}, "invalid_tool"), ({"right_tool": "market_price"}, "invalid_tool"),
                         ({"count": 0}, "invalid_count"), ({"query": "  "}, "invalid_query"),
                         ({"embedding": "[1]"}, "invalid_payload")):
        with pytest.raises(ValueError, match=code):
            engine.update_learning_control_record("correction", rid, values)
    assert _rows(engine)[0]["right_tool"] == "search_products"
    assert engine.update_learning_control_record("correction", 999, {"count": 2}) is False


def test_correction_delete_preview_has_no_vector(engine):
    rid = _seed(engine)
    rec = engine.preview_learning_dependencies("correction", rid)["will_delete"]["records"][0]
    assert "embedding" not in rec and rec["query"] == "giá thịt bò"
    assert engine.delete_learning_control_record("correction", rid) is True and _rows(engine) == []


def test_memory_control_api_accepts_correction_kind():
    import asyncio
    from engine.UIUX import ui_engine
    calls = []

    class _LE:
        def update_learning_control_record(self, kind, rid, values):
            calls.append(("update", kind, rid))
            return True

        def delete_learning_control_record(self, kind, rid):
            calls.append(("delete", kind, rid))
            return True
    import engine.core.learning as L
    orig = L.get_learning_engine
    L.get_learning_engine = lambda: _LE()
    try:
        assert asyncio.run(ui_engine.api_memory_control_update(
            ui_engine.MemoryControlUpdateBody(kind="correction", id=1, values={"count": 2}))) == {"success": True}
        assert asyncio.run(ui_engine.api_memory_control_delete(
            ui_engine.MemoryControlDeleteBody(kind="correction", id=1))) == {"success": True}
    finally:
        L.get_learning_engine = orig
    assert calls == [("update", "correction", 1), ("delete", "correction", 1)]
