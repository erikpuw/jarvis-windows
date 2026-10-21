"""Bài học chỉ nêu khái niệm: không lưu kèm "(ví dụ: 'câu của ngài')" / "(Evidence: …)" — các câu đó vào prompt chat
mỗi lượt và model chép theo (đo 2026-10-08: Learning.md có "(ví dụ: 'mở bài tôi thích')")."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.core.learning import strip_examples


def test_strip_examples_removes_example_and_evidence_parentheses():
    assert strip_examples("Khi người dùng lặp lại yêu cầu không rõ (ví dụ: 'mở bài tôi thích'), hãy làm rõ.") == \
        "Khi người dùng lặp lại yêu cầu không rõ, hãy làm rõ."
    assert strip_examples("Ghi nhận vai trò người dùng. (Evidence: \"Tôi đã xây dựng\"). Trả lời chi tiết.") == \
        "Ghi nhận vai trò người dùng. Trả lời chi tiết."
    assert strip_examples("Tránh từ chối dài (vd: yêu cầu ôm).") == "Tránh từ chối dài."


def test_strip_examples_keeps_real_facts():
    s = "Người dùng thích bài 'Making My Way' của Sơn Tùng M-TP (ca sĩ yêu thích)."
    assert strip_examples(s) == s


def test_store_learning_saves_stripped_content(tmp_path, monkeypatch):
    import engine.core.learning as learning
    monkeypatch.setattr(learning, "MEMORY_DB_PATH", tmp_path / "jarvis.db")
    for name in ("PREFERENCES_WIKI_PATH", "LESSONS_WIKI_PATH", "LEARNING_HUB_WIKI_PATH"):
        monkeypatch.setattr(learning, name, tmp_path / f"{name}.md")
    engine = learning.LearningEngine()
    monkeypatch.setattr(engine, "_embedding_fields", lambda text: ("", ""))
    assert engine._store_learning("Khi ngài phàn nàn (ví dụ: 'sai rồi'), hãy sửa ngay.", "behaviour_lesson", "fix_fast")
    contents = [r["content"] for r in engine.list_learning_records(limit=20)["items"]]
    assert contents == ["Khi ngài phàn nàn, hãy sửa ngay."]


def test_restatement_adds_no_new_information():
    """Nói lại điều đã học (khác chữ) không được ghi đè/thêm luật (probe 2026-10-08: 'Luôn trả lời ngắn gọn.')."""
    from engine.core.learning import adds_new_information
    old = "Trả lời ngắn gọn, không giải thích dài dòng."
    assert not adds_new_information("Luôn trả lời ngắn gọn.", old)
    assert not adds_new_information("Trả lời thật ngắn gọn, không dài dòng.", old)
    assert adds_new_information("Trả lời ngắn gọn, dùng gạch đầu dòng khi liệt kê.", old)
