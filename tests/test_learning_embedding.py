"""Test embedding, lexical dedupe (không cosine), và các tính năng B của Task B.
Run: python -m pytest tests/test_learning_embedding.py -v"""

import asyncio
import json
import sqlite3
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import engine.core.memory as memory
from engine.core import learning


@pytest.fixture
def engine(tmp_path, monkeypatch):
    """Setup DB tạm và mock embedder."""
    monkeypatch.setattr(learning, "MEMORY_DB_PATH", tmp_path / "jarvis.db")
    monkeypatch.setattr(learning, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(learning, "LEARNING_HUB_WIKI_PATH", tmp_path / "hub.md")
    for name in ("PREFERENCES_WIKI_PATH", "LESSONS_WIKI_PATH"):
        monkeypatch.setattr(learning, name, tmp_path / f"{name}.md")
    monkeypatch.setattr(memory, "DB_PATH", tmp_path / "jarvis.db")

    # Mock embedder: trả vector giả nhưng khác chiều nếu có embedding_model column
    def fake_embed(content):
        """Mock embedder trả 384 chiều vector."""
        return [float(i % 384) / 384 for i in range(384)]

    monkeypatch.setattr(learning.LearningEngine, "_embed_text", staticmethod(fake_embed))
    memory.init_db()
    le = learning.LearningEngine()
    le._init_db()
    return le


def _ids(le):
    """Lấy dict {id: content} của tất cả learnings."""
    conn = le._get_learning_db()
    rows = conn.execute("SELECT id, content FROM learnings").fetchall()
    conn.close()
    return {r["id"]: r["content"] for r in rows}


# ============================================================================
# B1: Bỏ cosine, dùng lexical dedupe
# ============================================================================

def test_different_topics_same_embedding_not_duplicate(engine):
    """Hai bài khác chủ đề nhưng embedder giả trả cùng vector ⇒ KHÔNG bị coi là trùng.
    RED hiện tại vì code dùng cosine."""
    engine._store_learning("Ngài thích emoji", "preference", "emoji_pref")
    engine._store_learning("Người dùng là kỹ sư AI", "user_fact", "profession")
    ids = _ids(engine)
    # Cả hai bài khác chủ đề nên phải cùng tồn tại (không bị xoá)
    assert len(ids) == 2, f"Expected 2 learnings, got {len(ids)}: {ids}"


def test_consolidate_removes_lexical_duplicates_keeps_newest(engine):
    """consolidate_learnings removes lexically similar learnings, keeps newest."""
    import time
    # Create 2 learnings directly in DB (bypass _store_learning to avoid duplicate check)
    conn = engine._get_learning_db()
    cur = conn.execute("""INSERT INTO learnings (type, content, created_at)
                   VALUES (?, ?, ?)""",
                 ("lesson", "Do not run tools when user is only asking", time.time()))
    old_id = cur.lastrowid
    cur = conn.execute("""INSERT INTO learnings (type, content, created_at)
                   VALUES (?, ?, ?)""",
                 ("lesson", "Do not run tools when user is only chatting", time.time() + 1))
    new_id = cur.lastrowid
    conn.commit()
    conn.close()

    removed = engine.consolidate_learnings()
    # Must remove old, keep new
    assert removed >= 1, f"Expected removal, but removed={removed}, ids={_ids(engine)}"
    assert new_id in _ids(engine), f"new_id={new_id} not in {_ids(engine)}"
    assert old_id not in _ids(engine), f"old_id={old_id} still in {_ids(engine)}"


def test_find_closest_existing_no_match_under_threshold(engine):
    """_find_closest_existing_learning trả None khi không có mục nào đạt LEXICAL_CLOSEST_MIN."""
    engine._store_learning("Người dùng làm AI", "user_fact", "profession")

    # Bài mới không trùng từ vựng với bài cũ
    closest = engine._find_closest_existing_learning(
        "user_fact", "hobby", "Ngài thích cơm tấm"
    )
    assert closest is None, f"Expected None, got {closest}"


def test_find_closest_existing_matches_semantic_key_first(engine):
    """_find_closest_existing_learning khớp semantic_key trước, không dùng cosine."""
    engine._store_learning("Ngài thích emoji", "preference", "emoji_pref")

    # Đề xuất cùng key
    closest = engine._find_closest_existing_learning(
        "preference", "emoji_pref", "Ngài yêu thích emoji"
    )
    assert closest is not None
    assert closest["id"] == 1


# ============================================================================
# B2: Bộ lọc chủ đề (chỉ chặn thẻ giao thức)
# ============================================================================

def test_forbidden_keywords_only_protocol_tags(engine):
    """Chỉ chặn <ask_user>, <action_run>, <offer_protocol>.
    Từ 'hỏi', 'xin phép', 'công cụ', 'tool', 'agent' được qua."""

    # Những cái PHẢI bị chặn (thẻ giao thức)
    assert engine._is_forbidden_topic("Bọc lệnh trong <ask_user>", "behaviour_lesson") is True
    assert engine._is_forbidden_topic("Dùng <action_run> để chạy công cụ", "behaviour_lesson") is True
    assert engine._is_forbidden_topic("Áp dụng <offer_protocol> lúc mở app", "behaviour_lesson") is True

    # Những từ này ĐƯỢC QUA (không phải luật hành vi hoặc người dùng yêu cầu)
    assert engine._is_forbidden_topic("Hạn chế gợi ý khi ngài chưa yêu cầu", "behaviour_lesson") is False
    assert engine._is_forbidden_topic("Đừng hỏi lại hai lần", "behaviour_lesson") is False
    assert engine._is_forbidden_topic("Không xin phép, chỉ làm thôi", "behaviour_lesson") is False


# ============================================================================
# B3: Bằng chứng chuẩn hoá
# ============================================================================

def test_evidence_normalized_casefold_and_unicode(engine):
    """Evidence chuẩn hoá: casefold, unicode normalize, bỏ dấu câu."""
    # Evidence khác dấu câu, emoji, hoa-thường nhưng cùng ý ⇒ vẫn khớp
    user_msg = "Tôi thích GIAO DIỆN màu tối, đơn giản!!! 😍"
    proposal = {
        "kind": "preference",
        "key": "dark_mode",
        "content": "Ngài thích giao diện màu tối",
        "evidence": "thích giao diện màu tối"  # khác hoa-thường, không emoji
    }
    assert engine._validate_proposal_evidence(proposal, user_msg) is True


def test_evidence_fabricated_still_rejected(engine):
    """Evidence bịa vẫn bị loại dù có chuẩn hoá."""
    user_msg = "Tôi thích trà xanh"
    proposal = {
        "kind": "preference",
        "key": "tea",
        "content": "Ngài thích cà phê đen",
        "evidence": "thích cà phê đen"  # bịa ra, không có trong user_msg
    }
    assert engine._validate_proposal_evidence(proposal, user_msg) is False


# ============================================================================
# B4: Yêu cầu học tường minh
# ============================================================================

def test_explicit_learning_request_patterns(engine):
    """Test regex patterns cho yêu cầu học rõ ràng."""
    # Những pattern PHẢI detect
    patterns = [
        "ghi nhớ rằng tôi thích cơm tấm",
        "Hãy nhớ điều này",
        "Nhớ giùm tôi kỹ năng này",
        "Nhớ giúp tôi",
        "Nhớ nhé!",
        "Nhớ lại lần sau",
        "Từ giờ không hỏi lại nữa",
        "Từ nay tôi chỉ dùng lệnh này",
        "Về sau làm cách này",
        "Hạn chế gợi ý quá mức",
        "Đừng hỏi lại nữa",
        "Không được gợi ý nữa",
    ]

    for text in patterns:
        result = engine._is_explicit_learning_request(text)
        assert result is True, f"Failed to detect: {text}"


def test_explicit_learning_with_skip_critique_still_stores(engine, monkeypatch):
    """Yêu cầu tường minh + critique skip + mục cũ không trùng ⇒ vẫn lưu mới."""
    memory.save_message("user", "hãy ghi nhớ hạn chế gợi ý")

    seen = []

    async def fake_llm(messages, **kwargs):
        seen.append(messages[0]["content"])
        # Lượt 1: propose
        if len(seen) == 1:
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                content=json.dumps({"proposals": [{
                    "kind": "behaviour_lesson",
                    "key": "limit_suggestions",
                    "content": "Hạn chế gợi ý không cần thiết",
                    "evidence": "hạn chế gợi ý"
                }]})
            ))])
        # Lượt 2: critique trả skip
        else:
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                content=json.dumps({"decision": "skip", "reason": "tạm thời"})
            ))])

    monkeypatch.setattr("engine.server.llm_server.call_llm", fake_llm)

    # Gọi learning lần 1
    result1 = asyncio.run(engine.process_conversation_learning(
        "hãy ghi nhớ hạn chế gợi ý", "Vâng, tôi sẽ ghi nhớ."
    ))
    # Vì yêu cầu tường minh, dù critique trả skip vẫn phải lưu
    assert result1["stored"] >= 1, f"Expected store, got {result1}"


# ============================================================================
# B6: Embedding là dữ liệu có thể xem/sửa
# ============================================================================

def test_embedding_column_exists(engine):
    """Cột embedding tồn tại."""
    conn = engine._get_learning_db()
    cols = {row[1] for row in conn.execute("PRAGMA table_info(learnings)").fetchall()}
    conn.close()
    assert "embedding" in cols, f"embedding column not found in {cols}"


def test_embedding_model_column_exists(engine):
    """Cột embedding_model tồn tại."""
    conn = engine._get_learning_db()
    cols = {row[1] for row in conn.execute("PRAGMA table_info(learnings)").fetchall()}
    conn.close()
    assert "embedding_model" in cols, f"embedding_model column not found in {cols}"


def test_list_learning_records_includes_embedding_fields(engine):
    """list_learning_records trả embedding, embedding_model, embedding_dim."""
    engine._store_learning("Test bài", "user_fact", "test")

    records = engine.list_learning_records()
    assert len(records["items"]) >= 1
    item = records["items"][0]
    assert "embedding" in item, f"embedding not in {item.keys()}"
    assert "embedding_model" in item, f"embedding_model not in {item.keys()}"
    assert "embedding_dim" in item, f"embedding_dim not in {item.keys()}"


def test_embedding_dim_is_zero_when_empty(engine):
    """embedding_dim = 0 khi embedding trống."""
    import time
    conn = engine._get_learning_db()
    conn.execute("INSERT INTO learnings (type, content, embedding, created_at) VALUES (?, ?, ?, ?)",
                 ("user_fact", "Test", "", time.time()))
    conn.commit()
    conn.close()

    records = engine.list_learning_records()
    item = records["items"][0]
    assert item["embedding_dim"] == 0


def test_embedding_dim_correct_when_populated(engine):
    """embedding_dim = độ dài vector khi có embedding."""
    engine._store_learning("Test", "user_fact", "test")

    records = engine.list_learning_records()
    item = records["items"][0]
    # Mock embedder trả 384 chiều
    assert item["embedding_dim"] == 384, f"Expected 384, got {item['embedding_dim']}"


def test_preview_not_includes_embedding_full_vector(engine):
    """preview_learning_dependencies không chứa embedding (quá dài), chỉ có embedding_dim."""
    engine._store_learning("Test", "user_fact", "test")
    record_id = next(iter(_ids(engine).keys()))

    preview = engine.preview_learning_dependencies("learning", record_id)
    record = preview["will_delete"]["records"][0]

    # embedding_dim có, nhưng embedding không (hoặc ngắn gọn)
    assert "embedding_dim" in record
    # embedding không được in nguyên vào preview JSON (quá lớn sẽ làm hộp xác nhận bị lỗi)
    if "embedding" in record:
        assert isinstance(record["embedding"], str)
        # Nếu có embedding, nó phải được bỏ hoặc rút gọn
        assert len(json.dumps(record)) < 2000, "Preview JSON too large for confirmation dialog"


def test_delete_preserves_embedding_on_restore(engine):
    """Khi xoá bài học rồi _sync_learning_wiki lỗi, khôi phục phải kèm embedding."""
    engine._store_learning("Test", "user_fact", "test")
    record_id = next(iter(_ids(engine).keys()))

    # Mock _sync_learning_wiki để raise
    original_sync = engine._sync_learning_wiki
    call_count = [0]

    def sync_with_error():
        call_count[0] += 1
        if call_count[0] == 1:
            # Lần đầu gọi (khi xoá) thì raise
            raise Exception("Wiki sync failed")
        else:
            # Lần khôi phục không raise
            return original_sync()

    engine._sync_learning_wiki = sync_with_error

    # Xoá sẽ thất bại và khôi phục
    try:
        engine.delete_learning_control_record("learning", record_id)
    except:
        pass

    # Bài học vẫn ở đó và giữ nguyên embedding
    ids = _ids(engine)
    assert record_id in ids, "Learning was not restored after wiki sync failed"


def test_reembed_learnings_updates_missing_embeddings(engine):
    """reembed_learnings tính lại embedding cho bản ghi."""
    # Tạo learning không có embedding
    import time
    conn = engine._get_learning_db()
    conn.execute("INSERT INTO learnings (type, content, embedding, embedding_model, created_at) "
                 "VALUES (?, ?, ?, ?, ?)",
                 ("user_fact", "Test no embed", "", "", time.time()))
    conn.commit()
    record_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()

    # Tính lại embedding
    result = engine.reembed_learnings(record_id)
    assert result["updated"] >= 1

    # Kiểm tra embedding đã được tính
    records = engine.list_learning_records()
    item = next(r for r in records["items"] if r["id"] == record_id)
    assert item["embedding_dim"] > 0


def test_reembed_all_learnings_when_no_id(engine):
    """reembed_learnings(None) tính lại tất cả embedding."""
    engine._store_learning("Test 1", "user_fact", "test1")
    engine._store_learning("Test 2", "preference", "test2")

    result = engine.reembed_learnings(None)
    # Phải cập nhật cả 2
    assert result["updated"] >= 2


def test_update_learning_with_embedding_value(engine):
    """update_learning_control_record cho phép thêm/sửa embedding."""
    engine._store_learning("Test", "user_fact", "test")
    record_id = 1

    # Update với embedding JSON hợp lệ
    test_embedding = [0.1, 0.2, 0.3]
    try:
        engine.update_learning_control_record(
            "learning", record_id,
            {"embedding": json.dumps(test_embedding)}
        )
        # Phải set embedding_model = "manual"
        conn = engine._get_learning_db()
        row = conn.execute("SELECT embedding, embedding_model FROM learnings WHERE id=?",
                          (record_id,)).fetchone()
        conn.close()
        assert row["embedding_model"] == "manual"
    except ValueError as e:
        assert False, f"Should accept valid embedding JSON: {e}"


def test_update_learning_with_empty_embedding_removes_it(engine):
    """update_learning_control_record với embedding='' xoá embedding."""
    engine._store_learning("Test", "user_fact", "test")
    record_id = 1

    engine.update_learning_control_record(
        "learning", record_id,
        {"embedding": ""}
    )

    conn = engine._get_learning_db()
    row = conn.execute("SELECT embedding, embedding_model FROM learnings WHERE id=?",
                      (record_id,)).fetchone()
    conn.close()
    assert row["embedding"] == ""
    assert row["embedding_model"] == ""


def test_update_learning_with_recompute_embedding(engine):
    """update_learning_control_record với embedding='recompute' tính lại."""
    engine._store_learning("Test", "user_fact", "test")
    record_id = 1

    engine.update_learning_control_record(
        "learning", record_id,
        {"embedding": "recompute"}
    )

    records = engine.list_learning_records()
    item = next(r for r in records["items"] if r["id"] == record_id)
    assert item["embedding_dim"] > 0


def test_update_learning_with_invalid_embedding_raises(engine):
    """update_learning_control_record với embedding sai định dạng raise ValueError."""
    engine._store_learning("Test", "user_fact", "test")
    record_id = 1

    with pytest.raises(ValueError, match="invalid_embedding"):
        engine.update_learning_control_record(
            "learning", record_id,
            {"embedding": "not_json"}
        )


def test_update_content_recalculates_embedding(engine):
    """update_learning_control_record với content mới ⇒ embedding tính lại."""
    engine._store_learning("Old content", "user_fact", "test")
    record_id = 1

    # Đổi content
    engine.update_learning_control_record(
        "learning", record_id,
        {"content": "New content"}
    )

    # Embedding phải tính lại (model sẽ trở thành tên embedder, không phải "manual")
    records = engine.list_learning_records()
    item = next(r for r in records["items"] if r["id"] == record_id)
    assert item["content"] == "New content"
    assert item["embedding_dim"] > 0


# ---- Review Task B (2026-10-01): các lỗi implementer bỏ sót -------------------------------------------------

def _vectors(engine):
    c = sqlite3.connect(learning.MEMORY_DB_PATH)
    rows = c.execute("SELECT id, length(embedding), embedding_model FROM learnings ORDER BY id").fetchall()
    c.close()
    return rows


def test_store_learning_never_dedupes_by_embedding(engine, monkeypatch):
    """Bài 2 khác chủ đề nhưng embedder trả CÙNG vector (đúng như e5-small) vẫn phải được lưu."""
    monkeypatch.setenv("LOCAL_EMBED_MODEL", "m-test")
    assert engine._store_learning("Người dùng thích cà phê sữa buổi sáng", "user_fact", "coffee") is True
    assert engine._store_learning("Dự án dùng Gemma bốn chạy trên llama cpp", "user_fact", "project_gemma") is True
    rows = _vectors(engine)
    assert [r[2] for r in rows] == ["m-test", "m-test"], rows  # embedding_model được ghi khi INSERT
    assert not hasattr(engine, "_find_semantic_duplicate") and not hasattr(engine, "SEMANTIC_DUPLICATE_THRESHOLD")


def test_critique_merge_records_embedding_model(engine, monkeypatch):
    monkeypatch.setenv("LOCAL_EMBED_MODEL", "m-merge")
    engine._store_learning("Người dùng thích cà phê sữa", "user_fact", "coffee")
    target = {"id": 1}
    assert engine._apply_critique_decision("merge", target, {"kind": "user_fact", "key": "coffee", "content": "x"},
                                           merged_content="Người dùng thích cà phê sữa buổi sáng")
    assert _vectors(engine)[0][2] == "m-merge"


def test_delete_workflow_and_outcome_still_work(engine, tmp_path, monkeypatch):
    wf_dir = tmp_path / "Workflows"  # không để _sync_workflow_wiki đụng wiki thật
    wf_dir.mkdir()
    monkeypatch.setattr(learning, "WORKFLOWS_WIKI_DIR", wf_dir)
    monkeypatch.setattr(learning, "WORKFLOWS_HUB_WIKI_PATH", wf_dir / "Công cụ.md")
    c = sqlite3.connect(learning.MEMORY_DB_PATH)
    c.execute("INSERT INTO workflows(tools,intent,tool_chain,sample_queries,success_evidence,validation_count,"
              "wiki_path,created_at,updated_at) VALUES('open_app','x','[{\"tool\": \"open_app\"}]','[]','ok',1,?,1,1)",
              (str(wf_dir / "open_app.md"),))
    c.execute("INSERT INTO outcomes(tools,query,status,result,traces,created_at) VALUES('open_app','q','success','ok','[]',1)")
    c.commit()
    wid = c.execute("SELECT id FROM workflows").fetchone()[0]
    oid = c.execute("SELECT id FROM outcomes").fetchone()[0]
    c.close()
    assert engine.delete_learning_control_record("workflow", wid) is True
    assert engine.delete_learning_control_record("outcome", oid) is True
    assert (wf_dir / "Công cụ.md").exists()  # hub ghi vào thư mục tạm, không đè hub thật (review 2026-10-13)


def test_reembed_with_embedder_down_keeps_existing_vectors(engine, monkeypatch):
    engine._store_learning("Người dùng thích cà phê sữa", "user_fact", "coffee")
    before = _vectors(engine)
    monkeypatch.setattr(learning.LearningEngine, "_embed_text", staticmethod(lambda c: None))
    result = engine.reembed_learnings()
    assert result == {"updated": 0, "error": "embedder_unavailable"}, result
    assert _vectors(engine) == before


def test_recompute_with_embedder_down_raises_and_keeps_vector(engine, monkeypatch):
    engine._store_learning("Người dùng thích cà phê sữa", "user_fact", "coffee")
    before = _vectors(engine)
    monkeypatch.setattr(learning.LearningEngine, "_embed_text", staticmethod(lambda c: None))
    with pytest.raises(ValueError, match="embedder_unavailable"):
        engine.update_learning_control_record("learning", 1, {"embedding": "recompute"})
    assert _vectors(engine) == before


def test_delete_confirm_preview_is_small_with_a_real_384_vector(engine):
    """Hộp xác nhận xoá in nguyên JSON preview: với vector 384 chiều thật preview phải gọn (trước: 8.900 ký tự)."""
    engine._store_learning("Người dùng thích cà phê sữa buổi sáng", "user_fact", "coffee")
    preview = engine.preview_learning_dependencies("learning", 1)
    text = json.dumps(preview, ensure_ascii=False, indent=2)
    assert len(text) < 1500, len(text)
    assert preview["will_delete"]["records"][0]["embedding_dim"] == 384
